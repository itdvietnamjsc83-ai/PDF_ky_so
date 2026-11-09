"""Mẫu chữ viết tay của chính người dùng, tạo từ bản scan.

Quy trình:
1. In "phiếu mẫu chữ" (1 trang A4, 100 ô): chữ cái thường/hoa, ă â đ ê ô ơ ư, số, dấu câu và 5 dấu thanh.
2. Viết tay vào từng ô (bút bi/bút ký), scan hoặc chụp lại.
3. Phần mềm tìm 4 ô vuông đen ở góc -> nắn thẳng ảnh (kể cả scan lệch, chụp nghiêng) -> cắt từng ô,
   tách nền -> lưu thành một "bộ chữ tay" (1 ảnh gộp) trong thư viện dấu (có mã hóa nếu đặt mật khẩu).
4. Khi gõ chữ: ghép từng chữ cái đã viết, tự đặt dấu thanh (huyền, sắc, hỏi, ngã, nặng) lên đúng chữ,
   xê dịch nhẹ ngẫu nhiên cho tự nhiên -> ảnh chữ tay trong suốt, đặt lên trang như con dấu.
"""
from __future__ import annotations

import io
import random
import unicodedata

VERSION = 2
LOWER = list("abcdefghijklmnopqrstuvwxyz") + list("ăâđêôơư")
UPPER = [c.upper() for c in LOWER]
DIGITS = list("0123456789")
PUNCT = list(".,:;!?-()/\"'")
TONES = ["̀", "́", "̉", "̃", "̣"]           # huyền, sắc, hỏi, ngã, nặng
TONE_LABEL = {"̀": "huyền", "́": "sắc", "̉": "hỏi", "̃": "ngã", "̣": "nặng"}
CHARS = LOWER + UPPER + DIGITS + PUNCT + TONES                     # 95 ô
COLS, ROWS = 10, 10

# bố cục phiếu (mm, khổ A4 210 x 297)
PAGE_W, PAGE_H = 210.0, 297.0
MARK = 8.0                        # cạnh ô vuông định vị
MARK_POS = [(10, 10), (192, 10), (10, 279), (192, 279)]           # góc trên-trái của 4 ô định vị
GRID_X0, GRID_Y0 = 15.0, 38.0
CELL_W, CELL_H = 18.0, 24.0
BASELINE = 0.70                   # đường kẻ chân chữ ở 70% chiều cao ô
LABEL_W, LABEL_H = 7.0, 4.2       # vùng nhãn in sẵn ở góc trên-trái mỗi ô (mm)

# ảnh gộp lưu trong thư viện
SPRITE_W, SPRITE_H = 180, 240      # px mỗi ô (≈ 254 dpi)


def mark_centers_mm():
    return [(x + MARK / 2, y + MARK / 2) for x, y in MARK_POS]


def cell_rect_mm(k: int):
    r, c = divmod(k, COLS)
    x, y = GRID_X0 + c * CELL_W, GRID_Y0 + r * CELL_H
    return x, y, x + CELL_W, y + CELL_H


def label(ch: str) -> str:
    return TONE_LABEL.get(ch, ch)


# ------------------------------------------------------------------ 1. phiếu mẫu
# 1.0.22 – phiếu v2 dễ viết hơn: 2 trang, ô to (21 x 28 mm), nhãn in RÕ phía trên ô (không lẫn vào ô viết),
# đường kẻ chân chữ + đường giữa chữ mờ như vở ô ly. Trang 1 (bắt buộc): chữ thường, số, dấu thanh.
# Trang 2 (nên có): chữ hoa, dấu câu – thiếu trang 2 thì chữ hoa dùng tạm chữ thường.
V2_PAGES = [LOWER + DIGITS + TONES, UPPER + PUNCT]
V2_COLS = 8
V2_W, V2_H = 21.0, 28.0            # ô viết (đúng tỉ lệ 3:4 của ảnh gộp)
V2_LABEL = 5.0                     # dải nhãn phía trên ô
V2_PITCH_X, V2_PITCH_Y = 22.5, 35.0
V2_X0, V2_Y0 = 15.0, 50.0
V2_XHEIGHT = 0.45                  # đường giữa chữ (chiều cao chữ thường)
PAGE_ID_Y = 281.0                  # ô nhận diện trang (giữa mép dưới): trang 1 một ô, trang 2 hai ô
PAGE_ID = {1: [(97.0, PAGE_ID_Y)], 2: [(85.0, PAGE_ID_Y), (109.0, PAGE_ID_Y)]}
PAGE_ID_SIZE = 6.0


