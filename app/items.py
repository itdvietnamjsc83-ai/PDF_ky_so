"""Đợt 2 – "nội dung đã thêm" chọn lại được để sửa tiếp.

Mỗi thứ người dùng thêm lên trang (hộp chữ, hình vẽ, ký hiệu, nét vẽ tay) vẫn là đối tượng PDF thật
(vector / chữ thật), nhưng được gắn thêm một dấu marked-content ``PdfKySoItem`` mang:
  - ``id``   : mã riêng của nội dung (mọi đối tượng PDF thuộc cùng nội dung có chung id)
  - ``spec`` : mô tả JSON đủ để dựng lại nội dung (loại, khung, góc xoay, màu, nét, chữ, điểm...)
Dấu được lưu ngay trong file PDF -> đóng file, mở lại hôm sau vẫn chọn lại được để sửa.
Phần mềm PDF khác chỉ thấy nội dung bình thường (marked-content bị bỏ qua khi hiển thị).

Sửa = gỡ các đối tượng của nội dung rồi dựng lại từ spec mới (vị trí / cỡ / góc / kiểu mới).

Toạ độ: toạ độ hiển thị (pt, gốc trên-trái, đã tính xoay trang), như trên màn hình.
"""
from __future__ import annotations

import ctypes
import json
import math
import uuid
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as C

from . import fonts
from .editing import (K_BEZ, _Frame, _load_font, _rgba, _text_obj, simplify, smooth_curves)

MARK = b"PdfKySoItem"

# ------------------------------------------------------------------ thư viện hình (kiểu Word Shapes)
# (mã, nhãn) theo nhóm
SHAPE_GROUPS = [
    ("Đường", [("line", "Đường thẳng"), ("arrow", "Mũi tên"), ("darrow", "Mũi tên hai đầu"),
               ("curve", "Đường cong"), ("carrow", "Mũi tên cong"), ("polyline", "Đường gấp khúc"),
               ("freeform", "Vẽ tự do")]),
    ("Hình cơ bản", [("rect", "Hình chữ nhật"), ("roundrect", "Chữ nhật bo góc"), ("ellipse", "Elip / tròn"),
                     ("triangle", "Tam giác"), ("rtriangle", "Tam giác vuông"), ("diamond", "Hình thoi"),
                     ("parallelogram", "Hình bình hành"), ("trapezoid", "Hình thang"), ("pentagon", "Ngũ giác"),
                     ("hexagon", "Lục giác"), ("octagon", "Bát giác"), ("polygon", "Đa giác tự do"),
                     ("star5", "Ngôi sao 5 cánh"), ("star4", "Ngôi sao 4 cánh"), ("heart", "Trái tim"),
                     ("cloud", "Đám mây"), ("plus", "Dấu cộng")]),
    ("Mũi tên khối", [("barrow_r", "Mũi tên phải"), ("barrow_l", "Mũi tên trái"), ("barrow_u", "Mũi tên lên"),
                      ("barrow_d", "Mũi tên xuống"), ("barrow_lr", "Mũi tên trái-phải")]),
    ("Lưu đồ", [("fc_process", "Xử lý"), ("fc_alt", "Xử lý thay thế"), ("fc_decision", "Quyết định"),
                ("fc_data", "Dữ liệu vào/ra"), ("fc_terminator", "Bắt đầu / kết thúc"),
                ("fc_document", "Tài liệu"), ("fc_predefined", "Quy trình con"), ("fc_manual", "Nhập tay"),
                ("fc_connector", "Điểm nối"), ("fc_database", "Cơ sở dữ liệu")]),
    ("Chú thích", [("co_rect", "Chú thích vuông"), ("co_round", "Chú thích bo góc"), ("co_oval", "Chú thích tròn"),
                   ("co_cloud", "Chú thích đám mây")]),
    ("Khung & dấu", [("frame", "Khung"), ("frame_double", "Khung đôi"), ("check", "Dấu tích ✓"),
                     ("cross", "Dấu nhân ✗"), ("highlight", "Bút dạ quang (vùng)")]),
]
SHAPE_LABEL = {k: lbl for _, items in SHAPE_GROUPS for k, lbl in items}
LINE_SHAPES = {"line", "arrow", "darrow", "curve", "carrow", "polyline"}
SYMBOL_SHAPES = {"check", "cross", "dot", "circle", "box", "boxcheck"}
OPEN_SHAPES = LINE_SHAPES | {"check", "cross"}
DASHES = [("solid", "Liền"), ("dash", "Đứt"), ("dot", "Chấm"), ("dashdot", "Gạch chấm")]
HEADS = [("none", "Không"), ("end", "Ở cuối"), ("start", "Ở đầu"), ("both", "Hai đầu")]
PENS = [("ball", "Bút bi"), ("sign", "Bút ký (nét to nhỏ)"), ("marker", "Bút dạ"), ("pencil", "Bút chì"),
        ("brush", "Bút lông"), ("highlighter", "Bút dạ quang")]
SMOOTH_EPS = [0.08, 0.3, 0.8, 1.6]        # 15d: mức làm mượt nét vẽ tay (0 = giữ sát nét, 3 = rất mượt)
SMOOTH_LEVELS = [(0, "Sát nét tay"), (1, "Vừa"), (2, "Mượt"), (3, "Rất mượt")]
PEN_DEFAULT_WIDTH = {"ball": 1.0, "sign": 1.6, "marker": 2.5, "pencil": 0.8, "brush": 3.5, "highlighter": 10.0}
VARIABLE_PENS = {"sign", "brush"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def default_heads(shape: str) -> str:
    return {"arrow": "end", "carrow": "end", "darrow": "both"}.get(shape, "none")


# ---------- hình học: đường dẫn trong toạ độ cục bộ (0..w, 0..h) ----------
# mỗi đường con: ("M", p), ("L", p), ("C", c1, c2, p), ("Z",)

def _poly(pts, closed=True):
    segs = [("M", pts[0])] + [("L", p) for p in pts[1:]]
    if closed:
        segs.append(("Z",))
    return segs


def _round_poly(pts, r):
    """Đa giác bo góc bán kính r (pt)."""
    n = len(pts)
    if r <= 0 or n < 3:
        return _poly(pts)
    segs = []
    for k in range(n):
        p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % n]
        d1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1e-9
        d2 = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1e-9
        rr = min(r, d1 / 2, d2 / 2)
        a = (p1[0] + (p0[0] - p1[0]) * rr / d1, p1[1] + (p0[1] - p1[1]) * rr / d1)
        b = (p1[0] + (p2[0] - p1[0]) * rr / d2, p1[1] + (p2[1] - p1[1]) * rr / d2)
        c1 = (a[0] + (p1[0] - a[0]) * K_BEZ, a[1] + (p1[1] - a[1]) * K_BEZ)
        c2 = (b[0] + (p1[0] - b[0]) * K_BEZ, b[1] + (p1[1] - b[1]) * K_BEZ)
        segs.append(("M", a) if k == 0 else ("L", a))
        segs.append(("C", c1, c2, b))
    segs.append(("Z",))
    return segs


def _ellipse(x0, y0, x1, y1, reverse=False):
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
    kx, ky = rx * K_BEZ, ry * K_BEZ
    segs = [("M", (cx + rx, cy)),
            ("C", (cx + rx, cy + ky), (cx + kx, cy + ry), (cx, cy + ry)),
            ("C", (cx - kx, cy + ry), (cx - rx, cy + ky), (cx - rx, cy)),
            ("C", (cx - rx, cy - ky), (cx - kx, cy - ry), (cx, cy - ry)),
            ("C", (cx + kx, cy - ry), (cx + rx, cy - ky), (cx + rx, cy)), ("Z",)]
    if reverse:
        segs = [("M", (cx + rx, cy)),
                ("C", (cx + rx, cy - ky), (cx + kx, cy - ry), (cx, cy - ry)),
                ("C", (cx - kx, cy - ry), (cx - rx, cy - ky), (cx - rx, cy)),
                ("C", (cx - rx, cy + ky), (cx - kx, cy + ry), (cx, cy + ry)),
                ("C", (cx + kx, cy + ry), (cx + rx, cy + ky), (cx + rx, cy)), ("Z",)]
    return segs


def _ngon(w, h, n, inner=None, rot=-90):
    pts = []
    m = n * 2 if inner else n
    for k in range(m):
        a = math.radians(rot + 360 * k / m)
        rad = inner if inner and k % 2 else 1.0
        pts.append((w / 2 + w / 2 * rad * math.cos(a), h / 2 + h / 2 * rad * math.sin(a)))
    return pts


def _cloud(w, h, bumps=10):
    segs = []
    cx, cy = w / 2, h / 2
    rx, ry = w / 2 * 0.80, h / 2 * 0.78
    step = 2 * math.pi / bumps

    def at(a, k=1.0):
        return cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)
    for j in range(bumps):
        a0, a1 = j * step, (j + 1) * step
        if j == 0:
            segs.append(("M", at(a0)))
        segs.append(("C", at(a0 + step * 0.15, 1.32), at(a1 - step * 0.15, 1.32), at(a1)))
    segs.append(("Z",))
    return segs


