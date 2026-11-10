"""Vùng xem trang PDF: cuộn liên tục, zoom quanh con trỏ, render theo nhu cầu.

Tối ưu:
- Chỉ vẽ các trang đang nằm trong vùng nhìn thấy.
- Cache ảnh trang (LRU theo tổng số pixel) để cuộn lại không phải render.
- Khi zoom: vẽ tạm ảnh cũ phóng/thu (tức thì), render nét ở mức mới sau ~60 ms.
- Zoom lớn: chia trang thành ô 1024 px, chỉ render các ô đang hiện, cuộn lại dùng lại ô cũ.
"""
from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QScrollArea, QWidget

from .document import PdfDocument

PX_PER_PT = 96 / 72
LIB_MIME = "application/x-pdfkyso-lib"
MARGIN = 24
GAP = 16
ZOOM_MIN, ZOOM_MAX = 10, 6400
FULL_RENDER_LIMIT = 4_000_000      # trang lớn hơn mức này -> render theo ô (tile), chỉ ô đang thấy
TILE = 1024                        # cạnh ô render (pixel thiết bị)
CACHE_PIXELS = 50_000_000          # tối đa ~150 MB ảnh RGB trong cache


def to_qimage(bm) -> QImage:
    """PdfBitmap (RGB) -> QImage, sao chép một lần rồi giải phóng bitmap ngay."""
    fmt = QImage.Format_RGB888 if bm.n_channels == 3 else QImage.Format_RGBX8888
    img = QImage(bm.buffer, bm.width, bm.height, bm.stride, fmt).copy()
    bm.close()
    return img


def _mods(ev):
    """Phím bổ trợ của sự kiện (sự kiện giả lập trong kiểm thử có thể không có)."""
    m = getattr(ev, "modifiers", None)
    return m() if callable(m) else Qt.NoModifier


