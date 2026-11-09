"""Giai đoạn 6 – công cụ: nén theo dung lượng, so sánh 2 bản, dấu chữ (ĐÃ DUYỆT, BẢN SAO…),
tạo hàng loạt từ Excel, lịch sử phiên bản, sao lưu & chuyển máy."""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field


# ================================================================== nén theo dung lượng
def _recompress(pdf_bytes: bytes, dpi: int, quality: int, gray: bool) -> bytes:
    """Nén lại ảnh lớn (trang scan, ảnh chụp) về dpi/chất lượng cho trước. Ảnh nhỏ, ảnh trong suốt,
    ảnh đen trắng 1 bit giữ nguyên."""
    import pikepdf
    from PIL import Image
    from pikepdf import Name, PdfImage
    pk = pikepdf.open(io.BytesIO(pdf_bytes))
    done = {}
    try:
        for page in pk.pages:
            box = [float(v) for v in page.mediabox]
            pw_in = max(abs(box[2] - box[0]), 1) / 72
            ph_in = max(abs(box[3] - box[1]), 1) / 72
            for name, raw in list(page.images.items()):
                key = raw.objgen
                if key in done:
                    continue
                done[key] = True
                try:
                    if "/SMask" in raw or "/Mask" in raw or int(raw.get("/BitsPerComponent", 8)) < 8:
                        continue
                    pim = PdfImage(raw)
                    w, h = pim.width, pim.height
                    cur_dpi = max(w / pw_in, h / ph_in)
                    if w * h < 250_000:                   # ảnh nhỏ (logo, dấu) -> để nguyên
                        continue
                    img = pim.as_pil_image()
                    k = min(1.0, dpi / cur_dpi) if cur_dpi > dpi else 1.0
                    if k < 1:
                        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
                    mode = "L" if gray or img.mode in ("L", "1") else "RGB"
                    img = img.convert(mode)
                    b = io.BytesIO()
                    img.save(b, "JPEG", quality=quality, optimize=True)
                    data = b.getvalue()
                    if len(data) >= len(raw.read_raw_bytes()) and k == 1 and not gray:
                        continue                          # không nhỏ hơn -> giữ ảnh gốc
                    raw.write(data, filter=Name.DCTDecode)
                    raw.Width, raw.Height = img.width, img.height
                    raw.ColorSpace = Name.DeviceGray if mode == "L" else Name.DeviceRGB
                    raw.BitsPerComponent = 8
                    for k2 in ("/DecodeParms", "/Decode"):
                        if k2 in raw:
                            del raw[k2]
                except Exception:
                    continue
        pk.remove_unreferenced_resources()
        out = io.BytesIO()
        pk.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True)
        return out.getvalue()
    finally:
        pk.close()


LEVELS = [(200, 80), (150, 72), (150, 60), (120, 55), (100, 50), (85, 45), (72, 40)]


def compress_to_size(pdf_bytes: bytes, target_bytes: int | None = None, gray: bool = False,
                     level: int | None = None, progress=None) -> tuple[bytes, str]:
    """Nén dần tới khi đạt dung lượng mong muốn (vd. cổng dịch vụ công giới hạn 5 MB/10 MB).
    Trả về (bytes, mô tả mức đã dùng). level: dùng đúng một mức (0 = nhẹ … 6 = mạnh nhất)."""
    if level is not None:
        dpi, q = LEVELS[level]
        return _recompress(pdf_bytes, dpi, q, gray), f"{dpi} dpi, chất lượng {q}"
    best = pdf_bytes
    desc = "giữ nguyên"
    for k, (dpi, q) in enumerate(LEVELS):
        if progress:
            progress(k + 1, len(LEVELS))
        out = _recompress(pdf_bytes, dpi, q, gray)
        if len(out) < len(best):
            best, desc = out, f"{dpi} dpi, chất lượng {q}"
        if target_bytes and len(best) <= target_bytes:
            break
    return best, desc


