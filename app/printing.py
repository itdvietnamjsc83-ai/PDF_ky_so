"""In tài liệu (1.0.22): bố cục in linh hoạt như Foxit / Adobe – vừa khổ giấy, chỉ thu nhỏ trang quá khổ,
kích thước thật, tỉ lệ % tùy chỉnh (10–400%), nhiều trang trên 1 tờ, tự xoay, căn giữa, đen trắng.
Cùng một hàm bố cục dùng cho cả bản xem trước và lúc in thật -> xem trước đúng như bản in.
Đơn vị bố cục: point (1/72 inch) trên tờ giấy, gốc ở góc trên trái tờ."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform

from .viewer import to_qimage

MM = 72 / 25.4

SCALE_MODES = [("fit", "Vừa khổ giấy"), ("shrink", "Chỉ thu nhỏ trang lớn hơn khổ giấy"),
               ("none", "Kích thước thật (100%)"), ("custom", "Tùy chỉnh tỉ lệ %")]
NUP_GRID = {1: (1, 1), 2: (2, 1), 4: (2, 2), 6: (3, 2), 9: (3, 3), 16: (4, 4)}   # (cột, hàng) trên tờ ngang
PAPERS = [("A4", 210, 297), ("A3", 297, 420), ("A5", 148, 210), ("Letter", 215.9, 279.4),
          ("Legal", 215.9, 355.6), ("B5", 176, 250)]


@dataclass
class PrintOptions:
    scale_mode: str = "fit"           # fit | shrink | none | custom
    percent: float = 100.0            # khi custom
    nup: int = 1                      # số trang trên 1 tờ
    orientation: str = "auto"         # auto | portrait | landscape
    auto_rotate: bool = True          # trang ngang in trên giấy dọc (hoặc ngược lại) -> xoay 90° cho vừa
    center: bool = True
    margin_mm: float = 0.0            # lề thêm ngoài lề tối thiểu của máy in
    border: bool = False              # kẻ viền từng trang khi in nhiều trang / tờ
    gray: bool = False
    notes: bool = False
    reverse: bool = False
    subset: str = "all"               # all | odd | even
    max_dpi: int = 300


@dataclass
class Slot:
    page: int
    rect: tuple                       # (x, y, w, h) pt trên tờ
    rotate: bool = False              # xoay trang 90°
    scale: float = 1.0                # tỉ lệ so với kích thước thật của trang


@dataclass
class Sheet:
    landscape: bool
    slots: list = field(default_factory=list)


def parse_range(text: str, n: int) -> list[int]:
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, 8, ...] (đánh số từ 0). Bỏ qua phần sai, giữ thứ tự gõ, không trùng."""
    out: list[int] = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                lo = int(a) if a.strip() else 1
                hi = int(b) if b.strip() else n
                rng = range(lo, hi + 1) if lo <= hi else range(lo, hi - 1, -1)
            else:
                rng = [int(part)]
        except ValueError:
            continue
        for k in rng:
            if 1 <= k <= n and k - 1 not in out:
                out.append(k - 1)
    return out


def select_pages(pages: list[int], opts: PrintOptions) -> list[int]:
    if opts.subset == "odd":
        pages = [p for p in pages if (p + 1) % 2 == 1]
    elif opts.subset == "even":
        pages = [p for p in pages if (p + 1) % 2 == 0]
    return list(reversed(pages)) if opts.reverse else list(pages)


def _fit_scale(w, h, aw, ah, opts: PrintOptions) -> float:
    fit = min(aw / w, ah / h) if w > 0 and h > 0 else 1.0
    if opts.scale_mode == "fit":
        return fit
    if opts.scale_mode == "shrink":
        return min(1.0, fit)
    if opts.scale_mode == "custom":
        return max(0.05, float(opts.percent) / 100.0)
    return 1.0