def _block_arrow(w, h, direction):
    """Mũi tên khối. direction: r l u d lr."""
    if direction in ("u", "d"):
        pts = _block_arrow(h, w, "r" if direction == "d" else "l")
        return [(y, x) for x, y in pts]              # hoán đổi trục
    hl = min(w * 0.45, h * 0.9)
    t0, t1 = h * 0.28, h * 0.72
    if direction == "r":
        return [(0, t0), (w - hl, t0), (w - hl, 0), (w, h / 2), (w - hl, h), (w - hl, t1), (0, t1)]
    if direction == "l":
        return [(w, t0), (hl, t0), (hl, 0), (0, h / 2), (hl, h), (hl, t1), (w, t1)]
    hl = min(w * 0.3, h * 0.9)
    return [(0, h / 2), (hl, 0), (hl, t0), (w - hl, t0), (w - hl, 0), (w, h / 2), (w - hl, h), (w - hl, t1),
            (hl, t1), (hl, h)]


def shape_paths(shape: str, w: float, h: float, radius: float = 0.0) -> list:
    """Các đường con (đơn vị pt, gốc = góc trên-trái khung) của một hình kín/hở trong khung w×h."""
    R = radius

    def poly(pts):
        return _round_poly(pts, R) if R > 0 else _poly(pts)
    if shape in ("rect", "fc_process"):
        return [poly([(0, 0), (w, 0), (w, h), (0, h)])]
    if shape in ("roundrect", "fc_alt"):
        return [_round_poly([(0, 0), (w, 0), (w, h), (0, h)], max(R, min(w, h) * 0.18))]
    if shape in ("ellipse", "fc_connector", "circle"):
        return [_ellipse(0, 0, w, h)]
    if shape == "triangle":
        return [poly([(w / 2, 0), (w, h), (0, h)])]
    if shape == "rtriangle":
        return [poly([(0, 0), (w, h), (0, h)])]
    if shape in ("diamond", "fc_decision"):
        return [poly([(w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)])]
    if shape in ("parallelogram", "fc_data"):
        o = min(w * 0.25, h * 0.6)
        return [poly([(o, 0), (w, 0), (w - o, h), (0, h)])]
    if shape == "trapezoid":
        o = min(w * 0.22, h * 0.6)
        return [poly([(o, 0), (w - o, 0), (w, h), (0, h)])]
    if shape == "pentagon":
        return [poly(_ngon(w, h, 5))]
    if shape == "hexagon":
        return [poly(_ngon(w, h, 6, rot=0))]
    if shape == "octagon":
        return [poly(_ngon(w, h, 8, rot=22.5))]
    if shape == "star5":
        return [poly(_ngon(w, h, 5, inner=0.40))]
    if shape == "star4":
        return [poly(_ngon(w, h, 4, inner=0.32))]
    if shape == "heart":
        def p(u, v):
            return u * w, v * h
        return [[("M", p(.5, .28)), ("C", p(.5, .10), p(.30, 0), p(.16, .02)),
                 ("C", p(0, .06), p(-.01, .36), p(.12, .56)), ("C", p(.22, .72), p(.40, .84), p(.5, 1)),
                 ("C", p(.60, .84), p(.78, .72), p(.88, .56)), ("C", p(1.01, .36), p(1, .06), p(.84, .02)),
                 ("C", p(.70, 0), p(.5, .10), p(.5, .28)), ("Z",)]]
    if shape == "cloud":
        return [_cloud(w, h)]
    if shape == "plus":
        a, b = w / 3, h / 3
        return [poly([(a, 0), (2 * a, 0), (2 * a, b), (w, b), (w, 2 * b), (2 * a, 2 * b), (2 * a, h), (a, h),
                      (a, 2 * b), (0, 2 * b), (0, b), (a, b)])]
    if shape.startswith("barrow_"):
        return [poly(_block_arrow(w, h, shape[7:]))]
    if shape == "fc_terminator":
        return [_round_poly([(0, 0), (w, 0), (w, h), (0, h)], min(w, h) / 2)]
    if shape == "fc_document":
        return [[("M", (0, 0)), ("L", (w, 0)), ("L", (w, h * .84)),
                 ("C", (w * .75, h * .66), (w * .62, h * .72), (w * .5, h * .84)),
                 ("C", (w * .36, h * .98), (w * .16, h * 1.0), (0, h * .9)), ("Z",)]]
    if shape == "fc_predefined":
        d = min(w * 0.1, 14)
        return [poly([(0, 0), (w, 0), (w, h), (0, h)]), [("M", (d, 0)), ("L", (d, h))],
                [("M", (w - d, 0)), ("L", (w - d, h))]]
    if shape == "fc_manual":
        return [poly([(0, h * .25), (w, 0), (w, h), (0, h)])]
    if shape == "fc_database":
        ry = min(h * 0.12, w * 0.25)
        kx, ky = w / 2 * K_BEZ, ry * K_BEZ
        cx = w / 2
        body = [("M", (0, ry)), ("L", (0, h - ry)),
                ("C", (0, h - ry + ky), (cx - kx, h), (cx, h)), ("C", (cx + kx, h), (w, h - ry + ky), (w, h - ry)),
                ("L", (w, ry)),
                ("C", (w, ry - ky), (cx + kx, 0), (cx, 0)), ("C", (cx - kx, 0), (0, ry - ky), (0, ry)), ("Z",)]
        front = [("M", (0, ry)), ("C", (0, ry + ky), (cx - kx, 2 * ry), (cx, 2 * ry)),
                 ("C", (cx + kx, 2 * ry), (w, ry + ky), (w, ry))]
        return [body, front]
    if shape in ("co_rect", "co_round"):
        b = h * 0.76
        pts = [(0, 0), (w, 0), (w, b), (w * .42, b), (w * .16, h), (w * .24, b), (0, b)]
        if shape == "co_round":
            return [_round_poly(pts, max(R, min(w, b) * 0.15))]
        return [poly(pts)]
    if shape == "co_oval":
        b = h * 0.8
        cx, cy, rx, ry = w / 2, b / 2, w / 2, b / 2
        pts = []
        n = 72
        a_lo, a_hi = math.radians(112), math.radians(128)
        tail_done = False
        for k in range(n):
            a = 2 * math.pi * k / n
            if a_lo <= a <= a_hi:
                if not tail_done:
                    pts += [(cx + rx * math.cos(a_lo), cy + ry * math.sin(a_lo)), (w * .12, h),
                            (cx + rx * math.cos(a_hi), cy + ry * math.sin(a_hi))]
                    tail_done = True
                continue
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        return [_poly(pts)]
    if shape == "co_cloud":
        b = h * 0.78
        s = min(w, h)
        return [_cloud(w, b), _ellipse(w * .2, b + s * .02, w * .2 + s * .1, b + s * .1),
                _ellipse(w * .1, b + s * .12, w * .1 + s * .06, b + s * .17)]
    if shape == "frame":
        t = min(w, h) * 0.12
        return [_poly([(0, 0), (w, 0), (w, h), (0, h)]), _poly([(t, t), (t, h - t), (w - t, h - t), (w - t, t)])]
    if shape == "frame_double":
        t = min(w, h) * 0.08
        return [_poly([(0, 0), (w, 0), (w, h), (0, h)]), _poly([(t, t), (w - t, t), (w - t, h - t), (t, h - t)])]
    if shape == "check":
        s = min(w, h)
        ox, oy = (w - s) / 2, (h - s) / 2
        return [_poly([(ox + s * .1, oy + s * .5), (ox + s * .38, oy + s * .8), (ox + s * .92, oy + s * .15)], False)]
    if shape == "cross":
        s = min(w, h)
        ox, oy = (w - s) / 2, (h - s) / 2
        return [[("M", (ox + s * .15, oy + s * .15)), ("L", (ox + s * .85, oy + s * .85))],
                [("M", (ox + s * .85, oy + s * .15)), ("L", (ox + s * .15, oy + s * .85))]]
    if shape == "dot":
        s = min(w, h) * 0.45
        return [_ellipse(w / 2 - s, h / 2 - s, w / 2 + s, h / 2 + s)]
    if shape in ("box", "boxcheck"):
        s = min(w, h)
        ox, oy = (w - s) / 2, (h - s) / 2
        out = [_poly([(ox, oy), (ox + s, oy), (ox + s, oy + s), (ox, oy + s)])]
        if shape == "boxcheck":
            out.append(_poly([(ox + s * .2, oy + s * .5), (ox + s * .42, oy + s * .74), (ox + s * .82, oy + s * .22)],
                             False))
        return out
    if shape == "highlight":
        return [_poly([(0, 0), (w, 0), (w, h), (0, h)])]
    raise ValueError(shape)