# ================================================================== so sánh 2 bản
@dataclass
class PageDiff:
    page: int                         # chỉ số trang (0-based) theo bản mới
    boxes: list = field(default_factory=list)    # vùng khác nhau, toạ độ pt trên trang bản mới
    removed: list = field(default_factory=list)  # chữ bị xóa
    added: list = field(default_factory=list)    # chữ thêm vào


def _words(t: str) -> list[str]:
    return re.findall(r"\S+", t)


def compare_docs(a, b, dpi: int = 50, cell_pt: float = 12.0) -> tuple[list[PageDiff], str]:
    """So sánh bản cũ a và bản mới b (PdfDocument). Trả về danh sách trang khác nhau + tóm tắt."""
    from PIL import ImageChops
    diffs = []
    n = max(a.page_count, b.page_count)
    for i in range(n):
        if i >= a.page_count or i >= b.page_count:
            diffs.append(PageDiff(min(i, b.page_count - 1), [], [] if i < a.page_count else [], []))
            continue
        ta, tb = _words(a.text(i)), _words(b.text(i))
        removed, added = [], []
        if ta != tb:
            sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
            for op, a0, a1, b0, b1 in sm.get_opcodes():
                if op in ("replace", "delete"):
                    removed.append(" ".join(ta[a0:a1]))
                if op in ("replace", "insert"):
                    added.append(" ".join(tb[b0:b1]))
        k = dpi / 72
        ia = a.render(i, k).to_pil().convert("L")
        ib = b.render(i, k).to_pil().convert("L")
        if ia.size != ib.size:
            ia = ia.resize(ib.size)
        diff = ImageChops.difference(ia, ib).point(lambda v: 255 if v > 48 else 0)
        boxes = []
        if diff.getbbox():
            c = max(2, int(cell_pt * k))
            W, H = diff.size
            cells = set()
            for y in range(0, H, c):
                for x in range(0, W, c):
                    if diff.crop((x, y, min(W, x + c), min(H, y + c))).getbbox():
                        cells.add((x // c, y // c))
            boxes = _merge_cells(cells, c / k)
        if boxes or removed or added:
            diffs.append(PageDiff(i, boxes, removed, added))
    extra = ""
    if a.page_count != b.page_count:
        extra = f" Số trang: {a.page_count} → {b.page_count}."
    summary = (f"Khác nhau ở {len(diffs)} trang: " + ", ".join(str(d.page + 1) for d in diffs[:20]) + "." if diffs
               else "Hai bản giống nhau.") + extra
    return diffs, summary


def _merge_cells(cells: set, size: float) -> list[tuple]:
    """Gộp các ô khác nhau liền kề thành khung chữ nhật."""
    boxes = []
    seen = set()
    for c in sorted(cells):
        if c in seen:
            continue
        stack, comp = [c], []
        seen.add(c)
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                nb = (x + d[0], y + d[1])
                if nb in cells and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        xs, ys = [p[0] for p in comp], [p[1] for p in comp]
        boxes.append((min(xs) * size, min(ys) * size, (max(xs) + 1) * size, (max(ys) + 1) * size))
    return boxes


def make_compare_report(a, b, diffs: list[PageDiff], summary: str):
    """Bản mới có khung đỏ đánh dấu chỗ khác + trang tóm tắt ở đầu (PdfDocument mới)."""
    from . import editing, fonts
    from .document import PdfDocument
    rep = PdfDocument(data=b.to_bytes())
    for d in diffs:
        if d.page < rep.page_count:
            shapes = [("rect", (x0 - 2, y0 - 2, x1 + 2, y1 + 2), "#e00000", 1.2, None) for x0, y0, x1, y1 in d.boxes]
            if shapes:
                editing.add_shapes(rep, d.page, shapes, snapshot=False)
    rep.insert_blank(-1)
    lines = [(50, 50, "BÁO CÁO SO SÁNH HAI BẢN", 16, "#000000"),
             (50, 80, f"Bản cũ: {a.name}   ·   Bản mới: {b.name}", 9, "#444444"),
             (50, 96, summary, 10, "#b00000")]
    y = 125
    for d in diffs:
        if y > 780:
            break
        lines.append((50, y, f"Trang {d.page + 1}:", 10, "#000000"))
        y += 15
        for label, items, col in (("Bỏ đi", d.removed, "#b00000"), ("Thêm vào", d.added, "#006400")):
            for t in items[:6]:
                if y > 790:
                    break
                lines.append((66, y, f"{label}: {t[:110]}", 9, col))
                y += 13
        y += 6
    font = fonts.system_font("sans")
    safe = [(x, yy, "".join(ch for ch in t if not fonts.missing_chars(font, ch)), s, c) for x, yy, t, s, c in lines]
    editing.add_texts(rep, 0, safe, font, snapshot=False)
    rep.modified = True
    return rep


# ================================================================== dấu chữ
STAMP_TEXTS = ["ĐÃ DUYỆT", "BẢN SAO", "BẢN CHÍNH", "MẬT", "NHÁP", "ĐÃ THANH TOÁN", "HỦY", "LƯU HÀNH NỘI BỘ"]


def text_stamp(doc, pages, text: str, style: str = "watermark", color: str = "#d32f2f", opacity: float = 0.25,
               size: float | None = None, position: str = "top-right"):
    """style: watermark (chữ lớn chéo giữa trang, mờ) | box (khung chữ như con dấu, đặt ở góc)."""
    import math
    import pypdfium2.raw as C
    from . import editing, fonts
    font_path = fonts.system_font("sans", bold=True)
    doc._snapshot()
    r, g, b, _ = editing._rgba(color)
    alpha = int(255 * (opacity if style == "watermark" else 1.0))
    data = fonts.subset(font_path, "".join(sorted(set(text))))
    asc, desc = fonts.metrics(font_path)
    for i in pages:
        pw, ph = doc.page_size_pt(i)
        fr = editing._Frame(doc, i)
        objs = []
        font = editing._load_font(doc, data)
        try:
            if style == "watermark":
                sz = size or min(pw, ph) * 0.14
                tw = fonts.measure(font_path, text, sz)
                ang = math.atan2(ph, pw)
                diag = math.hypot(pw, ph)
                if tw > diag * 0.85:
                    sz *= diag * 0.85 / tw
                    tw = fonts.measure(font_path, text, sz)
                ca, sa = math.cos(ang), math.sin(ang)
                dx, dy = ca, -sa                   # hướng dòng chữ trên màn hình (chéo lên phải)
                ux, uy = -sa, -ca                  # hướng "lên" của chữ
                midh = asc * sz * 0.36
                ox = pw / 2 - dx * tw / 2 - ux * midh
                oy = ph / 2 - dy * tw / 2 - uy * midh
                o = fr.u(ox, oy)
                m = C.FS_MATRIX(dx * fr.ex[0] + dy * fr.ey[0], dx * fr.ex[1] + dy * fr.ey[1],
                                ux * fr.ex[0] + uy * fr.ey[0], ux * fr.ex[1] + uy * fr.ey[1], o[0], o[1])
                obj = editing._text_obj(doc, font, sz, text, m, (r, g, b, alpha))
                objs.append(obj)
            else:
                sz = size or 16
                tw = fonts.measure(font_path, text, sz)
                pad = sz * 0.45
                bw, bh = tw + 2 * pad, (asc + desc) * sz + 2 * pad * 0.8
                margin = 28
                x = pw - bw - margin if "right" in position else margin
                y = margin if "top" in position else ph - bh - margin
                if position == "center":
                    x, y = (pw - bw) / 2, (ph - bh) / 2
                objs += editing.shape_objects(fr, "rect", x, y, x + bw, y + bh, stroke=(r, g, b, 255),
                                              width=max(1.2, sz * 0.09))
                objs += editing.shape_objects(fr, "rect", x + sz * 0.15, y + sz * 0.15, x + bw - sz * 0.15,
                                              y + bh - sz * 0.15, stroke=(r, g, b, 255), width=max(0.5, sz * 0.03))
                objs.append(editing._text_obj(doc, font, sz, text, fr.matrix_at(x + pad, y + pad * 0.8 + asc * sz),
                                              (r, g, b, 255)))
        finally:
            C.FPDFFont_Close(font)
        page = doc.page(i)
        for o in objs:
            C.FPDFPage_InsertObject(page.raw, o)
        page.gen_content()
    doc._changed()


# ================================================================== tạo hàng loạt từ Excel
def read_table(path: str) -> tuple[list[str], list[list[str]]]:
    """Đọc Excel (.xlsx) hoặc CSV -> (tiêu đề cột, các dòng). Không cần cài thêm thư viện."""
    if path.lower().endswith((".csv", ".txt")):
        import csv
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "cp1258", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text.splitlines()[0] if text else ",", delimiters=",;\t")
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    else:
        rows = _read_xlsx(path)
    if not rows:
        return [], []
    head = [h.strip() for h in rows[0]]
    body = [r + [""] * (len(head) - len(r)) for r in rows[1:]]
    return head, body


def _read_xlsx(path: str) -> list[list[str]]:
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheet = "xl/worksheets/sheet1.xml"
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            first = wb.find("m:sheets/m:sheet", ns)
            rid = first.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            for r in rels:
                if r.get("Id") == rid:
                    t = r.get("Target").lstrip("/")
                    sheet = t if t.startswith("xl/") else "xl/" + t
        except Exception:
            pass
        root = ET.fromstring(z.read(sheet))
    rows = []
    for row in root.iter("{%s}row" % ns["m"]):
        cells = {}
        for c in row.findall("m:c", ns):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0) if ref else "A":
                col = col * 26 + ord(ch) - 64
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None and v.text else ""
                if re.fullmatch(r"-?\d+\.0", val):
                    val = val[:-2]
            cells[col - 1] = val
        if cells:
            rows.append([cells.get(k, "") for k in range(max(cells) + 1)])
    return rows