def plan_sheets(page_sizes, pages: list[int], paper_pt: tuple, margins_pt=(0, 0, 0, 0),
                opts: PrintOptions | None = None) -> list[Sheet]:
    """Xếp các trang lên các tờ giấy. page_sizes[i] = (rộng, cao) pt của trang i (đã tính xoay trang);
    paper_pt = (rộng, cao) của khổ giấy khi đặt dọc; margins_pt = lề tối thiểu của máy in (trái, trên, phải, dưới)."""
    opts = opts or PrintOptions()
    pw, ph = sorted(paper_pt)
    extra = max(0.0, float(opts.margin_mm)) * MM
    nup = opts.nup if opts.nup in NUP_GRID else 1
    sheets: list[Sheet] = []
    if nup == 1:
        for i in pages:
            w, h = page_sizes[i]
            page_land = w > h
            if opts.orientation == "auto":
                land = page_land
            else:
                land = opts.orientation == "landscape"
            rotate = opts.auto_rotate and opts.orientation != "auto" and page_land != land and abs(w - h) > 1
            sw, sh = (ph, pw) if land else (pw, ph)
            ml, mt, mr, mb = _oriented_margins(margins_pt, land)
            ml, mt, mr, mb = ml + extra, mt + extra, mr + extra, mb + extra
            aw, ah = max(10.0, sw - ml - mr), max(10.0, sh - mt - mb)
            cw, ch = (h, w) if rotate else (w, h)
            s = _fit_scale(cw, ch, aw, ah, opts)
            dw, dh = cw * s, ch * s
            x = ml + (aw - dw) / 2 if opts.center else ml
            y = mt + (ah - dh) / 2 if opts.center else mt
            sheets.append(Sheet(land, [Slot(i, (x, y, dw, dh), rotate, s)]))
        return sheets
    cols, rows = NUP_GRID[nup]
    first = page_sizes[pages[0]] if pages else (pw, ph)
    if opts.orientation == "auto":
        land = (cols > rows) == (first[1] >= first[0])      # trang dọc: 2 / 6 trang/tờ -> giấy ngang
    else:
        land = opts.orientation == "landscape"
    if (cols > rows) != land:
        cols, rows = rows, cols
    sw, sh = (ph, pw) if land else (pw, ph)
    ml, mt, mr, mb = _oriented_margins(margins_pt, land)
    ml, mt, mr, mb = ml + extra, mt + extra, mr + extra, mb + extra
    gap = 4 * MM
    cw_ = (sw - ml - mr - gap * (cols - 1)) / cols
    ch_ = (sh - mt - mb - gap * (rows - 1)) / rows
    for k0 in range(0, len(pages), nup):
        sheet = Sheet(land)
        for j, i in enumerate(pages[k0:k0 + nup]):
            r, c = divmod(j, cols)
            w, h = page_sizes[i]
            rotate = opts.auto_rotate and (w > h) != (cw_ > ch_) and abs(w - h) > 1
            pw_, ph_ = (h, w) if rotate else (w, h)
            fit = min(cw_ / pw_, ch_ / ph_)
            s = fit * (float(opts.percent) / 100.0 if opts.scale_mode == "custom" else 1.0)
            if opts.scale_mode == "shrink":
                s = min(s, 1.0)
            dw, dh = pw_ * s, ph_ * s
            cx = ml + c * (cw_ + gap)
            cy = mt + r * (ch_ + gap)
            x = cx + (cw_ - dw) / 2 if opts.center else cx
            y = cy + (ch_ - dh) / 2 if opts.center else cy
            sheet.slots.append(Slot(i, (x, y, dw, dh), rotate, s))
        sheets.append(sheet)
    return sheets


def _oriented_margins(m, land: bool):
    l, t, r, b = m
    return (t, r, b, l) if land else (l, t, r, b)       # lề máy in theo giấy dọc -> quay theo giấy ngang


def sheet_size(paper_pt, sheet: Sheet) -> tuple[float, float]:
    pw, ph = sorted(paper_pt)
    return (ph, pw) if sheet.landscape else (pw, ph)


def page_image(doc, slot: Slot, px_per_pt: float, opts: PrintOptions, cache: dict | None = None) -> QImage:
    """Ảnh trang đúng cỡ sẽ vẽ trên tờ (đã xoay, đen trắng nếu chọn)."""
    sc = max(0.05, slot.scale * px_per_pt)
    key = (slot.page, round(sc, 3), slot.rotate, opts.gray, opts.notes)
    if cache is not None and key in cache:
        return cache[key]
    img = to_qimage(doc.render(slot.page, sc, for_print=True, notes=opts.notes))
    if slot.rotate:
        img = img.transformed(QTransform().rotate(90))
    if opts.gray:
        img = img.convertToFormat(QImage.Format_Grayscale8)
    if cache is not None:
        if len(cache) > 40:
            cache.clear()
        cache[key] = img
    return img


def draw_sheet(p: QPainter, doc, sheet: Sheet, px_per_pt: float, opts: PrintOptions, cache=None):
    """Vẽ một tờ lên painter đã đặt hệ tọa độ = point của tờ giấy."""
    for slot in sheet.slots:
        img = page_image(doc, slot, px_per_pt, opts, cache)
        x, y, w, h = slot.rect
        p.drawImage(QRectF(x, y, w, h), img)
        if opts.border and opts.nup > 1:
            p.save()
            p.setPen(QPen(QColor("#555555"), 0.5))
            p.drawRect(QRectF(x, y, w, h))
            p.restore()


