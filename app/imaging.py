"""Xử lý ảnh con dấu / chữ ký: tách nền giấy trắng, làm đậm, đổi màu mực, cắt viền thừa.

Dùng Pillow (các phép tính chạy bằng C, nhanh) và chỉ nạp khi cần -> không làm chậm khởi động.

Cách tách nền: độ "trắng" của điểm ảnh = kênh màu nhỏ nhất min(R, G, B). Giấy trắng/ngả vàng
có min cao -> trong suốt; mực đỏ/xanh/đen có ít nhất một kênh thấp -> giữ lại. Màu mực được
"gỡ" khỏi nền trắng (unmix) để viền nét không bị bệt hồng/xám.
"""
from __future__ import annotations

import io

INK_COLORS = {"keep": None, "red": (200, 20, 30), "blue": (20, 50, 170), "black": (25, 25, 25)}
MAX_SIDE = 1600      # ảnh thư viện tối đa 1600 px cạnh dài (đủ nét khi in dấu 4-5 cm ở 600 dpi)


PAPERS_IN = {"A4": (8.27, 11.69), "A5": (5.83, 8.27), "A3": (11.69, 16.54), "Letter": (8.5, 11.0)}


def scan_dpi(data: bytes) -> float | None:
    """Độ phân giải thật của ảnh scan (điểm/inch) để chèn đúng kích thước thật.
    Ưu tiên thông tin DPI máy scan ghi trong file; không có (hoặc là 72/96 mặc định của phần mềm)
    mà ảnh đúng tỉ lệ khổ giấy (scan nguyên trang A4/A5/A3/Letter) thì suy ra từ khổ giấy."""
    img = _open(data)
    dpi = img.info.get("dpi")
    try:
        d = float(dpi[0]) if dpi else 0.0
    except (TypeError, ValueError, IndexError):
        d = 0.0
    if d >= 100 and abs(d - 96) > 0.5:
        return d
    w, h = sorted(img.size)
    for pw, ph in PAPERS_IN.values():
        if abs(h / w - ph / pw) < 0.02:
            est = h / ph
            if est >= 100:
                return round(est)
    return d if d >= 100 else None


def _ink_box(rgb, threshold: int, existing_alpha=None, probe: int = 1200):
    """Khung bao nét mực, tính trên ảnh thu nhỏ cho nhanh rồi quy về toạ độ ảnh gốc."""
    from PIL import ImageChops
    k = max(1.0, max(rgb.size) / probe)
    small = rgb.resize((max(1, int(rgb.width / k)), max(1, int(rgb.height / k)))) if k > 1 else rgb
    r, g, b = small.split()
    mn = ImageChops.darker(ImageChops.darker(r, g), b)
    mask = mn.point(lambda v: 255 if v < threshold - 10 else 0)
    if existing_alpha is not None:
        ea = existing_alpha.resize(small.size) if k > 1 else existing_alpha
        mask = ImageChops.multiply(mask, ea.point(lambda v: 255 if v > 24 else 0))
    box = mask.getbbox()
    if not box:
        return None
    return (int(box[0] * k), int(box[1] * k), min(rgb.width, int(box[2] * k + k)),
            min(rgb.height, int(box[3] * k + k)))


def ink_width_mm(data: bytes, threshold: int = 200) -> float | None:
    """Chiều rộng thật (mm) của phần nét mực (con dấu/chữ ký) trong ảnh scan, None nếu không rõ DPI."""
    dpi = scan_dpi(data)
    if not dpi:
        return None
    img = _open(data)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        src = img.convert("RGBA")
        from PIL import Image
        rgb = Image.new("RGB", src.size, (255, 255, 255))
        rgb.paste(src, mask=src.getchannel("A"))
        box = _ink_box(rgb, threshold, src.getchannel("A"))
    else:
        box = _ink_box(img.convert("RGB"), threshold)
    if not box:
        return None
    return (box[2] - box[0]) / dpi * 25.4


