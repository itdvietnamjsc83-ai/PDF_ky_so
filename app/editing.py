"""Giai đoạn 5 – chỉnh sửa nội dung trang.

Mọi thứ thêm vào trang đều là đối tượng PDF thật (vector / chữ thật), không phải ảnh chụp:
nét luôn sắc khi phóng to hay in, file tăng rất ít, chữ vẫn tìm kiếm/sao chép được.

- Hộp chữ, chữ viết tay bằng phông: đối tượng chữ, phông nhúng dạng rút gọn (vài KB).
- Hình vẽ, ký hiệu, nét vẽ tay, bút dạ quang: đường vector.
- Ghi chú: chú thích (annotation) kiểu "sticky note" – mở ra đọc được trong mọi phần mềm PDF.
- Che/tẩy vùng: gỡ hẳn chữ nằm trong vùng + phủ nền trắng (trang scan: phủ trắng phần ảnh).
- Sửa chữ (chỉ PDF từ Word/Excel): thay đối tượng chữ bằng chữ mới cùng vị trí, cỡ, màu, kiểu phông.

Toạ độ nhận vào: toạ độ hiển thị (pt, gốc trên-trái, đã tính xoay trang) như trên màn hình.
"""
from __future__ import annotations

import ctypes
import math
import os
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as C

from . import fonts

K_BEZ = 0.5522847498                  # hệ số xấp xỉ cung tròn bằng Bézier


def _rgba(color) -> tuple[int, int, int, int]:
    if isinstance(color, str):
        c = color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        a = int(c[6:8], 16) if len(c) >= 8 else 255
        return r, g, b, a
    if len(color) == 3:
        return (*color, 255)
    return tuple(color)


def _wide(text: str):
    b = (text + "\0").encode("utf-16-le")
    buf = ctypes.create_string_buffer(b, len(b))
    return buf, ctypes.cast(buf, C.FPDF_WIDESTRING)


class _Frame:
    """Hệ toạ độ hiển thị của một trang -> toạ độ PDF (có /Rotate, CropBox)."""

    def __init__(self, doc, i: int):
        self.doc, self.i = doc, i
        self.o = doc.display_to_user(i, 0, 0)
        ex = doc.display_to_user(i, 1, 0)
        ey = doc.display_to_user(i, 0, 1)
        self.ex = (ex[0] - self.o[0], ex[1] - self.o[1])      # 1 pt sang phải trên màn hình
        self.ey = (ey[0] - self.o[0], ey[1] - self.o[1])      # 1 pt xuống dưới trên màn hình

    def u(self, x: float, y: float) -> tuple[float, float]:
        return (self.o[0] + x * self.ex[0] + y * self.ey[0], self.o[1] + x * self.ex[1] + y * self.ey[1])

    def matrix_at(self, x: float, y: float, scale: float = 1.0, hscale: float = 1.0):
        """Ma trận đặt chữ/ảnh đứng thẳng khi nhìn trên màn hình, gốc tại (x, y).
        hscale < 1: co ngang (chữ hẹp lại, giữ nguyên chiều cao)."""
        ox, oy = self.u(x, y)
        hs = scale * hscale
        return C.FS_MATRIX(self.ex[0] * hs, self.ex[1] * hs, -self.ey[0] * scale, -self.ey[1] * scale, ox, oy)

    def display_rect(self, left, bottom, right, top):
        """Khung PDF -> khung hiển thị (x0, y0, x1, y1)."""
        pts = [self.doc.user_to_display(self.i, x, y) for x, y in ((left, bottom), (right, top), (left, top), (right, bottom))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------ đường vector
def _new_path(fr: _Frame, pts, closed=False, curves=None):
    x0, y0 = fr.u(*pts[0])
    obj = C.FPDFPageObj_CreateNewPath(x0, y0)
    if curves:
        for c1, c2, p in curves:
            a, b, c = fr.u(*c1), fr.u(*c2), fr.u(*p)
            C.FPDFPath_BezierTo(obj, a[0], a[1], b[0], b[1], c[0], c[1])
    else:
        for p in pts[1:]:
            x, y = fr.u(*p)
            C.FPDFPath_LineTo(obj, x, y)
    if closed:
        C.FPDFPath_Close(obj)
    return obj


def _style(obj, stroke=None, width=1.0, fill=None, round_=True, blend: str | None = None, dash=None):
    if stroke is not None:
        C.FPDFPageObj_SetStrokeColor(obj, *_rgba(stroke))
        C.FPDFPageObj_SetStrokeWidth(obj, float(width))
    if fill is not None:
        C.FPDFPageObj_SetFillColor(obj, *_rgba(fill))
    C.FPDFPath_SetDrawMode(obj, C.FPDF_FILLMODE_WINDING if fill is not None else C.FPDF_FILLMODE_NONE,
                           bool(stroke is not None))
    if round_:
        C.FPDFPageObj_SetLineCap(obj, C.FPDF_LINECAP_ROUND)
        C.FPDFPageObj_SetLineJoin(obj, C.FPDF_LINEJOIN_ROUND)
    if blend:
        C.FPDFPageObj_SetBlendMode(obj, blend.encode())
    if dash:
        arr = (ctypes.c_float * len(dash))(*dash)
        C.FPDFPageObj_SetDashArray(obj, arr, len(dash), 0.0)
    return obj


def _insert(doc, i, objs, snapshot=True):
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    for o in objs:
        C.FPDFPage_InsertObject(page.raw, o)
    page.gen_content()
    if snapshot:
        doc._changed()


def ellipse_curves(x0, y0, x1, y1):
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
    kx, ky = rx * K_BEZ, ry * K_BEZ
    start = (cx + rx, cy)
    curves = [((cx + rx, cy + ky), (cx + kx, cy + ry), (cx, cy + ry)),
              ((cx - kx, cy + ry), (cx - rx, cy + ky), (cx - rx, cy)),
              ((cx - rx, cy - ky), (cx - kx, cy - ry), (cx, cy - ry)),
              ((cx + kx, cy - ry), (cx + rx, cy - ky), (cx + rx, cy))]
    return start, curves


def shape_objects(fr: _Frame, kind: str, x0, y0, x1, y1, stroke="#d32f2f", width=1.5, fill=None):
    """kind: rect, ellipse, line, arrow, highlight, check, cross, dot, box, boxcheck, circle."""
    if kind == "rect":
        return [_style(_new_path(fr, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True), stroke, width, fill,
                       round_=False)]
    if kind == "ellipse" or kind == "circle":
        if kind == "circle":
            r = max(abs(x1 - x0), abs(y1 - y0)) / 2
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            x0, y0, x1, y1 = cx - r, cy - r, cx + r, cy + r
        start, curves = ellipse_curves(x0, y0, x1, y1)
        return [_style(_new_path(fr, [start], closed=True, curves=curves), stroke, width, fill)]
    if kind == "line":
        return [_style(_new_path(fr, [(x0, y0), (x1, y1)]), stroke, width)]
    if kind == "arrow":
        ang = math.atan2(y1 - y0, x1 - x0)
        head = max(6.0, width * 4)
        a1 = (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45))
        a2 = (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))
        back = (x1 - head * 0.8 * math.cos(ang), y1 - head * 0.8 * math.sin(ang))
        return [_style(_new_path(fr, [(x0, y0), back]), stroke, width),
                _style(_new_path(fr, [(x1, y1), a1, a2], closed=True), stroke, width * 0.5, stroke)]
    if kind == "highlight":                     # bút dạ quang: vàng trong suốt, chữ bên dưới vẫn rõ
        r, g, b, _ = _rgba(fill or "#ffe600")
        return [_style(_new_path(fr, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True), None, 0,
                       (r, g, b, 110), round_=False, blend="Multiply")]
    s = max(abs(x1 - x0), abs(y1 - y0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = s / 2
    if kind == "check":
        pts = [(cx - h * 0.8, cy), (cx - h * 0.25, cy + h * 0.6), (cx + h * 0.85, cy - h * 0.7)]
        return [_style(_new_path(fr, pts), stroke, max(width, s * 0.12))]
    if kind == "cross":
        return [_style(_new_path(fr, [(cx - h * .7, cy - h * .7), (cx + h * .7, cy + h * .7)]), stroke, max(width, s * .12)),
                _style(_new_path(fr, [(cx + h * .7, cy - h * .7), (cx - h * .7, cy + h * .7)]), stroke, max(width, s * .12))]
    if kind == "dot":
        start, curves = ellipse_curves(cx - h * .45, cy - h * .45, cx + h * .45, cy + h * .45)
        return [_style(_new_path(fr, [start], closed=True, curves=curves), None, 0, stroke)]
    if kind in ("box", "boxcheck"):
        objs = [_style(_new_path(fr, [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)],
                                 closed=True), stroke, max(width * 0.7, s * 0.06), round_=False)]
        if kind == "boxcheck":
            objs += shape_objects(fr, "check", cx - h * .8, cy - h * .8, cx + h * .8, cy + h * .8, stroke, width)
        return objs
    raise ValueError(kind)


def add_shape(doc, i: int, kind: str, rect, stroke="#d32f2f", width=1.5, fill=None, snapshot=True):
    fr = _Frame(doc, i)
    _insert(doc, i, shape_objects(fr, kind, *rect, stroke=stroke, width=width, fill=fill), snapshot)


def simplify(points, eps=0.35):
    """Ramer–Douglas–Peucker: bỏ điểm thừa của nét vẽ tay (file nhỏ, nét mượt)."""
    if len(points) < 3:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1e-9
    best, idx = -1.0, 0
    for k in range(1, len(points) - 1):
        px, py = points[k]
        d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / n if n > 1e-9 else math.hypot(px - x0, py - y0)
        if d > best:
            best, idx = d, k
    if best <= eps:
        return [points[0], points[-1]]
    return simplify(points[:idx + 1], eps)[:-1] + simplify(points[idx:], eps)


def smooth_curves(pts):
    """Catmull-Rom -> Bézier: nét vẽ tay mềm như bút thật."""
    curves = []
    for k in range(len(pts) - 1):
        p0 = pts[k - 1] if k > 0 else pts[k]
        p1, p2 = pts[k], pts[k + 1]
        p3 = pts[k + 2] if k + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        curves.append((c1, c2, p2))
    return curves


def add_ink(doc, i: int, strokes: list[list[tuple[float, float]]], color="#0d47a1", width=1.2, snapshot=True):
    """Nét vẽ tay (mỗi nét là danh sách điểm hiển thị)."""
    fr = _Frame(doc, i)
    objs = []
    for s in strokes:
        if not s:
            continue
        if len(s) == 1:
            s = [s[0], (s[0][0] + 0.01, s[0][1])]
        pts = simplify(s)
        objs.append(_style(_new_path(fr, pts[:1], curves=smooth_curves(pts)), color, width))
    if objs:
        _insert(doc, i, objs, snapshot)


# ------------------------------------------------------------------ chữ
def _load_font(doc, data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    doc.__dict__.setdefault("_font_bufs", []).append(buf)      # giữ bộ nhớ tới khi tài liệu đóng
    f = C.FPDFText_LoadFont(doc.pdf.raw, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)), len(data),
                            C.FPDF_FONT_TRUETYPE, True)
    if not f:
        raise RuntimeError("Không nạp được phông chữ")
    return f


