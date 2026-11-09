"""Nhận biết hướng trang scan (không cần phần mềm nhận dạng chữ OCR) – bản 1.0.22 nhanh và chắc hơn.

Cách làm (chỉ dùng ảnh trang, toàn bộ phép tính ảnh chạy trong Pillow (mã C) -> ~10–20 ms/trang):
1. Nhị phân hóa (ngưỡng Otsu) ảnh trang thu nhỏ; BỎ đường kẻ bảng / khung (hàng hoặc cột gần như kín mực,
   nét mảnh dài) – trước đây kẻ bảng làm nhận nhầm hướng.
2. Dòng chữ nằm ngang hay dọc: so độ "sọc" của biểu đồ chiếu theo hàng và theo cột.
3. Xuôi hay lộn ngược – bỏ phiếu theo TỪNG DÒNG bằng 2 dấu hiệu độc lập:
   a) phần mực NẰM TRÊN thân chữ (chữ hoa, nét lên b d h k l t, dấu tiếng Việt á à ả ã ê ô ơ...) nhiều hơn
      phần nằm dưới (nét xuống g p q y, dấu nặng);
   b) lề trái thẳng hàng, lề phải so le (văn bản căn trái) – trang lộn ngược thì lề thẳng nằm bên phải.
   Hai dấu hiệu phải không mâu thuẫn; không đủ chắc thì trả None (để người dùng tự xoay) thay vì xoay sai.
Trả về góc cần xoay THÊM (chiều kim đồng hồ, 0/90/180/270) và độ tin cậy.
"""
from __future__ import annotations

import math

TARGET = 1100          # cạnh dài ảnh phân tích (điểm ảnh)


def _otsu(hist) -> int:
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best, thr = -1.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        between = wb * wf * (mb - mf) ** 2
        if between > best:
            best, thr = between, t
    return thr


def _binarize(img):
    """Ảnh "L": 255 = mực, 0 = nền."""
    g = img.convert("L")
    t = _otsu(g.histogram())
    return g.point(lambda v, t=t: 255 if v < t else 0)