def v2_cell_mm(page: int, k: int):
    """Ô viết thứ k của trang page (1, 2) theo mm: (x0, y0, x1, y1) – không gồm dải nhãn."""
    r, c = divmod(k, V2_COLS)
    x = V2_X0 + c * V2_PITCH_X
    y = V2_Y0 + r * V2_PITCH_Y + V2_LABEL
    return x, y, x + V2_W, y + V2_H


def make_template(path: str | None = None, version: int = 2) -> bytes:
    """Tạo phiếu mẫu chữ (PDF A4) – dùng chính lõi PDF của phần mềm. version=1: phiếu cũ 1 trang 95 ô."""
    if version == 1:
        return _make_template_v1(path)
    from . import editing, fonts
    from .document import PdfDocument
    mm = 72 / 25.4
    d = PdfDocument()
    d.insert_blank(-1)
    d.insert_blank(0)
    font = fonts.system_font("sans")
    for pi, chars in enumerate(V2_PAGES):
        page = pi + 1
        shapes = [("rect", (x * mm, y * mm, (x + MARK) * mm, (y + MARK) * mm), None, 0, "#000000") for x, y in MARK_POS]
        shapes += [("rect", (x * mm, y * mm, (x + PAGE_ID_SIZE) * mm, (y + PAGE_ID_SIZE) * mm), None, 0, "#000000")
                   for x, y in PAGE_ID[page]]
        what = ("Trang 1/2 – chữ thường, chữ số, dấu thanh (bắt buộc)" if page == 1 else
                "Trang 2/2 – chữ hoa, dấu câu (nên viết; bỏ trống thì chữ hoa dùng tạm chữ thường)")
        texts = [(22 * mm, 12 * mm, "PHIẾU MẪU CHỮ VIẾT TAY", 15, "#000000"),
                 (22 * mm, 19.5 * mm, what, 9.5, "#000000"),
                 (22 * mm, 26 * mm, "• Viết mỗi chữ vào giữa ô, CHÂN CHỮ CHẠM ĐƯỜNG KẺ ĐẬM (g, p, y, q thò xuống dưới); "
                  "chữ thường cao tới đường chấm.\n• Ô dấu thanh: chỉ viết dấu, ở khoảng giữa ô. Không viết lên nhãn "
                  "và 4 ô vuông đen ở góc.\n• Bút bi / bút ký xanh hoặc đen. Scan 300 dpi hoặc chụp thẳng, đủ sáng, "
                  "cả trang (PDF nhiều trang hoặc từng ảnh đều được).\n• Sau khi nạp, phần mềm cho xem lại từng chữ đã "
                  "cắt để chỉnh khung cắt hoặc viết lại chữ chưa đẹp.", 7.5, "#444444"),
                 (15 * mm, 289 * mm, f"PDF Ký Số · mẫu chữ tay v2 · trang {page}", 6.5, "#999999")]
        for k, ch in enumerate(chars):
            x0, y0, x1, y1 = v2_cell_mm(page, k)
            shapes.append(("rect", (x0 * mm, y0 * mm, x1 * mm, y1 * mm), "#c4c4c4", 0.5, None))
            by = y0 + V2_H * BASELINE
            shapes.append(("line", ((x0 + 1) * mm, by * mm, (x1 - 1) * mm, by * mm), "#bdbdbd", 0.7, None))
            xy = by - V2_H * BASELINE * V2_XHEIGHT
            xx = x0 + 1.2
            while xx < x1 - 1.2:                                       # đường chấm: chiều cao chữ thường
                shapes.append(("line", (xx * mm, xy * mm, (xx + 0.6) * mm, xy * mm), "#dadada", 0.4, None))
                xx += 1.6
            lab = label(ch) if ch in TONES else ch
            size = 7.5 if ch in TONES else 10.5
            tw = fonts.measure(font, lab, size) / mm
            texts.append(((x0 + (V2_W - tw) / 2) * mm, (y0 - V2_LABEL + 0.6) * mm, lab, size, "#8a8a8a"))
        editing.add_shapes(d, pi, shapes, snapshot=False)
        editing.add_texts(d, pi, texts, font, snapshot=False)
    data = d.to_bytes()
    d.close()
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