def placeholders(doc) -> list[str]:
    """Các chỗ cần điền dạng {{Tên cột}} trong mẫu."""
    found = []
    for i in range(doc.page_count):
        for m in re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", doc.text(i)):
            if m not in found:
                found.append(m)
    return found


def batch_from_table(template_bytes: bytes, head: list[str], rows: list[list[str]], out_dir: str,
                     name_col: str | None = None, progress=None) -> tuple[list[str], list[str]]:
    """Mỗi dòng Excel -> một file PDF: thay {{Tên cột}} bằng giá trị. Trả về (file đã tạo, cảnh báo)."""
    from . import editing
    from .document import PdfDocument
    os.makedirs(out_dir, exist_ok=True)
    made, warns = [], []
    for k, row in enumerate(rows, 1):
        d = PdfDocument(data=template_bytes)
        try:
            for col, val in zip(head, row):
                for pat in ("{{%s}}" % col, "{{ %s }}" % col):
                    done, left = editing.find_replace(d, pat, val, match_case=True)
                    if left:
                        warns.append(f"Dòng {k}: “{pat}” bị tách đoạn trong mẫu, không thay được {left} chỗ.")
            rest = placeholders(d)
            if rest and k == 1:
                warns.append("Mẫu có chỗ cần điền không có cột tương ứng trong Excel: " + ", ".join(rest))
            base = row[head.index(name_col)] if name_col in head else f"{k:03d}"
            base = re.sub(r'[\\/:*?"<>|]+', "_", base).strip() or f"{k:03d}"
            path = os.path.join(out_dir, base + ".pdf")
            n = 2
            while os.path.exists(path) or path in made:
                path = os.path.join(out_dir, f"{base} ({n}).pdf")
                n += 1
            d.save(path)
            made.append(path)
        finally:
            d.close()
        if progress:
            progress(k, len(rows))
    return made, warns