def preview_image(doc, sheet: Sheet, paper_pt, margins_pt, opts: PrintOptions, px_per_pt: float,
                  cache=None) -> QImage:
    """Ảnh xem trước một tờ: giấy trắng, nội dung đúng vị trí, đường gạch = vùng máy in in được."""
    sw, sh = sheet_size(paper_pt, sheet)
    img = QImage(max(1, int(sw * px_per_pt)), max(1, int(sh * px_per_pt)), QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(px_per_pt, px_per_pt)
    p.setClipRect(QRectF(0, 0, sw, sh))
    draw_sheet(p, doc, sheet, px_per_pt, opts, cache)
    if not (opts.border and opts.nup > 1):           # chỉ trên bản xem trước: viền mờ cho thấy mép trang
        p.setPen(QPen(QColor(0, 0, 0, 45), 0))
        for slot in sheet.slots:
            p.drawRect(QRectF(*slot.rect))
    ml, mt, mr, mb = _oriented_margins(margins_pt, sheet.landscape)
    if any((ml, mt, mr, mb)):
        pen = QPen(QColor(0, 120, 215, 150), 0)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setClipping(False)
        p.drawRect(QRectF(ml, mt, sw - ml - mr, sh - mt - mb))
    p.end()
    return img


def printer_margins_pt(printer) -> tuple:
    """Lề tối thiểu (không in được) của máy in, theo giấy dọc, đơn vị pt."""
    try:
        from PySide6.QtGui import QPageLayout
        lay = printer.pageLayout()
        m = lay.minimumMargins() if lay.mode() == QPageLayout.StandardMode else lay.margins()
        k = {QPageLayout.Millimeter: MM, QPageLayout.Point: 1.0, QPageLayout.Inch: 72.0}.get(lay.units(), 1.0)
        vals = (m.left() * k, m.top() * k, m.right() * k, m.bottom() * k)
        if lay.orientation() == QPageLayout.Landscape:            # trả về theo giấy dọc
            l, t, r, b = vals
            vals = (b, l, t, r)
        return vals
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def print_document(doc, printer, pages: list[int], opts: PrintOptions | None = None, paper_pt=None,
                   progress=None) -> int:
    """In thật. paper_pt None: khổ giấy đang đặt trên máy in. Trả về số tờ đã in."""
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtCore import QSizeF
    opts = opts or PrintOptions()
    if not doc.can_print:
        raise PermissionError("Người gửi tài liệu không cho phép in.")
    max_dpi = opts.max_dpi if doc.can_print_high else min(opts.max_dpi, 150)   # chỉ cho in chất lượng thấp
    pages = select_pages(pages, opts)
    if not pages:
        return 0
    if paper_pt is not None:
        printer.setPageSize(QPageSize(QSizeF(*sorted(paper_pt)), QPageSize.Point, "", QPageSize.FuzzyMatch))
    margins = printer_margins_pt(printer)
    sz = printer.pageLayout().fullRect(QPageLayout.Point)
    paper = paper_pt or (sz.width(), sz.height())
    sheets = plan_sheets([doc.page_size_pt(i) for i in range(doc.page_count)], pages, paper, margins, opts)
    printer.setFullPage(True)
    printer.setPageOrientation(QPageLayout.Landscape if sheets[0].landscape else QPageLayout.Portrait)
    dpi = min(printer.resolution(), max_dpi)
    p = QPainter()
    if not p.begin(printer):
        raise RuntimeError("Không khởi động được máy in")
    count = 0
    try:
        for k, sh in enumerate(sheets):
            if k:
                printer.setPageOrientation(QPageLayout.Landscape if sh.landscape else QPageLayout.Portrait)
                printer.newPage()
            full = printer.pageLayout().fullRectPixels(printer.resolution())
            sw, shh = sheet_size(paper, sh)
            p.save()
            p.setViewport(0, 0, full.width(), full.height())
            p.setWindow(0, 0, int(round(sw)), int(round(shh)))
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            draw_sheet(p, doc, sh, dpi / 72, opts)
            p.restore()
            count += 1
            if progress is not None and progress(count, len(sheets)) is False:
                break
    finally:
        p.end()
    return count


def print_pages(doc, printer, first: int, last: int, max_dpi: int = 300, notes: bool = True) -> int:
    """Kiểu cũ: in trang first..last vừa khổ giấy."""
    return print_document(doc, printer, list(range(first, last + 1)),
                          PrintOptions(scale_mode="fit", notes=notes, max_dpi=max_dpi, auto_rotate=False))