def _make_template_v1(path: str | None = None) -> bytes:
    from . import editing, fonts
    from .document import PdfDocument
    mm = 72 / 25.4
    d = PdfDocument()
    d.insert_blank(-1)                                   # tài liệu trống -> trang A4
    font = fonts.system_font("sans")
    shapes = [("rect", (x * mm, y * mm, (x + MARK) * mm, (y + MARK) * mm), None, 0, "#000000") for x, y in MARK_POS]
    texts = [(22 * mm, 13 * mm, "PHIẾU MẪU CHỮ VIẾT TAY", 15, "#000000"),
             (22 * mm, 20.5 * mm, "Viết mỗi ký tự vào giữa ô, chân chữ chạm đường kẻ mờ (g, p, y… thò xuống dưới). "
              "Ô dấu thanh: chỉ viết dấu.\nDùng bút bi/bút ký màu xanh hoặc đen, không viết đè lên 4 ô vuông "
              "đen. Scan 300–600 dpi hoặc chụp thẳng cả trang.", 8, "#444444"),
             (15 * mm, 281 * mm, "PDF Ký Số · mẫu chữ tay v1", 7, "#999999")]
    for k, ch in enumerate(CHARS):
        x0, y0, x1, y1 = cell_rect_mm(k)
        shapes.append(("rect", (x0 * mm, y0 * mm, x1 * mm, y1 * mm), "#c8c8c8", 0.4, None))
        by = y0 + CELL_H * BASELINE
        shapes.append(("line", ((x0 + 1.5) * mm, by * mm, (x1 - 1.5) * mm, by * mm), "#dddddd", 0.35, None))
        texts.append(((x0 + 1) * mm, (y0 + 0.8) * mm, label(ch), 6.5, "#b4b4b4"))
    editing.add_shapes(d, 0, shapes, snapshot=False)
    editing.add_texts(d, 0, texts, font, snapshot=False)
    data = d.to_bytes()
    d.close()
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


# ------------------------------------------------------------------ 2. đọc bản scan
def load_scans(data: bytes, dpi: int = 200, max_pages: int = 4) -> list:
    """Ảnh (PNG/JPG…) hoặc PDF (tới 4 trang) -> danh sách ảnh PIL RGB."""
    from PIL import Image, ImageOps
    if data[:5] == b"%PDF-":
        from .document import PdfDocument
        d = PdfDocument(data=data)
        try:
            return [d.render(i, dpi / 72).to_pil().convert("RGB") for i in range(min(max_pages, d.page_count))]
        finally:
            d.close()
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    return [img.convert("RGB")]


def load_scan(data: bytes, dpi: int = 200):
    return load_scans(data, dpi, 1)[0]


def find_marks(img) -> list[tuple[float, float]]:
    """Tâm 4 ô vuông đen ở 4 góc (toạ độ pixel), theo thứ tự trên-trái, trên-phải, dưới-trái, dưới-phải."""
    k = max(1.0, max(img.size) / 1000)
    small = img.convert("L").resize((max(1, int(img.width / k)), max(1, int(img.height / k))))
    w, h = small.size
    px = small.load()
    out = []
    rw, rh = int(w * 0.2), int(h * 0.16)
    for qx, qy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x0 = 0 if qx == 0 else w - rw
        y0 = 0 if qy == 0 else h - rh
        # ô đen đặc: điểm tối có nhiều hàng xóm tối (loại chữ, nét mảnh)
        sx = sy = n = 0
        for y in range(y0 + 1, y0 + rh - 1):
            for x in range(x0 + 1, x0 + rw - 1):
                if px[x, y] < 90 and px[x - 1, y] < 90 and px[x + 1, y] < 90 and px[x, y - 1] < 90 and px[x, y + 1] < 90:
                    sx += x
                    sy += y
                    n += 1
        if n < 12:
            raise ValueError("Không tìm thấy đủ 4 ô vuông đen ở góc phiếu. Hãy scan/chụp cả trang, "
                             "đủ sáng, không che góc.")
        out.append((sx / n * k, sy / n * k))
    return out