class _Canvas(QWidget):
    def __init__(self, view: "PageView"):
        super().__init__()
        self.view = view
        self.setObjectName("pages")
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMouseTracking(True)

    def paintEvent(self, ev):
        self.view._paint(self, ev.rect())

    def mousePressEvent(self, ev):
        v = self.view
        if v.callout_outside():                   # bấm ra ngoài khung ghi chú: lưu / đóng khung, không làm gì thêm
            return
        had_inline = v._inline is not None
        v._finish_inline()
        if had_inline and v.tool and v.tool.kind == "textbox":
            return                               # bấm ra ngoài hộp chữ đang gõ: chỉ để xong, không mở hộp mới
        if v._place_press(ev):
            return
        if v.tool and ev.button() == Qt.LeftButton:
            v._tool_press(ev)
            return
        hit = v.page_at(ev.position())
        if hit and ev.button() == Qt.LeftButton:
            v.pagePressed.emit(*hit)
            if v.placement is not None:          # vừa chọn một đối tượng -> kéo luôn, không phải bấm lại
                v._place_press(ev)
                return
            under = v.hover_provider(*hit) if v.hover_provider else None
            if under in (None, "text") and v._inline is None:
                idx = v.char_at(*hit) if not (_mods(ev) & Qt.ControlModifier) else None
                if idx is not None:                  # trên chữ: kéo để bôi chọn chữ (như Foxit / Adobe)
                    if _mods(ev) & Qt.ShiftModifier and v.text_sel and v.text_sel[0] == hit[0]:
                        v._tsel = [hit[0], v.text_sel[1], idx, True]
                        v._update_text_sel()
                    else:
                        v._tsel = [hit[0], idx, idx, False]
                    return
                v.clear_text_selection()
                v._band = [hit[0], (hit[1], hit[2]), (hit[1], hit[2])]   # chỗ trống: kéo khung chọn nhiều nội dung
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        v = self.view
        if v._tsel is not None:
            r = v._rects[v._tsel[0]]
            s = v.scale
            x, y = (ev.position().x() - r.left()) / s, (ev.position().y() - r.top()) / s
            idx = v.char_at(v._tsel[0], x, y, near=True)
            if idx is not None and (idx != v._tsel[2] or not v._tsel[3]):
                v._tsel[2] = idx
                v._tsel[3] = True
                v._update_text_sel()
            return
        if v._band is not None:
            r = v._rects[v._band[0]]
            s = v.scale
            pw, ph = v.doc.page_size_pt(v._band[0])
            v._band[2] = (min(max((ev.position().x() - r.left()) / s, 0), pw),
                          min(max((ev.position().y() - r.top()) / s, 0), ph))
            self.update()
            return
        if v.placement:
            v._place_move(ev)
        elif v.tool:
            v._tool_move(ev)
        else:
            v._hover(ev)

    def mouseReleaseEvent(self, ev):
        v = self.view
        if v._tsel is not None:
            moved = v._tsel[3]
            v._tsel = None
            if not moved:                        # chỉ bấm (không kéo): bỏ vùng chọn cũ
                v.clear_text_selection()
            elif v.text_sel:
                v.textSelected.emit()
            return
        if v._band is not None:
            page, a, b = v._band
            v._band = None
            self.update()
            if abs(a[0] - b[0]) > 3 and abs(a[1] - b[1]) > 3:
                v.bandSelected.emit(page, min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            return
        if self.view.placement:
            self.view._place_release(ev)
        elif self.view.tool:
            self.view._tool_release(ev)

    def mouseDoubleClickEvent(self, ev):
        v = self.view
        if v.tool and v.tool.kind in POLY_TOOLS:
            v._poly_finish()
            return
        if v.placement:
            pl = v.placement
            if pl.on_dblclick and v._placement_hit(ev.position()) is not None:
                pl.on_dblclick(pl)
                return
            v.commit_placement()
            return
        hit = v.page_at(ev.position())
        if hit and not v.tool:
            if v.select_word(*hit):              # nháy đúp lên chữ: chọn cả từ (không mở sửa chữ)
                v.textSelected.emit()
                return
            v.pageDoubleClicked.emit(*hit)

    def contextMenuEvent(self, ev):
        v = self.view
        if v.tool or v.placement or v._inline is not None:
            return super().contextMenuEvent(ev)
        hit = v.page_at(QPointF(ev.pos()))
        if hit:
            v.textMenu.emit(hit[0], hit[1], hit[2], ev.globalPos())

    def tabletEvent(self, ev):
        """Bút cảm ứng / bảng vẽ: ghi lại lực nhấn cho bút ký, bút lông. Qt vẫn tạo sự kiện chuột như thường."""
        try:
            self.view._pressure = float(ev.pressure())
        except Exception:
            self.view._pressure = None
        ev.ignore()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(LIB_MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(LIB_MIME):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        hit = self.view.page_at(ev.position())
        if ev.mimeData().hasFormat(LIB_MIME) and hit:
            ev.acceptProposedAction()
            self.view.libraryDropped.emit(bytes(ev.mimeData().data(LIB_MIME)).decode(), *hit)


def rotated_bbox(rect, angle: float) -> tuple[float, float, float, float]:
    """Khung bao của khung (x0, y0, x1, y1) khi xoay `angle` độ quanh tâm."""
    x0, y0, x1, y1 = rect
    if not angle:
        return (x0, y0, x1, y1)
    a = math.radians(angle)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    w, h = x1 - x0, y1 - y0
    bw, bh = w * c + h * s, w * s + h * c
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)


class Placement:
    """Đối tượng đang đặt lên trang (ảnh, con dấu, nội dung đã thêm...):
    kéo để di chuyển, kéo góc để đổi cỡ, kéo núm tròn phía trên để xoay (nếu cho phép)."""

    HANDLE = 10
    ROT_GAP = 22                   # khoảng cách núm xoay phía trên khung (pixel)

    def __init__(self, image: QImage, page: int, rect_pt: QRectF, on_commit, label: str = "",
                 on_delete=None, on_cancel=None, keep_ratio: bool = True):
        self.image = image
        self.page = page
        self.rect = rect_pt            # toạ độ hiển thị của trang, đơn vị pt (khung chưa xoay)
        self.on_commit = on_commit
        self.on_delete = on_delete     # sửa đối tượng đã chèn: phím Delete để xóa
        self.on_cancel = on_cancel
        self.keep_ratio = keep_ratio
        self.label = label
        self.drag = None               # ("move"|"resize"|"rotate", điểm bắt đầu, rect ban đầu, góc, góc xoay ban đầu)
        self.angle = 0.0               # độ, chiều kim đồng hồ
        self.rotatable = False
        self.resizable = True
        self.on_click = None           # bấm (không kéo) lên khung
        self.on_dblclick = None        # nháy đúp lên khung (vd. sửa chữ tại chỗ)
        self.on_change = None          # khung vừa đổi (kéo / xoay) -> cập nhật bảng thuộc tính
        self.commit_outside = False    # bấm ra ngoài: đặt luôn (sửa đối tượng) thay vì chuyển khung tới đó
        self.cancel_outside = False    # bấm ra ngoài: bỏ (xem trước vùng tẩy)
        self.guides = []               # đường gióng đang hiện khi kéo [("x"|"y", giá trị pt)]
        self.moved = False
        self.hint = ""


DRAG_TOOLS = {"rect", "ellipse", "line", "arrow", "highlight", "erase", "textbox", "handarea", "shape", "scanedit"}
CLICK_TOOLS = {"check", "cross", "dot", "circle", "box", "boxcheck", "note", "edittext"}
POLY_TOOLS = {"polyline", "polygon"}
LINE_KINDS = {"line", "arrow", "darrow", "curve", "carrow"}
FREE_TOOLS = {"ink", "lasso", "brush", "inkerase"}   # vẽ theo đường di chuột


class Tool:
    """Công cụ vẽ/ghi chú đang bật: kéo (hình, vùng), bấm (ký hiệu, ghi chú, sửa chữ), vẽ tay (ink)."""

    def __init__(self, kind: str, on_done, color: str = "#d32f2f", width: float = 1.5, sticky: bool = True):
        self.kind = kind
        self.on_done = on_done          # kéo: (trang, (x0,y0,x1,y1)); bấm: (trang, (x,y)); vẽ tay: (trang, [điểm])
        self.color = color
        self.width = width
        self.sticky = sticky            # dùng xong vẫn giữ công cụ (vẽ liên tiếp)
        self.page = None
        self.start = None
        self.cur = None
        self.points = []
        self.samples = []               # vẽ tay: [(x, y, thời gian, lực nhấn)]
        self.shape = ""                 # kind == "shape": mã hình trong thư viện
        self.erase_shape = "rect"       # tẩy vùng: rect | ellipse | lasso | brush
        self.size = 12.0                # cỡ cọ tẩy (pt)
        self.magnifier = False          # kính lúp khi kéo vùng tẩy
        self.stroke_done = None         # vẽ tay: gom nhiều nét rồi mới xong (None = xong ngay mỗi nét)


class PageView(QScrollArea):
    zoomChanged = Signal(int)
    currentPageChanged = Signal(int)
    libraryDropped = Signal(str, int, float, float)    # (id mẫu, trang, x_pt, y_pt)
    pagePressed = Signal(int, float, float)            # bấm chuột trái lên trang (không có công cụ)
    pageDoubleClicked = Signal(int, float, float)
    toolChanged = Signal(str)
    placementEnded = Signal()                           # đặt xong / hủy / xóa khung đặt ảnh
    bandSelected = Signal(int, float, float, float, float)   # 13d: kéo khung chọn nhiều nội dung (trang, x0, y0, x1, y1)
    textSelected = Signal()                             # vừa bôi chọn xong một đoạn chữ
    textMenu = Signal(int, float, float, QPoint)        # bấm phải lên trang (trang, x, y, vị trí màn hình)
    clipboardAction = Signal(str)                       # 13d: "copy" | "cut" | "paste" | "dup"

    def __init__(self, doc: PdfDocument, canvas_color: str = "#e2e2e2"):
        super().__init__()
        self.setObjectName("viewer")
        self.doc = doc
        self.zoom = 100
        self.canvas_color = QColor(canvas_color)
        self._rects: list[QRectF] = []
        self._cache: OrderedDict = OrderedDict()   # key -> QImage
        self._cache_px = 0
        self._current = 0
        self.canvas = _Canvas(self)
        self.canvas.setAcceptDrops(True)
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._hires = QTimer(self, singleShot=True, interval=60, timeout=self.canvas.update)
        self._fast_pass = False
        self.placement: Placement | None = None
        self.tool: Tool | None = None
        self.hover_provider = None       # (trang, x, y) -> "item" | "text" | "note" | "image" | None (đổi con trỏ)
        self.guide_provider = None       # (trang) -> ([x...], [y...]) các cạnh/tâm để bắt thẳng hàng
        self.snap_grid = 0.0             # > 0: bắt lưới (pt)
        self.show_grid = False
        self._pressure = None
        self._inline = None              # ô sửa chữ tại chỗ đang mở
        self._callout = None             # khung ghi chú nổi trên trang: (widget, trang, (x, y) pt, bấm ra ngoài)
        # widget -> True: bấm vào đó (vd. bảng cỡ chữ / đậm / màu bên phải) KHÔNG đóng ô sửa chữ tại chỗ
        self.inline_keep = None
        self._mag = None                 # kính lúp: (trang, x, y)
        self._band = None                # khung kéo chọn: [trang, (x0, y0), (x1, y1)]
        self._tsel = None                # đang kéo bôi chọn chữ: [trang, chỉ số đầu, chỉ số cuối, đã kéo?]
        self.text_sel = None             # chữ đang bôi chọn: (trang, đầu, số ký tự)
        self._tp_cache = None            # (trang, phiên bản tài liệu, PdfTextPage)
        # lớp tô màu phía trên trang (không ghi vào file): "search" (chỗ tìm thấy – vàng), "search_cur" (chỗ đang
        # xem – cam), "select" (chữ đang bôi chọn – xanh). {loại: {trang: [(x0, y0, x1, y1) pt]}}
        self.marks: dict[str, dict[int, list]] = {}
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.relayout()

    # ---------- bố cục ----------
    @property
    def scale(self) -> float:
        return self.zoom / 100 * PX_PER_PT

    def relayout(self):
        s = self.scale
        sizes = [self.doc.page_size_pt(i) for i in range(self.doc.page_count)]
        maxw = max((w for w, _ in sizes), default=0) * s
        cw = max(self.viewport().width(), int(maxw + 2 * MARGIN))
        y = MARGIN
        rects = []
        for w, h in sizes:
            pw, ph = w * s, h * s
            rects.append(QRectF((cw - pw) / 2, y, pw, ph))
            y += ph + GAP
        self._rects = rects
        self.canvas.resize(cw, int(y - GAP + MARGIN) if rects else self.viewport().height())
        self.canvas.update()
        self._place_callout()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        anchor = self._anchor(QPoint(0, 0))
        self.relayout()
        if anchor:
            self._restore_anchor(anchor, QPoint(0, 0))

    def document_changed(self):
        """Gọi sau khi nội dung đổi (xoay/xóa/chèn trang, hoàn tác)."""
        self._drop_textpage()
        if self.text_sel is not None:
            self.text_sel = None
            self.marks.pop("select", None)
        self._cache.clear()
        self._cache_px = 0
        self.relayout()
        self._on_scroll()

    # ---------- chuyển đổi toạ độ ----------
    def _anchor(self, vp: QPoint):
        """Điểm trên viewport -> (trang, x_pt, y_pt)."""
        pos = QPointF(vp.x() + self.horizontalScrollBar().value(),
                      vp.y() + self.verticalScrollBar().value())
        if not self._rects:
            return None
        s = self.scale
        best = min(range(len(self._rects)),
                   key=lambda i: 0 if self._rects[i].top() <= pos.y() <= self._rects[i].bottom()
                   else min(abs(self._rects[i].top() - pos.y()), abs(self._rects[i].bottom() - pos.y())))
        r = self._rects[best]
        return best, (pos.x() - r.left()) / s, (pos.y() - r.top()) / s

    def _restore_anchor(self, anchor, vp: QPoint):
        i, xpt, ypt = anchor
        if i >= len(self._rects):
            return
        r = self._rects[i]
        s = self.scale
        self.horizontalScrollBar().setValue(int(r.left() + xpt * s - vp.x()))
        self.verticalScrollBar().setValue(int(r.top() + ypt * s - vp.y()))

    # ---------- zoom ----------
    def set_zoom(self, z: float, anchor_vp: QPoint | None = None):
        z = int(round(max(ZOOM_MIN, min(ZOOM_MAX, z))))
        if z == self.zoom:
            return
        if anchor_vp is None:
            anchor_vp = QPoint(self.viewport().width() // 2, self.viewport().height() // 2)
        anchor = self._anchor(anchor_vp)
        self.zoom = z
        self._fast_pass = True
        self.relayout()
        if anchor:
            self._restore_anchor(anchor, anchor_vp)
        self._hires.start()
        self.zoomChanged.emit(z)

    def zoom_step(self, direction: int, anchor_vp: QPoint | None = None):
        steps = [10, 25, 33, 50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400,
                 500, 800, 1200, 1600, 3200, 6400]
        if direction > 0:
            nxt = next((v for v in steps if v > self.zoom), ZOOM_MAX)
        else:
            nxt = next((v for v in reversed(steps) if v < self.zoom), ZOOM_MIN)
        self.set_zoom(nxt, anchor_vp)

    def fit_page(self):
        if not self._rects:
            return
        w, h = self.doc.page_size_pt(self._current)
        vw = self.viewport().width() - 2 * MARGIN
        vh = self.viewport().height() - 2 * MARGIN
        self.set_zoom(min(vw / (w * PX_PER_PT), vh / (h * PX_PER_PT)) * 100)
        self.go_to(self._current)

    def fit_width(self):
        if not self._rects:
            return
        maxw = max(self.doc.page_size_pt(i)[0] for i in range(self.doc.page_count))
        vw = self.viewport().width() - 2 * MARGIN - self.verticalScrollBar().sizeHint().width()
        self.set_zoom(vw / (maxw * PX_PER_PT) * 100)

    def scale_placement(self, factor: float) -> bool:
        """Phóng to / thu nhỏ khung đang đặt quanh tâm (giữ tỉ lệ)."""
        pl = self.placement
        if pl is None or not pl.resizable or factor <= 0:
            return False
        r = pl.rect
        w, h = r.width() * factor, r.height() * factor
        if min(w, h) < 4:
            return False
        c = r.center()
        pl.rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        if pl.on_change:
            pl.on_change(pl)
        self.canvas.update()
        return True

    def wheelEvent(self, ev: QWheelEvent):
        if _mods(ev) & Qt.ControlModifier:
            dy = ev.angleDelta().y()
            pl = self.placement
            if dy and pl is not None and pl.resizable:   # Ctrl + lăn trên ảnh đang đặt: đổi cỡ ảnh, không zoom trang
                cpos = QPointF(self.canvas.mapFrom(self.viewport(), ev.position().toPoint()))
                if self._placement_hit(cpos) is not None:
                    self.scale_placement(1.05 ** (dy / 120))
                    ev.accept()
                    return
            if dy:
                # mỗi nấc ~10%, zoom quanh vị trí con trỏ
                factor = 1.1 ** (dy / 120)
                self.set_zoom(self.zoom * factor if abs(dy) < 120 else
                              self.zoom + (10 if dy > 0 else -10) * max(1, self.zoom // 100),
                              ev.position().toPoint())
            ev.accept()
            return
        super().wheelEvent(ev)

    # ---------- điều hướng ----------
    def go_to(self, i: int):
        if 0 <= i < len(self._rects):
            self.verticalScrollBar().setValue(int(self._rects[i].top() - MARGIN / 2))
            self._set_current(i)

    def current_page(self) -> int:
        return self._current

    def _set_current(self, i: int):
        if i != self._current:
            self._current = i
            self.currentPageChanged.emit(i)

    def _on_scroll(self, *_):
        if not self._rects:
            return
        cy = self.verticalScrollBar().value() + self.viewport().height() / 3
        for i, r in enumerate(self._rects):
            if r.bottom() + GAP >= cy:
                self._set_current(i)
                break

    # ---------- vẽ ----------
    def _cache_put(self, key, img: QImage):
        self._cache[key] = img
        self._cache_px += img.width() * img.height()
        while self._cache_px > CACHE_PIXELS and len(self._cache) > 1:
            _, old = self._cache.popitem(last=False)
            self._cache_px -= old.width() * old.height()

    def _best_cached(self, i: int):
        best = None
        for (ver, pi, sc, clip), img in self._cache.items():
            if ver == self.doc.version and pi == i and clip is None:
                if best is None or abs(sc - self.scale) < abs(best[0] - self.scale):
                    best = (sc, img)
        return best

    def _paint(self, w: QWidget, area: QRect):
        p = QPainter(w)
        p.fillRect(area, self.canvas_color)
        dpr = w.devicePixelRatioF()
        s = self.scale
        fast = self._fast_pass
        self._fast_pass = False
        visible = QRectF(self.horizontalScrollBar().value(), self.verticalScrollBar().value(),
                         self.viewport().width(), self.viewport().height())
        for i, r in enumerate(self._rects):
            if r.bottom() < area.top() or r.top() > area.bottom():
                continue
            # bóng đổ nhẹ
            p.fillRect(r.adjusted(1, 2, 2, 3), QColor(0, 0, 0, 40))
            p.fillRect(r, Qt.white)
            full_px = r.width() * r.height() * dpr * dpr
            if full_px <= FULL_RENDER_LIMIT:
                key = (self.doc.version, i, round(s * dpr, 4), None)
                img = self._cache.get(key)
                if img is None and fast:
                    cached = self._best_cached(i)
                    if cached:
                        p.drawImage(r, cached[1])
                        continue
                if img is None:
                    img = to_qimage(self.doc.render(i, s * dpr))
                    img.setDevicePixelRatio(dpr)
                    self._cache_put(key, img)
                else:
                    self._cache.move_to_end(key)
                p.drawImage(r.topLeft(), img)
            else:
                # zoom lớn: chỉ render các ô (tile) giao với vùng đang thấy
                part = r & visible & QRectF(area)
                if part.isEmpty():
                    continue
                S = s * dpr
                wd, hd = r.width() * dpr, r.height() * dpr
                ax0, ay0 = (part.left() - r.left()) * dpr, (part.top() - r.top()) * dpr
                ax1, ay1 = (part.right() - r.left()) * dpr, (part.bottom() - r.top()) * dpr
                tiles = [(tx, ty) for ty in range(int(ay0 // TILE), int(max(ay0, ay1 - 1) // TILE) + 1)
                         for tx in range(int(ax0 // TILE), int(max(ax0, ax1 - 1) // TILE) + 1)]
                keys = [(self.doc.version, i, round(S, 4), ("t", tx, ty)) for tx, ty in tiles]
                if fast and any(k not in self._cache for k in keys):
                    cached = self._best_cached(i)
                    if cached:
                        p.drawImage(r, cached[1])
                        continue
                for (tx, ty), key in zip(tiles, keys):
                    x0, y0 = tx * TILE, ty * TILE
                    x1, y1 = min(wd, x0 + TILE), min(hd, y0 + TILE)
                    img = self._cache.get(key)
                    if img is None:
                        crop = (x0 / S, max(0.0, (hd - y1) / S), max(0.0, (wd - x1) / S), y0 / S)
                        img = to_qimage(self.doc.render(i, S, crop=crop))
                        self._cache_put(key, img)
                    else:
                        self._cache.move_to_end(key)
                    p.drawImage(QRectF(r.left() + x0 / dpr, r.top() + y0 / dpr,
                                       (x1 - x0) / dpr, (y1 - y0) / dpr), img)
        if self.marks:
            self._paint_marks(p, QRectF(area))
        if self.show_grid and self.snap_grid > 0:
            self._paint_grid(p, QRectF(area))
        if self.placement:
            self._paint_placement(p)
        if self._band is not None:
            from PySide6.QtGui import QPen
            page, a, b = self._band
            r = self._rects[page]
            sc = self.scale
            band = QRectF(QPointF(r.left() + a[0] * sc, r.top() + a[1] * sc),
                          QPointF(r.left() + b[0] * sc, r.top() + b[1] * sc)).normalized()
            p.setPen(QPen(QColor("#005fb8"), 1, Qt.DashLine))
            p.setBrush(QColor(0, 95, 184, 30))
            p.drawRect(band)
        if self.tool and (self.tool.page is not None or self.tool.points):
            self._paint_tool(p)
        p.end()



    # ---------- bôi chọn chữ có sẵn trong PDF (để sao chép) ----------
    def _textpage(self, page: int):
        c = self._tp_cache
        if c and c[0] == page and c[1] == self.doc.version:
            return c[2]
        self._drop_textpage()
        try:
            tp = self.doc.page(page).get_textpage()
        except Exception:
            return None
        self._tp_cache = (page, self.doc.version, tp)
        return tp

    def _drop_textpage(self):
        if self._tp_cache:
            try:
                self._tp_cache[2].close()
            except Exception:
                pass
            self._tp_cache = None

    def char_at(self, page: int, x: float, y: float, near: bool = False):
        """Chỉ số ký tự dưới điểm (pt hiển thị) – None nếu không có chữ. near: tìm rộng hơn khi đang kéo."""
        if self.doc is None or not (0 <= page < self.doc.page_count):
            return None
        tp = self._textpage(page)
        if tp is None:
            return None
        try:
            if tp.count_chars() <= 0:
                return None
            ux, uy = self.doc.display_to_user(page, x, y)
            for tol in ((2.0, 4.0, 12.0, 40.0) if near else (1.5, 3.0)):
                idx = tp.get_index(ux, uy, tol, tol)
                if idx is not None:
                    return idx
        except Exception:
            return None
        return None

    def _update_text_sel(self):
        page, a, b = self._tsel[0], self._tsel[1], self._tsel[2]
        lo, hi = min(a, b), max(a, b)
        self.text_sel = (page, lo, hi - lo + 1)
        self._show_text_sel()

    def _show_text_sel(self):
        if not self.text_sel:
            self.set_marks("select", None)
            return
        page, start, count = self.text_sel
        tp = self._textpage(page)
        rects = self.doc.text_rects(page, tp, start, count) if tp is not None else []
        self.set_marks("select", {page: rects} if rects else None)

    def select_word(self, page: int, x: float, y: float) -> bool:
        idx = self.char_at(page, x, y)
        if idx is None:
            return False
        tp = self._textpage(page)
        n = tp.count_chars()
        text = tp.get_text_range(0, n)
        if len(text) != n:                      # chữ ghép (ligature) / ký tự đặc biệt: chọn đúng ký tự đó
            self.text_sel = (page, idx, 1)
            self._show_text_sel()
            return True

        def is_word(c):
            return c.isalnum() or c == "_"
        if not is_word(text[idx]):
            self.text_sel = (page, idx, 1)
        else:
            a = b = idx
            while a > 0 and is_word(text[a - 1]):
                a -= 1
            while b + 1 < n and is_word(text[b + 1]):
                b += 1
            self.text_sel = (page, a, b - a + 1)
        self._show_text_sel()
        return True

    def select_page_text(self, page: int) -> bool:
        tp = self._textpage(page)
        n = tp.count_chars() if tp is not None else 0
        if n <= 0:
            return False
        self.text_sel = (page, 0, n)
        self._show_text_sel()
        return True

    def selected_text(self) -> str:
        if not self.text_sel:
            return ""
        page, start, count = self.text_sel
        tp = self._textpage(page)
        if tp is None:
            return ""
        try:
            t = tp.get_text_range(start, count)
        except Exception:
            return ""
        return t.replace("\r\n", "\n").replace("\r", "\n").replace("\x02", "").replace("\ufffe", "")

    def selected_rects(self):
        m = self.marks.get("select") or {}
        return next(iter(m.items()), (None, []))

    def clear_text_selection(self):
        if self.text_sel is not None or "select" in self.marks:
            self.text_sel = None
            self.set_marks("select", None)

    MARK_COLORS = {"search": QColor(255, 222, 0, 150), "search_cur": QColor(255, 140, 0, 190),
                   "select": QColor(0, 120, 215, 90)}

    def set_marks(self, kind: str, marks: dict | None):
        """Đặt / xóa (marks=None) một lớp tô màu: {trang: [(x0, y0, x1, y1) pt, ...]}."""
        if marks:
            self.marks[kind] = marks
        else:
            self.marks.pop(kind, None)
        self.canvas.update()

    def _paint_marks(self, p: QPainter, area: QRectF):
        s = self.scale
        p.save()
        p.setPen(Qt.NoPen)
        for kind in ("search", "search_cur", "select"):
            pages = self.marks.get(kind)
            if not pages:
                continue
            # tô kiểu bút dạ quang: nhân màu -> chữ đen vẫn rõ nét bên dưới
            p.setCompositionMode(QPainter.CompositionMode_Multiply if kind != "select"
                                 else QPainter.CompositionMode_SourceOver)
            p.setBrush(self.MARK_COLORS[kind])
            for i, rects in pages.items():
                if not (0 <= i < len(self._rects)):
                    continue
                r = self._rects[i]
                if r.bottom() < area.top() or r.top() > area.bottom():
                    continue
                for x0, y0, x1, y1 in rects:
                    p.drawRect(QRectF(r.left() + x0 * s - 1, r.top() + y0 * s - 1,
                                      (x1 - x0) * s + 2, (y1 - y0) * s + 2))
        p.restore()

    def show_rect(self, page: int, rect):
        """Cuộn để khung (pt) trên trang nằm giữa vùng xem (tới chỗ tìm thấy)."""
        if not (0 <= page < len(self._rects)):
            return
        r = self._rects[page]
        s = self.scale
        cx = r.left() + (rect[0] + rect[2]) / 2 * s
        cy = r.top() + (rect[1] + rect[3]) / 2 * s
        vw, vh = self.viewport().width(), self.viewport().height()
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        x0, y0 = hs.value(), vs.value()
        if not (x0 + 40 <= cx <= x0 + vw - 40):
            hs.setValue(int(cx - vw / 2))
        if not (y0 + 40 <= cy <= y0 + vh - 40):
            vs.setValue(int(cy - vh / 2))
        self._set_current(page)
        self.canvas.update()

    # ---------- đặt ảnh / con dấu / nội dung đã thêm lên trang ----------
    def page_at(self, pos) -> tuple[int, float, float] | None:
        """Điểm trên canvas -> (trang, x_pt, y_pt) nếu nằm trong một trang."""
        s = self.scale
        for i, r in enumerate(self._rects):
            if r.contains(pos):
                return i, (pos.x() - r.left()) / s, (pos.y() - r.top()) / s
        return None

    def begin_edit(self, image: QImage, page: int, rect, on_commit, on_delete=None, on_cancel=None,
                   label: str = "", keep_ratio: bool = True, angle: float = 0.0, rotatable: bool = False,
                   resizable: bool = True, commit_outside: bool = False) -> Placement:
        """Sửa một đối tượng đã có trên trang: khung đặt đúng chỗ cũ, Delete để xóa."""
        x0, y0, x1, y1 = rect
        pl = Placement(image, page, QRectF(x0, y0, x1 - x0, y1 - y0), on_commit, label, on_delete, on_cancel,
                       keep_ratio)
        pl.angle, pl.rotatable, pl.resizable, pl.commit_outside = float(angle or 0), rotatable, resizable, commit_outside
        self.placement = pl
        self.setFocus()
        self.canvas.setCursor(Qt.SizeAllCursor)
        self.canvas.update()
        return pl

    def begin_placement(self, image: QImage, on_commit, width_pt: float | None = None, label: str = "",
                        page: int | None = None, center_pt: tuple[float, float] | None = None):
        """Bắt đầu đặt ảnh lên trang. on_commit(page, (x0, y0, x1, y1) pt) khi xác nhận."""
        i = self.current_page() if page is None else page
        pw, ph = self.doc.page_size_pt(i)
        ratio = image.height() / max(1, image.width())
        w = width_pt or min(pw * 0.4, image.width() * 72 / 150)
        h = w * ratio
        if width_pt is None and h > ph * 0.8:     # kích thước thật (ảnh scan có DPI) thì giữ nguyên
            h = ph * 0.8
            w = h / ratio
        cx, cy = center_pt if center_pt else (pw / 2, ph / 2)
        self.placement = Placement(image, i, QRectF(cx - w / 2, cy - h / 2, w, h), on_commit, label)
        self._clamp_placement()
        self.setFocus()
        self.canvas.setCursor(Qt.SizeAllCursor)
        self.canvas.update()

    def replace_placement_image(self, image: QImage, rect_pt: QRectF | None = None):
        """Đổi ảnh xem trước của khung đang đặt (xoay / độ đậm / xóa nền / đổi kiểu nét...).
        Không truyền rect_pt: giữ tâm và tỉ lệ pt/điểm ảnh."""
        pl = self.placement
        if pl is None:
            return
        if rect_pt is not None:
            pl.image = image
            pl.rect = QRectF(rect_pt)
            self.canvas.update()
            return
        old = pl.image
        k = pl.rect.width() / max(1, old.width())
        c = pl.rect.center()
        w, h = image.width() * k, image.height() * k
        pl.image = image
        pl.rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        self._clamp_placement()
        self.canvas.update()

    def cancel_placement(self):
        pl = self.placement
        self.placement = None
        self.canvas.unsetCursor()
        if pl and pl.on_cancel:
            pl.on_cancel()
        self.canvas.update()
        if pl:
            self.placementEnded.emit()

    def delete_placement(self):
        pl = self.placement
        if not pl or not pl.on_delete:
            return
        self.placement = None
        self.canvas.unsetCursor()
        pl.on_delete()
        self.canvas.update()
        self.placementEnded.emit()

    def commit_placement(self):
        pl = self.placement
        if not pl:
            return
        self.placement = None
        self.canvas.unsetCursor()
        r = pl.rect
        try:
            if pl.rotatable:
                pl.on_commit(pl.page, (r.left(), r.top(), r.right(), r.bottom()), pl.angle)
            else:
                pl.on_commit(pl.page, (r.left(), r.top(), r.right(), r.bottom()))
        finally:
            self.canvas.update()
            self.placementEnded.emit()

    def _placement_screen_rect(self) -> QRectF:
        pl = self.placement
        r = self._rects[pl.page]
        s = self.scale
        return QRectF(r.left() + pl.rect.left() * s, r.top() + pl.rect.top() * s,
                      pl.rect.width() * s, pl.rect.height() * s)

    def _to_local(self, pos) -> QPointF:
        """Điểm màn hình -> hệ khung chưa xoay (xoay ngược quanh tâm khung)."""
        pl = self.placement
        sr = self._placement_screen_rect()
        if not pl.angle:
            return QPointF(pos)
        c = sr.center()
        a = -math.radians(pl.angle)
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        return QPointF(c.x() + dx * math.cos(a) - dy * math.sin(a), c.y() + dx * math.sin(a) + dy * math.cos(a))

    def _placement_hit(self, pos):
        """"rotate" | số góc (0..3) | "move" | None."""
        pl = self.placement
        if not pl:
            return None
        sr = self._placement_screen_rect()
        lp = self._to_local(pos)
        if pl.rotatable:
            rp = QPointF(sr.center().x(), sr.top() - Placement.ROT_GAP)
            if math.hypot(lp.x() - rp.x(), lp.y() - rp.y()) <= Placement.HANDLE:
                return "rotate"
        if pl.resizable:
            c = self._corner_at(sr, lp)
            if c is not None:
                return c
        if sr.adjusted(-3, -3, 3, 3).contains(lp):
            return "move"
        return None

    def _paint_placement(self, p: QPainter):
        from PySide6.QtGui import QPen
        pl = self.placement
        sr = self._placement_screen_rect()
        c = sr.center()
        p.save()
        p.translate(c)
        p.rotate(pl.angle)
        r0 = sr.translated(-c.x(), -c.y())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(r0, pl.image)
        p.setPen(QPen(QColor("#005fb8"), 1, Qt.DashLine if pl.commit_outside else Qt.SolidLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r0)
        h = Placement.HANDLE
        p.setPen(QColor("#005fb8"))
        p.setBrush(QColor("#ffffff"))
        if pl.resizable:
            for pt in (r0.topLeft(), r0.topRight(), r0.bottomLeft(), r0.bottomRight()):
                p.drawRect(QRectF(pt.x() - h / 2, pt.y() - h / 2, h, h))
        if pl.rotatable:
            top = QPointF(0, r0.top())
            knob = QPointF(0, r0.top() - Placement.ROT_GAP)
            p.drawLine(top, knob)
            p.setBrush(QColor("#005fb8"))
            p.drawEllipse(knob, h / 2 + 1, h / 2 + 1)
        p.restore()
        if pl.guides:
            p.setPen(QPen(QColor("#e91e63"), 1, Qt.DashLine))
            r = self._rects[pl.page]
            s = self.scale
            for axis, v in pl.guides:
                if axis == "x":
                    p.drawLine(QPointF(r.left() + v * s, r.top()), QPointF(r.left() + v * s, r.bottom()))
                else:
                    p.drawLine(QPointF(r.left(), r.top() + v * s), QPointF(r.right(), r.top() + v * s))
        if pl.angle and pl.drag and pl.drag[0] == "rotate":
            tip = f"{pl.angle:.0f}°  (giữ Shift: bước 15°)"
        else:
            tip = pl.hint or ((pl.label + " · " if pl.label else "") +
                              ("Kéo để di chuyển, kéo góc (hoặc Ctrl + lăn chuột, phím + −) để đổi cỡ" if pl.resizable else "Kéo để di chuyển") +
                              (", kéo núm tròn để xoay" if pl.rotatable else "") +
                              ("" if pl.commit_outside else " · Bấm vào trang khác để chuyển sang trang đó") +
                              " · Enter/nháy đúp: đặt · " +
                              ("Delete: xóa · Esc: giữ nguyên" if pl.on_delete else "Esc: hủy"))
        p.setBrush(QColor(27, 27, 27, 220))
        p.setPen(Qt.NoPen)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(tip) + 16
        vis_right = self.horizontalScrollBar().value() + self.viewport().width() - 8
        x = max(self.horizontalScrollBar().value() + 8, min(sr.left(), vis_right - tw))
        box = QRectF(x, sr.bottom() + 8 + (abs(math.sin(math.radians(pl.angle))) * sr.width() / 2), tw, fm.height() + 8)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#ffffff"))
        p.drawText(box, Qt.AlignCenter, tip)

    def _place_press(self, ev) -> bool:
        pl = self.placement
        if not pl or ev.button() != Qt.LeftButton:
            return False
        pos = ev.position()
        hit = self._placement_hit(pos)
        pl.moved = False
        if hit == "rotate":
            pl.drag = ("rotate", pos, QRectF(pl.rect), None, pl.angle)
        elif isinstance(hit, int):
            pl.drag = ("resize", pos, QRectF(pl.rect), hit, pl.angle)
        elif hit == "move":
            pl.drag = ("move", pos, QRectF(pl.rect), None, pl.angle)
        elif pl.cancel_outside:
            self.cancel_placement()
            return False
        elif pl.commit_outside:
            # sửa đối tượng: bấm ra ngoài = xong, rồi xử lý cú bấm như bình thường (chọn đối tượng khác...)
            self.commit_placement()
            return False
        else:
            # đặt mới: bấm ra ngoài -> chuyển khung sang trang/vị trí được bấm
            for i, r in enumerate(self._rects):
                if r.contains(pos):
                    s = self.scale
                    pl.page = i
                    w, hh = pl.rect.width(), pl.rect.height()
                    pl.rect = QRectF((pos.x() - r.left()) / s - w / 2, (pos.y() - r.top()) / s - hh / 2, w, hh)
                    self._clamp_placement()
                    self.canvas.update()
                    break
        return True

    def _cursor_for_corner(self, corner: int) -> Qt.CursorShape:
        diag_f = corner in (0, 3)
        a = (self.placement.angle % 180) if self.placement else 0
        if 45 <= a < 135:
            diag_f = not diag_f
        return Qt.SizeFDiagCursor if diag_f else Qt.SizeBDiagCursor

    def _place_move(self, ev):
        pl = self.placement
        if not pl:
            return
        pos = ev.position()
        if not pl.drag:
            hit = self._placement_hit(pos)
            if hit == "rotate":
                self.canvas.setCursor(Qt.PointingHandCursor)
            elif isinstance(hit, int):
                self.canvas.setCursor(self._cursor_for_corner(hit))
            elif hit == "move":
                inner = self._placement_screen_rect().adjusted(6, 6, -6, -6).contains(self._to_local(pos))
                self.canvas.setCursor(Qt.IBeamCursor if pl.on_dblclick and inner else Qt.SizeAllCursor)
            else:
                self.canvas.setCursor(Qt.ArrowCursor if pl.commit_outside else Qt.SizeAllCursor)
            return
        kind, start, orig, corner, orig_angle = pl.drag
        s = self.scale
        if math.hypot(pos.x() - start.x(), pos.y() - start.y()) > 2:
            pl.moved = True
        if not pl.moved:
            return
        dx, dy = (pos.x() - start.x()) / s, (pos.y() - start.y()) / s
        shift = bool(_mods(ev) & Qt.ShiftModifier)
        if kind == "move":
            pl.rect = orig.translated(dx, dy)
            self._snap_move()
        elif kind == "rotate":
            sr = self._placement_screen_rect()
            c = sr.center()
            ang = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())) + 90
            ang = (ang + 360) % 360
            step = 15 if shift else 0
            if step:
                ang = round(ang / step) * step
            else:
                near = round(ang / 45) * 45            # tự hít vào 0°/45°/90°... khi gần
                if abs(ang - near) < 3:
                    ang = near
            pl.angle = ang % 360
        else:
            a = math.radians(orig_angle)
            ca, sa = math.cos(a), math.sin(a)
            ldx, ldy = dx * ca + dy * sa, -dx * sa + dy * ca          # về hệ khung chưa xoay
            sx = -1 if corner in (0, 2) else 1
            sy = -1 if corner in (0, 1) else 1
            w0, h0 = orig.width(), orig.height()
            w = max(4.0, w0 + sx * ldx)
            h = max(4.0, h0 + sy * ldy)
            if pl.keep_ratio or shift:
                kw, kh = w / max(w0, 1e-6), h / max(h0, 1e-6)
                k = kw if abs(kw - 1) >= abs(kh - 1) else kh
                k = max(k, 4.0 / max(min(w0, h0), 1e-6))
                w, h = w0 * k, h0 * k
            c0 = orig.center()
            ox, oy = -sx * w0 / 2, -sy * h0 / 2                     # góc đối diện (giữ cố định)
            opp = QPointF(c0.x() + ox * ca - oy * sa, c0.y() + ox * sa + oy * ca)
            nx, ny = sx * w / 2, sy * h / 2
            c = QPointF(opp.x() + nx * ca - ny * sa, opp.y() + nx * sa + ny * ca)
            pl.rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
            if self.snap_grid > 0 and not orig_angle:
                g = self.snap_grid
                r = pl.rect
                if corner in (1, 3):
                    r.setRight(round(r.right() / g) * g)
                else:
                    r.setLeft(round(r.left() / g) * g)
                if corner in (2, 3):
                    r.setBottom(round(r.bottom() / g) * g)
                else:
                    r.setTop(round(r.top() / g) * g)
                if r.width() >= 2 and r.height() >= 2 and not (pl.keep_ratio or shift):
                    pl.rect = r
        self._clamp_placement()
        self.canvas.update()

    def _snap_move(self):
        """Bắt lưới + gióng thẳng hàng với cạnh/tâm các nội dung khác và trang khi kéo."""
        pl = self.placement
        pl.guides = []
        r = pl.rect
        if self.snap_grid > 0:
            g = self.snap_grid
            r.moveTo(round(r.left() / g) * g, round(r.top() / g) * g)
        pw, ph = self.doc.page_size_pt(pl.page)
        xs, ys = [0.0, pw / 2, pw], [0.0, ph / 2, ph]
        if self.guide_provider:
            try:
                gx, gy = self.guide_provider(pl.page)
                xs += list(gx)
                ys += list(gy)
            except Exception:
                pass
        tol = 5 / self.scale
        best = None
        for v in xs:
            for cand in (r.left(), r.center().x(), r.right()):
                d = v - cand
                if abs(d) <= tol and (best is None or abs(d) < abs(best[0])):
                    best = (d, v)
        if best:
            r.translate(best[0], 0)
            pl.guides.append(("x", best[1]))
        best = None
        for v in ys:
            for cand in (r.top(), r.center().y(), r.bottom()):
                d = v - cand
                if abs(d) <= tol and (best is None or abs(d) < abs(best[0])):
                    best = (d, v)
        if best:
            r.translate(0, best[0])
            pl.guides.append(("y", best[1]))
        pl.rect = r

    @staticmethod
    def _corner_at(sr: QRectF, pos) -> int | None:
        h = Placement.HANDLE
        for k, pt in enumerate((sr.topLeft(), sr.topRight(), sr.bottomLeft(), sr.bottomRight())):
            if abs(pos.x() - pt.x()) <= h and abs(pos.y() - pt.y()) <= h:
                return k
        return None

    def _place_release(self, ev):
        pl = self.placement
        if not pl:
            return
        drag = pl.drag
        pl.drag = None
        pl.guides = []
        if drag and drag[0] == "move" and not pl.moved and pl.on_click:
            pl.on_click(pl)
            return
        if drag and pl.moved and pl.on_change:
            pl.on_change(pl)
        self.canvas.update()

    def _clamp_placement(self):
        pl = self.placement
        pw, ph = self.doc.page_size_pt(pl.page)
        r = pl.rect
        if pl.angle:
            c = r.center()
            cx, cy = min(max(c.x(), 0), pw), min(max(c.y(), 0), ph)
            pl.rect = r.translated(cx - c.x(), cy - c.y())
            return
        if r.width() > pw or r.height() > ph:
            if pl.commit_outside:                  # sửa đối tượng: cho phép lấn lề (vd. lề ảnh xem trước)
                return
            k = min(pw / r.width(), ph / r.height())
            r = QRectF(r.left(), r.top(), r.width() * k, r.height() * k)
        if pl.commit_outside:
            c = r.center()
            cx, cy = min(max(c.x(), 0), pw), min(max(c.y(), 0), ph)
            pl.rect = r.translated(cx - c.x(), cy - c.y())
            return
        x = min(max(r.left(), 0), pw - r.width())
        y = min(max(r.top(), 0), ph - r.height())
        pl.rect = QRectF(x, y, r.width(), r.height())

    def _paint_grid(self, p: QPainter, area: QRectF):
        g = self.snap_grid * self.scale
        if g < 6:
            return
        p.save()
        p.setPen(QColor(0, 95, 184, 40))
        for r in self._rects:
            vis = r & area
            if vis.isEmpty():
                continue
            x = r.left() + math.ceil((vis.left() - r.left()) / g) * g
            while x <= vis.right():
                p.drawLine(QPointF(x, vis.top()), QPointF(x, vis.bottom()))
                x += g
            y = r.top() + math.ceil((vis.top() - r.top()) / g) * g
            while y <= vis.bottom():
                p.drawLine(QPointF(vis.left(), y), QPointF(vis.right(), y))
                y += g
        p.restore()

    # ---------- con trỏ theo ngữ cảnh ----------
    def _hover(self, ev):
        if not self.hover_provider or self._inline is not None:
            return
        hit = self.page_at(ev.position())
        kind = None
        if hit:
            try:
                kind = self.hover_provider(*hit)
            except Exception:
                kind = None
        if kind == "text" or (kind is None and hit and self.char_at(*hit) is not None):   # cả lớp chữ OCR
            self.canvas.setCursor(Qt.IBeamCursor)
        elif kind in ("item", "note", "image"):
            self.canvas.setCursor(Qt.SizeAllCursor)
        else:
            self.canvas.unsetCursor()

    # ---------- sửa chữ tại chỗ ----------
    def begin_inline_text(self, page: int, rect, text: str, family: str, size_pt: float, color: str, on_done,
                          align: str = "left", caret=None, bold: bool = False, italic: bool = False, bar=None,
                          grow_right: float | None = None):
        """Ô nhập chữ phủ đúng chỗ hộp chữ: gõ sửa trực tiếp trên trang.
        caret=(x, y) pt: đặt con trỏ nhấp nháy đúng chỗ vừa bấm (như Word) thay vì chọn hết chữ.
        on_done(chữ_mới | None). Ctrl+Enter hoặc bấm ra ngoài: xong · Esc: hủy.
        grow_right (pt): sửa 1 dòng – không tự xuống dòng, ô gõ kéo dài sang phải tới mép này khi gõ thêm."""
        from PySide6.QtWidgets import QPlainTextEdit
        self._finish_inline()
        x0, y0, x1, y1 = rect
        r = self._rects[page]
        s = self.scale
        ed = QPlainTextEdit(self.canvas)
        ed.setFrameStyle(0)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.document().setDocumentMargin(0)
        ed.setPlainText(text)
        w = max(40.0, (x1 - x0) * s) + 4
        ed.setGeometry(int(r.left() + x0 * s) - 2, int(r.top() + y0 * s) - 2, int(w), int(max(20, (y1 - y0) * s) + 6))

        if grow_right is not None:
            ed.setLineWrapMode(QPlainTextEdit.NoWrap)
        w_min = int(w)
        w_max = int(max(w, (float(grow_right) - x0) * s + 4)) if grow_right is not None else int(w)

        def grow():
            if grow_right is not None:              # 1 dòng: kéo dài sang phải, giữ nguyên cỡ chữ
                fm = ed.fontMetrics()
                need = max(fm.horizontalAdvance(t) for t in (ed.toPlainText().split("\n") or [""])) + 8
                ed.setFixedWidth(int(min(max(w_min, need), max(w_min, w_max + 40))))
            doc_h = ed.document().size().height() * ed.fontMetrics().lineSpacing() + 8
            ed.setFixedHeight(int(max(doc_h, 20)))
            self._place_inline_bar()
        ed.textChanged.connect(grow)
        ed._grow = grow
        ed._style = {"family": family, "size": size_pt, "color": color, "bold": bool(bold), "italic": bool(italic),
                     "align": align}
        self._apply_inline_style(ed)
        ed.installEventFilter(self)
        ed.show()
        QTimer.singleShot(0, grow)                  # sau khi hiện mới tính đúng số dòng tự xuống
        ed.setFocus()
        if caret is not None:
            cx = (float(caret[0]) - x0) * s + 2
            cy = (float(caret[1]) - y0) * s + 2
            cur = ed.cursorForPosition(QPoint(int(max(0, cx)), int(max(0, cy))))
            ed.setTextCursor(cur)
            ed.ensureCursorVisible()
        else:
            ed.selectAll()
        self._inline = (ed, on_done)
        self._inline_bar = bar
        if bar is not None:                         # thanh định dạng nổi ngay trên ô gõ (như Word)
            bar.setParent(self.canvas)
            bar.adjustSize()
            bar.show()
            bar.raise_()
            self._place_inline_bar()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().focusChanged.connect(self._inline_focus_changed)

    def _place_inline_bar(self):
        bar = getattr(self, "_inline_bar", None)
        if bar is None or self._inline is None:
            return
        ed = self._inline[0]
        g = ed.geometry()
        vis_top = self.verticalScrollBar().value()
        vis_left = self.horizontalScrollBar().value()
        vw = self.viewport().width()
        y = g.top() - bar.height() - 6
        if y < vis_top + 2:                          # sát mép trên màn hình: đặt bên dưới ô gõ
            y = g.bottom() + 6
        x = min(max(g.left(), vis_left + 4), vis_left + max(4, vw - bar.width() - 4))
        bar.move(int(x), int(y))

    def _apply_inline_style(self, ed):
        from PySide6.QtGui import QFont
        st = ed._style
        px = max(4, int(round(float(st["size"]) * self.scale)))
        f = QFont(st["family"])
        f.setPixelSize(px)
        f.setBold(bool(st["bold"]))
        f.setItalic(bool(st["italic"]))
        ed.setFont(f)
        # stylesheet chung của phần mềm đặt cỡ chữ cho ô nhập -> ghi rõ phông, cỡ để khớp chữ trên trang
        ed.setStyleSheet(f"QPlainTextEdit{{background:rgba(255,255,255,235);color:{st['color']};"
                         f"font-family:'{st['family']}';font-size:{px}px;"
                         f"font-weight:{'bold' if st['bold'] else 'normal'};"
                         f"font-style:{'italic' if st['italic'] else 'normal'};"
                         f"border:1px dashed #005fb8;padding:0px}}")
        opt = ed.document().defaultTextOption()
        opt.setAlignment({"center": Qt.AlignHCenter, "right": Qt.AlignRight}.get(st.get("align") or "left",
                                                                                   Qt.AlignLeft))
        ed.document().setDefaultTextOption(opt)
        ed._grow()

    def restyle_inline(self, **kw):
        """Đổi phông / cỡ / màu / đậm / nghiêng / canh lề của ô sửa chữ đang mở (xem ngay khi chỉnh bảng bên phải).
        Bỏ qua giá trị None."""
        if self._inline is None:
            return
        ed = self._inline[0]
        ed._style.update({k: v for k, v in kw.items() if v is not None and k in ed._style})
        self._apply_inline_style(ed)

    def _keeps_inline(self, w) -> bool:
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return True                               # bảng chọn màu, danh sách thả xuống... đang mở
        keep = self.inline_keep
        bar = getattr(self, "_inline_bar", None)
        while w is not None:                          # đi ngược lên cả qua cửa sổ con (popup của ô chọn)
            if self._inline is not None and w is self._inline[0]:
                return True
            if bar is not None and w is bar:
                return True
            if keep is not None and keep(w):
                return True
            w = w.parentWidget()
        return False

    def _inline_focus_changed(self, old, new):
        if self._inline is None:
            return
        if new is None:                               # chuyển sang ứng dụng khác: giữ nguyên
            return
        if self._keeps_inline(new):
            return
        QTimer.singleShot(0, self._inline_focus_check)

    def _inline_focus_check(self):
        """Ô sửa chữ mất tiêu điểm hẳn ra ngoài (không phải sang bảng tùy chọn) -> xong."""
        from PySide6.QtWidgets import QApplication
        if self._inline is None:
            return
        fw = QApplication.focusWidget()
        if fw is None or self._keeps_inline(fw):
            return
        self._finish_inline(True)

    def _finish_inline(self, commit: bool = True):
        if self._inline is None:
            return
        ed, cb = self._inline
        self._inline = None
        from PySide6.QtWidgets import QApplication
        try:
            QApplication.instance().focusChanged.disconnect(self._inline_focus_changed)
        except (RuntimeError, TypeError):
            pass
        text = ed.toPlainText()
        ed.removeEventFilter(self)
        ed.hide()
        ed.deleteLater()
        bar = getattr(self, "_inline_bar", None)
        self._inline_bar = None
        if bar is not None:
            bar.hide()
            bar.deleteLater()
        self.setFocus()
        cb(text if commit else None)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        inl = getattr(self, "_inline", None)
        if inl is not None and obj is inl[0]:
            if ev.type() == QEvent.KeyPress:
                if ev.key() == Qt.Key_Escape:
                    self._finish_inline(False)
                    return True
                if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and _mods(ev) & Qt.ControlModifier:
                    self._finish_inline(True)
                    return True
                bar = getattr(self, "_inline_bar", None)
                if bar is not None and _mods(ev) & Qt.ControlModifier and ev.key() in (Qt.Key_B, Qt.Key_I):
                    b = bar.btn_bold if ev.key() == Qt.Key_B else bar.btn_italic
                    if b.isEnabled():
                        b.toggle()
                    return True
        return super().eventFilter(obj, ev)

    # ---------- khung ghi chú nổi (mũi tên trỏ vào chỗ ghi chú) ----------
    def show_callout(self, w, page: int, anchor_pt, on_outside=None):
        """Hiện khung w ngay trên trang, mũi tên trỏ vào anchor_pt (x, y pt). on_outside(): bấm ra ngoài khung."""
        self.close_callout()
        self._finish_inline()
        w.setParent(self.canvas)
        self._callout = (w, page, (float(anchor_pt[0]), float(anchor_pt[1])), on_outside)
        w.adjustSize()
        w.show()
        w.raise_()
        self._place_callout()
        self.ensureWidgetVisible(w, 8, 8)
        self._place_callout()

    def callout(self):
        return self._callout[0] if self._callout else None

    def close_callout(self):
        c = self._callout
        self._callout = None
        if c is not None:
            c[0].hide()
            c[0].deleteLater()
            self.setFocus()

    def callout_outside(self) -> bool:
        """Bấm ra ngoài khung ghi chú. True nếu có khung đang mở (đã xử lý cú bấm)."""
        c = self._callout
        if c is None:
            return False
        if c[3] is not None:
            c[3]()
        if self._callout is c:
            self.close_callout()
        return True

    def _place_callout(self):
        c = self._callout
        if c is None or c[1] >= len(self._rects):
            return
        from .note_callout import TAIL
        w, page, (ax, ay), _ = c
        r = self._rects[page]
        s = self.scale
        px, py = r.left() + ax * s, r.top() + ay * s
        w.adjustSize()
        ww, wh = w.width(), w.height()
        vis_l, vis_t = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        vis_r = vis_l + self.viewport().width()
        if px + ww <= vis_r - 4 or px - ww < vis_l + 4:
            side = "left"                                # khung bên phải chỗ trỏ (mũi tên bên trái)
        else:
            side = "right"
        x = px - 3 if side == "left" else px - ww + 3
        vis_b = vis_t + self.viewport().height()
        y = py - 28
        if y + wh > vis_b - 4:                           # gần mép dưới màn hình: đẩy khung lên
            y = vis_b - 4 - wh
        if y < vis_t + 4:
            y = vis_t + 4
        y = min(max(y, py - wh + 22), py - 22)            # mũi tên luôn nằm trong cạnh khung
        y = min(max(y, 0), max(0, self.canvas.height() - wh))
        w.set_side(side, py - y)
        w.move(int(round(x)), int(round(y)))
        w.raise_()

    # ---------- công cụ vẽ / ghi chú ----------
    def set_tool(self, tool: "Tool | None"):
        self._finish_inline()
        if self._callout is not None:
            self.callout_outside()
        self.tool = tool
        self._mag = None
        if tool:
            self.canvas.setCursor(Qt.IBeamCursor if tool.kind == "edittext" else Qt.CrossCursor)
            self.setFocus()
        else:
            self.canvas.unsetCursor()
        self.canvas.update()
        self.toolChanged.emit(tool.kind if tool else "")

    def _is_free(self, t) -> bool:
        return t.kind in FREE_TOOLS or (t.kind == "erase" and t.erase_shape in ("lasso", "brush"))

    def _snap_pt(self, x, y):
        g = self.snap_grid
        if g > 0:
            return round(x / g) * g, round(y / g) * g
        return x, y

    def _tool_press(self, ev):
        import time
        t = self.tool
        hit = self.page_at(ev.position())
        if not hit:
            return
        i, x, y = hit
        if t.kind in CLICK_TOOLS:
            if not t.sticky:
                self.set_tool(None)
            t.on_done(i, (x, y))
            return
        if t.kind in POLY_TOOLS:
            x, y = self._snap_pt(x, y)
            if t.page is None or t.page != i:
                t.page, t.points = i, [(x, y)]
            else:
                if _mods(ev) & Qt.ShiftModifier and t.points:
                    x, y = self._constrain_line(t.points[-1], (x, y))
                t.points.append((x, y))
            t.cur = (x, y)
            self.canvas.update()
            return
        if not self._is_free(t):
            x, y = self._snap_pt(x, y)
        t.page, t.start, t.cur = i, (x, y), (x, y)
        t.points = [(x, y)]
        t.samples = [(x, y, time.monotonic(), self._pressure)]
        self.canvas.update()

    def _tool_pos(self, ev):
        t = self.tool
        r = self._rects[t.page]
        s = self.scale
        pw, ph = self.doc.page_size_pt(t.page)
        x = min(max((ev.position().x() - r.left()) / s, 0), pw)
        y = min(max((ev.position().y() - r.top()) / s, 0), ph)
        return x, y

    @staticmethod
    def _constrain_line(a, b):
        """Giữ Shift: đường thẳng bắt về bội số 45°."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        return a[0] + L * math.cos(ang), a[1] + L * math.sin(ang)

    @staticmethod
    def _constrain_box(a, b):
        """Giữ Shift: hình vuông / tròn."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        m = max(abs(dx), abs(dy))
        return a[0] + math.copysign(m, dx or 1), a[1] + math.copysign(m, dy or 1)

    def _is_line_tool(self, t) -> bool:
        return t.kind in ("line", "arrow") or (t.kind == "shape" and t.shape in LINE_KINDS)

    def _constrained(self, t, cur, ev):
        if not (_mods(ev) & Qt.ShiftModifier) or t.start is None:
            return cur
        if self._is_line_tool(t):
            return self._constrain_line(t.start, cur)
        if t.kind in ("rect", "ellipse", "shape", "erase", "highlight"):
            return self._constrain_box(t.start, cur)
        return cur

    def _tool_move(self, ev):
        import time
        t = self.tool
        if t.kind in POLY_TOOLS:
            if t.page is not None:
                cur = self._tool_pos(ev)
                if _mods(ev) & Qt.ShiftModifier and t.points:
                    cur = self._constrain_line(t.points[-1], cur)
                t.cur = self._snap_pt(*cur)
                self.canvas.update()
            return
        if t.page is None:
            return
        cur = self._tool_pos(ev)
        if self._is_free(t):
            t.cur = cur
            if t.kind == "ink" and _mods(ev) & Qt.ShiftModifier:          # 15d: giữ Shift -> kẻ thẳng
                a = self._constrain_line(t.points[0], cur) if _mods(ev) & Qt.AltModifier else cur
                t.points = [t.points[0], a]
                t.samples = [t.samples[0], (a[0], a[1], time.monotonic(), self._pressure)]
            elif math.hypot(cur[0] - t.points[-1][0], cur[1] - t.points[-1][1]) >= 0.6:
                t.points.append(cur)
                t.samples.append((cur[0], cur[1], time.monotonic(), self._pressure))
        else:
            t.cur = self._constrained(t, self._snap_pt(*cur), ev)
        if t.kind == "erase" and t.magnifier:
            self._mag = (t.page, cur[0], cur[1])
        self.canvas.update()

    def _tool_release(self, ev):
        t = self.tool
        if t.kind in POLY_TOOLS or t.page is None:
            return
        page, (x0, y0) = t.page, t.start
        if self._is_free(t):
            x1, y1 = self._tool_pos(ev)
            if t.kind == "ink" and _mods(ev) & Qt.ShiftModifier and len(t.points) == 2:
                x1, y1 = t.points[1]
        else:
            x1, y1 = self._constrained(t, self._snap_pt(*self._tool_pos(ev)), ev)
        pts = t.points + [(x1, y1)]
        t.last_samples = list(t.samples)
        t.page = t.start = t.cur = None
        t.points = []
        t.samples = []
        self._mag = None
        self.canvas.update()
        if self._is_free(t):
            if not t.sticky:
                self.set_tool(None)
            t.on_done(page, pts)
            return
        if abs(x1 - x0) < 2 and abs(y1 - y0) < 2:
            if t.kind in ("textbox", "handarea"):                     # bấm (không kéo): khung mặc định
                x1, y1 = x0 + 200, y0 + 40
            elif t.kind == "shape" and not self._is_line_tool(t):      # bấm: hình mặc định 80×60
                x1, y1 = x0 + 80, y0 + 60
            else:
                return
        rect = (x0, y0, x1, y1) if self._is_line_tool(t) else \
            (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if not t.sticky:
            self.set_tool(None)
        t.on_done(page, rect)

    def _poly_finish(self):
        t = self.tool
        if not t or t.kind not in POLY_TOOLS or t.page is None:
            return
        pts = []
        for p in t.points:
            if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 0.5:
                pts.append(p)
        page = t.page
        t.page, t.points, t.cur = None, [], None
        self.canvas.update()
        if len(pts) >= 2:
            if not t.sticky:
                self.set_tool(None)
            t.on_done(page, pts)

    def _paint_tool(self, p: QPainter):
        from PySide6.QtGui import QPainterPath, QPen
        t = self.tool
        if t.page is None:
            return
        r = self._rects[t.page]
        s = self.scale

        def sp(pt):
            return QPointF(r.left() + pt[0] * s, r.top() + pt[1] * s)
        p.setRenderHint(QPainter.Antialiasing)
        red = QColor(229, 57, 53)
        if t.kind == "erase":
            fill = QColor(229, 57, 53, 70)
            p.setPen(QPen(red, 1.2, Qt.DashLine))
            if t.erase_shape == "brush":
                path = QPainterPath(sp(t.points[0]))
                for pt in t.points[1:]:
                    path.lineTo(sp(pt))
                p.setPen(QPen(fill, max(2.0, t.size * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)
            elif t.erase_shape == "lasso":
                path = QPainterPath(sp(t.points[0]))
                for pt in t.points[1:]:
                    path.lineTo(sp(pt))
                path.closeSubpath()
                p.setBrush(fill)
                p.drawPath(path)
            else:
                rect = QRectF(sp(t.start), sp(t.cur)).normalized()
                p.setBrush(fill)
                if t.erase_shape == "ellipse":
                    p.drawEllipse(rect)
                else:
                    p.drawRect(rect)
            if self._mag:
                self._paint_magnifier(p)
            return
        color = QColor("#005fb8" if t.kind in ("textbox", "handarea", "scanedit") else t.color)
        pen = QPen(color, max(1.0, t.width * s), Qt.SolidLine if t.kind not in ("textbox", "handarea", "scanedit")
                   else Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if t.kind in POLY_TOOLS:
            pts = t.points + ([t.cur] if t.cur else [])
            path = QPainterPath(sp(pts[0]))
            for pt in pts[1:]:
                path.lineTo(sp(pt))
            if t.kind == "polygon" and len(pts) > 2:
                path.closeSubpath()
            p.drawPath(path)
            return
        if t.kind == "inkerase":
            path = QPainterPath(sp(t.points[0]))
            for pt in t.points[1:]:
                path.lineTo(sp(pt))
            p.setPen(QPen(QColor(229, 57, 53, 90), max(2.0, t.size * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            return
        if t.kind in FREE_TOOLS:
            path = QPainterPath(sp(t.points[0]))
            for pt in t.points[1:]:
                path.lineTo(sp(pt))
            if getattr(t, "pen", "") == "highlighter":
                c = QColor(color)
                c.setAlpha(110)
                pen.setColor(c)
                pen.setCapStyle(Qt.SquareCap)
                p.setPen(pen)
            p.drawPath(path)
            return
        a, b = sp(t.start), sp(t.cur)
        rect = QRectF(a, b).normalized()
        if t.kind == "shape":
            self._paint_shape_preview(p, t, a, b, rect, pen)
        elif t.kind in ("line", "arrow"):
            p.drawLine(a, b)
        elif t.kind in ("ellipse", "circle"):
            p.drawEllipse(rect)
        elif t.kind == "highlight":
            p.fillRect(rect, QColor(255, 230, 0, 110))
        else:
            p.drawRect(rect)

    def _paint_shape_preview(self, p, t, a, b, rect, pen):
        from PySide6.QtGui import QPainterPath
        from . import items
        if t.shape in LINE_KINDS:
            if t.shape in ("curve", "carrow"):
                c1, c2 = items.curve_ctrl((a.x(), a.y()), (b.x(), b.y()))
                path = QPainterPath(a)
                path.cubicTo(QPointF(*c1), QPointF(*c2), b)
                p.drawPath(path)
            else:
                p.drawLine(a, b)
            return
        try:
            subs = items.shape_paths(t.shape if t.shape != "freeform" else "rect", max(rect.width(), 1),
                                     max(rect.height(), 1))
        except ValueError:
            p.drawRect(rect)
            return
        path = QPainterPath()
        ox, oy = rect.left(), rect.top()
        for sub in subs:
            for seg in sub:
                if seg[0] == "M":
                    path.moveTo(ox + seg[1][0], oy + seg[1][1])
                elif seg[0] == "L":
                    path.lineTo(ox + seg[1][0], oy + seg[1][1])
                elif seg[0] == "C":
                    path.cubicTo(ox + seg[1][0], oy + seg[1][1], ox + seg[2][0], oy + seg[2][1],
                                 ox + seg[3][0], oy + seg[3][1])
                elif seg[0] == "Z":
                    path.closeSubpath()
        if getattr(t, "fill", None):
            c = QColor(t.fill)
            c.setAlpha(90)
            p.setBrush(c)
        p.drawPath(path)

    def _paint_magnifier(self, p: QPainter):
        """Kính lúp 3× quanh con trỏ khi kéo vùng tẩy: thấy rõ mép chữ để khoanh chính xác."""
        from PySide6.QtGui import QPainterPath, QPen
        i, x, y = self._mag
        r = self._rects[i]
        s = self.scale
        pw, ph = self.doc.page_size_pt(i)
        half = 60 / (s * 3)                                   # nửa cạnh vùng phóng (pt)
        key = (self.doc.version, i, round(x, 1), round(y, 1), round(s, 3))
        img = getattr(self, "_mag_img", (None, None))
        if img[0] != key:
            crop = (max(0.0, x - half), max(0.0, ph - (y + half)), max(0.0, pw - (x + half)), max(0.0, y - half))
            try:
                q = to_qimage(self.doc.render(i, s * 3, crop=crop))
            except Exception:
                return
            self._mag_img = (key, q, crop)
        _, q, crop = self._mag_img
        c = QPointF(r.left() + x * s + 90, r.top() + y * s - 90)
        rad = 60
        box = QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)
        src_x0 = x - half if x - half > 0 else 0
        src_y0 = y - half if y - half > 0 else 0
        ox = (src_x0 - (x - half)) * s * 3
        oy = (src_y0 - (y - half)) * s * 3
        clip = QPainterPath()
        clip.addEllipse(box)
        p.save()
        p.setClipPath(clip)
        p.fillRect(box, Qt.white)
        p.drawImage(QPointF(box.left() + ox, box.top() + oy), q)
        p.setPen(QPen(QColor(229, 57, 53), 1))
        p.drawLine(QPointF(c.x() - 8, c.y()), QPointF(c.x() + 8, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 8), QPointF(c.x(), c.y() + 8))
        p.restore()
        p.setPen(QPen(QColor("#005fb8"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(box)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.text_sel and not self.placement and not self.tool:
            self.clear_text_selection()
            return
        if _mods(ev) & Qt.ControlModifier and self._inline is None and ev.key() == Qt.Key_A \
                and not self.placement and not self.tool:
            if self.select_page_text(self.current_page()):
                self.textSelected.emit()
            return
        if _mods(ev) & Qt.ControlModifier and self._inline is None:
            act = {Qt.Key_C: "copy", Qt.Key_X: "cut", Qt.Key_V: "paste", Qt.Key_D: "dup"}.get(ev.key())
            if act:
                self.clipboardAction.emit(act)
                return
        t = self.tool
        if t and t.kind in POLY_TOOLS and not self.placement:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._poly_finish()
                return
            if ev.key() == Qt.Key_Escape and t.page is not None:
                t.page, t.points, t.cur = None, [], None
                self.canvas.update()
                return
            if ev.key() == Qt.Key_Backspace and len(t.points) > 1:
                t.points.pop()
                self.canvas.update()
                return
        if self.tool and not self.placement and ev.key() == Qt.Key_Escape:
            self.set_tool(None)
            return
        if self.placement:
            if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.placement.on_delete:
                self.delete_placement()
                return
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.commit_placement()
                return
            if ev.key() == Qt.Key_Escape:
                self.cancel_placement()
                return
            if ev.key() in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus) and not (_mods(ev) & Qt.ControlModifier):
                self.scale_placement(1.05 if ev.key() != Qt.Key_Minus else 1 / 1.05)   # + / −: đổi cỡ ảnh
                return
            step = 10 if _mods(ev) & Qt.ShiftModifier else 1
            d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
            if ev.key() in d:
                self.placement.rect.translate(*d[ev.key()])
                self._clamp_placement()
                if self.placement.on_change:
                    self.placement.on_change(self.placement)
                self.canvas.update()
                return
        super().keyPressEvent(ev)
