"""Đợt 2 – ghi chú (sticky note) sửa được, trả lời, đánh dấu đã xử lý.

Ghi chú là chú thích PDF chuẩn (/Text) nên mở ở phần mềm PDF nào cũng đọc được:
  - màu, biểu tượng vẽ bằng giao diện riêng (/AP) để hiển thị đúng màu/biểu tượng đã chọn
  - độ mờ: /CA
  - trạng thái "đã xử lý": khóa riêng /PdfKySo_status (và huy hiệu ✓ xanh trên biểu tượng)
  - trả lời: ghi chú mới trỏ về ghi chú gốc bằng /IRT (Acrobat, Foxit... hiển thị thành luồng trả lời)
Toạ độ hiển thị (pt, gốc trên-trái) như trên màn hình.
"""
from __future__ import annotations

import ctypes
import io
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import pypdfium2.raw as C

from .editing import _rgba, _wide

ICON_SIZE = 20.0
NOTE_ICONS = [("comment", "Ghi chú"), ("help", "Câu hỏi  ?"), ("alert", "Quan trọng  !"), ("check", "Đã duyệt  ✓"),
              ("note", "Tờ giấy")]
NOTE_COLORS = [("Vàng", "#ffd400"), ("Cam", "#ff9800"), ("Đỏ", "#e53935"), ("Xanh lá", "#43a047"),
               ("Xanh dương", "#1e88e5"), ("Tím", "#8e24aa")]
# các loại chú thích có nội dung bình luận (ghi chú từ Acrobat, Foxit, Word...)
SUBTYPE_LABEL = {
    C.FPDF_ANNOT_TEXT: "Ghi chú", C.FPDF_ANNOT_FREETEXT: "Hộp chữ", C.FPDF_ANNOT_LINE: "Đường kẻ",
    C.FPDF_ANNOT_SQUARE: "Hình chữ nhật", C.FPDF_ANNOT_CIRCLE: "Hình tròn", C.FPDF_ANNOT_POLYGON: "Đa giác",
    C.FPDF_ANNOT_POLYLINE: "Đường gấp khúc", C.FPDF_ANNOT_HIGHLIGHT: "Tô sáng", C.FPDF_ANNOT_UNDERLINE: "Gạch chân",
    C.FPDF_ANNOT_SQUIGGLY: "Gạch sóng", C.FPDF_ANNOT_STRIKEOUT: "Gạch ngang", C.FPDF_ANNOT_STAMP: "Dấu",
    C.FPDF_ANNOT_CARET: "Chèn chữ", C.FPDF_ANNOT_INK: "Nét vẽ", C.FPDF_ANNOT_FILEATTACHMENT: "Tệp đính kèm",
}
_PDF_NAME = {"comment": "Comment", "help": "Help", "alert": "Comment", "check": "Comment", "note": "Note"}
_FROM_PDF_NAME = {"Comment": "comment", "Help": "help", "Note": "note", "Key": "comment", "Insert": "comment",
                  "NewParagraph": "comment", "Paragraph": "note"}


@dataclass
class NoteInfo:
    page: int
    index: int                    # vị trí chú thích trên trang
    nm: str                       # mã riêng (/NM)
    text: str
    author: str
    date: datetime | None
    color: str
    icon: str
    opacity: int
    done: bool
    reply_to: str                 # /NM của ghi chú gốc ("" nếu là ghi chú gốc)
    rect: tuple                   # khung hiển thị (x0, y0, x1, y1)
    replies: list = field(default_factory=list)
    subtype: int = 1              # loại chú thích PDF (1 = ghi chú dán /Text)

    @property
    def is_sticky(self) -> bool:
        return self.subtype == C.FPDF_ANNOT_TEXT

    @property
    def kind_label(self) -> str:
        return SUBTYPE_LABEL.get(self.subtype, "Chú thích")

    @property
    def date_text(self) -> str:
        return self.date.strftime("%d/%m/%Y %H:%M") if self.date else ""


