"""In tài liệu: render từng trang ở độ phân giải máy in (tối đa 300 dpi để in nhanh, nhẹ bộ nhớ)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter

from .viewer import to_qimage


def print_pages(doc, printer, first: int, last: int, max_dpi: int = 300, notes: bool = True) -> int:
    if not doc.can_print:
        raise PermissionError("Người gửi tài liệu không cho phép in.")
    if not doc.can_print_high:
        max_dpi = min(max_dpi, 150)          # chỉ cho in chất lượng thấp
    dpi = min(printer.resolution(), max_dpi)
    p = QPainter()
    if not p.begin(printer):
        raise RuntimeError("Không khởi động được máy in")
    count = 0
    try:
        for i in range(first, last + 1):
            if i > first:
                printer.newPage()
            img = to_qimage(doc.render(i, dpi / 72, for_print=True, notes=notes))
            area = p.viewport()
            sz = img.size().scaled(area.size(), Qt.KeepAspectRatio)
            p.save()
            p.setViewport(area.x() + (area.width() - sz.width()) // 2, area.y(), sz.width(), sz.height())
            p.setWindow(img.rect())
            p.drawImage(0, 0, img)
            p.restore()
            count += 1
    finally:
        p.end()
    return count
