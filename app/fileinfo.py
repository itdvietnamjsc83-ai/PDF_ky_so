"""Thông tin file PDF (tác giả, tiêu đề, phần mềm tạo, ngày tạo / sửa, XMP…): xem, sửa, xóa trước khi gửi đi."""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta, timezone

# trường chuẩn của PDF (/Info) -> nhãn tiếng Việt
STD_FIELDS = [("/Title", "Tiêu đề"), ("/Author", "Tác giả"), ("/Subject", "Chủ đề"), ("/Keywords", "Từ khóa"),
              ("/Creator", "Phần mềm soạn"), ("/Producer", "Phần mềm tạo PDF"),
              ("/CreationDate", "Ngày tạo"), ("/ModDate", "Ngày sửa")]
STD_KEYS = [k for k, _ in STD_FIELDS]
DATE_KEYS = ("/CreationDate", "/ModDate")
LABEL = dict(STD_FIELDS)


def parse_pdf_date(s: str) -> datetime | None:
    """D:20261110093000+07'00' -> datetime."""
    m = re.match(r"(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz+\-])?(\d{2})?'?(\d{2})?'?", s or "")
    if not m:
        return None
    y, mo, d, h, mi, se = (int(m.group(k) or dflt) for k, dflt in zip(range(1, 7), (0, 1, 1, 0, 0, 0)))
    try:
        dt = datetime(y, mo, d, h, mi, se)
    except ValueError:
        return None
    sign = m.group(7)
    if sign in ("Z", "z"):
        return dt.replace(tzinfo=timezone.utc)
    if sign in ("+", "-"):
        off = timedelta(hours=int(m.group(8) or 0), minutes=int(m.group(9) or 0))
        return dt.replace(tzinfo=timezone(off if sign == "+" else -off))
    return dt


def date_text(s: str) -> str:
    dt = parse_pdf_date(s)
    return dt.strftime("%d/%m/%Y %H:%M:%S") if dt else (s or "")


def read_info(data: bytes) -> dict:
    """{"fields": {khóa: chữ}, "xmp": có XMP?, "version": "1.7", "extra": [(nhãn, chữ)...]}"""
    import pikepdf
    out = {"fields": {}, "xmp": False, "version": "", "xmp_fields": {}}
    with pikepdf.open(io.BytesIO(data)) as pk:
        out["version"] = str(pk.pdf_version)
        info = pk.trailer.get("/Info")
        if info is not None:
            for k, v in info.items():
                try:
                    out["fields"][str(k)] = str(v)
                except Exception:
                    pass
        if "/Metadata" in pk.Root:
            out["xmp"] = True
            try:
                with pk.open_metadata(set_pikepdf_as_editor=False) as meta:
                    for k, v in meta.items():
                        out["xmp_fields"][str(k)] = str(v)
            except Exception:
                pass
    return out


def write_info(data: bytes, fields: dict, remove_xmp: bool = False, remove_custom: bool = False) -> bytes:
    """Ghi lại /Info: fields {khóa: chữ}; chữ rỗng / None = xóa trường đó. Khóa không có trong fields giữ nguyên,
    trừ khi remove_custom (xóa mọi trường không chuẩn). remove_xmp: bỏ hẳn gói XMP (thường lặp lại tác giả, phần
    mềm, ngày) – nếu giữ XMP thì các trường chuẩn trong XMP cũng được cập nhật theo."""
    import pikepdf
    with pikepdf.open(io.BytesIO(data)) as pk:
        info = pk.trailer.get("/Info")
        if info is None:
            info = pk.make_indirect(pikepdf.Dictionary())
            pk.trailer.Info = info
        for k, v in fields.items():
            key = pikepdf.Name(k if k.startswith("/") else "/" + k)
            if v is None or str(v).strip() == "":
                if key in info:
                    del info[key]
            else:
                info[key] = pikepdf.String(str(v))
        if remove_custom:
            for k in list(info.keys()):
                if str(k) not in STD_KEYS:
                    del info[k]
        if remove_xmp:
            if "/Metadata" in pk.Root:
                del pk.Root["/Metadata"]
        elif "/Metadata" in pk.Root:
            import warnings
            try:                                          # XMP khớp với /Info vừa sửa
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with pk.open_metadata(set_pikepdf_as_editor=False) as meta:
                        meta.load_from_docinfo(info, delete_missing=True)
            except Exception:
                pass
        if len(info.keys()) == 0:
            del pk.trailer["/Info"]
        buf = io.BytesIO()
        pk.save(buf)
        return buf.getvalue()


def clean_all(data: bytes) -> bytes:
    """Xóa hết thông tin file (mọi trường /Info + XMP) trước khi gửi đi."""
    fields = {k: None for k in read_info(data)["fields"]}
    return write_info(data, fields, remove_xmp=True, remove_custom=True)


def file_facts(doc) -> list[tuple[str, str]]:
    """Thông tin chung không nằm trong trường: đường dẫn, dung lượng, số trang, bảo vệ, chữ ký."""
    out = []
    if doc.path:
        out.append(("Tên file", os.path.basename(doc.path)))
        out.append(("Thư mục", os.path.dirname(doc.path)))
        try:
            st = os.stat(doc.path)
            out.append(("Dung lượng", f"{st.st_size / 1024 / 1024:.2f} MB" if st.st_size > 1024 * 1024
                        else f"{st.st_size / 1024:.1f} KB"))
            out.append(("Sửa trên máy lúc", datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")))
        except OSError:
            pass
    out.append(("Số trang", str(doc.page_count)))
    if doc.page_count:
        out.append(("Khổ trang 1", doc.page_info(0).label))
    limits = [x for x, ok in (("không cho sửa", not doc.can_modify), ("không cho in", not doc.can_print)) if ok]
    out.append(("Bảo vệ", ("Có (" + ", ".join(limits) + ")" if limits else "Có") if doc.encrypted else "Không"))
    n = doc.signature_count()
    out.append(("Chữ ký số", f"{n} chữ ký" if n else "Chưa có"))
    return out


__all__ = ["STD_FIELDS", "STD_KEYS", "DATE_KEYS", "LABEL", "parse_pdf_date", "date_text", "read_info",
           "write_info", "clean_all", "file_facts"]