def _rules_mask(b, seg: int = 16, cells: int = 4):
    """Mặt nạ đường kẻ NGANG: đoạn mực liền (gần kín) dài >= seg*cells điểm ảnh. Chữ có khoảng trống giữa
    các nét/chữ nên không bao giờ tạo đoạn kín dài như vậy."""
    from PIL import Image, ImageChops
    w, h = b.size
    cw = max(1, w // seg)
    small = b.resize((cw, h), Image.BOX).point(lambda v: 255 if v >= 225 else 0)   # ô seg điểm gần kín mực
    acc = small
    for k in range(1, cells):                           # đủ `cells` ô kín liền nhau
        acc = ImageChops.darker(acc, ImageChops.offset(small, -k, 0))
    grow = acc
    for k in range(1, cells):                           # trả lại đủ chiều dài đoạn kẻ
        grow = ImageChops.lighter(grow, ImageChops.offset(acc, k, 0))
    thick = grow
    for k in (-2, -1, 1, 2):                            # phủ cả mép nét kẻ (nét mờ, nhòe khi scan)
        thick = ImageChops.lighter(thick, ImageChops.offset(grow, 0, k))
    return thick.resize((w, h), Image.NEAREST)


def _deskew(b):
    """Trang scan bị nghiêng nhẹ (±4°): tìm góc làm dòng chữ / đường kẻ "sọc" rõ nhất rồi xoay thẳng lại."""
    from PIL import Image
    w, h = b.size
    k = 500 / max(w, h)
    small = b.resize((max(1, int(w * k)), max(1, int(h * k))), Image.BOX) if k < 1 else b

    def score(a):
        r = small.rotate(a, Image.BILINEAR) if a else small
        return max(_sharp(_profile(r, 0)), _sharp(_profile(r, 1)))
    best_a, best = 0.0, score(0.0)
    for a in (-4, -3, -2, -1, 1, 2, 3, 4):
        sc = score(a)
        if sc > best * 1.03:
            best_a, best = float(a), sc
    if best_a:                                           # tinh chỉnh ±0.5°
        for a in (best_a - 0.5, best_a + 0.5):
            sc = score(a)
            if sc > best:
                best_a, best = a, sc
    return b.rotate(best_a, Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0) if best_a else b


def _sharp(p) -> float:
    """Độ "sắc" của biểu đồ chiếu: tổng bình phương (dòng chữ thẳng hàng -> các đỉnh cao, rõ)."""
    tot = sum(p) or 1.0
    return sum(v * v for v in p) / (tot * tot)


def _remove_rules(b):
    """Xóa đường kẻ ngang/dọc dài (bảng, khung, gạch chân dài) – chúng không phải chữ."""
    from PIL import Image, ImageChops
    hmask = _rules_mask(b)
    vmask = _rules_mask(b.transpose(Image.Transpose.TRANSPOSE)).transpose(Image.Transpose.TRANSPOSE)
    return ImageChops.subtract(ImageChops.subtract(b, hmask), vmask)


def _profile(b, axis: int) -> list[float]:
    """Lượng mực trung bình theo hàng (axis=0) hoặc theo cột (axis=1), 0..255 – tính bằng Pillow (nhanh)."""
    from PIL import Image
    w, h = b.size
    if axis == 0:
        return list(b.resize((1, h), Image.BOX).tobytes())
    return list(b.resize((w, 1), Image.BOX).tobytes())


def _smooth(p, k=1):
    n = len(p)
    if n == 0:
        return []
    pre = [0.0]
    for v in p:
        pre.append(pre[-1] + v)
    out = []
    for i in range(n):
        a, b = max(0, i - k), min(n, i + k + 1)
        out.append((pre[b] - pre[a]) / (b - a))
    return out


def _stripe_score(p) -> float:
    """Độ sọc: tổng biến thiên giữa các hàng liền kề / tổng mực (dòng chữ -> lên xuống liên tục)."""
    p = _smooth(p, 1)
    tot = sum(p) or 1.0
    return sum(abs(p[i + 1] - p[i]) for i in range(len(p) - 1)) / tot


def _lines(rows, min_h=5):
    """Các dòng chữ (y0, y1) từ biểu đồ chiếu theo hàng."""
    mx = max(rows) if rows else 0
    if mx == 0:
        return []
    thr = max(1, mx * 0.04)
    out, start = [], None
    for y, v in enumerate(list(rows) + [0]):
        if v > thr and start is None:
            start = y
        elif v <= thr and start is not None:
            if y - start >= min_h:
                out.append((start, y))
            start = None
    return out


def _votes(b) -> tuple[float, float, int]:
    """Dòng chữ nằm ngang trong b. Trả về (điểm trên/dưới, điểm lề trái/phải, số dòng dùng được).
    Điểm > 0: trang xuôi; < 0: lộn ngược. Mỗi điểm là trung bình log-tỉ lệ có trọng số theo dòng."""
    rows = _profile(b, 0)
    lines = _lines(rows)
    if not lines:
        return 0.0, 0.0, 0
    hs = sorted(y1 - y0 for y0, y1 in lines)
    med = hs[len(hs) // 2]
    ud_sum = ud_w = 0.0
    lefts, rights, used = [], [], 0
    w = b.size[0]
    for y0, y1 in lines:
        h = y1 - y0
        if h < max(6, med * 0.5) or h > med * 2.2:        # bỏ dòng kẻ còn sót, hình, dấu lớn
            continue
        seg = rows[y0:y1]
        peak = max(seg)
        core = [i for i, v in enumerate(seg) if v >= peak * 0.5]
        if not core:
            continue
        c0, c1 = core[0], core[-1]
        top, bot = sum(seg[:c0]), sum(seg[c1 + 1:])
        if top + bot > 0:
            wt = math.sqrt(top + bot)
            ud_sum += wt * math.log((top + 1) / (bot + 1))
            ud_w += wt
        box = b.crop((0, y0, w, y1)).getbbox()
        if box and box[2] - box[0] > w * 0.15:             # dòng đủ dài mới xét lề
            lefts.append(box[0])
            rights.append(box[2])
        used += 1
    ud = ud_sum / ud_w if ud_w else 0.0
    edge = 0.0
    if len(lefts) >= 4:
        def spread(xs):
            xs = sorted(xs)
            q1, q3 = xs[len(xs) // 4], xs[(3 * len(xs)) // 4]
            return (q3 - q1) + 0.25 * (xs[-1] - xs[0]) / max(1, len(xs) ** 0.5)
        sl, sr = spread(lefts), spread(rights)
        edge = math.log((sr + 3) / (sl + 3))               # lề phải so le hơn lề trái -> xuôi
    return ud, edge, used


def _decide(ud: float, edge: float, n: int) -> tuple[int | None, float]:
    """(0 xuôi | 180 ngược | None, độ tin cậy)."""
    if n < 3:
        return None, 0.0
    UD, ED = 0.22, 0.35                                   # ngưỡng: log(1.25) ≈ 0.22
    s_ud = 1 if ud >= UD else (-1 if ud <= -UD else 0)
    s_ed = 1 if edge >= ED else (-1 if edge <= -ED else 0)
    if ud * edge < 0 and abs(edge) > 0.1 and abs(ud) < 0.6:   # 2 dấu hiệu ngược nhau (dù yếu) -> không chắc
        return None, 0.0
    if s_ud and s_ed and s_ud != s_ed:                    # 2 dấu hiệu mâu thuẫn -> không chắc
        # chỉ tin dấu hiệu trên/dưới khi nó rất mạnh
        if abs(ud) < 0.6:
            return None, 0.0
        s_ed = 0
    sign = s_ud or s_ed
    if not sign:
        # cả hai yếu: cộng dồn, cần tổng đủ lớn
        tot = ud / UD + edge / ED
        if abs(tot) < 1.4:
            return None, 0.0
        sign = 1 if tot > 0 else -1
    conf = min(1.0, (abs(ud) / UD * 0.25 + abs(edge) / ED * 0.15) * (1 if s_ud == s_ed else 0.7))
    conf = max(conf, 0.31)
    return (0 if sign > 0 else 180), conf


def detect(img) -> tuple[int | None, float]:
    """img: ảnh trang (PIL) như đang hiển thị. Trả về (góc cần xoay thêm theo chiều kim đồng hồ | None, độ tin cậy 0..1)."""
    from PIL import Image
    w, h = img.size
    k = TARGET / max(w, h)
    if k < 1:
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.BILINEAR)
    b = _binarize(img)
    W, H = b.size
    ink = b.histogram()[255]
    if ink < W * H * 0.002 or ink > W * H * 0.5:          # trang gần như trắng / ảnh chụp tối
        return None, 0.0
    b = _remove_rules(_deskew(b))
    if b.histogram()[255] < W * H * 0.001:
        return None, 0.0
    sh, sv = _stripe_score(_profile(b, 0)), _stripe_score(_profile(b, 1))
    if max(sh, sv) < 0.05:
        return None, 0.0
    b90 = b.transpose(Image.Transpose.ROTATE_270)          # xoay 90° theo chiều kim đồng hồ: dòng dọc -> ngang

    def as_vertical(res):
        got, conf = res
        return (None, 0.0) if got is None else ((90 if got == 0 else 270), conf)
    if max(sh, sv) / max(1e-6, min(sh, sv)) >= 1.15:
        if sh >= sv:
            return _decide(*_votes(b))
        return as_vertical(_decide(*_votes(b90)))
    # chưa rõ dòng ngang hay dọc (bảng nhiều cột, ít chữ): thử cả hai, chỉ nhận khi một hướng rõ hơn hẳn
    vh, vv = _votes(b), _votes(b90)
    dh, dv = _decide(*vh), _decide(*vv)

    def strength(v):
        ud, edge, n = v
        return (abs(ud) + 0.5 * abs(edge)) * min(n, 20)
    if dh[0] is not None and (dv[0] is None or strength(vh) > 1.8 * strength(vv)):
        return dh
    if dv[0] is not None and (dh[0] is None or strength(vv) > 1.8 * strength(vh)):
        return as_vertical(dv)
    return None, 0.0


def page_fix(doc, i: int) -> int | None:
    """Góc /Rotate cho trang scan i để chữ đứng thẳng (bằng góc hiện tại nếu đã đúng; None = không chắc)."""
    pw, ph = doc.page_size_pt(i)
    scale = TARGET / max(pw, ph, 1)
    bm = doc.render(i, scale, notes=False) if _render_has_notes(doc) else doc.render(i, scale)
    img = bm.to_pil()
    bm.close()
    add, conf = detect(img)
    if add is None:
        return None
    return (doc.page(i).get_rotation() + add) % 360


def _render_has_notes(doc) -> bool:
    import inspect
    try:
        return "notes" in inspect.signature(doc.render).parameters
    except (TypeError, ValueError):
        return False


__all__ = ["detect", "page_fix"]