def curve_ctrl(p0, p1, bend=0.3):
    """Điểm điều khiển Bézier bậc 3 của đường cong từ p0 tới p1 (phồng sang trái hướng đi)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = dy * bend, -dx * bend
    c1 = (p0[0] + dx / 3 + nx, p0[1] + dy / 3 + ny)
    c2 = (p0[0] + 2 * dx / 3 + nx, p0[1] + 2 * dy / 3 + ny)
    return c1, c2


def arrow_head(tip, frm, width):
    """Tam giác đầu mũi tên tại tip, hướng từ frm tới tip. Trả về (3 điểm, điểm lùi để rút ngắn thân)."""
    ang = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
    head = max(6.0, width * 4)
    a1 = (tip[0] - head * math.cos(ang - 0.45), tip[1] - head * math.sin(ang - 0.45))
    a2 = (tip[0] - head * math.cos(ang + 0.45), tip[1] - head * math.sin(ang + 0.45))
    back = (tip[0] - head * 0.8 * math.cos(ang), tip[1] - head * 0.8 * math.sin(ang))
    return [tip, a1, a2], back


def dash_array(kind: str, width: float):
    w = max(width, 0.8)
    return {"dash": [4 * w, 2.5 * w], "dot": [0.01, 2.2 * w], "dashdot": [5 * w, 2 * w, 0.01, 2 * w]}.get(kind)


# ---------- nét bút biến thiên (bút ký, bút lông) ----------
def pen_widths(samples, base: float, pen: str) -> list[float]:
    """samples: [(x, y, t_giây, lực_nhấn 0..1 hoặc None)]. Nét to khi đi chậm / nhấn mạnh, nhỏ khi đi nhanh."""
    out = []
    lo, hi = (0.35, 1.45) if pen == "sign" else (0.2, 1.9)
    prev_w = base
    for k, s in enumerate(samples):
        x, y, t, pr = (tuple(s) + (0.0, None))[:4]
        if pr is not None and pr > 0:
            f = lo + (hi - lo) * pr
        else:
            if k == 0:
                v = 0.0
            else:
                px, py, pt = samples[k - 1][0], samples[k - 1][1], samples[k - 1][2] if len(samples[k - 1]) > 2 else 0
                dt = max(1e-3, (t or 0) - (pt or 0))
                v = math.hypot(x - px, y - py) / dt            # pt/giây
            f = hi - (hi - lo) * min(1.0, v / 900.0)
        w = base * f
        w = prev_w * 0.65 + w * 0.35                           # làm mượt, không giật cục
        prev_w = w
        out.append(round(w, 3))
    n = len(out)
    for k in range(min(4, n)):                                 # đầu/cuối nét thon như bút thật
        taper = 0.45 + 0.55 * (k + 1) / 5
        out[k] *= taper
        out[n - 1 - k] *= taper
    return out


def outline_polygon(pts, widths):
    """Đa giác bao của nét có độ rộng thay đổi (tô kín)."""
    n = len(pts)
    if n == 1:
        x, y = pts[0]
        r = max(widths[0] / 2, 0.3)
        return [(x + r * math.cos(a * math.pi / 6), y + r * math.sin(a * math.pi / 6)) for a in range(12)]
    left, right = [], []
    for k in range(n):
        a = pts[max(0, k - 1)]
        b = pts[min(n - 1, k + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1e-9
        nx, ny = -dy / d, dx / d
        r = max(widths[k] / 2, 0.15)
        left.append((pts[k][0] + nx * r, pts[k][1] + ny * r))
        right.append((pts[k][0] - nx * r, pts[k][1] - ny * r))

    def cap(center, frm, r, steps=5):
        ang = math.atan2(frm[1] - center[1], frm[0] - center[0])
        return [(center[0] + r * math.cos(ang - math.pi * j / steps), center[1] + r * math.sin(ang - math.pi * j / steps))
                for j in range(1, steps)]
    end = cap(pts[-1], left[-1], max(widths[-1] / 2, 0.15))
    start = cap(pts[0], right[0], max(widths[0] / 2, 0.15))
    return simplify(left, 0.08) + end + simplify(right[::-1], 0.08) + start


# ------------------------------------------------------------------ dựng đối tượng PDF từ spec
def _path_obj(fr: _Frame, subpaths, ox, oy):
    obj = None
    for sp in subpaths:
        for seg in sp:
            op = seg[0]
            if op == "M":
                x, y = fr.u(ox + seg[1][0], oy + seg[1][1])
                if obj is None:
                    obj = C.FPDFPageObj_CreateNewPath(x, y)
                else:
                    C.FPDFPath_MoveTo(obj, x, y)
            elif op == "L":
                x, y = fr.u(ox + seg[1][0], oy + seg[1][1])
                C.FPDFPath_LineTo(obj, x, y)
            elif op == "C":
                a = fr.u(ox + seg[1][0], oy + seg[1][1])
                b = fr.u(ox + seg[2][0], oy + seg[2][1])
                c = fr.u(ox + seg[3][0], oy + seg[3][1])
                C.FPDFPath_BezierTo(obj, a[0], a[1], b[0], b[1], c[0], c[1])
            elif op == "Z":
                C.FPDFPath_Close(obj)
    return obj


def _apply_style(obj, stroke=None, width=1.0, fill=None, cap="round", blend=None, dash=None):
    if stroke is not None:
        C.FPDFPageObj_SetStrokeColor(obj, *stroke)
        C.FPDFPageObj_SetStrokeWidth(obj, float(max(width, 0.05)))
    if fill is not None:
        C.FPDFPageObj_SetFillColor(obj, *fill)
    C.FPDFPath_SetDrawMode(obj, C.FPDF_FILLMODE_WINDING if fill is not None else C.FPDF_FILLMODE_NONE,
                           bool(stroke is not None))
    if cap == "round":
        C.FPDFPageObj_SetLineCap(obj, C.FPDF_LINECAP_ROUND)
        C.FPDFPageObj_SetLineJoin(obj, C.FPDF_LINEJOIN_ROUND)
    elif cap == "square":
        C.FPDFPageObj_SetLineCap(obj, C.FPDF_LINECAP_PROJECTING_SQUARE)
        C.FPDFPageObj_SetLineJoin(obj, C.FPDF_LINEJOIN_MITER)
    else:
        C.FPDFPageObj_SetLineJoin(obj, C.FPDF_LINEJOIN_MITER)
    if blend:
        C.FPDFPageObj_SetBlendMode(obj, blend.encode())
    if dash:
        arr = (ctypes.c_float * len(dash))(*dash)
        C.FPDFPageObj_SetDashArray(obj, arr, len(dash), 0.0)
    return obj


def _col(color, opacity=100):
    r, g, b, a = _rgba(color or "#000000")
    return r, g, b, int(round(a * max(0, min(100, opacity)) / 100))


def spec_rect(spec):
    return tuple(float(v) for v in spec["rect"])


def _denorm(spec, pts):
    x0, y0, x1, y1 = spec_rect(spec)
    return [(x0 + u * (x1 - x0), y0 + v * (y1 - y0)) for u, v in pts]


def normalize(points, rect):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    return [[round((x - x0) / w, 5) if w > 1e-6 else 0.0, round((y - y0) / h, 5) if h > 1e-6 else 0.0]
            for x, y in points]


def bbox(points, min_size=0.0):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if x1 - x0 < min_size:
        c = (x0 + x1) / 2
        x0, x1 = c - min_size / 2, c + min_size / 2
    if y1 - y0 < min_size:
        c = (y0 + y1) / 2
        y0, y1 = c - min_size / 2, c + min_size / 2
    return x0, y0, x1, y1


def _shape_objs(fr, spec):
    shape = spec["shape"]
    x0, y0, x1, y1 = spec_rect(spec)
    w, h = x1 - x0, y1 - y0
    width = float(spec.get("width", 1.5))
    stroke = _col(spec.get("stroke", "#d32f2f"), spec.get("opacity", 100)) if spec.get("stroke") else None
    fill = _col(spec["fill"], spec.get("fill_opacity", 100)) if spec.get("fill") else None
    dash = dash_array(spec.get("dash", "solid"), width)
    objs = []
    if shape == "highlight":
        r, g, b, _ = _rgba(spec.get("fill") or spec.get("stroke") or "#ffe600")
        o = _path_obj(fr, shape_paths("highlight", w, h), x0, y0)
        return [_apply_style(o, None, 0, (r, g, b, int(110 * spec.get("opacity", 100) / 100)), cap="butt",
                             blend="Multiply")]
    if shape in LINE_SHAPES:
        pts = _denorm(spec, spec["pts"])
        heads = spec.get("heads", default_heads(shape))
        if shape in ("curve", "carrow") and len(pts) >= 2:
            p0, p1 = pts[0], pts[-1]
            c1, c2 = curve_ctrl(p0, p1, float(spec.get("bend", 0.3)))
            end_from, start_from = c2, c1
        else:
            end_from, start_from = pts[-2], pts[1]
        head_objs = []
        if heads in ("end", "both"):
            tri, back = arrow_head(pts[-1], end_from, width)
            head_objs.append(tri)
            pts = pts[:-1] + [back]
        if heads in ("start", "both"):
            tri, back = arrow_head(pts[0], start_from, width)
            head_objs.append(tri)
            pts = [back] + pts[1:]
        if shape in ("curve", "carrow"):
            c1, c2 = curve_ctrl(pts[0], pts[-1], float(spec.get("bend", 0.3)))
            segs = [[("M", pts[0]), ("C", c1, c2, pts[-1])]]
        else:
            segs = [_poly(pts, False)]
        body = _apply_style(_path_obj(fr, segs, 0, 0), stroke or _col("#000000"), width, None, dash=dash)
        objs.append(body)
        for tri in head_objs:
            o = _path_obj(fr, [_poly(tri)], 0, 0)
            objs.append(_apply_style(o, stroke, width * 0.5, stroke))
        return objs
    if shape == "polygon":
        segs = [_poly(_denorm(spec, spec["pts"]))]
        return [_apply_style(_path_obj(fr, segs, 0, 0), stroke, width, fill, dash=dash)]
    subpaths = shape_paths(shape, w, h, float(spec.get("radius", 0) or 0))
    open_ = shape in OPEN_SHAPES
    if shape in SYMBOL_SHAPES and shape not in ("dot",):
        width = max(width, min(w, h) * (0.12 if shape in ("check", "cross") else 0.06))
    if shape == "dot":
        fill, stroke = stroke or _col("#d32f2f"), None
    o = _path_obj(fr, subpaths, x0, y0)
    cap = "round" if (open_ or shape in ("ellipse", "cloud", "heart", "circle")) else "butt"
    objs.append(_apply_style(o, stroke, width, None if open_ else fill, cap=cap, dash=dash))
    return objs


def _ink_objs(fr, spec):
    pen = spec.get("pen", "ball")
    color = spec.get("stroke", "#0d47a1")
    width = float(spec.get("width", PEN_DEFAULT_WIDTH.get(pen, 1.2)))
    op = spec.get("opacity", 100)
    objs = []
    widths_all = spec.get("widths") or []
    for k, s in enumerate(spec.get("strokes", [])):
        if not s:
            continue
        pts = _denorm(spec, s)
        if pen in VARIABLE_PENS and k < len(widths_all) and len(widths_all[k]) == len(pts):
            poly = outline_polygon(pts, widths_all[k])
            o = _path_obj(fr, [_poly(poly)], 0, 0)
            objs.append(_apply_style(o, None, 0, _col(color, op)))
            continue
        if len(pts) == 1:
            pts = [pts[0], (pts[0][0] + 0.01, pts[0][1])]
        lvl = int(spec.get("smooth", 1))
        pts = simplify(pts, SMOOTH_EPS[max(0, min(3, lvl))] if pen != "pencil" or lvl != 1 else 0.2)
        segs = [[("M", pts[0])] + [("C", c1, c2, p) for c1, c2, p in smooth_curves(pts)]]
        o = _path_obj(fr, segs, 0, 0)
        if pen == "highlighter":
            r, g, b, _ = _rgba(color)
            objs.append(_apply_style(o, (r, g, b, int(115 * op / 100)), width, None, cap="square", blend="Multiply"))
        elif pen == "pencil":
            objs.append(_apply_style(o, _col(color, op * 0.72), width, None))
        elif pen == "marker":
            objs.append(_apply_style(o, _col(color, op * 0.93), width, None))
        else:
            objs.append(_apply_style(o, _col(color, op), width, None))
    return objs


def text_layout(spec):
    """(các dòng, chiều cao khối) của hộp chữ."""
    fp = font_path(spec)
    size = float(spec.get("size", 12))
    x0, y0, x1, y1 = spec_rect(spec)
    width = x1 - x0
    text = spec.get("text", "")
    lines = fonts.wrap(fp, text, size, width) if spec.get("wrap", True) and width > 0 else text.split("\n")
    asc, desc = fonts.metrics(fp)
    lh = size * float(spec.get("line_height", 1.25))
    h = (len(lines) - 1) * lh + (asc + desc) * size
    return lines, h


def font_path(spec) -> str:
    import os
    fp = spec.get("font") or ""
    if not (fp and os.path.exists(fp)):
        fp = fonts.system_font("serif")
    if spec.get("bold") or spec.get("italic"):            # 1.0.22: hộp chữ đậm / nghiêng (phông hệ thống)
        fp = fonts.styled_variant(fp, bool(spec.get("bold")), bool(spec.get("italic")))
    return fp


def _text_objs(doc, fr, spec):
    fp = font_path(spec)
    text = spec.get("text", "")
    if not text.strip():
        return []
    size = float(spec.get("size", 12))
    chars = "".join(sorted(set(text) - {"\n"}))
    miss = fonts.missing_chars(fp, chars)
    if miss:
        raise ValueError(f"Phông chữ không có ký tự: {miss}")
    lines, _ = text_layout(spec)
    font = _load_font(doc, fonts.subset(fp, chars))
    asc, _ = fonts.metrics(fp)
    x0, y0, x1, y1 = spec_rect(spec)
    lh = size * float(spec.get("line_height", 1.25))
    align = spec.get("align", "left")
    color = _col(spec.get("color", "#000000"), spec.get("opacity", 100))
    objs = []
    try:
        for k, line in enumerate(lines):
            if not line.strip():
                continue
            x = x0
            if align in ("center", "right"):
                lw = fonts.measure(fp, line, size)
                x = x0 + ((x1 - x0) - lw) / (2 if align == "center" else 1)
            objs.append(_text_obj(doc, font, size, line, fr.matrix_at(x, y0 + asc * size + k * lh), color))
    finally:
        C.FPDFFont_Close(font)
    return objs


def _shadow(objs_builder, fr, spec, dx=2.5, dy=2.5):
    """Bóng đổ: dựng lại hình lệch (dx, dy), màu xám trong suốt."""
    sh = dict(spec)
    x0, y0, x1, y1 = spec_rect(spec)
    sh["rect"] = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
    grey = "#000000"
    if sh.get("fill"):
        sh["fill"], sh["fill_opacity"] = grey, 28
    if sh.get("stroke"):
        sh["stroke"], sh["opacity"] = grey, 28
    return objs_builder(fr, sh)


TEXT_SHAPES_BODY = {"co_rect": 0.76, "co_round": 0.76, "co_oval": 0.8, "co_cloud": 0.78}


def shape_text_spec(spec) -> dict | None:
    """14d – chữ bên trong hình / khung chú thích: canh giữa trong thân hình (trừ đuôi chú thích)."""
    text = spec.get("text") or ""
    if not text.strip() or spec.get("shape") in LINE_SHAPES:
        return None
    x0, y0, x1, y1 = spec_rect(spec)
    h = (y1 - y0) * TEXT_SHAPES_BODY.get(spec.get("shape"), 1.0)
    inset = {"ellipse": 0.15, "fc_connector": 0.15, "diamond": 0.25, "fc_decision": 0.25, "triangle": 0.2,
             "cloud": 0.18, "co_oval": 0.15, "co_cloud": 0.18, "star5": 0.3, "heart": 0.22}.get(spec.get("shape"), 0.0)
    pad = 5 + float(spec.get("width", 1)) / 2
    bx0 = x0 + pad + (x1 - x0) * inset / 2
    bx1 = x1 - pad - (x1 - x0) * inset / 2
    if bx1 - bx0 < 8:
        bx0, bx1 = x0 + 2, x1 - 2
    t = {"kind": "text", "text": text, "font": spec.get("font", ""), "size": float(spec.get("text_size", 11)),
         "color": spec.get("text_color", "#1b1b1b"), "align": spec.get("text_align", "center"),
         "rect": [bx0, y0, bx1, y0 + 10], "opacity": spec.get("opacity", 100)}
    _, th = text_layout(t)
    ty = y0 + (h - th) / 2
    t["rect"] = [bx0, ty, bx1, ty + th]
    return t


# ------------------------------------------------------------------ 1.0.22: con dấu chữ tùy biến
STAMP_PRESETS = ["ĐÃ DUYỆT", "SAO Y BẢN CHÍNH", "BẢN SAO", "BẢN CHÍNH", "ĐÃ KIỂM TRA", "ĐÃ NHẬN", "ĐÃ THANH TOÁN",
                 "MẬT", "KHẨN", "HỎA TỐC", "NHÁP", "HỦY", "LƯU HÀNH NỘI BỘ"]
STAMP_SHAPES = [("rect", "Chữ nhật"), ("roundrect", "Chữ nhật bo góc"), ("ellipse", "Bầu dục"),
                ("circle", "Tròn (chữ chạy vòng)"), ("hexagon", "Lục giác"), ("none", "Không khung (chỉ chữ)")]
STAMP_BORDERS = [("single", "Viền đơn"), ("double", "Viền đôi"), ("thick", "Viền đậm")]
STAMP_FONTS = [("sans", "Không chân, đậm"), ("serif", "Có chân, đậm (Times)")]


def stamp_spec(text: str = "ĐÃ DUYỆT", shape: str = "rect", rect=(0, 0, 150, 50), **kw) -> dict:
    s = {"kind": "stamp", "text": text, "shape": shape, "rect": list(rect), "angle": 0, "border": "double",
         "color": "#d32f2f", "opacity": 100, "sub": "", "arc": "", "family": "sans"}
    s.update({k: v for k, v in kw.items() if v is not None})
    return s


def stamp_font(spec) -> str:
    return fonts.system_font(spec.get("family") or "sans", bold=True)


def _stamp_line_w(spec, w, h) -> float:
    base = max(0.8, min(w, h) * 0.035)
    return base * (1.9 if spec.get("border") == "thick" else 1.0)


def stamp_layout(spec):
    """Bố cục con dấu (toạ độ trong khung, gốc trên-trái):
    {"paths": [(subpaths, ox, oy, nét)], "lines": [(chữ, cỡ, x, y_baseline)], "arc": [(ký tự, cỡ, x, y, góc)]}."""
    x0, y0, x1, y1 = spec_rect(spec)
    w, h = max(4.0, x1 - x0), max(4.0, y1 - y0)
    shape = spec.get("shape", "rect")
    fp = stamp_font(spec)
    asc, desc = fonts.metrics(fp)
    lw = _stamp_line_w(spec, w, h)
    out = {"paths": [], "lines": [], "arc": [], "lw": lw}
    if shape != "none":
        sh = "ellipse" if shape == "circle" else shape
        out["paths"].append((shape_paths(sh, w - lw, h - lw), lw / 2, lw / 2, lw))
        if spec.get("border", "double") == "double":
            t = lw * 2.6
            out["paths"].append((shape_paths(sh, w - 2 * t, h - 2 * t), t, t, max(0.5, lw * 0.45)))
    # vùng chữ bên trong
    inset = {"ellipse": 0.15, "circle": 0.15, "hexagon": 0.12, "roundrect": 0.04}.get(shape, 0.0)
    pad = (lw * 3.6 if spec.get("border", "double") == "double" else lw * 2.2) if shape != "none" else 0.0
    bx0, by0 = pad + w * inset / 2, pad + h * inset / 2
    bw, bh = max(2.0, w - 2 * bx0), max(2.0, h - 2 * by0)
    arc = (spec.get("arc") or "").strip() if shape == "circle" else ""
    if arc:                                          # chữ chạy vòng phía trên + vòng trong ngăn cách
        R = min(w, h) / 2
        cx, cy = w / 2, h / 2
        r_in = R * 0.58
        out["paths"].append(([_ellipse(cx - r_in, cy - r_in, cx + r_in, cy + r_in)], 0, 0, max(0.5, lw * 0.6)))
        top = R - pad - lw * 0.3                          # mép ngoài của chữ (trong viền)
        band = top - r_in - lw * 0.8
        fs = max(2.0, min(R * 0.2, band / (asc + 0.1)))
        base = top - asc * fs
        for _ in range(12):
            total = sum(fonts.measure(fp, ch, fs) for ch in arc) + fs * 0.12 * (len(arc) - 1)
            span = total / max(1.0, base)
            if span <= math.radians(300):
                break
            fs *= 0.92
            base = top - asc * fs
        a = -math.pi / 2 - span / 2
        for ch in arc:
            adv = fonts.measure(fp, ch, fs)
            mid = a + (adv / 2) / base
            out["arc"].append((ch, fs, cx + base * math.cos(mid), cy + base * math.sin(mid), mid))
            a += (adv + fs * 0.12) / base
        k = r_in * 0.78
        bx0, by0, bw, bh = cx - k, cy - k * 0.8, 2 * k, 1.6 * k
    lines = [ln for ln in (spec.get("text") or "").split("\n") if ln.strip()]
    sub = [ln for ln in (spec.get("sub") or "").split("\n") if ln.strip()]
    if not lines and not sub:
        return out
    ratio = 0.5                                       # cỡ dòng phụ so với dòng chính
    gap = 1.12
    units = len(lines) * (asc + desc) * gap + len(sub) * (asc + desc) * gap * ratio
    fs = bh / max(0.1, units)
    for ln in lines:
        fs = min(fs, bw / max(1e-3, fonts.measure(fp, ln, 1.0)))
    for ln in sub:
        fs = min(fs, bw / max(1e-3, fonts.measure(fp, ln, ratio)))
    fs = max(2.0, fs * 0.98)
    rows = [(ln, fs) for ln in lines] + [(ln, fs * ratio) for ln in sub]
    total = sum((asc + desc) * s * gap for _, s in rows)
    y = by0 + (bh - total) / 2
    for ln, s in rows:
        lh = (asc + desc) * s * gap
        x = bx0 + (bw - fonts.measure(fp, ln, s)) / 2
        out["lines"].append((ln, s, x, y + (lh - (asc + desc) * s) / 2 + asc * s))
        y += lh
    return out


def _stamp_objs(doc, fr, spec):
    x0, y0, x1, y1 = spec_rect(spec)
    col = _col(spec.get("color", "#d32f2f"), spec.get("opacity", 100))
    lay = stamp_layout(spec)
    objs = []
    for subpaths, ox, oy, lw in lay["paths"]:
        objs.append(_apply_style(_path_obj(fr, subpaths, x0 + ox, y0 + oy), col, lw, None, cap="round"))
    chars = "".join(sorted({c for ln, *_ in lay["lines"] for c in ln} | {c for c, *_ in lay["arc"]} - {" "}))
    if not chars:
        return objs
    fp = stamp_font(spec)
    miss = fonts.missing_chars(fp, chars)
    if miss:
        raise ValueError(f"Phông chữ không có ký tự: {miss}")
    font = _load_font(doc, fonts.subset(fp, chars))
    try:
        for ln, s, x, yb in lay["lines"]:
            objs.append(_text_obj(doc, font, s, ln, fr.matrix_at(x0 + x, y0 + yb), col))
        for ch, s, cx, cy, a in lay["arc"]:
            if ch == " ":
                continue
            ux, uy = math.cos(a), math.sin(a)             # "lên" của chữ = hướng ra ngoài vòng tròn
            dx, dy = -uy, ux                              # hướng dòng chữ = tiếp tuyến chiều kim đồng hồ
            adv = fonts.measure(fp, ch, s)
            ox, oy = fr.u(x0 + cx - dx * adv / 2, y0 + cy - dy * adv / 2)
            m = C.FS_MATRIX(dx * fr.ex[0] + dy * fr.ey[0], dx * fr.ex[1] + dy * fr.ey[1],
                            ux * fr.ex[0] + uy * fr.ey[0], ux * fr.ex[1] + uy * fr.ey[1], ox, oy)
            objs.append(_text_obj(doc, font, s, ch, m, col))
    finally:
        C.FPDFFont_Close(font)
    return objs


def build_objects(doc, i: int, spec: dict) -> list:
    """Dựng các đối tượng PDF (chưa chèn vào trang) của một nội dung."""
    fr = _Frame(doc, i)
    kind = spec["kind"]
    if kind == "shape":
        objs = (_shadow(_shape_objs, fr, spec) if spec.get("shadow") and spec["shape"] != "highlight" else []) + \
            _shape_objs(fr, spec)
        ts = shape_text_spec(spec)
        if ts:
            objs += _text_objs(doc, fr, ts)
    elif kind == "ink":
        objs = _ink_objs(fr, spec)
    elif kind == "text":
        objs = _text_objs(doc, fr, spec)
    elif kind == "stamp":
        objs = _stamp_objs(doc, fr, spec)
    else:
        raise ValueError(kind)
    angle = float(spec.get("angle", 0) or 0)
    if angle % 360:
        x0, y0, x1, y1 = spec_rect(spec)
        m = _display_rotation_in_user(fr, (x0 + x1) / 2, (y0 + y1) / 2, angle)
        for o in objs:
            C.FPDFPageObj_Transform(o, *m)
    return objs


def _display_rotation_in_user(fr: _Frame, cx, cy, angle):
    """Ma trận (a..f) trong toạ độ PDF tương đương xoay `angle` độ (chiều kim đồng hồ trên màn hình) quanh (cx, cy)."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    # F: hiển thị -> user: u = o + x*ex + y*ey ; F^-1 dùng ma trận nghịch đảo
    ex, ey, o = fr.ex, fr.ey, fr.o
    det = ex[0] * ey[1] - ex[1] * ey[0]

    def to_disp(ux, uy):
        dx, dy = ux - o[0], uy - o[1]
        return ((dx * ey[1] - dy * ey[0]) / det, (ex[0] * dy - ex[1] * dx) / det)

    def rot(x, y):
        x, y = x - cx, y - cy
        return cx + x * c - y * s, cy + x * s + y * c

    def T(ux, uy):
        return fr.u(*rot(*to_disp(ux, uy)))
    p0 = T(0, 0)
    p1 = T(1, 0)
    p2 = T(0, 1)
    return (p1[0] - p0[0], p1[1] - p0[1], p2[0] - p0[0], p2[1] - p0[1], p0[0], p0[1])


