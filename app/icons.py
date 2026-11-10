"""Bộ icon nét mảnh kiểu Fluent (SVG nội tuyến, không cần file ảnh ngoài).

Icon được vẽ một lần theo màu chủ đề rồi lưu cache -> nhẹ và nhanh.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

P = {
    "open": '<path d="M3 6.5V15a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 17 15V8a1.5 1.5 0 0 0-1.5-1.5H10L8.3 4.5H4.5A1.5 1.5 0 0 0 3 6z"/>',
    "save": '<path d="M5 3.5h8.5l3 3V15a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 15V5A1.5 1.5 0 0 1 5 3.5zM7 3.5v4h6v-4M6.5 16.5v-5h7v5"/>',
    "print": '<path d="M6 7V3.5h8V7M6 13.5H4.5A1.5 1.5 0 0 1 3 12V8.5A1.5 1.5 0 0 1 4.5 7h11A1.5 1.5 0 0 1 17 8.5V12a1.5 1.5 0 0 1-1.5 1.5H14M6 11h8v5.5H6z"/>',
    "undo": '<path d="M7.5 5.5 4 9l3.5 3.5M4 9h8a4 4 0 0 1 0 8H9"/>',
    "redo": '<path d="M12.5 5.5 16 9l-3.5 3.5M16 9H8a4 4 0 0 0 0 8h3"/>',
    "text": '<path d="M4 5V3.5h12V5M10 3.5v13M7.5 16.5h5"/>',
    "textbox": '<rect x="3" y="4" width="14" height="12" rx="1.5"/><path d="M7 8h6M10 8v5"/>',
    "hand": '<path d="M3 15.5c1.5 0 2-2.5 3-5.5s1.8-5 2.8-5-.3 6 .7 9 2.5-4 3.5-4-.5 3.5.8 3.5 1.7-1.5 2.7-2M3 17.5h14"/>',
    "image": '<rect x="3" y="4" width="14" height="12" rx="1.5"/><circle cx="7.5" cy="8.5" r="1.5"/><path d="M17 13l-4-4-7 7"/>',
    "note": '<path d="M4.5 3.5h11A1.5 1.5 0 0 1 17 5v7l-4.5 4.5h-8A1.5 1.5 0 0 1 3 15V5a1.5 1.5 0 0 1 1.5-1.5zM12.5 16.5V13a1 1 0 0 1 1-1H17"/>',
    "check": '<path d="M5 10.5l3 3 7-7"/>',
    "shape": '<rect x="3" y="3" width="8" height="8" rx="1"/><circle cx="13" cy="13" r="4"/>',
    "pen": '<path d="M13.5 3.5l3 3L8 15l-4 1 1-4z"/>',
    "erase": '<path d="M8.5 16.5h8M4 12.5l7-7 4.5 4.5-6 6H6.5z"/>',
    "search": '<circle cx="9" cy="9" r="5.5"/><path d="M13 13l3.5 3.5"/>',
    "pageadd": '<path d="M11.5 3.5H6A1.5 1.5 0 0 0 4.5 5v10A1.5 1.5 0 0 0 6 16.5h8a1.5 1.5 0 0 0 1.5-1.5V7.5zM10 9v5M7.5 11.5h5"/>',
    "page": '<path d="M11.5 3.5H6A1.5 1.5 0 0 0 4.5 5v10A1.5 1.5 0 0 0 6 16.5h8a1.5 1.5 0 0 0 1.5-1.5V7.5zM11.5 3.5v4h4"/>',
    "delete": '<path d="M4 5.5h12M8 5.5V4h4v1.5M5.5 5.5l.8 10a1.5 1.5 0 0 0 1.5 1.4h4.4a1.5 1.5 0 0 0 1.5-1.4l.8-10"/>',
    "rotate": '<path d="M15.5 10a5.5 5.5 0 1 1-1.6-3.9M16 3.5V7h-3.5"/>',
    "rotateleft": '<path d="M4.5 10a5.5 5.5 0 1 0 1.6-3.9M4 3.5V7h3.5"/>',
    "autorotate": '<path d="M15.5 10a5.5 5.5 0 1 1-1.6-3.9M16 3.5V7h-3.5M8 10.5l1.5 1.5 3-3"/>',
    "split": '<circle cx="6" cy="14.5" r="2"/><circle cx="14" cy="14.5" r="2"/><path d="M7.3 13 14 3.5M12.7 13 6 3.5"/>',
    "resize": '<path d="M3.5 8V3.5H8M16.5 12v4.5H12M3.5 3.5l5 5M16.5 16.5l-5-5"/>',
    "stamp": '<path d="M7.5 11V9a2.5 2.5 0 1 1 5 0v2M4 11h12v3H4zM5 16.5h10"/>',
    "sign": '<path d="M3 14c2-4 3-8.5 5-8.5S7 13 9 13s2-3.5 3.5-3.5 1 3 2.5 3M3 17h14"/>',
    "seam": '<rect x="2.5" y="4" width="7" height="12" rx="1"/><rect x="10.5" y="4" width="7" height="12" rx="1"/><circle cx="10" cy="10" r="3"/>',
    "token": '<rect x="7" y="2.5" width="6" height="5"/><path d="M5.5 7.5h9v8a2 2 0 0 1-2 2h-5a2 2 0 0 1-2-2zM9 4.5v1M11 4.5v1"/>',
    "batch": '<path d="M6.5 3.5h8A1.5 1.5 0 0 1 16 5v9M4 8a1.5 1.5 0 0 1 1.5-1.5H12A1.5 1.5 0 0 1 13.5 8v7a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 15z"/>',
    "shield": '<path d="M10 2.5 16 5v5c0 3.5-2.5 6-6 7.5C6.5 16 4 13.5 4 10V5z"/><path d="M7.5 10l2 2 3-3.5"/>',
    "flow": '<circle cx="4.5" cy="10" r="1.8"/><circle cx="10" cy="10" r="1.8"/><circle cx="15.5" cy="10" r="1.8"/><path d="M6.3 10h1.9M11.8 10h1.9"/>',
    "phone": '<rect x="6" y="2.5" width="8" height="15" rx="1.5"/><path d="M9 15h2"/>',
    "lock": '<rect x="4.5" y="9" width="11" height="8" rx="1.5"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/>',
    "key": '<circle cx="7" cy="13" r="3.5"/><path d="M9.5 10.5 16 4M13.5 6.5l2 2"/>',
    "merge": '<path d="M3.5 6.5 10 3l6.5 3.5L10 10zM3.5 10l6.5 3.5 6.5-3.5M3.5 13.5 10 17l6.5-3.5"/>',
    "tabs": '<rect x="3" y="6" width="14" height="10.5" rx="1.5"/><path d="M3 9h14M7 6V4h10v7"/>',
    "toc": '<path d="M7.5 5h9M7.5 10h9M7.5 15h9M4 5h.5M4 10h.5M4 15h.5"/>',
    "mail": '<rect x="3" y="4.5" width="14" height="11" rx="1.5"/><path d="M3.5 5.5 10 10.5l6.5-5"/>',
    "compare": '<rect x="2.5" y="4" width="6.5" height="12" rx="1"/><rect x="11" y="4" width="6.5" height="12" rx="1"/><path d="M4.5 8h2.5M13 8h2.5M4.5 11h2.5M13 11h2.5"/>',
    "stamptext": '<rect x="2.5" y="6" width="15" height="8" rx="1.5"/><path d="M5.5 10h9"/>',
    "compress": '<path d="M10 3v5M7.5 5.5 10 8l2.5-2.5M10 17v-5M7.5 14.5 10 12l2.5 2.5M4 10h12"/>',
    "batchxl": '<rect x="3" y="3" width="9" height="11" rx="1"/><path d="M5.5 6.5h4M5.5 9.5h4M14.5 6.5v10H6.5"/>',
    "ocr": '<path d="M3.5 7V4.5a1 1 0 0 1 1-1H7M13 3.5h2.5a1 1 0 0 1 1 1V7M16.5 13v2.5a1 1 0 0 1-1 1H13M7 16.5H4.5a1 1 0 0 1-1-1V13M7 13l3-7 3 7M8 11h4"/>',
    "autofolder": '<path d="M3 6.5V15a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 17 15V8a1.5 1.5 0 0 0-1.5-1.5H10L8.3 4.5H4.5A1.5 1.5 0 0 0 3 6zM10.5 8.5 8.5 12h3l-2 3.5"/>',
    "history": '<path d="M3.5 10a6.5 6.5 0 1 0 2-4.7M3.5 3.5v3h3M10 6.5V10l2.5 1.5"/>',
    "backup": '<path d="M6 15H5a3.5 3.5 0 0 1-.4-7 5 5 0 0 1 9.7-1A3.5 3.5 0 0 1 15 15h-1M10 10v7M7.5 12.5 10 10l2.5 2.5"/>',
    "zin": '<circle cx="9" cy="9" r="5.5"/><path d="M13 13l3.5 3.5M9 6.5v5M6.5 9h5"/>',
    "zout": '<circle cx="9" cy="9" r="5.5"/><path d="M13 13l3.5 3.5M6.5 9h5"/>',
    "fitpage": '<rect x="4.5" y="3" width="11" height="14" rx="1.5"/><path d="M7.5 7.5 10 6l2.5 1.5M7.5 12.5 10 14l2.5-1.5"/>',
    "fitwidth": '<rect x="3" y="5" width="14" height="10" rx="1.5"/><path d="M6.5 10h7M8 8.5 6.5 10 8 11.5M12 8.5l1.5 1.5-1.5 1.5"/>',
    "sun": '<circle cx="10" cy="10" r="3.5"/><path d="M10 2.5V4M10 16v1.5M2.5 10H4M16 10h1.5M4.7 4.7l1 1M14.3 14.3l1 1M4.7 15.3l1-1M14.3 5.7l1-1"/>',
    "moon": '<path d="M15.5 12.5A6 6 0 0 1 7.5 4.5a6 6 0 1 0 8 8z"/>',
    "close": '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/>',
    "plus": '<path d="M10 4.5v11M4.5 10h11"/>',
    "info": '<circle cx="10" cy="10" r="7"/><path d="M10 9v5M10 6.2v.3"/>',
    "home": '<path d="M3.5 9 10 3.5 16.5 9M5 8v8h3.5v-4.5h3V16H15V8"/>',
    "gear": '<circle cx="10" cy="10" r="2.5"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"/>',
    "layout": '<rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M7 3.5v13M13 3.5v13"/>',
    "window": '<rect x="2.5" y="5.5" width="11" height="10" rx="1.5"/><path d="M6.5 5.5V4a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 17.5 4v7a1.5 1.5 0 0 1-1.5 1.5h-2.5"/>',
    "chevup": '<path d="M5 12.5 10 7.5l5 5"/>',
    "chevdown": '<path d="M5 7.5 10 12.5l5-5"/>',
    "chevleft": '<path d="M12.5 5 7.5 10l5 5"/>',
    "chevright": '<path d="M7.5 5l5 5-5 5"/>',
    "ribbon": '<rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M2.5 8h15M6 5.8h.01M9 5.8h.01"/>',
    "usb": '<rect x="7" y="9" width="6" height="8.5" rx="1"/><path d="M8 9V3.5h4V9M9 5.5h.01M11 5.5h.01"/>',
    "recent": '<circle cx="10" cy="10" r="6.5"/><path d="M10 6.5V10l2.5 1.5"/>',
    "select": '<path d="M5 3.5v12l3.3-3.2 2.3 5.2 2.2-1-2.3-5.1H15z"/>',
    "notelist": '<path d="M4.5 3.5h11A1.5 1.5 0 0 1 17 5v8a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3h-1A1.5 1.5 0 0 1 3 13V5a1.5 1.5 0 0 1 1.5-1.5zM6.5 7h7M6.5 10h5"/>',
    "colormode": '<circle cx="10" cy="10" r="6.5"/><path d="M10 3.5v13a6.5 6.5 0 0 0 0-13z" fill="currentColor"/>',
    "app": None,  # vẽ riêng
}

APP_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16" '
           'rx="4" fill="#005fb8"/><path d="M6 13.5c1.2-2.5 1.8-5 3-5s-.6 4.5.6 4.5 1.2-2 2.2-2 .6 1.6 1.8 1.6" '
           'fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round"/></svg>')


def _render(svg: str, size: int) -> QPixmap:
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


# con dấu "Ấn triện": vòng đỏ son + chữ ký
SEAL_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="21" fill="#B8322A"/>'
            '<circle cx="24" cy="24" r="17" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="2.2 2.2"/>'
            '<path d="M14 29c3-5 4.5-11 7-11s-1.2 9 1.3 9 2.6-4.5 4.8-4.5 1.2 3.2 3.8 3.2 2.4-1.5 3.1-2.2" fill="none" '
            'stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')

# lệnh -> nhóm màu ô (theo mẫu giao diện: đỏ = ký/dấu, xanh = file/trang, lá = kiểm tra, tím = sửa, vàng = bảo vệ)
TILE_OF = {
    "open": "blue", "save": "blue", "print": "gray", "undo": "gray", "redo": "gray", "tray": "violet",
    "image": "green", "protect": "amber", "mail": "blue",
    "edittext": "violet", "textbox": "violet", "hand": "violet", "note": "amber", "symbol": "green",
    "shape": "blue", "pen": "violet", "erase": "gray", "find": "blue",
    "insertpdf": "blue", "blank": "gray", "delete": "red", "rotateleft": "blue", "rotate": "blue",
    "autorotate": "violet", "split": "amber", "resize": "green",
    "stamp": "red", "sigimg": "blue", "seam": "amber", "batchsign": "violet", "verify": "green", "flow": "blue",
    "remote": "gray", "password": "amber", "printperm": "gray", "presets": "green",
    "trayadd": "blue", "traytabs": "blue", "toc": "amber", "merge": "violet",
    "compare": "blue", "stamptext": "red", "compress": "green", "batchxl": "green", "ocr": "gray",
    "autofolder": "amber", "history": "violet", "backup": "blue", "license": "amber", "about": "gray",
}


@lru_cache(maxsize=512)
def tile_icon(name: str, bg: str, fg: str, size: int = 64) -> QIcon:
    """Icon nằm trong ô vuông bo góc có nền nhạt (dải công cụ, trang bắt đầu)."""
    body = P.get(name) or P["page"]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="0" y="0" width="32" height="32" '
           f'rx="9" fill="{bg}"/><g transform="translate(6 6)" fill="none" stroke="{fg}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round">{body}</g></svg>')
    return QIcon(_render(svg, size))


@lru_cache(maxsize=4)
def seal(size: int = 96) -> QIcon:
    return QIcon(_render(SEAL_SVG, size))


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#1b1b1b", size: int = 40) -> QIcon:
    if name == "app":
        return QIcon(_render(SEAL_SVG, 64))
    body = P.get(name) or P["page"]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" color="{color}" stroke="{color}" '
           f'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    return QIcon(_render(svg, size))