# ------------------------------------------------------------------ đọc / ghi thuộc tính chú thích
def _get_str(annot, key: str) -> str:
    n = C.FPDFAnnot_GetStringValue(annot, key.encode(), None, 0)
    if n <= 2:
        return ""
    buf = ctypes.create_string_buffer(n)
    C.FPDFAnnot_GetStringValue(annot, key.encode(), ctypes.cast(buf, ctypes.POINTER(C.FPDF_WCHAR)), n)
    return buf.raw[:n].decode("utf-16-le", "ignore").rstrip("\0")


def _set_str(annot, key: str, val: str):
    buf, ptr = _wide(val)
    C.FPDFAnnot_SetStringValue(annot, key.encode(), ptr)


def _pdf_date(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    off = -time.timezone if not time.localtime().tm_isdst else -time.altzone
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return dt.strftime("D:%Y%m%d%H%M%S") + f"{sign}{off // 3600:02d}'{off % 3600 // 60:02d}'"


def parse_pdf_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if s.startswith("D:"):
        s = s[2:]
    digits = "".join(ch for ch in s[:14] if ch.isdigit())
    for fmt, n in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(digits) >= n:
            try:
                return datetime.strptime(digits[:n], fmt)
            except ValueError:
                return None
    return None


def _hex(r, g, b) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


# ------------------------------------------------------------------ giao diện biểu tượng (/AP)
def _icon_stream(icon: str, color: str, done: bool, rot: int) -> str:
    """Lệnh vẽ biểu tượng 20×20 (hệ PDF, gốc dưới-trái của ô)."""
    r, g, b, _ = _rgba(color)
    fr, fg, fb = r / 255, g / 255, b / 255
    ops = []
    if icon == "note":        # tờ giấy gấp góc
        ops.append(f"{fr:.3f} {fg:.3f} {fb:.3f} rg 0.15 0.15 0.15 RG 0.8 w "
                   "3 1 m 3 19 l 13 19 l 17 15 l 17 1 l h B 13 19 m 13 15 l 17 15 l S "
                   "6 12 m 14 12 l 6 9 m 14 9 l 6 6 m 12 6 l S")
    else:                     # bong bóng lời thoại
        ops.append(f"{fr:.3f} {fg:.3f} {fb:.3f} rg 0.15 0.15 0.15 RG 0.8 w "
                   "2 18.5 m 18 18.5 l 18 6 l 8 6 l 4.5 2 l 5.5 6 l 2 6 l h B")
        if icon == "comment":
            ops.append("0.15 0.15 0.15 RG 1 w 5 15 m 15 15 l 5 12 m 15 12 l 5 9 m 12 9 l S")
        elif icon == "help":           # dấu ?
            ops.append("0.1 0.1 0.1 RG 1.6 w 1 J 7.2 14.2 m 7.2 16.6 12.8 16.6 12.8 14.2 c "
                       "12.8 12.4 10 12.4 10 10.6 c 10 10 l S 0.1 0.1 0.1 rg 10 8 m 10.9 8 l 10.9 7.1 l 10 7.1 l h f")
        elif icon == "alert":          # dấu !
            ops.append("0.1 0.1 0.1 RG 2 w 1 J 10 16.8 m 10 10.6 l S 0.1 0.1 0.1 rg "
                       "9.1 8.6 m 10.9 8.6 l 10.9 6.9 l 9.1 6.9 l h f")
        elif icon == "check":          # dấu ✓
            ops.append("0.1 0.1 0.1 RG 1.8 w 1 J 1 j 5.5 12.2 m 8.6 9.2 l 14.6 15.6 l S")
    if done:                           # huy hiệu "đã xử lý"
        ops.append("0.18 0.49 0.2 rg 1 1 1 RG 0.7 w 12.5 4.5 m 12.5 6.4 14.1 8 16 8 c 17.9 8 19.5 6.4 19.5 4.5 c "
                   "19.5 2.6 17.9 1 16 1 c 14.1 1 12.5 2.6 12.5 4.5 c h B 1.1 w 1 J 14.3 4.6 m 15.6 3.3 l 17.8 5.8 l S")
    body = " ".join(ops)
    if rot:
        import math
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        # xoay quanh tâm ô (10, 10) để biểu tượng đứng thẳng khi trang có /Rotate
        e = 10 - (10 * c - 10 * s)
        f = 10 - (10 * s + 10 * c)
        body = f"q {c:.4f} {s:.4f} {-s:.4f} {c:.4f} {e:.3f} {f:.3f} cm {body} Q"
    return body


def _set_color(annot, color, opacity):
    """/C và /CA (pdfium chỉ cho đặt màu khi chưa có /AP -> gỡ /AP trước)."""
    C.FPDFAnnot_SetAP(annot, C.FPDF_ANNOT_APPEARANCEMODE_NORMAL, None)
    rr, gg, bb, _ = _rgba(color)
    C.FPDFAnnot_SetColor(annot, C.FPDFANNOT_COLORTYPE_Color, rr, gg, bb, int(round(opacity * 2.55)))
    _set_str(annot, "PdfKySo_color", color)
    _set_str(annot, "PdfKySo_opacity", str(int(opacity)))


def _apply_ap(annot, icon, color, done, rot, rect_lb, opacity=100, hidden=False):
    l, b = rect_lb
    if hidden:
        stream = ""
    else:
        if opacity < 100:             # làm nhạt màu nền (tương thích mọi trình xem; /CA vẫn được đặt)
            r, g, bb, _ = _rgba(color)
            k = opacity / 100
            color = _hex(int(255 - (255 - r) * k), int(255 - (255 - g) * k), int(255 - (255 - bb) * k))
        stream = f"q 1 0 0 1 {l:.3f} {b:.3f} cm {_icon_stream(icon, color, done, rot)} Q"
    buf, ptr = _wide(stream)
    C.FPDFAnnot_SetAP(annot, C.FPDF_ANNOT_APPEARANCEMODE_NORMAL, ptr)


def _rot(doc, i) -> int:
    try:
        return int(doc.page(i).get_rotation()) % 360
    except Exception:
        return 0


def _annot_rect(annot):
    r = C.FS_RECTF()
    C.FPDFAnnot_GetRect(annot, ctypes.byref(r))
    return min(r.left, r.right), min(r.bottom, r.top), max(r.left, r.right), max(r.bottom, r.top)


def _icon_of(annot) -> str:
    ic = _get_str(annot, "PdfKySo_icon")
    if ic:
        return ic
    n = C.FPDFAnnot_GetStringValue(annot, b"Name", None, 0)       # /Name là tên (name), không phải chuỗi
    return _FROM_PDF_NAME.get(_get_str(annot, "Name") if n > 2 else "", "comment")


def _color_of(annot) -> tuple[str, int]:
    c = _get_str(annot, "PdfKySo_color")
    if not c and not C.FPDFAnnot_HasKey(annot, b"C"):
        return "#ffd400", 100
    if c:
        try:
            return c, int(_get_str(annot, "PdfKySo_opacity") or 100)
        except ValueError:
            return c, 100
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if C.FPDFAnnot_GetColor(annot, C.FPDFANNOT_COLORTYPE_Color, *(ctypes.byref(v) for v in (r, g, b, a))):
        return _hex(r.value, g.value, b.value), int(round(a.value / 255 * 100))
    return "#ffd400", 100


# ------------------------------------------------------------------ danh sách
def _contents(annot) -> str:
    t = _get_str(annot, "Contents")
    if not t:                              # chỉ có nội dung định dạng (/RC, XHTML) -> bỏ thẻ
        import re
        rc = _get_str(annot, "RC")
        if rc:
            t = re.sub(r"<[^>]+>", "", rc.replace("</p>", "\n")).strip()
    return t


def _page_notes(doc, i: int) -> list[NoteInfo]:
    page = doc.page(i)
    out = []
    n_annot = C.FPDFPage_GetAnnotCount(page.raw)
    nm_of = {}
    for k in range(n_annot):
        a = C.FPDFPage_GetAnnot(page.raw, k)
        try:
            nm_of[k] = _get_str(a, "NM") or f"#idx{k}"
        finally:
            C.FPDFPage_CloseAnnot(a)
    for k in range(n_annot):
        a = C.FPDFPage_GetAnnot(page.raw, k)
        try:
            st = C.FPDFAnnot_GetSubtype(a)
            if st not in SUBTYPE_LABEL:
                continue
            text = _contents(a)
            if st != C.FPDF_ANNOT_TEXT and not text:
                continue                   # hình / tô sáng không kèm lời bình -> không phải ghi chú
            l, b, r, t = _annot_rect(a)
            p0 = doc.user_to_display(i, l, b)
            p1 = doc.user_to_display(i, r, t)
            rect = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
            color, op = _color_of(a)
            irt = _get_str(a, "PdfKySo_irt")
            if not irt and C.FPDFAnnot_HasKey(a, b"IRT"):      # trả lời tạo từ Acrobat / Foxit
                lk = C.FPDFAnnot_GetLinkedAnnot(a, b"IRT")
                if lk:
                    try:
                        idx = C.FPDFPage_GetAnnotIndex(page.raw, lk)
                        irt = nm_of.get(idx, "")
                    finally:
                        C.FPDFPage_CloseAnnot(lk)
            date = parse_pdf_date(_get_str(a, "M") or _get_str(a, "CreationDate"))
            out.append(NoteInfo(i, k, nm_of[k], text, _get_str(a, "T"), date, color,
                                _icon_of(a) if st == C.FPDF_ANNOT_TEXT else "comment",
                                op, _get_str(a, "PdfKySo_status") == "done", irt, rect, subtype=st))
        finally:
            C.FPDFPage_CloseAnnot(a)
    return out


def list_notes(doc, pages=None) -> list[NoteInfo]:
    """Ghi chú gốc (kèm .replies) trên các trang, theo thứ tự trang."""
    pages = range(doc.page_count) if pages is None else pages
    out = []
    for i in pages:
        allv = _page_notes(doc, i)
        by_nm = {n.nm: n for n in allv}
        for n in allv:
            if n.reply_to and n.reply_to in by_nm:
                by_nm[n.reply_to].replies.append(n)
        out += [n for n in allv if not (n.reply_to and n.reply_to in by_nm)]
    return out


def note_at(doc, i: int, x: float, y: float, pad: float = 2.0) -> NoteInfo | None:
    """Ghi chú tại điểm (ưu tiên biểu tượng ghi chú dán, rồi chú thích nhỏ nhất chứa điểm)."""
    best = None
    for n in list_notes(doc, [i]):
        x0, y0, x1, y1 = n.rect
        if x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad:
            key = (0 if n.is_sticky else 1, (x1 - x0) * (y1 - y0))
            if best is None or key <= best[0]:
                best = (key, n)
    return best[1] if best else None


def get_note(doc, i: int, nm: str) -> NoteInfo | None:
    for n in _page_notes(doc, i):
        if n.nm == nm:
            return n
    return None


def _find_index(doc, i, nm) -> int | None:
    if nm.startswith("#idx"):
        return int(nm[4:])
    for n in _page_notes(doc, i):
        if n.nm == nm:
            return n.index
    return None


# ------------------------------------------------------------------ thêm / sửa / xóa
def add_note(doc, i: int, x: float, y: float, text: str, author: str = "", color: str = "#ffd400",
             icon: str = "comment", opacity: int = 100, reply_to: str = "", snapshot: bool = True) -> str:
    """Thêm ghi chú (reply_to: trả lời ghi chú có /NM đó). Trả về /NM."""
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    ux, uy = doc.display_to_user(i, x, y)
    rot = _rot(doc, i)
    # ô biểu tượng 20×20 luôn nằm dưới-phải điểm bấm khi nhìn trên màn hình
    corners = [doc.display_to_user(i, x + dx, y + dy) for dx, dy in ((0, 0), (ICON_SIZE, ICON_SIZE))]
    l, b = min(c[0] for c in corners), min(c[1] for c in corners)
    r, t = max(c[0] for c in corners), max(c[1] for c in corners)
    annot = C.FPDFPage_CreateAnnot(page.raw, C.FPDF_ANNOT_TEXT)
    if not annot:
        raise RuntimeError("Không tạo được ghi chú")
    nm = "pks-" + uuid.uuid4().hex[:16]
    try:
        C.FPDFAnnot_SetRect(annot, C.FS_RECTF(l, t, r, b))
        now = _pdf_date()
        for key, val in (("Contents", text), ("T", author or ""), ("NM", nm), ("M", now), ("CreationDate", now),
                         ("PdfKySo_icon", icon)):
            _set_str(annot, key, val)
        _set_color(annot, color, opacity)
        _set_str(annot, "Name", _PDF_NAME.get(icon, "Comment"))
        if reply_to:
            _set_str(annot, "PdfKySo_irt", reply_to)
            _set_str(annot, "Subj", "Trả lời")
        C.FPDFAnnot_SetFlags(annot, C.FPDF_ANNOT_FLAG_PRINT if hasattr(C, "FPDF_ANNOT_FLAG_PRINT") else 4)
        _apply_ap(annot, icon, color, False, rot, (l, b), opacity, hidden=bool(reply_to))
    finally:
        C.FPDFPage_CloseAnnot(annot)
    if reply_to:
        _link_replies(doc)
    if snapshot:
        doc._changed()
    return nm


def _link_replies(doc):
    """Đặt /IRT (tham chiếu tới ghi chú gốc) cho các câu trả lời -> phần mềm PDF khác hiện thành luồng."""
    import pikepdf
    data = doc.to_bytes()
    changed = False
    with pikepdf.open(io.BytesIO(data)) as pk:
        for pg in pk.pages:
            annots = pg.obj.get("/Annots")
            if not annots:
                continue
            by_nm = {}
            for a in annots:
                try:
                    if a.get("/Subtype") == "/Text" and "/NM" in a:
                        by_nm[str(a.NM)] = a
                except Exception:
                    continue
            for a in annots:
                try:
                    irt = a.get("/PdfKySo_irt")
                    if irt is not None and "/IRT" not in a and str(irt) in by_nm:
                        a.IRT = by_nm[str(irt)]
                        a.RT = pikepdf.Name("/R")
                        changed = True
                except Exception:
                    continue
        if changed:
            out = io.BytesIO()
            pk.save(out)
    if changed:
        doc._load_bytes(out.getvalue())


def update_note(doc, i: int, nm: str, text=None, author=None, color=None, icon=None, opacity=None, done=None,
                snapshot: bool = True):
    k = _find_index(doc, i, nm)
    if k is None:
        raise ValueError("Ghi chú không còn")
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    a = C.FPDFPage_GetAnnot(page.raw, k)
    try:
        cur_color, cur_op = _color_of(a)
        cur_icon = _icon_of(a)
        cur_done = _get_str(a, "PdfKySo_status") == "done"
        is_reply = bool(_get_str(a, "PdfKySo_irt"))
        if text is not None:
            _set_str(a, "Contents", text)
        if author is not None:
            _set_str(a, "T", author)
        color = color or cur_color
        opacity = cur_op if opacity is None else opacity
        icon = icon or cur_icon
        done = cur_done if done is None else done
        _set_str(a, "PdfKySo_status", "done" if done else "")
        _set_str(a, "M", _pdf_date())
        if C.FPDFAnnot_GetSubtype(a) == C.FPDF_ANNOT_TEXT:   # tô sáng, hộp chữ... của phần mềm khác: giữ nguyên hình
            _set_color(a, color, opacity)
            _set_str(a, "PdfKySo_icon", icon)
            _set_str(a, "Name", _PDF_NAME.get(icon, "Comment"))
            l, b, r, t = _annot_rect(a)
            _apply_ap(a, icon, color, done, _rot(doc, i), (l, b), opacity, hidden=is_reply)
    finally:
        C.FPDFPage_CloseAnnot(a)
    if snapshot:
        doc._changed()


def move_note(doc, i: int, nm: str, x: float, y: float, snapshot: bool = True):
    """Dời biểu tượng ghi chú (góc trên-trái hiển thị tới (x, y)). Câu trả lời dời theo."""
    k = _find_index(doc, i, nm)
    if k is None:
        raise ValueError("Ghi chú không còn")
    if snapshot:
        doc._snapshot()
    targets = [k] + [n.index for n in _page_notes(doc, i) if n.reply_to == nm]
    corners = [doc.display_to_user(i, x + dx, y + dy) for dx, dy in ((0, 0), (ICON_SIZE, ICON_SIZE))]
    l, b = min(c[0] for c in corners), min(c[1] for c in corners)
    r, t = max(c[0] for c in corners), max(c[1] for c in corners)
    page = doc.page(i)
    for idx in targets:
        a = C.FPDFPage_GetAnnot(page.raw, idx)
        try:
            if C.FPDFAnnot_GetSubtype(a) != C.FPDF_ANNOT_TEXT:
                continue
            C.FPDFAnnot_SetRect(a, C.FS_RECTF(l, t, r, b))
            color, op = _color_of(a)
            _apply_ap(a, _icon_of(a), color, _get_str(a, "PdfKySo_status") == "done", _rot(doc, i), (l, b), op,
                      hidden=bool(_get_str(a, "PdfKySo_irt")))
        finally:
            C.FPDFPage_CloseAnnot(a)
    if snapshot:
        doc._changed()


def delete_note(doc, i: int, nm: str, snapshot: bool = True) -> int:
    """Xóa ghi chú (kèm các câu trả lời của nó). Trả về số chú thích đã xóa."""
    k = _find_index(doc, i, nm)
    if k is None:
        return 0
    if snapshot:
        doc._snapshot()
    targets = sorted({k} | {n.index for n in _page_notes(doc, i) if n.reply_to == nm}, reverse=True)
    page = doc.page(i)
    for idx in targets:
        C.FPDFPage_RemoveAnnot(page.raw, idx)
    if snapshot:
        doc._changed()
    return len(targets)


def set_hidden(doc, i: int, nm: str, hidden: bool):
    """Ẩn/hiện tạm biểu tượng (khi đang kéo di chuyển) – không tính là thay đổi file."""
    k = _find_index(doc, i, nm)
    if k is None:
        return
    page = doc.page(i)
    a = C.FPDFPage_GetAnnot(page.raw, k)
    try:
        fl = C.FPDFAnnot_GetFlags(a)
        H = getattr(C, "FPDF_ANNOT_FLAG_HIDDEN", 2)
        C.FPDFAnnot_SetFlags(a, (fl | H) if hidden else (fl & ~H))
    finally:
        C.FPDFPage_CloseAnnot(a)
    doc.version += 1


def icon_image(icon: str, color: str, done: bool = False, opacity: int = 100, px: int = 40):
    """Ảnh PIL RGBA của biểu tượng (xem trước khi kéo / trong danh sách)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(ICON_SIZE + 3, ICON_SIZE)
    try:
        if opacity < 100:
            r, g, b, _ = _rgba(color)
            k = opacity / 100
            color = _hex(int(255 - (255 - r) * k), int(255 - (255 - g) * k), int(255 - (255 - b) * k))
        stream = _icon_stream(icon, color, done, 0).encode()
        import pikepdf
        buf = io.BytesIO()
        pdf.save(buf)
        with pikepdf.open(io.BytesIO(buf.getvalue())) as pk:
            pk.pages[0].obj.Contents = pikepdf.Stream(pk, stream)
            out = io.BytesIO()
            pk.save(out)
        page.close()
        pdf.close()
        pdf = pdfium.PdfDocument(out.getvalue())
        page = pdf[0]
        bm = page.render(scale=px / ICON_SIZE, fill_color=(255, 255, 255, 0), rev_byteorder=True)
        img = bm.to_pil().convert("RGBA")
        bm.close()
        return img
    finally:
        page.close()
        pdf.close()


# ------------------------------------------------------------------ 12c: xuất tổng hợp ghi chú
def _rows(notes_list):
    rows = []
    for k, n in enumerate(notes_list, 1):
        reps = "\n".join(f"{r.author or 'Không tên'} ({r.date_text}): {r.text}" for r in n.replies)
        rows.append([k, n.page + 1, n.kind_label, n.author or "", n.date_text, n.text,
                     "Đã xử lý" if n.done else "Chưa xử lý", reps])
    return rows


def export_xlsx(notes_list, path: str, title: str = ""):
    from .xlsxwrite import write_xlsx
    write_xlsx(path, ["STT", "Trang", "Loại", "Người ghi", "Ngày", "Nội dung", "Trạng thái", "Trả lời"],
               _rows(notes_list), "Ghi chú", [6, 7, 12, 20, 17, 60, 12, 50], title or None)


def export_pdf(notes_list, path: str, title: str = ""):
    """Bản tổng hợp ghi chú dạng PDF (A4), chữ thật."""
    from . import items
    from .document import blank_document
    doc = blank_document(1, (595.28, 841.89))
    W, H, M = 595.28, 841.89, 50
    y = M
    page = 0

    from . import fonts
    fp = items.font_path({})

    def safe(text):
        """Bỏ ký tự phông không có (vd. biểu tượng cảm xúc trong ghi chú; Times New Roman thiếu nhiều ký hiệu)."""
        miss = set(fonts.missing_chars(fp, "".join(set(text) - {"\n"})))
        return "".join(ch for ch in text if ch not in miss) if miss else text

    def put(text, size=10.5, color="#1b1b1b", indent=0.0, gap=4.0):
        nonlocal y, page
        text = safe(text)
        spec = items.text_spec(M + indent, y, W - 2 * M - indent, text, None, size, color)
        h = spec["rect"][3] - spec["rect"][1]
        if y + h > H - M:
            doc.insert_blank(doc.page_count - 1, 1)
            page += 1
            y = M
            spec = items.text_spec(M + indent, y, W - 2 * M - indent, text, None, size, color)
        items.add_item(doc, page, spec, snapshot=False)
        y += h + gap
    put(title or "TỔNG HỢP GHI CHÚ", 16, "#B8322A", gap=2)
    done = sum(1 for n in notes_list if n.done)
    put(f"{len(notes_list)} ghi chú · {done} đã xử lý · {len(notes_list) - done} chưa xử lý · "
        f"xuất ngày {datetime.now().strftime('%d/%m/%Y %H:%M')}", 9.5, "#555555", gap=14)
    for k, n in enumerate(notes_list, 1):
        head = f"{k}. Trang {n.page + 1} · {n.kind_label} · {n.author or 'Không tên'}" + \
            (f" · {n.date_text}" if n.date_text else "") + (" · ĐÃ XỬ LÝ" if n.done else "")
        put(head, 10.5, "#2e7d32" if n.done else "#0d47a1", gap=2)
        put(n.text or "(không có nội dung)", 10.5, indent=12, gap=3)
        for r in n.replies:
            put(f"→ {r.author or 'Không tên'} ({r.date_text}): {r.text}", 9.5, "#444444", indent=24, gap=2)
        y += 8
    doc.save(path)
    doc.close()


__all__ = ["NoteInfo", "NOTE_ICONS", "NOTE_COLORS", "add_note", "list_notes", "note_at", "update_note",
           "move_note", "delete_note", "icon_image"]