def _mark(doc, obj, item_id: str, spec_json: str | None):
    mk = C.FPDFPageObj_AddMark(obj, MARK)
    C.FPDFPageObjMark_SetStringParam(doc.pdf.raw, obj, mk, b"id", item_id.encode())
    if spec_json is not None:
        C.FPDFPageObjMark_SetStringParam(doc.pdf.raw, obj, mk, b"spec", spec_json.encode())


def _spec_json(spec) -> str:
    return json.dumps(spec, ensure_ascii=True, separators=(",", ":"))


def _insert_objects(doc, i, spec, back=False):
    if back:
        doc._load_bytes(doc.to_bytes())             # mọi đối tượng cũ về luồng nội dung sẵn có
    objs = build_objects(doc, i, spec)
    if not objs:
        return 0
    js = _spec_json(spec)
    page = doc.page(i)
    for k, o in enumerate(objs):
        _mark(doc, o, spec["id"], js if k == 0 else None)
        C.FPDFPage_InsertObject(page.raw, o)
    page.gen_content()
    if back:
        doc._stream_to_back(i)
    return len(objs)


def add_item(doc, i: int, spec: dict, snapshot=True) -> dict:
    """Thêm nội dung mới lên trang. Trả về spec (đã có id)."""
    spec = dict(spec)
    spec.setdefault("id", new_id())
    spec.setdefault("angle", 0)
    if snapshot:
        doc._snapshot()
    _insert_objects(doc, i, spec, back=spec.get("z") == "back" and can_send_back(doc, i))
    if snapshot:
        doc._changed()
    return spec