def _text_obj(doc, font, size, text, matrix, color):
    obj = C.FPDFPageObj_CreateTextObj(doc.pdf.raw, font, float(size))
    buf, ptr = _wide(text)
    C.FPDFText_SetText(obj, ptr)
    C.FPDFPageObj_SetFillColor(obj, *_rgba(color))
    C.FPDFPageObj_SetMatrix(obj, ctypes.byref(matrix))
    return obj


def add_text(doc, i: int, x: float, y: float, text: str, font_path: str | None = None, size: float = 12,
             color="#000000", line_height: float = 1.25, width: float | None = None, snapshot=True):
    """Chèn chữ. (x, y) = góc trên-trái của khối chữ (toạ độ hiển thị). width: tự ngắt dòng.
    Trả về khung hiển thị (x0, y0, x1, y1) của khối chữ."""
    font_path = font_path or fonts.system_font("serif")
    lines = fonts.wrap(font_path, text, size, width) if width else text.split("\n")
    chars = "".join(sorted(set(text) - {"\n"}))
    miss = fonts.missing_chars(font_path, chars)
    if miss:
        raise ValueError(f"Phông chữ không có ký tự: {miss}")
    font = _load_font(doc, fonts.subset(font_path, chars))
    asc, desc = fonts.metrics(font_path)
    fr = _Frame(doc, i)
    objs = []
    lh = size * line_height
    maxw = 0.0
    try:
        for k, line in enumerate(lines):
            if not line.strip():
                continue
            base_y = y + asc * size + k * lh
            objs.append(_text_obj(doc, font, size, line, fr.matrix_at(x, base_y), color))
            maxw = max(maxw, fonts.measure(font_path, line, size))
    finally:
        C.FPDFFont_Close(font)
    if objs:
        _insert(doc, i, objs, snapshot)
    h = (len(lines) - 1) * lh + (asc + desc) * size
    return (x, y, x + (width or maxw), y + h)


def add_texts(doc, i: int, items, font_path: str | None = None, snapshot=True):
    """Chèn nhiều dòng chữ cùng phông một lần (1 phông nhúng dùng chung, 1 lần ghi nội dung trang).
    items: [(x_trái, y_trên, chữ, cỡ, màu)]."""
    font_path = font_path or fonts.system_font("serif")
    chars = "".join(sorted({c for it in items for c in it[2]} - {"\n"}))
    font = _load_font(doc, fonts.subset(font_path, chars))
    asc, _ = fonts.metrics(font_path)
    fr = _Frame(doc, i)
    objs = []
    try:
        for x, y, text, size, color in items:
            for k, line in enumerate(text.split("\n")):
                if line.strip():
                    objs.append(_text_obj(doc, font, size, line, fr.matrix_at(x, y + asc * size + k * size * 1.25), color))
    finally:
        C.FPDFFont_Close(font)
    _insert(doc, i, objs, snapshot)


def add_shapes(doc, i: int, shapes, snapshot=True):
    """Nhiều hình một lần: shapes = [(loại, rect, nét, độ dày, nền)]."""
    fr = _Frame(doc, i)
    objs = []
    for kind, rect, stroke, width, fill in shapes:
        objs += shape_objects(fr, kind, *rect, stroke=stroke, width=width, fill=fill)
    _insert(doc, i, objs, snapshot)


def add_page_numbers(doc, pages, fmt: str = "Trang {n} / {total}", size: float = 9, color="#555555",
                     start: int | None = None, snapshot=True):
    """Đánh số chân trang (giữa, cách mép dưới 22 pt). Một phông nhúng dùng chung cho mọi trang."""
    if not pages:
        return
    font_path = fonts.system_font("serif")
    total = doc.page_count
    first = pages[0] + 1 if start is None else start
    labels = {i: fmt.format(n=i + 1, total=total) for i in pages} if start is None else \
        {i: fmt.format(n=first + k, total=first + len(pages) - 1) for k, i in enumerate(pages)}
    chars = "".join(sorted(set("".join(labels.values()))))
    if snapshot:
        doc._snapshot()
    font = _load_font(doc, fonts.subset(font_path, chars))
    asc, _ = fonts.metrics(font_path)
    try:
        for i in pages:
            pw, ph = doc.page_size_pt(i)
            t = labels[i]
            x = (pw - fonts.measure(font_path, t, size)) / 2
            fr = _Frame(doc, i)
            obj = _text_obj(doc, font, size, t, fr.matrix_at(x, ph - 22 - size + asc * size), color)
            page = doc.page(i)
            C.FPDFPage_InsertObject(page.raw, obj)
            page.gen_content()
    finally:
        C.FPDFFont_Close(font)
    if snapshot:
        doc._changed()