def _open(data: bytes):
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)   # ảnh chụp điện thoại: xoay đúng chiều
    return img


def _flatten(rgb):
    """1.0.22 – làm phẳng nền: ước lượng màu giấy từng vùng (bóng tay, giấy ngả vàng, ảnh chụp điện thoại tối một góc)
    rồi chia ra -> nền về trắng đều, nét mực giữ đúng màu."""
    from PIL import Image, ImageFilter, ImageMath
    w, h = rgb.size
    k = max(1, min(w, h) // 120)                     # ảnh nhỏ ~120 px cạnh ngắn
    small = rgb.resize((max(1, w // k), max(1, h // k)), Image.BOX)
    # bỏ nét mực (tối) khỏi ảnh nhỏ bằng lọc "sáng nhất" rồi làm mượt -> chỉ còn màu giấy
    bg = small.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MaxFilter(5))
    bg = bg.filter(ImageFilter.GaussianBlur(max(2, min(bg.size) / 20))).resize((w, h), Image.BILINEAR)
    out = []
    for c, b in zip(rgb.split(), bg.split()):
        out.append(ImageMath.lambda_eval(
            lambda e: e["convert"](e["min"](e["c"] * 255 / e["max"](e["b"], 40), 255), "L"), c=c, b=b))
    return Image.merge("RGB", out)


def _otsu(hist) -> int:
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * v for i, v in enumerate(hist))
    wb = sb = 0
    best, t = -1.0, 128
    for i, v in enumerate(hist):
        wb += v
        if not wb:
            continue
        wf = total - wb
        if not wf:
            break
        sb += i * v
        mb, mf = sb / wb, (sum_all - sb) / wf
        var = wb * wf * (mb - mf) ** 2
        if var > best:
            best, t = var, i
    return t


def auto_threshold(mn) -> tuple[int, int]:
    """(ngưỡng giấy, độ mềm) tự tìm từ histogram độ trắng min(R,G,B): giấy là đỉnh sáng nhất, mực là phần tối."""
    hist = mn.histogram()
    t = _otsu(hist)
    hi = hist[t + 1:]
    paper = t + 1 + max(range(len(hi)), key=lambda i: hi[i]) if hi and sum(hi) else 250
    # độ nhiễu của giấy: nửa độ rộng đỉnh phía tối
    cnt, need, lo = 0, hist[paper] * 0.25, paper
    while lo > t and hist[lo] > need:
        lo -= 1
    noise = max(4, paper - lo)
    thr = int(max(150, min(240, paper - 2.2 * noise)))
    soft = int(max(15, min(80, (thr - t) * 0.9)))
    return thr, soft


def dominant_ink(rgb, alpha=None):
    """Màu mực chủ đạo (đỏ dấu, xanh bút ký...) – (hue 0..255, (r, g, b)) hoặc None nếu ảnh gần như không màu."""
    from PIL import Image, ImageChops
    small = rgb.copy()
    small.thumbnail((300, 300))
    hsv = small.convert("HSV")
    h, sat, val = hsv.split()
    r, g, b = small.split()
    chroma = ImageChops.subtract(ImageChops.lighter(ImageChops.lighter(r, g), b),
                                 ImageChops.darker(ImageChops.darker(r, g), b))
    mask = chroma.point(lambda v: 255 if v > 60 else 0)
    if alpha is not None:
        a = alpha.resize(small.size)
        mask = ImageChops.multiply(mask, a.point(lambda v: 255 if v > 128 else 0))
    hist = h.histogram(mask)
    n = sum(hist)
    if n < max(30, small.width * small.height * 0.002):
        return None
    smooth = [sum(hist[(i + d) % 256] for d in range(-6, 7)) for i in range(256)]
    hue = max(range(256), key=lambda i: smooth[i])
    sel = h.point([255 if min(abs(v - hue), 256 - abs(v - hue)) <= 14 else 0 for v in range(256)])
    sel = ImageChops.multiply(sel, mask)
    cols = [c.histogram(sel) for c in (r, g, b)]
    m = sum(cols[0]) or 1
    rgb_mean = tuple(int(sum(i * v for i, v in enumerate(ch)) / m) for ch in cols)
    return hue, rgb_mean


def remove_background(data: bytes, threshold: int | None = 200, softness: int = 40, boost: bool = True,
                      ink: str = "keep", trim: bool = True, max_side: int = MAX_SIDE, flatten: bool = False,
                      keep: str = "all", clean: bool = False) -> bytes:
    """Trả về PNG RGBA đã tách nền.
    threshold: điểm có min(R,G,B) >= threshold coi là giấy (trong suốt hoàn toàn).
    softness : dải chuyển tiếp mềm dưới ngưỡng (khử răng cưa mép nét).
    boost    : làm đậm nét (tăng độ phủ + độ bão hòa màu).
    ink      : keep | red | blue | black | auto (màu mực chủ đạo, đều màu) - đổi màu mực đồng nhất.
    1.0.22:
    threshold=None: tự tìm ngưỡng theo bản scan · flatten: làm phẳng nền (bóng, giấy vàng, ảnh chụp)
    keep="color": chỉ giữ nét cùng màu mực chủ đạo (bỏ chữ đen in sẵn, đường kẻ, chữ ký khác màu đè lên dấu)
    clean: lọc chấm nhiễu li ti của bản scan."""
    from PIL import Image, ImageChops, ImageEnhance

    img = _open(data)
    dpi = scan_dpi(data)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        src = img.convert("RGBA")
        existing_alpha = src.getchannel("A")
        rgb = Image.new("RGB", src.size, (255, 255, 255))
        rgb.paste(src, mask=existing_alpha)
    else:
        existing_alpha = None
        rgb = img.convert("RGB")
    if flatten and existing_alpha is None:
        rgb = _flatten(rgb)
    if threshold is None:
        r0, g0, b0 = rgb.split()
        threshold, softness = auto_threshold(ImageChops.darker(ImageChops.darker(r0, g0), b0))
    if trim:
        # cắt sát nét mực NGAY trên ảnh gốc (vd. cả trang A4 scan 600 dpi) rồi mới thu nhỏ
        # -> con dấu giữ đủ độ nét, không bị thu nhỏ theo cả trang
        box = _ink_box(rgb, threshold, existing_alpha)
        if box:
            pad = max(4, int(max(box[2] - box[0], box[3] - box[1]) * 0.03))
            box = (max(0, box[0] - pad), max(0, box[1] - pad), min(rgb.width, box[2] + pad),
                   min(rgb.height, box[3] + pad))
            rgb = rgb.crop(box)
            if existing_alpha is not None:
                existing_alpha = existing_alpha.crop(box)
    if max(rgb.size) > max_side:
        if dpi:
            dpi = dpi * max_side / max(rgb.size)
        rgb.thumbnail((max_side, max_side), Image.LANCZOS)
        if existing_alpha is not None:
            existing_alpha = existing_alpha.resize(rgb.size, Image.LANCZOS)

    r, g, b = rgb.split()
    mn = ImageChops.darker(ImageChops.darker(r, g), b)            # min(R, G, B)
    lo = max(0, threshold - max(1, softness))
    span = max(1, threshold - lo)

    def a_of(v):
        if v >= threshold:
            return 0
        if v <= lo:
            return 255
        return int(255 * (threshold - v) / span)
    alpha = mn.point([a_of(v) for v in range(256)])
    dom = dominant_ink(rgb, alpha) if (keep == "color" or ink == "auto") else None
    if keep == "color" and dom is not None:
        # chỉ giữ nét cùng màu mực: độ "đậm màu" (max - min) đủ lớn và cùng sắc với mực chủ đạo
        from PIL import ImageFilter
        hue = dom[0]
        hch = rgb.convert("HSV").getchannel("H")
        mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
        chroma = ImageChops.subtract(mx, mn)
        hue_ok = hch.point([255 if min(abs(v - hue), 256 - abs(v - hue)) <= 22 else 0 for v in range(256)])
        c_alpha = chroma.point([0 if v < 28 else (255 if v > 90 else int(255 * (v - 28) / 62)) for v in range(256)])
        col_a = ImageChops.multiply(c_alpha, hue_ok)
        # chỗ chữ đen / nét khác màu đè ngang nét dấu: lấp lại bằng màu dấu (đóng lỗ nhỏ, chỉ trong vùng có mực)
        ks = 7 if max(rgb.size) >= 700 else 5
        closed = col_a.filter(ImageFilter.MaxFilter(ks)).filter(ImageFilter.MinFilter(ks))
        alpha = ImageChops.lighter(col_a, ImageChops.darker(closed, alpha))
        alpha = ImageChops.darker(alpha, ImageChops.lighter(col_a, closed))
    if clean:
        from PIL import ImageFilter
        hard = alpha.point(lambda v: 255 if v > 60 else 0).filter(ImageFilter.MedianFilter(3))
        hard = hard.filter(ImageFilter.MaxFilter(3))        # giữ mép mềm quanh nét thật, bỏ chấm lẻ
        alpha = ImageChops.multiply(alpha, hard)
    if boost:
        alpha = alpha.point([min(255, int(v * 1.35)) for v in range(256)])
    if existing_alpha is not None:
        alpha = ImageChops.multiply(alpha, existing_alpha)

    if ink == "auto" and dom is not None:
        color = Image.new("RGB", rgb.size, dom[1])
        if boost:
            color = ImageEnhance.Color(color).enhance(1.15)
    elif INK_COLORS.get(ink):
        color = Image.new("RGB", rgb.size, INK_COLORS[ink])
    else:
        # gỡ màu mực khỏi nền trắng: c_ink = 255 - (255 - c) * 255 / a
        def unmix(ch):
            inv = ImageChops.invert(ch)                              # 255 - c
            try:
                from PIL import ImageMath
                out = ImageMath.lambda_eval(
                    lambda e: e["convert"](255 - e["min"](e["inv"] * 255 / e["max"](e["a"], 1), 255), "L"),
                    inv=inv, a=alpha)
            except Exception:
                out = ch
            return out
        color = Image.merge("RGB", [unmix(c) for c in (r, g, b)])
        if boost:
            color = ImageEnhance.Color(color).enhance(1.3)
            color = ImageEnhance.Brightness(color).enhance(0.92)
    out = color.convert("RGBA")
    out.putalpha(alpha)
    if trim:
        box = alpha.point(lambda v: 255 if v > 24 else 0).getbbox()
        if box:
            pad = max(2, int(max(out.size) * 0.01))
            box = (max(0, box[0] - pad), max(0, box[1] - pad),
                   min(out.width, box[2] + pad), min(out.height, box[3] + pad))
            out = out.crop(box)
    buf = io.BytesIO()
    if dpi:
        out.save(buf, "PNG", optimize=True, dpi=(dpi, dpi))   # ghi lại DPI -> luôn biết kích thước thật
    else:
        out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def image_size(data: bytes) -> tuple[int, int]:
    return _open(data).size


def normalize_png(data: bytes, max_side: int = MAX_SIDE) -> bytes:
    """Ảnh đã trong suốt sẵn (PNG): chỉ thu nhỏ + tối ưu, không tách nền."""
    from PIL import Image
    img = _open(data).convert("RGBA")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def has_transparency(data: bytes) -> bool:
    img = _open(data)
    if img.mode == "RGBA":
        lo, _ = img.getchannel("A").getextrema()
        return lo < 250
    return img.mode == "P" and "transparency" in img.info