def can_send_back(doc, i) -> bool:
    return doc.layer_for(i, "behind") == "behind"


# ------------------------------------------------------------------ tìm lại nội dung đã thêm
@dataclass
class Item:
    id: str
    page: int
    spec: dict
    indices: list = field(default_factory=list)       # vị trí các đối tượng PDF trên trang
    rect: tuple = (0, 0, 0, 0)                          # khung bao hiển thị (đã xoay)

    @property
    def kind(self) -> str:
        return self.spec.get("kind", "")

    @property
    def label(self) -> str:
        k = self.kind
        if k == "text":
            return "Hộp chữ"
        if k == "ink":
            return dict(PENS).get(self.spec.get("pen", "ball"), "Nét vẽ tay")
        if k == "stamp":
            return "Con dấu"
        return SHAPE_LABEL.get(self.spec.get("shape", ""), "Hình vẽ")


def _mark_info(obj):
    """(id, spec_json | None) nếu đối tượng mang dấu PdfKySoItem."""
    for k in range(max(0, C.FPDFPageObj_CountMarks(obj))):
        mk = C.FPDFPageObj_GetMark(obj, k)
        buf = (ctypes.c_ushort * 64)()
        n = ctypes.c_ulong(0)
        if not C.FPDFPageObjMark_GetName(mk, buf, ctypes.sizeof(buf), ctypes.byref(n)):
            continue
        if bytes(buf)[:max(0, n.value - 2)] != MARK.decode().encode("utf-16-le"):
            continue
        vals = {}
        for key in (b"id", b"spec"):
            n = ctypes.c_ulong(0)
            if not C.FPDFPageObjMark_GetParamStringValue(mk, key, None, 0, ctypes.byref(n)) or n.value <= 0:
                continue
            sb = (ctypes.c_ushort * (n.value // 2 + 1))()
            C.FPDFPageObjMark_GetParamStringValue(mk, key, sb, n.value, ctypes.byref(n))
            vals[key] = bytes(sb)[:max(0, n.value - 2)].decode("utf-16-le", "ignore")
        if "id" in {k.decode() for k in vals}:
            return vals[b"id"], vals.get(b"spec")
    return None


_CACHE: dict = {}


def find_items(doc, i: int) -> list[Item]:
    """Mọi nội dung đã thêm (chọn lại được) trên trang, theo thứ tự dưới -> trên."""
    key = (id(doc), doc.version, i, id(doc.pdf))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    page = doc.page(i)
    fr = _Frame(doc, i)
    items: dict[str, Item] = {}
    order = []
    for k in range(C.FPDFPage_CountObjects(page.raw)):
        obj = C.FPDFPage_GetObject(page.raw, k)
        info = _mark_info(obj)
        if not info:
            continue
        iid, sj = info
        it = items.get(iid)
        if it is None:
            it = items[iid] = Item(iid, i, {})
            order.append(iid)
        it.indices.append(k)
        if sj and not it.spec:
            try:
                it.spec = json.loads(sj)
            except ValueError:
                pass
        l, b, r, t = (ctypes.c_float() for _ in range(4))
        C.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(t))
        rr = fr.display_rect(l.value, b.value, r.value, t.value)
        if it.rect == (0, 0, 0, 0):
            it.rect = rr
        else:
            it.rect = (min(it.rect[0], rr[0]), min(it.rect[1], rr[1]), max(it.rect[2], rr[2]), max(it.rect[3], rr[3]))
    out = [items[k] for k in order if items[k].spec.get("kind")]
    out.sort(key=lambda it: max(it.indices))
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def _local(spec, x, y):
    """Điểm hiển thị -> toạ độ trong khung chưa xoay của nội dung."""
    a = -math.radians(float(spec.get("angle", 0) or 0))
    x0, y0, x1, y1 = spec_rect(spec)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


def item_at(doc, i: int, x: float, y: float, pad: float = 3.0) -> Item | None:
    """Nội dung trên cùng tại điểm (x, y)."""
    for it in reversed(find_items(doc, i)):
        x0, y0, x1, y1 = it.rect
        if not (x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad):
            continue
        spec = it.spec
        if spec.get("kind") == "shape" and spec.get("shape") in LINE_SHAPES:
            pts = _denorm(spec, spec["pts"])
            lx, ly = _local(spec, x, y)
            tol = max(pad + 2, float(spec.get("width", 1)) + 3)
            if spec["shape"] in ("curve", "carrow"):
                c1, c2 = curve_ctrl(pts[0], pts[-1], float(spec.get("bend", 0.3)))
                pts = [_bez(pts[0], c1, c2, pts[-1], t / 12) for t in range(13)]
            if any(_seg_dist((lx, ly), pts[k], pts[k + 1]) <= tol for k in range(len(pts) - 1)):
                return it
            continue
        if spec.get("kind") == "ink":
            lx, ly = _local(spec, x, y)
            tol = max(pad + 2, float(spec.get("width", 1)) + 3)
            hit = False
            for s in spec.get("strokes", []):
                pts = _denorm(spec, s)
                if len(pts) == 1 and math.hypot(lx - pts[0][0], ly - pts[0][1]) <= tol:
                    hit = True
                if any(_seg_dist((lx, ly), pts[k], pts[k + 1]) <= tol for k in range(len(pts) - 1)):
                    hit = True
                if hit:
                    break
            if hit:
                return it
            continue
        lx, ly = _local(spec, x, y)
        rx0, ry0, rx1, ry1 = spec_rect(spec)
        if spec.get("kind") == "text":
            _, h = text_layout(spec)
            ry1 = max(ry1, ry0 + h)
        if rx0 - pad <= lx <= rx1 + pad and ry0 - pad <= ly <= ry1 + pad:
            return it
    return None


def _bez(p0, c1, c2, p1, t):
    mt = 1 - t
    return (mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p1[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p1[1])


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    if L < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def get_item(doc, i, item_id) -> Item | None:
    return next((it for it in find_items(doc, i) if it.id == item_id), None)


def _remove(doc, i, item_id, destroy=True):
    page = doc.page(i)
    removed = []
    for k in range(C.FPDFPage_CountObjects(page.raw) - 1, -1, -1):
        obj = C.FPDFPage_GetObject(page.raw, k)
        info = _mark_info(obj)
        if info and info[0] == item_id:
            C.FPDFPage_RemoveObject(page.raw, obj)
            if destroy:
                C.FPDFPageObj_Destroy(obj)
            else:
                removed.append((k, obj))
    return removed[::-1]


def delete_item(doc, i, item_id, snapshot=True):
    if snapshot:
        doc._snapshot()
    _remove(doc, i, item_id)
    doc.page(i).gen_content()
    if snapshot:
        doc._changed()


def update_item(doc, i, spec, snapshot=True):
    """Dựng lại nội dung theo spec mới (cùng id). spec["z"]: "front" | "back"."""
    if snapshot:
        doc._snapshot()
    _remove(doc, i, spec["id"])
    doc.page(i).gen_content()
    _insert_objects(doc, i, spec, back=spec.get("z") == "back" and can_send_back(doc, i))
    if snapshot:
        doc._changed()


class ItemEdit:
    """Sửa một nội dung: tạm gỡ khỏi trang (khung kéo hiển thị ảnh xem trước), rồi dựng lại (commit),
    trả lại như cũ (cancel) hoặc xóa hẳn (delete). Cả thao tác là 1 bước hoàn tác."""

    def __init__(self, doc, i: int, item: Item):
        self.doc, self.i, self.item = doc, i, item
        self.spec = json.loads(json.dumps(item.spec))
        self.orig = json.loads(json.dumps(item.spec))
        doc._snapshot()
        self.page = doc.page(i)
        self.removed = _remove(doc, i, item.id, destroy=False)
        doc.version += 1
        self.done = False

    def _put_back(self):
        for k, obj in self.removed:
            C.FPDFPage_InsertObjectAtIndex(self.page.raw, obj, k)

    def commit(self, spec=None, force: bool = False):
        if self.done:
            return
        spec = spec or self.spec
        if spec == self.orig and not force:
            self.cancel()
            return
        for _, obj in self.removed:
            C.FPDFPageObj_Destroy(obj)
        self.removed = []
        self.page.gen_content()
        self.done = True
        _insert_objects(self.doc, self.i, spec, back=spec.get("z") == "back" and can_send_back(self.doc, self.i))
        self.doc._changed()

    def cancel(self):
        if self.done:
            return
        self._put_back()
        self.done = True
        self.doc._undo.pop()
        self.doc.version += 1

    def delete(self):
        if self.done:
            return
        for _, obj in self.removed:
            C.FPDFPageObj_Destroy(obj)
        self.page.gen_content()
        self.done = True
        self.doc._changed()


# ------------------------------------------------------------------ biến đổi spec
def margin(spec) -> float:
    """Lề quanh khung để ảnh xem trước không cắt mất nét / đầu mũi tên / bóng đổ."""
    w = float(spec.get("width", 1.5))
    m = max(4.0, w * 4 + 2)
    if spec.get("shadow"):
        m += 3
    if spec.get("kind") == "ink" and spec.get("widths"):
        m = max(m, max((max(ws) for ws in spec["widths"] if ws), default=w) + 2)
    if spec.get("shape") in ("curve", "carrow"):
        x0, y0, x1, y1 = spec_rect(spec)
        m += 0.3 * math.hypot(x1 - x0, y1 - y0)
    return m


def resized(spec, new_rect):
    """Spec với khung mới (chưa xoay). Chữ: cỡ chữ theo tỉ lệ chiều rộng; nét: giữ độ dày."""
    s = json.loads(json.dumps(spec))
    ox0, oy0, ox1, oy1 = spec_rect(spec)
    nx0, ny0, nx1, ny1 = new_rect
    if s["kind"] == "text":
        k = (nx1 - nx0) / max(1e-6, ox1 - ox0)
        s["size"] = round(float(s.get("size", 12)) * k, 3)
        s["rect"] = [nx0, ny0, nx1, ny0 + (oy1 - oy0) * k]
        return s
    if s["kind"] == "ink" and s.get("widths") and abs((nx1 - nx0) - (ox1 - ox0)) > 0.01:
        k = math.sqrt(max(1e-6, (nx1 - nx0) * (ny1 - ny0)) / max(1e-6, (ox1 - ox0) * (oy1 - oy0))) \
            if (oy1 - oy0) > 0.01 and (ny1 - ny0) > 0.01 else (nx1 - nx0) / max(1e-6, ox1 - ox0)
        s["widths"] = [[round(w * min(3, max(0.3, k)), 3) for w in ws] for ws in s["widths"]]
    s["rect"] = [nx0, ny0, nx1, ny1]
    return s


def keep_ratio(spec) -> bool:
    if spec["kind"] == "stamp":
        return spec.get("shape") == "circle"
    if spec["kind"] == "text":
        return True
    if spec["kind"] == "shape" and spec.get("shape") in SYMBOL_SHAPES | {"check", "cross"}:
        return True
    return False


# ------------------------------------------------------------------ ảnh xem trước (nền trong suốt)
class _TempDoc:
    """Trang PDF tạm (không xoay) để dựng + render riêng một nội dung."""

    def __init__(self, w, h):
        self.pdf = pdfium.PdfDocument.new()
        self._page = self.pdf.new_page(w, h)
        self.h = h

    def page(self, i):
        return self._page

    def display_to_user(self, i, x, y):
        return x, self.h - y

    def user_to_display(self, i, x, y):
        return x, self.h - y

    def close(self):
        self._page.close()
        self.pdf.close()


def render_preview(spec, scale: float = 3.0):
    """Ảnh PIL RGBA của nội dung (không xoay), phủ khung rect nở thêm margin(spec). Trả về (ảnh, margin)."""
    m = margin(spec)
    x0, y0, x1, y1 = spec_rect(spec)
    if spec["kind"] == "text":
        _, h = text_layout(spec)
        y1 = max(y1, y0 + h)
    s = dict(spec)
    s["angle"] = 0
    W, H = (x1 - x0) + 2 * m, (y1 - y0) + 2 * m
    s["rect"] = [m, m, m + (x1 - x0), m + (y1 - y0)]
    if spec["kind"] == "text":
        s["rect"][3] = m + (spec_rect(spec)[3] - spec_rect(spec)[1])
    t = _TempDoc(max(W, 1), max(H, 1))
    try:
        objs = build_objects(t, 0, s)
        for o in objs:
            C.FPDFPage_InsertObject(t._page.raw, o)
        t._page.gen_content()
        scale = min(scale, 4000 / max(W, H))
        bm = t._page.render(scale=scale, fill_color=(255, 255, 255, 0), rev_byteorder=True)
        img = bm.to_pil().convert("RGBA")
        bm.close()
        return img, m
    finally:
        t.close()


def display_bounds(spec):
    """Khung chưa xoay của nội dung (chữ: theo chiều cao thực)."""
    x0, y0, x1, y1 = spec_rect(spec)
    if spec["kind"] == "text":
        _, h = text_layout(spec)
        y1 = y0 + h
    return x0, y0, x1, y1


# ------------------------------------------------------------------ tạo spec cho từng công cụ
def shape_spec(shape, rect, style: dict, pts=None) -> dict:
    s = {"kind": "shape", "shape": shape, "rect": list(rect), "angle": 0}
    s.update({k: v for k, v in style.items() if v is not None})
    if shape in LINE_SHAPES or shape == "polygon":
        s["pts"] = normalize(pts, rect)
        s.setdefault("heads", default_heads(shape))
        s.pop("fill", None) if shape in LINE_SHAPES else None
    if shape in SYMBOL_SHAPES or shape in ("check", "cross"):
        s.pop("fill", None)
    return s


def line_spec(shape, p0, p1, style, points=None) -> dict:
    pts = points or [p0, p1]
    rect = bbox(pts)
    return shape_spec(shape, rect, style, pts)


def ink_spec(strokes_samples, style: dict) -> dict:
    """strokes_samples: [[(x, y, t, lực)]] ."""
    pen = style.get("pen", "ball")
    width = float(style.get("width", PEN_DEFAULT_WIDTH.get(pen, 1.2)))
    allpts = [(p[0], p[1]) for s in strokes_samples for p in s]
    rect = bbox(allpts)
    spec = {"kind": "ink", "pen": pen, "rect": list(rect), "angle": 0, "stroke": style.get("stroke", "#0d47a1"),
            "width": width, "opacity": style.get("opacity", 100)}
    spec["strokes"] = [normalize([(p[0], p[1]) for p in s], rect) for s in strokes_samples]
    if pen in VARIABLE_PENS:
        spec["widths"] = [pen_widths(s, width, pen) for s in strokes_samples]
    return spec


def text_spec(x, y, width, text, font, size, color, **kw) -> dict:
    spec = {"kind": "text", "rect": [x, y, x + width, y + size * 1.3], "angle": 0, "text": text,
            "font": font or "", "size": size, "color": color}
    spec.update(kw)
    _, h = text_layout(spec)
    spec["rect"][3] = y + h
    return spec


__all__ = ["SHAPE_GROUPS", "SHAPE_LABEL", "add_item", "find_items", "item_at", "update_item", "delete_item",
           "ItemEdit", "render_preview", "shape_spec", "line_spec", "ink_spec", "text_spec", "resized"]


# ------------------------------------------------------------------ 13d: chọn nhiều, sao chép, dán
def union_rect(items_list) -> tuple:
    rs = [it.rect for it in items_list]
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def items_in_rect(doc, i, rect, partial: bool = False) -> list:
    x0, y0, x1, y1 = rect
    out = []
    for it in find_items(doc, i):
        a0, b0, a1, b1 = it.rect
        inside = a0 >= x0 and b0 >= y0 and a1 <= x1 and b1 <= y1
        touch = not (a1 < x0 or a0 > x1 or b1 < y0 or b0 > y1)
        if inside or (partial and touch):
            out.append(it)
    return out


def group_transform(spec, old, new) -> dict:
    """Spec sau khi khung nhóm đổi từ `old` sang `new` (dời + co giãn quanh góc trên-trái nhóm)."""
    ox0, oy0, ox1, oy1 = old
    nx0, ny0, nx1, ny1 = new
    kx = (nx1 - nx0) / max(1e-6, ox1 - ox0)
    ky = (ny1 - ny0) / max(1e-6, oy1 - oy0)
    if spec.get("kind") == "text" or keep_ratio(spec):
        kx = ky = min(kx, ky) if abs(kx - 1) > 1e-6 and abs(ky - 1) > 1e-6 else (kx if abs(kx - 1) > 1e-6 else ky)
    x0, y0, x1, y1 = spec_rect(spec)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ncx, ncy = nx0 + (cx - ox0) * kx, ny0 + (cy - oy0) * ky
    w, h = (x1 - x0) * kx, (y1 - y0) * ky
    if abs(kx - 1) < 1e-6 and abs(ky - 1) < 1e-6:
        s = json.loads(json.dumps(spec))
        s["rect"] = [ncx - w / 2, ncy - h / 2, ncx + w / 2, ncy + h / 2]
        return s
    return resized(spec, (ncx - w / 2, ncy - h / 2, ncx + w / 2, ncy + h / 2))


def render_group(page_size, specs, rect, scale: float = 3.0):
    """Ảnh PIL RGBA của nhiều nội dung (đúng vị trí, góc xoay) trong khung `rect` – xem trước khi kéo nhóm."""
    W, H = page_size
    t = _TempDoc(W, H)
    try:
        for sp in specs:
            for o in build_objects(t, 0, sp):
                C.FPDFPage_InsertObject(t._page.raw, o)
        t._page.gen_content()
        x0, y0, x1, y1 = rect
        scale = min(scale, 4000 / max(x1 - x0, y1 - y0, 1))
        crop = (max(0, x0), max(0, H - y1), max(0, W - x1), max(0, y0))
        bm = t._page.render(scale=scale, crop=crop, fill_color=(255, 255, 255, 0), rev_byteorder=True)
        img = bm.to_pil().convert("RGBA")
        bm.close()
        return img
    finally:
        t.close()


class GroupEdit:
    """Sửa nhiều nội dung cùng lúc (dời, co giãn, xóa) – 1 bước hoàn tác."""

    def __init__(self, doc, i: int, items_list):
        self.doc, self.i = doc, i
        self.specs = [json.loads(json.dumps(it.spec)) for it in items_list]
        self.frame = union_rect(items_list)
        doc._snapshot()
        self.page = doc.page(i)
        self.removed = []
        for it in items_list:
            self.removed += _remove(doc, i, it.id, destroy=False)
        self.removed.sort(key=lambda t: t[0])
        doc.version += 1
        self.done = False

    def commit(self, new_frame):
        if self.done:
            return
        if all(abs(a - b) < 0.05 for a, b in zip(new_frame, self.frame)):
            self.cancel()
            return
        for _, obj in self.removed:
            C.FPDFPageObj_Destroy(obj)
        self.page.gen_content()
        self.done = True
        for sp in self.specs:
            _insert_objects(self.doc, self.i, group_transform(sp, self.frame, new_frame))
        self.doc._changed()

    def cancel(self):
        if self.done:
            return
        for k, obj in self.removed:
            C.FPDFPage_InsertObjectAtIndex(self.page.raw, obj, k)
        self.done = True
        self.doc._undo.pop()
        self.doc.version += 1

    def delete(self):
        if self.done:
            return
        for _, obj in self.removed:
            C.FPDFPageObj_Destroy(obj)
        self.page.gen_content()
        self.done = True
        self.doc._changed()


def paste_items(doc, i: int, specs, dx: float = 12.0, dy: float = 12.0, snapshot=True) -> list[dict]:
    """Dán bản sao (mã mới), dời (dx, dy); nằm ngoài trang thì kéo vào trong."""
    if not specs:
        return []
    pw, ph = doc.page_size_pt(i)
    if snapshot:
        doc._snapshot()
    out = []
    for sp in specs:
        s = json.loads(json.dumps(sp))
        s["id"] = new_id()
        x0, y0, x1, y1 = spec_rect(s)
        ddx = min(max(dx, -x0), pw - x1) if x1 - x0 < pw else -x0
        ddy = min(max(dy, -y0), ph - y1) if y1 - y0 < ph else -y0
        s["rect"] = [x0 + ddx, y0 + ddy, x1 + ddx, y1 + ddy]
        s.pop("z", None)
        _insert_objects(doc, i, s)
        out.append(s)
    if snapshot:
        doc._changed()
    return out


# ------------------------------------------------------------------ 15c: cục tẩy nét vẽ tay
def erase_strokes(doc, i: int, path, radius: float, snapshot=True) -> int:
    """Gỡ các NÉT vẽ tay mà đường tẩy đi qua (nét khác trong cùng nội dung giữ nguyên). Trả về số nét đã gỡ."""
    removed = 0
    todo = []
    dense = []                                        # làm dày đường tẩy (mỗi ~1 pt một điểm)
    for k, p in enumerate(path):
        if k:
            q = path[k - 1]
            n = max(1, int(math.hypot(p[0] - q[0], p[1] - q[1])))
            dense += [(q[0] + (p[0] - q[0]) * j / n, q[1] + (p[1] - q[1]) * j / n) for j in range(1, n)]
        dense.append(p)
    path = dense
    for it in find_items(doc, i):
        sp = it.spec
        if sp.get("kind") != "ink":
            continue
        x0, y0, x1, y1 = it.rect
        if not any(x0 - radius <= px <= x1 + radius and y0 - radius <= py <= y1 + radius for px, py in path):
            continue
        keep, keepw = [], []
        tol = radius + float(sp.get("width", 1)) / 2
        for k, st in enumerate(sp.get("strokes", [])):
            pts = [_rot_point(sp, p) for p in _denorm(sp, st)]
            hit = False
            for px, py in path:
                if len(pts) == 1:
                    hit = math.hypot(px - pts[0][0], py - pts[0][1]) <= tol
                else:
                    hit = any(_seg_dist((px, py), pts[j], pts[j + 1]) <= tol for j in range(len(pts) - 1))
                if hit:
                    break
            if hit:
                removed += 1
            else:
                keep.append(st)
                if sp.get("widths") and k < len(sp["widths"]):
                    keepw.append(sp["widths"][k])
        if len(keep) != len(sp.get("strokes", [])):
            todo.append((it, keep, keepw))
    if not todo:
        return 0
    if snapshot:
        doc._snapshot()
    for it, keep, keepw in todo:
        if not keep:
            delete_item(doc, i, it.id, snapshot=False)
        else:
            ns = json.loads(json.dumps(it.spec))
            ns["strokes"] = keep
            if ns.get("widths"):
                ns["widths"] = keepw
            update_item(doc, i, ns, snapshot=False)
    if snapshot:
        doc._changed()
    return removed


def _rot_point(spec, p):
    """Điểm trong khung chưa xoay -> vị trí hiển thị thật (đã xoay)."""
    a = math.radians(float(spec.get("angle", 0) or 0))
    if not a:
        return p
    x0, y0, x1, y1 = spec_rect(spec)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = p[0] - cx, p[1] - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


# ------------------------------------------------------------------ 15e: tự nắn nét vẽ tay thành hình chuẩn
def recognize(points):
    """Nhận dạng nét vẽ tay: ("line", [p0, p1]) | ("arrow", [p0, p1]) | ("ellipse", rect) | ("rect", rect) |
    ("triangle", rect) | ("diamond", rect) | None (giữ nét tay)."""
    if len(points) < 5:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w, h = x1 - x0, y1 - y0
    diag = math.hypot(w, h)
    if diag < 12:
        return None
    length = sum(math.hypot(points[k + 1][0] - points[k][0], points[k + 1][1] - points[k][1])
                 for k in range(len(points) - 1))
    gap = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
    closed = gap < max(0.22 * diag, 10)
    if not closed:
        chord = gap
        if chord > 0 and length / chord < 1.08:
            dev = max(_seg_dist(p, points[0], points[-1]) for p in points)
            if dev < 0.06 * chord + 2:
                return "line", [points[0], points[-1]]
        # mũi tên: đường thẳng + móc ngược ở cuối (nét vẽ quay lại gần đầu mút)
        simp = simplify(points, 0.06 * diag)
        if 3 <= len(simp) <= 5:
            a, b = simp[0], simp[1]
            shaft = math.hypot(b[0] - a[0], b[1] - a[1])
            tail = sum(math.hypot(simp[k + 1][0] - simp[k][0], simp[k + 1][1] - simp[k][1])
                       for k in range(1, len(simp) - 1))
            c = simp[2]
            back = (c[0] - b[0]) * (b[0] - a[0]) + (c[1] - b[1]) * (b[1] - a[1]) < 0   # móc quay ngược về
            if shaft > 0.55 * length and tail < shaft * 0.6 and back:
                return "arrow", [a, b]
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max(w / 2, 1e-6), max(h / 2, 1e-6)
    rad = [math.hypot((p[0] - cx) / rx, (p[1] - cy) / ry) for p in points]
    mean = sum(rad) / len(rad)
    var = math.sqrt(sum((r - mean) ** 2 for r in rad) / len(rad))
    simp = simplify(points + [points[0]], 0.09 * diag)
    corners = len(simp) - 1
    if var < 0.09 and not (corners == 4 and _box_like(simp, (x0, y0, x1, y1))):
        return "ellipse", (x0, y0, x1, y1)
    if corners == 3:
        return "triangle", (x0, y0, x1, y1)
    if corners == 4:
        if _box_like(simp, (x0, y0, x1, y1)):
            return "rect", (x0, y0, x1, y1)
        return "diamond", (x0, y0, x1, y1)
    if var < 0.14:
        return "ellipse", (x0, y0, x1, y1)
    return None


def _box_like(simp, rect):
    x0, y0, x1, y1 = rect
    tol = 0.2 * max(x1 - x0, y1 - y0)
    near = 0
    for p in simp[:-1]:
        if min(abs(p[0] - x0), abs(p[0] - x1)) < tol and min(abs(p[1] - y0), abs(p[1] - y1)) < tol:
            near += 1
    return near >= 3