# ================================================================== lịch sử phiên bản
MAX_VERSIONS = 20
MAX_HISTORY_BYTES = 500 * 1024 * 1024


def history_dir(path: str) -> str:
    from .library import data_dir
    key = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(data_dir(), "lich_su", key)


def keep_version(path: str) -> str | None:
    """Trước khi ghi đè file: cất bản hiện có vào lịch sử (giữ 20 bản gần nhất, tổng tối đa 500 MB)."""
    if not os.path.exists(path):
        return None
    d = history_dir(path)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ten_file.txt"), "w", encoding="utf-8") as f:
        f.write(os.path.abspath(path))
    dst = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}.pdf")
    shutil.copy2(path, dst)
    vers = versions(path)
    for old in vers[MAX_VERSIONS:]:
        try:
            os.remove(old["file"])
        except OSError:
            pass
    _trim_history()
    return dst


def versions(path: str) -> list[dict]:
    d = history_dir(path)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.endswith(".pdf"):
            p = os.path.join(d, f)
            st = os.stat(p)
            out.append({"file": p, "time": st.st_mtime, "size": st.st_size,
                        "label": time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(st.st_mtime))})
    return out


def _trim_history():
    from .library import data_dir
    root = os.path.join(data_dir(), "lich_su")
    files = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(".pdf"):
                p = os.path.join(dp, f)
                files.append((os.path.getmtime(p), os.path.getsize(p), p))
    total = sum(s for _, s, _ in files)
    for _, s, p in sorted(files):
        if total <= MAX_HISTORY_BYTES:
            break
        try:
            os.remove(p)
            total -= s
        except OSError:
            pass