def _solve(a, b):
    """Giải hệ tuyến tính nhỏ (khử Gauss) – không cần numpy."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        if abs(m[c][c]) < 1e-12:
            raise ValueError("Ảnh bị méo quá mức")
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(src, dst):
    """Ma trận phối cảnh H (8 hệ số) biến điểm src -> dst."""
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return _solve(a, b)


def _apply(h, x, y):
    d = h[6] * x + h[7] * y + 1
    return (h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d


def _warp(img, H, x0, y0, x1, y1, size=(SPRITE_W, SPRITE_H)):
    from PIL import Image
    quad = [_apply(H, x0, y0), _apply(H, x0, y1), _apply(H, x1, y1), _apply(H, x1, y0)]
    return img.transform(size, Image.QUAD, [c for p in quad for c in p], Image.BICUBIC, fillcolor=(255, 255, 255))


def page_kind(img, H) -> int:
    """0 = phiếu cũ (v1), 1 / 2 = trang 1 / 2 của phiếu v2 – theo các ô nhận diện ở giữa mép dưới."""
    def dark(x, y):
        c = _warp(img, H, x + 1, y + 1, x + PAGE_ID_SIZE - 1, y + PAGE_ID_SIZE - 1, (12, 12)).convert("L")
        return sum(c.histogram()[:110]) > 100
    if dark(*PAGE_ID[2][0]) and dark(*PAGE_ID[2][1]):
        return 2
    if dark(*PAGE_ID[1][0]):
        return 1
    return 0


def extract_cells(datas) -> dict:
    """Các bản scan (1–2 trang phiếu, ảnh hoặc PDF) -> {"version", "pages", "cells": {ký tự: ảnh ô viết RGB}}.
    Ảnh ô đã nắn thẳng, đúng cỡ SPRITE_W x SPRITE_H, CHƯA tách nền – để xem lại / chỉnh trước khi tạo bộ chữ."""
    if isinstance(datas, (bytes, bytearray)):
        datas = [bytes(datas)]
    imgs = [im for data in datas for im in load_scans(data)]
    cells, pages, version = {}, [], 2
    last_err = None
    for img in imgs:
        try:
            marks = find_marks(img)
        except ValueError as e:
            last_err = e
            continue
        H = homography(mark_centers_mm(), marks)          # mm trên phiếu -> pixel trên ảnh
        kind = page_kind(img, H)
        if kind == 0:                                     # phiếu cũ 1 trang 95 ô
            version = 1
            inset = 1.3
            for k, ch in enumerate(CHARS):
                x0, y0, x1, y1 = cell_rect_mm(k)
                cells[ch] = _warp(img, H, x0 + inset, y0 + inset, x1 - inset, y1 - inset)
            pages.append(0)
            continue
        inset = 0.9
        for k, ch in enumerate(V2_PAGES[kind - 1]):
            x0, y0, x1, y1 = v2_cell_mm(kind, k)
            cells[ch] = _warp(img, H, x0 + inset, y0 + inset * 4 / 3, x1 - inset, y1 - inset * 4 / 3)
        pages.append(kind)
    if not cells:
        raise last_err or ValueError("Không nhận ra phiếu mẫu chữ.")
    return {"version": version, "pages": pages, "cells": cells}


def default_rect(version: int):
    """Khung cắt mặc định trong ô (px trên ảnh ô): v1 bỏ góc nhãn trên-trái; v2 cả ô."""
    return (0, 0, SPRITE_W, SPRITE_H)


def process_cell(cell, threshold: int = 175, rect=None, version: int = 2):
    """Ảnh ô (RGB) -> ảnh chữ RGBA trong suốt, hoặc None nếu ô trống.
    rect=(x0, y0, x1, y1) px: chỉ giữ nét bút trong khung này (người dùng kéo lại khung khi cắt chưa chuẩn)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    from .imaging import remove_background
    buf = io.BytesIO()
    cell.save(buf, "PNG")
    png = remove_background(buf.getvalue(), threshold=threshold, softness=35, boost=True, trim=False,
                            max_side=10000)
    g = Image.open(io.BytesIO(png)).convert("RGBA")
    a = g.getchannel("A").point(lambda v: 0 if v < 90 else v)      # bỏ vết mờ: đường kẻ, bụi
    dr = ImageDraw.Draw(a)
    if version == 1:            # xóa vùng nhãn in sẵn ở góc trên-trái ô (máy in có thể in đậm hơn thiết kế)
        inset = 1.3
        lab_w = int((LABEL_W - inset) / (CELL_W - 2 * inset) * SPRITE_W)
        lab_h = int((LABEL_H - inset) / (CELL_H - 2 * inset) * SPRITE_H)
        dr.rectangle((0, 0, lab_w, lab_h), fill=0)
    if rect is not None:
        x0, y0, x1, y1 = [int(round(v)) for v in rect]
        mask = Image.new("L", a.size, 0)
        ImageDraw.Draw(mask).rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
        a = ImageChops.multiply(a, mask)
    # bỏ nét mảnh (viền ô, đường kẻ lọt vào khi scan lệch) và bụi: chỉ giữ vùng quanh nét bút thật
    keep = a.point(lambda v: 255 if v > 90 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(11))
    a = ImageChops.multiply(a, keep)
    g.putalpha(a)
    if sum(a.resize((45, 60)).histogram()[61:]) < 6:               # ô trống / chỉ có vết bẩn nhỏ
        return None
    return g