def add_note(doc, i: int, x: float, y: float, text: str, author: str = "", color="#ffd400", snapshot=True):
    """Ghi chú dạng sticky note (biểu tượng nhỏ trên trang, bấm vào để đọc)."""
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    ux, uy = doc.display_to_user(i, x, y)
    annot = C.FPDFPage_CreateAnnot(page.raw, C.FPDF_ANNOT_TEXT)
    if not annot:
        raise RuntimeError("Không tạo được ghi chú")
    try:
        r = C.FS_RECTF(ux, uy, ux + 20, uy - 20)
        C.FPDFAnnot_SetRect(annot, r)
        for key, val in (("Contents", text), ("T", author or "")):
            buf, ptr = _wide(val)
            C.FPDFAnnot_SetStringValue(annot, key.encode(), ptr)
        C.FPDFAnnot_SetColor(annot, C.FPDFANNOT_COLORTYPE_Color, *_rgba(color))
        buf, ptr = _wide("Comment")
        C.FPDFAnnot_SetStringValue(annot, b"Name", ptr)
    finally:
        C.FPDFPage_CloseAnnot(annot)
    if snapshot:
        doc._changed()


def notes(doc, i: int) -> list[str]:
    page = doc.page(i)
    out = []
    for k in range(C.FPDFPage_GetAnnotCount(page.raw)):
        a = C.FPDFPage_GetAnnot(page.raw, k)
        try:
            if C.FPDFAnnot_GetSubtype(a) == C.FPDF_ANNOT_TEXT:
                n = C.FPDFAnnot_GetStringValue(a, b"Contents", None, 0)
                buf = ctypes.create_string_buffer(n)
                C.FPDFAnnot_GetStringValue(a, b"Contents", ctypes.cast(buf, ctypes.POINTER(C.FPDF_WCHAR)), n)
                out.append(buf.raw[:n].decode("utf-16-le").rstrip("\0"))
        finally:
            C.FPDFPage_CloseAnnot(a)
    return out


# ------------------------------------------------------------------ đối tượng chữ có sẵn (sửa chữ)
@dataclass
class TextRun:
    index: int                   # vị trí đối tượng trên trang
    text: str
    size: float                  # cỡ chữ hiệu dụng (pt)
    font_name: str
    bold: bool
    italic: bool
    color: tuple
    rect: tuple                  # khung hiển thị (x0, y0, x1, y1)
    raw: object = None
    orig_size: float | None = None   # 1.0.22: cỡ chữ gốc trước lần sửa đầu tiên (ghi trong file)


def _obj_text(obj, tp_raw) -> str:
    n = C.FPDFTextObj_GetText(obj, tp_raw, None, 0)
    if n <= 0:
        return ""
    buf = ctypes.create_string_buffer(n * 2)
    C.FPDFTextObj_GetText(obj, tp_raw, ctypes.cast(buf, ctypes.POINTER(C.FPDF_WCHAR)), n)
    # khoảng trắng cứng (U+00A0) -> dấu cách thường: tìm / sửa chữ gõ dấu cách bình thường vẫn khớp
    return buf.raw.decode("utf-16-le", errors="ignore").split("\0", 1)[0].replace("\xa0", " ")


def _font_info(obj):
    font = C.FPDFTextObj_GetFont(obj)
    name = ""
    if font:
        n = C.FPDFFont_GetBaseFontName(font, None, 0)
        if n > 0:
            buf = ctypes.create_string_buffer(n)
            C.FPDFFont_GetBaseFontName(font, buf, n)
            name = buf.value.decode("latin-1", errors="ignore")
        weight = C.FPDFFont_GetWeight(font)
        angle = ctypes.c_int(0)
        C.FPDFFont_GetItalicAngle(font, ctypes.byref(angle))
        bold = weight >= 600 or "bold" in name.lower() or "black" in name.lower()
        italic = angle.value != 0 or "italic" in name.lower() or "oblique" in name.lower()
        return name, bold, italic
    return name, False, False


ORIG_MARK = b"PdfKySoGoc"          # dấu đánh dấu nội dung (marked content) ghi cỡ chữ gốc vào chữ đã sửa


def _get_orig_size(obj) -> float | None:
    try:
        for k in range(C.FPDFPageObj_CountMarks(obj)):
            mk = C.FPDFPageObj_GetMark(obj, k)
            buf = (ctypes.c_ushort * 32)()
            n = ctypes.c_ulong(0)
            C.FPDFPageObjMark_GetName(mk, buf, 64, ctypes.byref(n))
            if bytes(buf)[:max(0, n.value - 2)].decode("utf-16-le", "ignore").encode() != ORIG_MARK:
                continue
            v = ctypes.c_float(0)
            if C.FPDFPageObjMark_GetParamFloatValue(mk, b"Size", ctypes.byref(v)) and v.value > 0:
                return nice_size(v.value)
            iv = ctypes.c_int(0)
            if C.FPDFPageObjMark_GetParamIntValue(mk, b"Size", ctypes.byref(iv)) and iv.value > 0:
                return float(iv.value)
    except Exception:
        pass
    return None


def _set_orig_size(doc, obj, size: float):
    try:
        mk = C.FPDFPageObj_AddMark(obj, ORIG_MARK)
        if mk:
            C.FPDFPageObjMark_SetFloatParam(doc.pdf.raw, obj, mk, b"Size", ctypes.c_float(float(size)))
    except Exception:
        pass


def nice_size(v: float) -> float:
    """1.0.22: cỡ chữ đọc từ PDF thường lệch vài phần trăm (12.98, 13.02 do làm tròn ma trận) -> làm tròn về cỡ
    người dùng đã chọn khi soạn (bước 0.5 pt); lệch nhiều thì giữ 1 chữ số thập phân."""
    h = round(v * 2) / 2
    return h if abs(v - h) <= 0.06 else round(v, 1)


def text_runs(doc, i: int) -> list[TextRun]:
    page = doc.page(i)
    tp = page.get_textpage()
    fr = _Frame(doc, i)
    out = []
    try:
        for k in range(C.FPDFPage_CountObjects(page.raw)):
            obj = C.FPDFPage_GetObject(page.raw, k)
            if C.FPDFPageObj_GetType(obj) != C.FPDF_PAGEOBJ_TEXT:
                continue
            txt = _obj_text(obj, tp.raw)
            if not txt.strip():
                continue
            sz = ctypes.c_float(0)
            C.FPDFTextObj_GetFontSize(obj, ctypes.byref(sz))
            m = C.FS_MATRIX()
            C.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
            eff = sz.value * math.hypot(m.c, m.d) if (m.c or m.d) else sz.value
            l, b, r, t = (ctypes.c_float() for _ in range(4))
            C.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(t))
            rgba = [ctypes.c_uint() for _ in range(4)]
            C.FPDFPageObj_GetFillColor(obj, *(ctypes.byref(v) for v in rgba))
            name, bold, italic = _font_info(obj)
            out.append(TextRun(k, txt, nice_size(eff), name, bold, italic, tuple(v.value for v in rgba),
                               fr.display_rect(l.value, b.value, r.value, t.value), obj, _get_orig_size(obj)))
    finally:
        tp.close()
    return out


def run_at(doc, i: int, x: float, y: float, pad: float = 1.5) -> TextRun | None:
    best = None
    for r in text_runs(doc, i):
        x0, y0, x1, y1 = r.rect
        if x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad:
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, r)
    return best[1] if best else None


def replacement_font(run: TextRun) -> str:
    return fonts.system_font(fonts.family_of(run.font_name), run.bold, run.italic)


def _parse_tounicode(data: bytes) -> dict[int, str]:
    """Bảng /ToUnicode của PDF (bfchar, bfrange) -> {mã ký tự (CID): chữ Unicode}."""
    import re
    txt = data.decode("latin-1", "ignore")
    out: dict[int, str] = {}

    def u16(h: str) -> str:
        b = bytes.fromhex(h if len(h) % 2 == 0 else "0" + h)
        try:
            return b.decode("utf-16-be", "ignore")
        except Exception:
            return ""
    for block in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            out[int(a, 16)] = u16(b)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for a, b, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)", block):
            lo, hi = int(a, 16), int(b, 16)
            if hi - lo > 65535:
                continue
            if rest.startswith("["):
                for k, h in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                    out[lo + k] = u16(h)
            else:
                base = u16(rest[1:-1])
                if not base:
                    continue
                for k in range(hi - lo + 1):
                    out[lo + k] = base[:-1] + chr(ord(base[-1]) + k)
    return out