def delete_version(ver: dict) -> bool:
    """Xóa một bản cũ trong lịch sử phiên bản."""
    try:
        os.remove(ver["file"])
        return True
    except OSError:
        return False


def clear_versions(path: str | None = None) -> int:
    """Xóa lịch sử phiên bản của một file (path) hoặc của tất cả các file (path=None). Trả về số bản đã xóa."""
    from .library import data_dir
    root = history_dir(path) if path else os.path.join(data_dir(), "lich_su")
    n = sum(1 for _, _, fs in os.walk(root) for f in fs if f.endswith(".pdf")) if os.path.isdir(root) else 0
    shutil.rmtree(root, ignore_errors=True)
    return n


# ================================================================== xóa lịch sử file đã xử lý
# (chuyển sang app/retention.py: thêm thời hạn tự xóa và các mục mới; giữ tên cũ cho tương thích)
from .retention import HISTORY_PARTS, clear_history, history_summary  # noqa: E402,F401


# ================================================================== sao lưu & chuyển máy
def backup(dest_zip: str, settings: dict) -> list[str]:
    """Gói thư viện dấu (vẫn mã hóa nếu có mật khẩu), nhật ký, mẫu khay, cài đặt vào 1 file .zip."""
    from .library import data_dir
    src = data_dir()
    names = []
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(src)):
            p = os.path.join(src, f)
            if os.path.isfile(p) and not f.endswith((".tmp", ".lock")) and f != "license.dat":
                z.write(p, f)
                names.append(f)
        z.writestr("settings.json", json.dumps(settings, ensure_ascii=False, indent=1))
        z.writestr("thong_tin.txt", f"Sao lưu PDF Ký Số lúc {time.strftime('%d/%m/%Y %H:%M')}\n"
                                    "Bản quyền không nằm trong bản sao lưu (gắn với từng máy).\n")
    return names


def restore(src_zip: str) -> dict:
    """Khôi phục từ bản sao lưu. File đang có được giữ lại với đuôi .truoc_khoi_phuc. Trả về cài đặt."""
    from .library import data_dir
    dst = data_dir()
    settings = {}
    with zipfile.ZipFile(src_zip) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename)
            if not name or name in ("thong_tin.txt",):
                continue
            if name == "settings.json":
                settings = json.loads(z.read(info).decode("utf-8"))
                continue
            target = os.path.join(dst, name)
            if os.path.exists(target):
                shutil.copy2(target, target + ".truoc_khoi_phuc")
            with open(target, "wb") as f:
                f.write(z.read(info))
    return settings