def build_sprite(glyphs: dict) -> bytes:
    """{ký tự: ảnh RGBA SPRITE_W x SPRITE_H} -> ảnh gộp PNG lưu trong thư viện."""
    from PIL import Image
    sheet = Image.new("RGBA", (SPRITE_W * COLS, SPRITE_H * ROWS), (0, 0, 0, 0))
    for k, ch in enumerate(CHARS):
        g = glyphs.get(ch)
        if g is None:
            continue
        if g.size != (SPRITE_W, SPRITE_H):
            g = g.resize((SPRITE_W, SPRITE_H), Image.LANCZOS)
        r, c = divmod(k, COLS)
        sheet.alpha_composite(g.convert("RGBA"), (c * SPRITE_W, r * SPRITE_H))
    out = io.BytesIO()
    sheet.save(out, "PNG", optimize=True)
    return out.getvalue()


def parse_scan(data, threshold: int = 175) -> bytes:
    """Bản scan phiếu mẫu (1 file hoặc danh sách file: ảnh / PDF) -> ảnh gộp PNG (mỗi ô SPRITE_W x SPRITE_H,
    trong suốt, mực giữ màu). Không qua bước xem lại."""
    ex = extract_cells(data)
    glyphs = {}
    for ch, cell in ex["cells"].items():
        g = process_cell(cell, threshold, version=ex["version"])
        if g is not None:
            glyphs[ch] = g
    if len(glyphs) < 10:
        raise ValueError("Phiếu chưa có đủ chữ viết tay (tìm thấy quá ít ô có chữ).")
    return build_sprite(glyphs)