def _cid_font_file(doc, i: int, base_name: str, data: bytes) -> str | None:
    """Phông nhúng kiểu CID (Word, PDF xuất từ Office) thường KHÔNG có bảng cmap -> dựng lại cmap từ /ToUnicode
    của file để dùng lại đúng phông gốc khi sửa chữ (chỉ gõ được các ký tự có sẵn trong bản rút gọn)."""
    import hashlib
    import io as _io
    import tempfile
    try:
        import pikepdf
        from fontTools.ttLib import TTFont, newTable
        from fontTools.ttLib.tables._c_m_a_p import cmap_format_4, cmap_format_12
    except Exception:
        return None
    key = hashlib.sha1(data + base_name.encode("utf-8", "ignore")).hexdigest()[:20]
    path = os.path.join(tempfile.gettempdir(), "pdfkyso-fonts", key + "-cmap.ttf")
    if os.path.isfile(path):
        return path
    cache = doc.__dict__.setdefault("_pk_cache", {})
    pk = cache.get(doc.version)
    if pk is None:
        for old in list(cache.values()):
            try:
                old.close()
            except Exception:
                pass
        cache.clear()
        pk = cache[doc.version] = pikepdf.open(_io.BytesIO(doc.to_bytes()))
    font = None
    try:
        todo, seen = [pk.pages[i].obj.get("/Resources")], set()
        while todo and font is None:
            res = todo.pop()
            if res is None or id(res) in seen:
                continue
            seen.add(id(res))
            for _, f in (res.get("/Font") or {}).items():
                if str(f.get("/BaseFont", "")) .lstrip("/") == base_name:
                    font = f
                    break
            for _, x in (res.get("/XObject") or {}).items():
                if x.get("/Subtype") == "/Form" and x.get("/Resources") is not None:
                    todo.append(x.Resources)
        if font is None or font.get("/Subtype") != "/Type0" or "/ToUnicode" not in font:
            return None
        desc = font.DescendantFonts[0]
        uni = _parse_tounicode(font.ToUnicode.read_bytes())
        c2g = desc.get("/CIDToGIDMap")
        gidmap = None
        if isinstance(c2g, pikepdf.Stream):
            raw = c2g.read_bytes()
            gidmap = {k // 2: (raw[k] << 8) | raw[k + 1] for k in range(0, len(raw) - 1, 2)}
        f = TTFont(_io.BytesIO(data))
        nglyphs = f["maxp"].numGlyphs
        glyf = f["glyf"] if "glyf" in f else None
        order = f.getGlyphOrder()
        mapping = {}
        for cid, txt in uni.items():
            if len(txt) != 1 or txt in "\x00\r\n":
                continue
            gid = gidmap.get(cid, 0) if gidmap is not None else cid
            if not (0 < gid < nglyphs):
                continue
            if glyf is not None and not txt.isspace():
                g = glyf[order[gid]]
                if getattr(g, "numberOfContours", 0) == 0:   # bản rút gọn đã bỏ nét chữ này -> không dùng
                    continue
            mapping.setdefault(ord(txt), gid)
        if len(mapping) < 3:
            return None
        cmap_dict = {u: order[g] for u, g in mapping.items()}
        t = newTable("cmap")
        t.tableVersion = 0
        sub4 = cmap_format_4(4)
        sub4.platformID, sub4.platEncID, sub4.language = 3, 1, 0
        sub4.cmap = {u: n for u, n in cmap_dict.items() if u <= 0xFFFF}
        t.tables = [sub4]
        if any(u > 0xFFFF for u in cmap_dict):
            sub12 = cmap_format_12(12)
            sub12.platformID, sub12.platEncID, sub12.language = 3, 10, 0
            sub12.cmap = dict(cmap_dict)
            t.tables.append(sub12)
        f["cmap"] = t
        if "post" not in f:
            post = newTable("post")
            post.formatType = 3.0
            post.italicAngle = post.underlinePosition = post.underlineThickness = 0
            post.isFixedPitch = post.minMemType42 = post.maxMemType42 = 0
            post.minMemType1 = post.maxMemType1 = 0
            f["post"] = post
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f.save(path)
        return path
    except Exception:
        return None


def embedded_font(run: TextRun, doc=None, i: int | None = None) -> str | None:
    """File phông NHÚNG trong PDF của mảnh chữ (đúng phông gốc), None nếu không lấy ra / không dùng lại được."""
    obj = getattr(run, "raw", None)
    if not obj:
        return None
    try:
        font = C.FPDFTextObj_GetFont(obj)
        if not font or not C.FPDFFont_GetIsEmbedded(font):
            return None
        n = ctypes.c_size_t(0)
        if not C.FPDFFont_GetFontData(font, None, 0, ctypes.byref(n)) or n.value <= 0:
            return None
        buf = (ctypes.c_uint8 * n.value)()
        if not C.FPDFFont_GetFontData(font, buf, n.value, ctypes.byref(n)):
            return None
        data = bytes(buf)
        path = fonts.embedded_font_file(data)
        if path is None and doc is not None and i is not None:
            path = _cid_font_file(doc, i, run.font_name, data)
            if path and not fonts._usable_embedded(path):
                path = None
        return path
    except Exception:
        return None


def original_font(run: TextRun, text: str = "", doc=None, i: int | None = None) -> tuple[str, str]:
    """Phông giống chữ gốc nhất có đủ ký tự của `text`: (đường dẫn, nguồn).
    Thứ tự: phông nhúng trong file -> phông cùng tên đã cài trên máy -> phông cùng họ (Times / Arial...)."""
    need = "".join(sorted(set(text.replace("\n", "")))) if text else ""
    emb = embedded_font(run, doc, i)
    if emb and (not need or not fonts.missing_chars(emb, need)):
        return emb, "embedded"
    inst = fonts.match_installed(run.font_name, run.bold, run.italic)
    if inst and (not need or not fonts.missing_chars(inst, need)):
        return inst, "installed"
    return replacement_font(run), "family"


def replace_run(doc, i: int, run: TextRun, new_text: str, font_path: str | None = None, color=None,
                snapshot=True):
    """Thay nội dung một đối tượng chữ: giữ nguyên vị trí, ma trận, cỡ chữ, màu; phông cùng kiểu."""
    page = doc.page(i)
    obj = C.FPDFPage_GetObject(page.raw, run.index)
    if not obj or C.FPDFPageObj_GetType(obj) != C.FPDF_PAGEOBJ_TEXT:
        raise ValueError("Đối tượng chữ không còn")
    if snapshot:
        doc._snapshot()
        page = doc.page(i)
        obj = C.FPDFPage_GetObject(page.raw, run.index)
    m = C.FS_MATRIX()
    C.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
    sz = ctypes.c_float(0)
    C.FPDFTextObj_GetFontSize(obj, ctypes.byref(sz))
    C.FPDFPage_RemoveObject(page.raw, obj)
    C.FPDFPageObj_Destroy(obj)
    if new_text.strip():
        fp = font_path or replacement_font(run)
        miss = fonts.missing_chars(fp, new_text)
        if miss:
            raise ValueError(f"Phông chữ không có ký tự: {miss}")
        font = _load_font(doc, fonts.subset(fp, "".join(sorted(set(new_text)))))
        try:
            new = _text_obj(doc, font, sz.value, new_text, m, color or run.color)
        finally:
            C.FPDFFont_Close(font)
        if hasattr(C, "FPDFPage_InsertObjectAtIndex"):
            C.FPDFPage_InsertObjectAtIndex(page.raw, new, run.index)
        else:
            C.FPDFPage_InsertObject(page.raw, new)
    page.gen_content()
    if snapshot:
        doc._changed()


# ------------------------------------------------------------------ đợt 4: sửa cả dòng / cả đoạn (11a–11d)
def run_origin(doc, i: int, run: TextRun):
    """(x, y_đường_chân_chữ) hiển thị của mảnh chữ, và mảnh chữ có nằm ngang (không xoay) không."""
    obj = C.FPDFPage_GetObject(doc.page(i).raw, run.index)
    m = C.FS_MATRIX()
    C.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
    x, y = doc.user_to_display(i, m.e, m.f)
    fr = _Frame(doc, i)
    # hướng trục x của chữ trên màn hình
    ux = (m.a, m.b)
    ex = fr.ex
    dot = (ux[0] * ex[0] + ux[1] * ex[1]) / (math.hypot(*ux) * math.hypot(*ex) or 1)
    return (x, y), dot > 0.999


def _same_line(a: TextRun, b: TextRun) -> bool:
    ay0, ay1 = a.rect[1], a.rect[3]
    by0, by1 = b.rect[1], b.rect[3]
    ov = min(ay1, by1) - max(ay0, by0)
    return ov > 0.6 * min(ay1 - ay0, by1 - by0) and 0.7 < (a.size or 1) / (b.size or 1) < 1.4


def line_of(runs, run: TextRun) -> list:
    """11c – các mảnh chữ cùng dòng, liền nhau (khoảng cách < 1.5 cỡ chữ – không nhảy sang ô bảng bên cạnh)."""
    row = sorted([r for r in runs if _same_line(r, run)], key=lambda r: r.rect[0])
    k = next(n for n, r in enumerate(row) if r.index == run.index)
    lo = hi = k
    while lo > 0 and row[lo].rect[0] - row[lo - 1].rect[2] < 1.5 * run.size:
        lo -= 1
    while hi < len(row) - 1 and row[hi + 1].rect[0] - row[hi].rect[2] < 1.5 * run.size:
        hi += 1
    return row[lo:hi + 1]


def paragraph_of(runs, run: TextRun) -> list[list]:
    """11c – các dòng cùng đoạn: cùng lề trái, cùng cỡ, cách dòng đều (≤ 1.9 cỡ chữ). Trả về [[mảnh chữ của dòng]]."""
    first = line_of(runs, run)
    lines = [first]
    left = first[0].rect[0]
    size = run.size
    same = [r for r in runs if abs(r.size - size) <= 0.1 * size and abs(r.rect[0] - left) <= 1.2 * size
            and abs(r.rect[1] - run.rect[1]) < 12 * size]        # các dòng lân cận cùng khối
    right_max = max((r.rect[2] for r in same), default=first[-1].rect[2])

    def full(ln):                                     # dòng chạy tới gần lề phải -> đoạn còn tiếp
        return ln[-1].rect[2] >= right_max - 3 * size

    def next_line(cur, direction):
        cy = cur[0].rect[1] if direction < 0 else cur[0].rect[3]
        cands = []
        for r in runs:
            if abs(r.size - size) > 0.2 * size or abs(r.rect[0] - left) > 1.2 * size:
                continue
            gap = (cy - r.rect[3]) if direction < 0 else (r.rect[1] - cy)
            if -0.2 * size <= gap <= 0.9 * size:
                cands.append((abs(gap), r))
        if not cands:
            return None
        return line_of(runs, min(cands, key=lambda t: t[0])[1])
    cur = first
    while full(cur):
        nxt = next_line(cur, 1)
        if not nxt or any(n.index in {x.index for ln in lines for x in ln} for n in nxt):
            break
        lines.append(nxt)
        cur = nxt
    cur = first
    while True:
        prv = next_line(cur, -1)
        if not prv or not full(prv) or any(n.index in {x.index for ln in lines for x in ln} for n in prv):
            break
        lines.insert(0, prv)
        cur = prv
    return lines


MIN_HSCALE = 0.8        # co ngang tối đa 80% – hẹp hơn nữa thì mới thu nhỏ cỡ chữ


def line_room(doc, i: int, lines, runs=None) -> float:
    """1.0.22: mép phải tối đa (pt) mà dòng chữ được phép kéo dài khi gõ thêm: tới chữ kế tiếp cùng dòng
    (nếu có) hoặc lề phải trang (lấy bằng lề trái của chữ trên trang, từ 18 tới 72 pt)."""
    group = [r for ln in lines for r in ln]
    ids = {r.index for r in group}
    if runs is None:
        runs = text_runs(doc, i)
    right = max(r.rect[2] for r in group)
    y0 = min(r.rect[1] for r in group)
    y1 = max(r.rect[3] for r in group)
    size = group[0].size or 10
    pw, _ph = doc.page_size_pt(i)
    lefts = [r.rect[0] for r in runs if r.rect[0] > 0]
    margin = min(72.0, max(18.0, min(lefts) if lefts else 36.0))
    limit = pw - margin
    for r in runs:
        if r.index in ids or r.rect[0] < right - 0.5:
            continue
        ov = min(y1, r.rect[3]) - max(y0, r.rect[1])
        if ov > 0.3 * min(y1 - y0, r.rect[3] - r.rect[1]):
            limit = min(limit, r.rect[0] - 0.4 * size)
    return max(limit, right)


def group_text(lines) -> str:
    return " ".join(" ".join(r.text.strip() for r in ln) for ln in lines)


def para_room(doc, i: int, lines, runs=None) -> float:
    """1.0.22: mép dưới (pt) mà đoạn văn được phép kéo dài thêm dòng: tới chữ gần nhất bên dưới (cùng cột)
    hoặc lề dưới trang."""
    group = [r for ln in lines for r in ln]
    ids = {r.index for r in group}
    if runs is None:
        runs = text_runs(doc, i)
    x0 = min(r.rect[0] for r in group)
    x1 = max(r.rect[2] for r in group)
    bottom = max(r.rect[3] for r in group)
    _pw, ph = doc.page_size_pt(i)
    limit = ph - 36.0
    for r in runs:
        if r.index in ids or r.rect[1] < bottom - 0.5:
            continue
        if min(x1, r.rect[2]) - max(x0, r.rect[0]) > 0:
            limit = min(limit, r.rect[1])
    return max(limit, bottom)


def replace_group(doc, i: int, lines, new_text: str, font_path: str | None = None, size: float | None = None,
                  color=None, fit: bool = True, snapshot: bool = True, dry: bool = False, runs_all=None,
                  allow_shrink: bool = True, allow_condense: bool = True) -> dict:
    """Thay cả dòng / cả đoạn (lines: [[TextRun]]) bằng chữ mới – giữ lề trái, đường chân chữ, cách dòng.
    1.0.22 – gõ thêm chữ GIỮ NGUYÊN cỡ chữ: một dòng thì kéo dài sang phải tới chữ kế tiếp / lề phải trang.
    fit: hết chỗ thì co ngang chữ (tối đa còn 80%, giữ chiều cao) cho vừa 1 dòng; vẫn không vừa mới thu nhỏ cỡ.
    size: người dùng chọn cỡ chữ -> luôn giữ đúng cỡ đó (không tự thu nhỏ lại), chỉ co ngang khi hết chỗ.
    Đoạn văn dài thêm: còn chỗ trống bên dưới thì thêm dòng (giữ cỡ chữ) trước khi co / thu nhỏ.
    dry: chỉ tính (không sửa file) – để cảnh báo trước. allow_shrink=False: không thu nhỏ cỡ chữ (chấp nhận tràn).
    allow_condense=False: không co hẹp chữ. Cả hai False = giữ nguyên hình thức (chỉ kéo dài / thêm dòng).
    Trả về {"size", "hscale", "extended", "condensed", "shrunk", "overflow", "added_lines"}."""
    runs = [r for ln in lines for r in ln]
    first = lines[0][0]
    (x0, base0), upright = run_origin(doc, i, first)
    if not upright:
        raise ValueError("Dòng chữ này bị xoay nghiêng – hãy sửa từng mảnh chữ")
    fp = font_path or replacement_font(first)
    size0 = float(size or first.size)
    keep = bool(size) and abs(float(size) - first.size) > 0.05     # cỡ do người dùng chọn: không thu nhỏ
    orig = first.orig_size or first.size                            # nhớ cỡ gốc để quay lại được
    col = color or first.color
    right = max(r.rect[2] for r in runs)
    width = max(8.0, right - x0)
    if len(lines) > 1:
        bases = [run_origin(doc, i, ln[0])[0][1] for ln in lines]
        pitch = (bases[-1] - bases[0]) / (len(bases) - 1)
    else:
        pitch = size0 * 1.2
    text = new_text.replace("\n", " ") if len(lines) > 1 else new_text.replace("\n", " ")
    info = {"size": size0, "hscale": 1.0, "extended": False, "condensed": False, "shrunk": False, "overflow": False,
            "added_lines": 0, "orig_size": float(first.size)}
    if not allow_shrink:
        keep = True
    if text.strip():
        miss = fonts.missing_chars(fp, text)
        if miss:
            raise ValueError(f"Phông chữ không có ký tự: {miss}")
    sz = size0
    hs = 1.0
    if len(lines) == 1:
        w = fonts.measure(fp, text, sz) if text.strip() else 0
        if w > width * 1.02:
            room = max(width, line_room(doc, i, lines, runs_all) - x0)
            wrapped = fonts.wrap(fp, text, sz, room)
            free = para_room(doc, i, lines, runs_all) - (base0 + size0 * 0.25)
            extra = max(0, int(free // max(1.0, pitch)))
            if w <= room:                                   # còn chỗ bên phải: giữ nguyên cỡ, kéo dài dòng
                info["extended"] = True
            elif len(wrapped) > 1 and len(wrapped) - 1 <= extra:   # chỗ trống bên dưới: xuống dòng, giữ cỡ
                info["extended"] = True
                info["added_lines"] = len(wrapped) - 1
                width = room
            elif fit and not allow_condense:
                info["overflow"] = True
            elif fit:
                hs = room / w
                if hs >= MIN_HSCALE:                        # co ngang cho vừa 1 dòng, chiều cao giữ nguyên
                    info["condensed"] = True
                elif keep:                                  # giữ cỡ người dùng chọn
                    hs = MIN_HSCALE
                    info["condensed"] = True
                    info["overflow"] = True
                else:                                       # quá dài: co ngang tối đa rồi mới thu nhỏ cỡ
                    hs = MIN_HSCALE
                    sz = max(size0 * 0.55, size0 * room / (w * hs))
                    info["condensed"] = info["shrunk"] = True
                    info["overflow"] = fonts.measure(fp, text, sz) * hs > room * 1.02
            else:
                info["overflow"] = True
        out_lines = fonts.wrap(fp, text, sz, width) if info["added_lines"] else [text]
    else:
        out_lines = fonts.wrap(fp, text, sz, width)
        n_ok = len(lines)
        if len(out_lines) > n_ok:                       # còn chỗ trống bên dưới: thêm dòng, giữ cỡ chữ
            last_base = base0 + (len(lines) - 1) * pitch
            free = para_room(doc, i, lines, runs_all) - (last_base + size0 * 0.25)
            extra = max(0, int(free // max(1.0, pitch)))
            n_ok = len(lines) + min(extra, len(out_lines) - len(lines))
            info["added_lines"] = n_ok - len(lines)
        while fit and allow_condense and len(out_lines) > n_ok and hs > MIN_HSCALE + 1e-6:   # co ngang trước, giữ cỡ chữ
            hs = max(MIN_HSCALE, hs - 0.05)
            out_lines = fonts.wrap(fp, text, sz, width / hs)
            info["condensed"] = True
        while fit and allow_condense and not keep and len(out_lines) > n_ok and sz > size0 * 0.6:
            sz *= 0.95
            out_lines = fonts.wrap(fp, text, sz, width / hs)
            info["shrunk"] = True
        info["added_lines"] = max(0, min(len(out_lines), n_ok) - len(lines))
        info["overflow"] = len(out_lines) > n_ok
        if keep and len(out_lines) > len(lines):        # cỡ lớn hơn: thêm dòng, cách dòng theo cỡ mới
            pitch = max(pitch, sz * 1.2)
    info["hscale"] = round(hs, 3)
    info["size"] = round(sz, 2)
    info["lines"] = len(out_lines)
    if dry:
        return info
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    for r in sorted(runs, key=lambda r: -r.index):
        obj = C.FPDFPage_GetObject(page.raw, r.index)
        C.FPDFPage_RemoveObject(page.raw, obj)
        C.FPDFPageObj_Destroy(obj)
    if text.strip():
        chars = "".join(sorted(set("".join(out_lines))))
        font = _load_font(doc, fonts.subset(fp, chars))
        fr = _Frame(doc, i)
        try:
            for k, ln in enumerate(out_lines):
                if ln.strip():
                    obj = _text_obj(doc, font, sz, ln, fr.matrix_at(x0, base0 + k * pitch, hscale=hs), col)
                    _set_orig_size(doc, obj, orig)
                    C.FPDFPage_InsertObject(page.raw, obj)
        finally:
            C.FPDFFont_Close(font)
    page.gen_content()
    if snapshot:
        doc._changed()
    return info


def styled_font(run: TextRun, family: str | None = None, bold: bool | None = None, italic: bool | None = None) -> str:
    """11b – phông cùng họ với chữ gốc (hoặc họ đã chọn), đậm / nghiêng theo lựa chọn."""
    fam = family or fonts.family_of(run.font_name)
    return fonts.system_font(fam, run.bold if bold is None else bold, run.italic if italic is None else italic)


# ------------------------------------------------------------------ 11f: tìm & thay có xem trước từng chỗ
@dataclass
class Hit:
    page: int
    run_index: int
    start: int
    end: int
    context: str
    replaceable: bool = True


def find_hits(doc, find: str, match_case: bool = False, pages=None) -> list[Hit]:
    """Mọi chỗ tìm thấy (thay được: nằm trọn trong một mảnh chữ; không thay được: bị tách nhiều mảnh)."""
    import re
    if not find:
        return []
    pat = re.compile(re.escape(find), 0 if match_case else re.IGNORECASE)
    out = []
    pages = range(doc.page_count) if pages is None else pages
    for i in pages:
        if doc.page_kind(i) != "text":
            continue
        from .document import text_search
        tp = doc.page(i).get_textpage()
        try:
            total = len(text_search(tp, find, match_case))
        finally:
            tp.close()
        if not total:
            continue
        inside = 0
        for r in text_runs(doc, i):
            for m in pat.finditer(r.text):
                a, b = max(0, m.start() - 25), min(len(r.text), m.end() + 25)
                ctx = ("…" if a else "") + r.text[a:b] + ("…" if b < len(r.text) else "")
                out.append(Hit(i, r.index, m.start(), m.end(), ctx))
                inside += 1
        for _ in range(max(0, total - inside)):
            out.append(Hit(i, -1, 0, 0, f"(cụm chữ bị tách nhiều đoạn trên trang {i + 1})", False))
    return out


def replace_hits(doc, hits: list[Hit], repl: str) -> int:
    """Thay các chỗ đã chọn (1 bước hoàn tác). Trả về số chỗ đã thay."""
    todo = {}
    for h in hits:
        if h.replaceable:
            todo.setdefault((h.page, h.run_index), []).append(h)
    if not todo:
        return 0
    doc._snapshot()
    done = 0
    for (i, idx) in sorted(todo, key=lambda k: (k[0], -k[1])):
        runs = {r.index: r for r in text_runs(doc, i)}
        r = runs.get(idx)
        if r is None:
            continue
        t = r.text
        for h in sorted(todo[(i, idx)], key=lambda h: -h.start):
            t = t[:h.start] + repl + t[h.end:]
            done += 1
        replace_run(doc, i, r, t, snapshot=False)
    doc._changed()
    return done


def find_replace(doc, find: str, repl: str, match_case: bool = False, pages=None) -> tuple[int, int]:
    """Tìm & thay trong các trang chữ. Trả về (số chỗ đã thay, số chỗ tìm thấy nhưng không thay được
    vì cụm chữ nằm vắt qua nhiều đối tượng chữ)."""
    import re
    if not find:
        return 0, 0
    flags = 0 if match_case else re.IGNORECASE
    pat = re.compile(re.escape(find), flags)
    pages = range(doc.page_count) if pages is None else pages
    done = found = 0
    snap = False
    for i in pages:
        if doc.page_kind(i) != "text":
            continue
        from .document import text_search
        tp = doc.page(i).get_textpage()
        try:
            n = len(text_search(tp, find, match_case))
        finally:
            tp.close()
        if not n:
            continue
        found += n
        runs = [r for r in text_runs(doc, i) if pat.search(r.text)]
        for r in sorted(runs, key=lambda r: -r.index):          # thay từ cuối lên -> chỉ số không lệch
            if not snap:
                doc._snapshot()
                snap = True
            new, k = pat.subn(repl.replace("\\", "\\\\"), r.text)
            replace_run(doc, i, text_runs(doc, i)[[x.index for x in text_runs(doc, i)].index(r.index)],
                        new, snapshot=False)
            done += k
    if snap:
        doc._changed()
    return done, max(0, found - done)


# ------------------------------------------------------------------ che / tẩy vùng
def erase_area(doc, i: int, rect, remove_text: bool = True, fill="#ffffff", snapshot=True) -> int:
    """Gỡ các đối tượng chữ nằm trọn trong vùng rồi phủ màu nền. Trả về số đối tượng chữ đã gỡ."""
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    x0, y0, x1, y1 = rect
    removed = 0
    if remove_text:
        for r in sorted(text_runs(doc, i), key=lambda r: -r.index):
            a0, b0, a1, b1 = r.rect
            if a0 >= x0 - 0.5 and b0 >= y0 - 0.5 and a1 <= x1 + 0.5 and b1 <= y1 + 0.5:
                obj = C.FPDFPage_GetObject(page.raw, r.index)
                C.FPDFPage_RemoveObject(page.raw, obj)
                C.FPDFPageObj_Destroy(obj)
                removed += 1
    fr = _Frame(doc, i)
    o = _style(_new_path(fr, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True), None, 0, fill, round_=False)
    C.FPDFPage_InsertObject(page.raw, o)
    page.gen_content()
    if snapshot:
        doc._changed()
    return removed


def region_polygon(region) -> list[tuple[float, float]]:
    """Vùng tẩy -> đa giác hiển thị. region: {"shape": rect|ellipse|lasso|brush, "rect", "pts", "size"}."""
    shape = region.get("shape", "rect")
    if shape in ("rect", "ellipse"):
        x0, y0, x1, y1 = region["rect"]
        if shape == "rect":
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
        return [(cx + rx * math.cos(2 * math.pi * k / 64), cy + ry * math.sin(2 * math.pi * k / 64)) for k in range(64)]
    return list(region.get("pts") or [])


def _point_in_poly(x, y, poly) -> bool:
    inside = False
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / ((y1 - y0) or 1e-12) + x0:
            inside = not inside
    return inside


def _dist_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def region_contains(region, x, y) -> bool:
    if region.get("shape") == "brush":
        pts = region.get("pts") or []
        r = float(region.get("size", 12)) / 2
        if len(pts) == 1:
            return math.hypot(x - pts[0][0], y - pts[0][1]) <= r
        return any(_dist_seg((x, y), pts[k], pts[k + 1]) <= r for k in range(len(pts) - 1))
    return _point_in_poly(x, y, region_polygon(region))


def region_bounds(region):
    if region.get("shape") in ("rect", "ellipse"):
        x0, y0, x1, y1 = region["rect"]
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    pts = region.get("pts") or [(0, 0)]
    m = float(region.get("size", 0)) / 2 if region.get("shape") == "brush" else 0
    return (min(p[0] for p in pts) - m, min(p[1] for p in pts) - m, max(p[0] for p in pts) + m,
            max(p[1] for p in pts) + m)


def sample_paper_color(doc, i: int, rect, ring: float = 4.0) -> str:
    """Màu nền giấy quanh vùng (trung vị các điểm ảnh trên viền ngoài vùng) – dùng phủ trang scan ố vàng."""
    x0, y0, x1, y1 = rect
    pw, ph = doc.page_size_pt(i)
    k = 2.0
    bm = doc.render(i, k)
    img = bm.to_pil().convert("RGB")
    bm.close()
    px = []
    X0, Y0 = max(0, int((x0 - ring) * k)), max(0, int((y0 - ring) * k))
    X1, Y1 = min(img.width - 1, int((x1 + ring) * k)), min(img.height - 1, int((y1 + ring) * k))
    load = img.load()
    step = max(1, int((X1 - X0 + Y1 - Y0) / 400))
    for x in range(X0, X1 + 1, step):
        for y in (Y0, Y1):
            px.append(load[x, y])
    for y in range(Y0, Y1 + 1, step):
        for x in (X0, X1):
            px.append(load[x, y])
    if not px:
        return "#ffffff"
    med = [sorted(c[j] for c in px)[len(px) // 2] for j in range(3)]
    return "#%02x%02x%02x" % tuple(med)


_TYPE_OF = {"text": "FPDF_PAGEOBJ_TEXT", "image": "FPDF_PAGEOBJ_IMAGE", "path": "FPDF_PAGEOBJ_PATH"}


def erase_region(doc, i: int, region: dict, fill: str = "white", only: str = "all", snapshot=True) -> dict:
    """Tẩy vùng: gỡ các đối tượng NẰM TRỌN trong vùng (theo loại: all | text | image | path) rồi phủ đúng hình vùng.
    fill: "white" | "sample" (màu nền giấy) | "none" (chỉ gỡ) | mã màu "#rrggbb".
    Không gỡ ảnh nền phủ gần kín trang (trang scan) -> phần đó được phủ màu thay vì mất cả trang.
    Trả về {"text": n, "image": n, "path": n, "other": n, "fill": màu | None}."""
    color = None
    if fill == "white":
        color = "#ffffff"
    elif fill == "sample":
        color = sample_paper_color(doc, i, region_bounds(region))
    elif fill and fill.startswith("#"):
        color = fill
    if snapshot:
        doc._snapshot()
    page = doc.page(i)
    fr = _Frame(doc, i)
    pw, ph = doc.page_size_pt(i)
    want = None if only == "all" else getattr(C, _TYPE_OF[only])
    counts = {"text": 0, "image": 0, "path": 0, "other": 0}
    names = {C.FPDF_PAGEOBJ_TEXT: "text", C.FPDF_PAGEOBJ_IMAGE: "image", C.FPDF_PAGEOBJ_PATH: "path"}
    bx0, by0, bx1, by1 = region_bounds(region)
    for k in range(C.FPDFPage_CountObjects(page.raw) - 1, -1, -1):
        obj = C.FPDFPage_GetObject(page.raw, k)
        t = C.FPDFPageObj_GetType(obj)
        if want is not None and t != want:
            continue
        l, b, r, tp = (ctypes.c_float() for _ in range(4))
        C.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(tp))
        a0, b0, a1, b1 = fr.display_rect(l.value, b.value, r.value, tp.value)
        if a0 < bx0 - 0.5 or b0 < by0 - 0.5 or a1 > bx1 + 0.5 or b1 > by1 + 0.5:
            continue
        if t == C.FPDF_PAGEOBJ_IMAGE and (a1 - a0) * (b1 - b0) > 0.85 * pw * ph:
            continue
        cx, cy = (a0 + a1) / 2, (b0 + b1) / 2
        probe = [(a0, b0), (a1, b0), (a0, b1), (a1, b1), (cx, b0), (cx, b1), (a0, cy), (a1, cy), (cx, cy)]
        if not all(region_contains(region, x, y) for x, y in probe):
            continue
        C.FPDFPage_RemoveObject(page.raw, obj)
        C.FPDFPageObj_Destroy(obj)
        counts[names.get(t, "other")] += 1
    if color is not None:
        shape = region.get("shape", "rect")
        if shape == "brush":
            pts = region.get("pts") or []
            if len(pts) == 1:
                pts = [pts[0], (pts[0][0] + 0.01, pts[0][1])]
            o = _style(_new_path(fr, pts), color, float(region.get("size", 12)), None)
        else:
            poly = region_polygon(region)
            if shape == "ellipse":
                x0, y0, x1, y1 = region["rect"]
                start, curves = ellipse_curves(x0, y0, x1, y1)
                o = _style(_new_path(fr, [start], closed=True, curves=curves), None, 0, color)
            else:
                o = _style(_new_path(fr, poly, closed=True), None, 0, color, round_=False)
        C.FPDFPage_InsertObject(page.raw, o)
    page.gen_content()
    if snapshot:
        doc._changed()
    counts["fill"] = color
    return counts


# ------------------------------------------------------------------ chọn / di chuyển / xóa ảnh đã chèn
@dataclass
class ObjInfo:
    index: int
    kind: str                    # "image"
    rect: tuple                  # khung hiển thị


def image_at(doc, i: int, x: float, y: float, max_cover: float = 0.85) -> ObjInfo | None:
    """Ảnh trên cùng tại điểm (x, y). Bỏ qua ảnh nền phủ gần kín trang (trang scan)."""
    page = doc.page(i)
    fr = _Frame(doc, i)
    pw, ph = doc.page_size_pt(i)
    best = None
    for k in range(C.FPDFPage_CountObjects(page.raw)):
        obj = C.FPDFPage_GetObject(page.raw, k)
        if C.FPDFPageObj_GetType(obj) != C.FPDF_PAGEOBJ_IMAGE:
            continue
        l, b, r, t = (ctypes.c_float() for _ in range(4))
        C.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(t))
        rect = fr.display_rect(l.value, b.value, r.value, t.value)
        if (rect[2] - rect[0]) * (rect[3] - rect[1]) > max_cover * pw * ph:
            continue
        if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
            best = ObjInfo(k, "image", rect)          # đối tượng sau nằm trên -> lấy cái cuối
    return best


def image_preview(doc, i: int, index: int, upright: bool = False):
    """Ảnh (PIL RGBA) của đối tượng ảnh như đang hiển thị (có cả nền trong suốt).
    upright=True: ảnh dựng thẳng theo chiều gốc của ảnh (bỏ góc xoay trên trang) – để sửa/xoay tiếp."""
    obj = C.FPDFPage_GetObject(doc.page(i).raw, index)
    img = pdfium.PdfImage(obj, doc.page(i), doc.pdf)
    saved = None
    if upright:
        saved = C.FS_MATRIX()
        C.FPDFPageObj_GetMatrix(obj, ctypes.byref(saved))
        pw, ph = img.get_px_size()
        m = C.FS_MATRIX(float(max(1, pw)), 0.0, 0.0, float(max(1, ph)), saved.e, saved.f)
        C.FPDFPageObj_SetMatrix(obj, ctypes.byref(m))
    try:
        bm = img.get_bitmap(render=True)
    finally:
        if saved is not None:
            C.FPDFPageObj_SetMatrix(obj, ctypes.byref(saved))
    try:
        return bm.to_pil().convert("RGBA")
    finally:
        bm.close()


def image_layer(doc, i: int, index: int) -> str | None:
    """Lớp của ảnh do phần mềm chèn ("top" | "multiply" | "behind"); None nếu không rõ (ảnh có sẵn trong file)."""
    obj = C.FPDFPage_GetObject(doc.page(i).raw, index)
    for k in range(max(0, C.FPDFPageObj_CountMarks(obj))):
        mk = C.FPDFPageObj_GetMark(obj, k)
        buf = (ctypes.c_ushort * 128)()
        n = ctypes.c_ulong(0)
        if C.FPDFPageObjMark_GetName(mk, buf, ctypes.sizeof(buf), ctypes.byref(n)):
            name = bytes(buf)[:max(0, n.value - 2)].decode("utf-16-le", "ignore")
            if name.startswith("PdfKySo_"):
                return name[8:]
    return None


def frame_from_matrix(doc, i: int, m):
    """Khung chưa xoay (x0, y0, x1, y1) + góc xoay hiện tại (độ, chiều kim đồng hồ) của ảnh trên trang.
    None nếu ảnh bị lật/xô nghiêng (không quy được về khung xoay)."""
    disp = [doc.user_to_display(i, m.e + m.a * u + m.c * v, m.f + m.b * u + m.d * v)
            for u, v in ((0, 0), (1, 0), (0, 1))]
    (blx, bly), (brx, bry), (tlx, tly) = disp
    ux, uy = brx - blx, bry - bly                  # cạnh dưới (trái -> phải)
    vx, vy = tlx - blx, tly - bly                  # cạnh trái (dưới -> trên)
    w, h = math.hypot(ux, uy), math.hypot(vx, vy)
    if w < 1e-6 or h < 1e-6:
        return None
    cross = ux * vy - uy * vx                      # ảnh đứng thẳng: cạnh trái hướng lên (ngược chiều y hiển thị)
    if cross >= 0 or abs(ux * vx + uy * vy) > 0.02 * w * h:
        return None
    angle = math.degrees(math.atan2(uy, ux)) % 360
    cx, cy = (brx + tlx) / 2, (bry + tly) / 2
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), round(angle, 2)


def image_frame(doc, i: int, index: int):
    """Khung chưa xoay + góc của ảnh thứ index trên trang i (None nếu bị lật/xô nghiêng)."""
    obj = C.FPDFPage_GetObject(doc.page(i).raw, index)
    m = C.FS_MATRIX()
    C.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
    return frame_from_matrix(doc, i, m)


class ObjectEdit:
    """Sửa một ảnh đã chèn: tạm gỡ khỏi trang (giữ nguyên dữ liệu ảnh gốc, không nén lại),
    người dùng kéo/đổi cỡ, rồi đặt lại (commit), trả về chỗ cũ (cancel) hoặc xóa hẳn (delete).
    Cả thao tác là 1 bước hoàn tác."""

    def __init__(self, doc, i: int, info: ObjInfo):
        self.doc, self.i, self.index = doc, i, info.index
        self.rect = info.rect
        doc._snapshot()
        self.page = doc.page(i)
        self.obj = C.FPDFPage_GetObject(self.page.raw, info.index)
        self.matrix = C.FS_MATRIX()
        C.FPDFPageObj_GetMatrix(self.obj, ctypes.byref(self.matrix))
        C.FPDFPage_RemoveObject(self.page.raw, self.obj)
        doc.version += 1                       # vẽ lại trang không có ảnh (ảnh hiện ở khung kéo)
        self.done = False

    def _put_back(self):
        if hasattr(C, "FPDFPage_InsertObjectAtIndex"):
            C.FPDFPage_InsertObjectAtIndex(self.page.raw, self.obj, self.index)
        else:
            C.FPDFPage_InsertObject(self.page.raw, self.obj)

    def frame(self):
        """Khung chưa xoay + góc xoay hiện tại của ảnh (xem frame_from_matrix)."""
        return frame_from_matrix(self.doc, self.i, self.matrix)

    def commit(self, rect, angle=None):
        """rect: khung bao (angle=None, như cũ) hoặc khung CHƯA XOAY khi có angle (xoay quanh tâm khung)."""
        if self.done:
            return
        x0, y0, x1, y1 = rect
        if angle is not None:
            a = math.radians(angle)
            c, s = math.cos(a), math.sin(a)
            cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2

            def rot(x, y):
                return cx + x * c - y * s, cy + x * s + y * c
            bl, br, tl = rot(-hw, hh), rot(hw, hh), rot(-hw, -hh)
        else:
            bl, br, tl = (x0, y1), (x1, y1), (x0, y0)
        p00 = self.doc.display_to_user(self.i, *bl)
        p10 = self.doc.display_to_user(self.i, *br)
        p01 = self.doc.display_to_user(self.i, *tl)
        m = C.FS_MATRIX(p10[0] - p00[0], p10[1] - p00[1], p01[0] - p00[0], p01[1] - p00[1], p00[0], p00[1])
        C.FPDFPageObj_SetMatrix(self.obj, ctypes.byref(m))
        self._put_back()
        self.page.gen_content()
        self.done = True
        self.doc._changed()

    def cancel(self):
        if self.done:
            return
        C.FPDFPageObj_SetMatrix(self.obj, ctypes.byref(self.matrix))
        self._put_back()
        self.done = True
        self.doc._undo.pop()                   # không có thay đổi -> bỏ bước hoàn tác vừa chụp
        self.doc.version += 1

    def delete(self):
        if self.done:
            return
        C.FPDFPageObj_Destroy(self.obj)
        self.page.gen_content()
        self.done = True
        self.doc._changed()


__all__ = ["add_shape", "add_ink", "add_text", "add_note", "notes", "text_runs", "run_at", "replace_run",
           "find_replace", "erase_area", "simplify", "smooth_curves", "pdfium"]
