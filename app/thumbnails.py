"""Cột ảnh thu nhỏ các trang. Render dần từng ít một khi rảnh -> không làm đơ giao diện."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

from .document import PdfDocument
from .viewer import to_qimage

THUMB_W = 112
MIN_W, MAX_W, PAD = 56, 420, 56
BATCH = 4          # số trang render mỗi lượt


class ThumbnailList(QListWidget):
    pageClicked = Signal(int)
    pagesMoved = Signal(list, int)      # (các trang, vị trí đích sau khi lấy ra)
    menuRequested = Signal(QPoint)
    rotateRequested = Signal(int, int)  # (trang, góc) – nút ⟲ ⟳ hiện khi di chuột lên ảnh trang
    deleteRequested = Signal()          # phím Delete
    filesDropped = Signal(list, int)    # 17e: kéo file từ thư mục vào cột ảnh -> (đường dẫn, vị trí chèn)

    def __init__(self, doc: PdfDocument):
        super().__init__()
        self.setObjectName("thumbs")
        self.doc = doc
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.thumb_w = THUMB_W                    # 1.0.22: cột kéo rộng / hẹp được -> ảnh to nhỏ theo
        self.setIconSize(QSize(self.thumb_w, int(self.thumb_w * 1.42)))
        self.setSpacing(4)
        self.setMinimumWidth(MIN_W + PAD)
        self.setMaximumWidth(MAX_W + PAD)
        self._resize_timer = QTimer(self, singleShot=True, interval=150, timeout=self._apply_width)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)   # kéo thả để sắp xếp trang
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menuRequested.emit(self.mapToGlobal(pos)))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self._done: set[int] = set()
        self._hover = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._version = -1
        self._timer = QTimer(self, interval=0, timeout=self._render_some)
        self.itemClicked.connect(lambda it: self.pageClicked.emit(self.row(it)))
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._timer.start())
        self.rebuild()

    def sizeHint(self):
        return QSize(self.thumb_w + PAD, 400)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if abs((self.width() - PAD) - self.thumb_w) > 3:
            self._resize_timer.start()

    def _apply_width(self):
        """Đổi cỡ ảnh thu nhỏ theo bề ngang cột (kéo vạch ngăn giữa cột ảnh và trang)."""
        w = max(MIN_W, min(MAX_W, self.width() - PAD))
        if w == self.thumb_w:
            return
        self.thumb_w = w
        self.setIconSize(QSize(w, int(w * 1.42)))
        for i in range(self.count()):
            self.item(i).setIcon(self._placeholder(i))
        self._done.clear()
        self._timer.start()

    def _placeholder(self, i: int) -> QIcon:
        w, h = self.doc.page_size_pt(i)
        tw = self.thumb_w
        th = int(tw * h / w) if w else tw
        pm = QPixmap(tw, max(th, 20))
        pm.fill(QColor("#ffffff"))
        return QIcon(pm)

    def rebuild(self):
        """Dựng lại danh sách (sau khi thêm/xóa/xoay trang)."""
        cur = self.currentRow()
        self.blockSignals(True)
        self.clear()
        for i in range(self.doc.page_count):
            it = QListWidgetItem(self._placeholder(i), str(i + 1))
            it.setTextAlignment(Qt.AlignHCenter)
            self.addItem(it)
        self.blockSignals(False)
        self._done.clear()
        self._version = self.doc.version
        if 0 <= cur < self.count():
            self.setCurrentRow(cur)
        self._timer.start()

    def _visible_rows(self) -> list[int]:
        if not self.count():
            return []
        vp = self.viewport().rect()
        x = vp.center().x()
        top = self.indexAt(QPoint(x, 4)).row()
        bottom = self.indexAt(QPoint(x, vp.height() - 4)).row()
        top = 0 if top < 0 else top
        bottom = self.count() - 1 if bottom < 0 else bottom
        return list(range(top, bottom + 1))

    def _render_some(self):
        if self._version != self.doc.version:
            self.rebuild()
            return
        todo = [i for i in self._visible_rows() if i not in self._done]
        if not todo:  # rảnh thì render trước các trang kế tiếp
            todo = [i for i in range(self.count()) if i not in self._done][:BATCH]
        if not todo:
            self._timer.stop()
            return
        dpr = self.devicePixelRatioF()
        for i in todo[:BATCH]:
            w, _ = self.doc.page_size_pt(i)
            img = to_qimage(self.doc.render(i, self.thumb_w * dpr / w))
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            framed = QPixmap(pm.size())
            framed.setDevicePixelRatio(dpr)
            framed.fill(Qt.transparent)
            p = QPainter(framed)
            p.drawPixmap(0, 0, pm)
            p.setPen(QColor(0, 0, 0, 50))
            p.drawRect(0, 0, int(pm.width() / dpr) - 1, int(pm.height() / dpr) - 1)
            p.end()
            self.item(i).setIcon(QIcon(framed))
            self._done.add(i)

    # ---------- nút xoay nhanh khi di chuột, phím Delete ----------
    BTN = 22

    def _rot_buttons(self, row: int):
        """Hai nút tròn ở đỉnh ảnh trang: ⟲ (trái 90°) và ⟳ (phải 90°)."""
        from PySide6.QtCore import QRect
        r = self.visualRect(self.model().index(row, 0))
        b = self.BTN
        y = r.top() + 6
        cx = r.center().x()
        return QRect(cx - b - 3, y, b, b), QRect(cx + 3, y, b, b)

    def mouseMoveEvent(self, ev):
        idx = self.indexAt(ev.position().toPoint())
        row = idx.row() if idx.isValid() else -1
        if row != self._hover:
            self._hover = row
            self.viewport().update()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._hover >= 0:
            left, right = self._rot_buttons(self._hover)
            p = ev.position().toPoint()
            if left.contains(p) or right.contains(p):
                self.rotateRequested.emit(self._hover, 270 if left.contains(p) else 90)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if 0 <= self._hover < self.count():
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.Antialiasing)
            for rect, sym, tip in zip(self._rot_buttons(self._hover), ("⟲", "⟳"), ("trái", "phải")):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(22, 32, 58, 215))
                p.drawEllipse(rect)
                p.setPen(QColor("#ffffff"))
                f = p.font()
                f.setPixelSize(14)
                f.setBold(True)
                p.setFont(f)
                p.drawText(rect, Qt.AlignCenter, sym)
            p.end()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Delete and self.selectedItems():
            self.deleteRequested.emit()
            return
        super().keyPressEvent(ev)

    def _external(self, ev) -> bool:
        return ev.source() is not self and ev.mimeData().hasUrls()

    def dragEnterEvent(self, ev):
        if self._external(ev):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if self._external(ev):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        """Không để Qt tự đổi thứ tự: tính vị trí đích rồi báo cho tài liệu xử lý (có hoàn tác)."""
        if self._external(ev):
            idx = self.indexAt(ev.position().toPoint())
            target = self.count()
            if idx.isValid():
                target = idx.row() + (1 if ev.position().y() > self.visualRect(idx).center().y() else 0)
            paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.toLocalFile()]
            ev.acceptProposedAction()
            if paths:
                self.filesDropped.emit(paths, target)
            return
        rows = self.selected_pages()
        idx = self.indexAt(ev.position().toPoint())
        if idx.isValid():
            target = idx.row()
            rect = self.visualRect(idx)
            if ev.position().y() > rect.center().y():
                target += 1
        else:
            target = self.count()
        ev.ignore()
        before = sum(1 for r in rows if r < target)
        dest = target - before
        if rows and not (rows == list(range(dest, dest + len(rows)))):
            self.pagesMoved.emit(rows, dest)

    def select_page(self, i: int):
        if 0 <= i < self.count() and self.currentRow() != i:
            self.blockSignals(True)
            self.setCurrentRow(i)
            self.blockSignals(False)
            self.scrollToItem(self.item(i))

    def selected_pages(self) -> list[int]:
        rows = sorted(self.row(it) for it in self.selectedItems())
        return rows or ([self.currentRow()] if self.currentRow() >= 0 else [])