# ------------------------------------------------------------------ 3. ghép chữ
class HandSet:
    def __init__(self, sprite_png: bytes):
        from PIL import Image
        self.sheet = Image.open(io.BytesIO(sprite_png)).convert("RGBA")
        self.glyphs = {}
        for k, ch in enumerate(CHARS):
            r, c = divmod(k, COLS)
            g = self.sheet.crop((c * SPRITE_W, r * SPRITE_H, (c + 1) * SPRITE_W, (r + 1) * SPRITE_H))
            box = g.getchannel("A").point(lambda v: 255 if v > 90 else 0).getbbox()
            if box:
                self.glyphs[ch] = (g, box)

    @property
    def coverage(self) -> float:
        return len(self.glyphs) / len(CHARS)

    def has(self, ch: str) -> bool:
        return ch in self.glyphs

    def _base(self, ch):
        if ch in self.glyphs:
            return self.glyphs[ch]
        alt = ch.lower() if ch.isupper() else ch.upper()
        if alt in self.glyphs:
            return self.glyphs[alt]
        plain = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        plain = plain.replace("đ", "d").replace("Đ", "D")
        for c in (plain, plain.lower(), plain.upper()):
            if c in self.glyphs:
                return self.glyphs[c]
        return None

    def render(self, text: str, color=(20, 50, 170), height_px: int = 120, seed: int | None = None,
               spacing: float = 0.05, jitter: bool = True):
        """Trả về ảnh PIL RGBA. height_px = chiều cao một ô chữ (chữ hoa ≈ 55% giá trị này)."""
        from PIL import Image
        rnd = random.Random(seed if seed is not None else sum(map(ord, text)))
        head, foot = int(SPRITE_H * 0.45), int(SPRITE_H * 0.15)
        line_h = head + SPRITE_H + foot
        pitch = int(SPRITE_H * 0.9)
        lines = text.split("\n")
        widest = max(len(l) for l in lines) + 1
        out = Image.new("RGBA", (SPRITE_W * widest, pitch * (len(lines) - 1) + line_h), (0, 0, 0, 0))
        for li, line in enumerate(lines):
            x, oy = 0, li * pitch
            for ch in line:
                nfd = unicodedata.normalize("NFD", ch)
                tones = [c for c in nfd if c in TONES]
                b = None if ch == " " else self._base(unicodedata.normalize("NFC", "".join(c for c in nfd if c not in TONES)))
                if b is None:
                    x += int(SPRITE_W * 0.3)
                    continue
                g, (gl, gt, gr, gb) = b
                piece = g.crop((gl, 0, gr, SPRITE_H))
                dy = rnd.randint(-3, 3) if jitter else 0
                s = 1 + (rnd.uniform(-0.03, 0.03) if jitter else 0)
                if s != 1:
                    piece = piece.resize((max(1, int(piece.width * s)), max(1, int(SPRITE_H * s))), Image.BICUBIC)
                py = oy + head + dy + int(SPRITE_H * BASELINE * (1 - s))     # giữ chân chữ trên cùng đường kẻ
                out.alpha_composite(piece, (x, py))
                top, bottom = py + gt * s, py + gb * s
                for t in tones:
                    tb = self.glyphs.get(t)
                    if not tb:
                        continue
                    tg, (tl, tt, tr, tbm) = tb
                    mark = tg.crop((tl, tt, tr, tbm))
                    mx = int(x + piece.width / 2 - mark.width / 2)
                    if t == "\u0323":                              # nặng: dưới chân chữ
                        my = int(bottom + SPRITE_H * 0.03)
                    else:                                           # huyền, sắc, hỏi, ngã: trên đỉnh chữ
                        mx += int(piece.width * 0.06)
                        my = int(top - mark.height - SPRITE_H * 0.03)
                    out.alpha_composite(mark, (max(0, mx), max(0, min(out.height - mark.height, my))))
                x += piece.width + int(SPRITE_W * spacing)
        a = out.getchannel("A")
        colored = Image.new("RGBA", out.size, (*color, 255))
        colored.putalpha(a)
        box = a.point(lambda v: 255 if v > 30 else 0).getbbox()
        if box:
            colored = colored.crop((max(0, box[0] - 4), max(0, box[1] - 4), min(out.width, box[2] + 4),
                                    min(out.height, box[3] + 4)))
        scale = height_px / SPRITE_H
        if scale != 1:
            colored = colored.resize((max(1, int(colored.width * scale)), max(1, int(colored.height * scale))),
                                     Image.LANCZOS)
        return colored

    def render_png(self, text: str, color=(20, 50, 170), height_px: int = 160, seed=None) -> bytes:
        b = io.BytesIO()
        self.render(text, color, height_px, seed).save(b, "PNG", optimize=True)
        return b.getvalue()
