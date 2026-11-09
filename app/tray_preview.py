"""Khay ghép: màn hình xem trước file trong khay – ảnh các trang (cuộn được, có số trang), tích giữ / bỏ từng trang,
nháy đúp để xem lớn từng trang (lật trang, phóng to, giữ/bỏ ngay trong cửa sổ xem)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout)

from .document import PasswordRequired, PdfDocument, parse_ranges
from .viewer import to_qimage

CACHE_W = 300                    # ảnh nền của mọi trang (vẽ một lần); cỡ lớn hơn -> vẽ lại nét cho trang đang xem
MAX_PAGES = 1000
MIN_W, MAX_W = 80, 1600          # cỡ ảnh trang (điểm ảnh) trên thanh Cỡ
HIRES_KEEP = 40                  # số trang giữ ảnh nét ở cỡ lớn (trang đang xem + lân cận) -> không tốn bộ nhớ


def _open(item) -> PdfDocument:
    return PdfDocument(item.path, password=item.password)


def dropped_overlay(img: QImage) -> QImage:
    """Trang bị bỏ: làm mờ + dấu ✕ đỏ + chữ BỎ."""
    out = img.convertToFormat(QImage.Format_ARGB32)
    p = QPainter(out)
    p.fillRect(out.rect(), QColor(255, 255, 255, 170))
    pen = QPen(QColor("#B8322A"))
    pen.setWidth(max(3, out.width() // 40))
    p.setPen(pen)
    m = out.width() // 6
    p.drawLine(m, m, out.width() - m, out.height() - m)
    p.drawLine(out.width() - m, m, m, out.height() - m)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(12, out.width() // 7))
    p.setFont(f)
    r = out.rect().adjusted(0, 0, 0, -out.height() // 12)
    p.drawText(r, Qt.AlignHCenter | Qt.AlignBottom, "BỎ")
    p.end()
    return out


def color_badge(img: QImage, text: str) -> QImage:
    """Nhãn nhỏ góc trên-phải ảnh trang: chế độ màu riêng của trang (Xám / ĐT / Chữ đen)."""
    out = img.convertToFormat(QImage.Format_ARGB32)
    p = QPainter(out)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(10, out.width() // 11))
    p.setFont(f)
    fm = p.fontMetrics()
    w, h = fm.horizontalAdvance(text) + 10, fm.height() + 4
    p.fillRect(out.width() - w - 4, 4, w, h, QColor(27, 27, 27, 200))
    p.setPen(QColor("#ffffff"))
    p.drawText(out.width() - w - 4, 4, w, h, Qt.AlignCenter, text)
    p.end()
    return out


class TrayPreview(QFrame):
    """Bảng xem trước bên phải khay ghép. Phát `changed` khi người dùng đổi trang giữ/bỏ,
    `colorsChanged` khi đổi màu riêng từng trang (Màu / Chữ đen / Xám / Đen trắng)."""
    changed = Signal()
    colorsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, objectName="card")
        self.item = None
        self.out_start = None                     # trang đầu của file này trong file ghép (để ghi "→ trang x")
        self._cache: dict[int, QImage] = {}
        self._hires: dict[int, QImage] = {}       # ảnh nét theo cỡ đang xem (chỉ vài chục trang gần chỗ xem)
        self._hi_queue: list[int] = []
        self._queue: list[int] = []
        self._doc = None
        self._conv: dict = {}                     # chế độ -> PdfDocument đã chuyển màu (xem trước đúng như khi ghép)
        self.default_color = "color"
        self._ref_px = 794.0                      # bề rộng trang đầu ở 100% (96 dpi) – để hiện phần trăm
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        self.title = QLabel("Xem trước", objectName="h")
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.info = QLabel("Bấm một file trong khay để xem trước các trang.", objectName="lbl", wordWrap=True)
        v.addWidget(self.info)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.quick_buttons = {}
        for text, key, tip in (("Tất cả", "all", "Giữ tất cả các trang"), ("Lẻ", "lẻ", "Chỉ giữ trang lẻ"),
                               ("Chẵn", "chẵn", "Chỉ giữ trang chẵn"), ("Đảo", "invert", "Đảo: trang giữ thành bỏ và ngược lại"),
                               ("Bỏ hết", "", "Bỏ tất cả các trang")):
            b = QToolButton(text=text, toolTip=tip)
            b.clicked.connect(lambda _=False, k=key: self.quick(k))
            row.addWidget(b)
            self.quick_buttons[key] = b
        row.addStretch()
        v.addLayout(row)
        from .colormode import MODE_TIP, MODES
        crow = QHBoxLayout()
        crow.setSpacing(4)
        crow.addWidget(QLabel("Màu trang:", objectName="lbl"))
        self.color_buttons = {}
        for key, text in MODES:
            b = QToolButton(text=text, toolTip=MODE_TIP[key] + " – cho các trang đang chọn (chưa chọn: cả file)")
            b.clicked.connect(lambda _=False, k=key: self.set_color_selected(k))
            crow.addWidget(b)
            self.color_buttons[key] = b
        crow.addStretch()
        v.addLayout(crow)
        zrow = QHBoxLayout()
        zrow.setSpacing(6)
        self.btn_fit = QToolButton(text="Vừa khung", checkable=True)
        self.btn_fit.setToolTip("Mỗi hàng một trang, giãn đúng bề rộng ô xem trước")
        self.btn_fit.toggled.connect(self._fit_toggled)
        zrow.addWidget(self.btn_fit)
        zrow.addWidget(QLabel("Cỡ:", objectName="lbl"))
        self.size_slider = QSlider(Qt.Horizontal, minimum=MIN_W, maximum=MAX_W, value=160)
        self.size_slider.setToolTip("Cỡ ảnh trang (Ctrl + lăn chuột trong ô để phóng to / thu nhỏ)")
        self.size_slider.valueChanged.connect(self._slider_moved)
        zrow.addWidget(self.size_slider, 1)
        self.lbl_zoom = QLabel("", objectName="lbl")
        self.lbl_zoom.setMinimumWidth(44)
        zrow.addWidget(self.lbl_zoom)
        v.addLayout(zrow)
        self.picker = QListWidget(objectName="trayprev")
        self.picker.setViewMode(QListView.IconMode)
        self.picker.setFlow(QListView.LeftToRight)
        self.picker.setWrapping(True)
        self.picker.setResizeMode(QListView.Adjust)
        self.picker.setMovement(QListView.Static)
        self.picker.setUniformItemSizes(True)
        self.picker.setSpacing(6)
        self.picker.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.picker.setSelectionMode(QListWidget.ExtendedSelection)
        self.picker.setContextMenuPolicy(Qt.CustomContextMenu)
        self.picker.customContextMenuRequested.connect(self._menu)
        self.picker.itemChanged.connect(self._item_changed)
        self.picker.itemDoubleClicked.connect(lambda it: self.open_large(self.picker.row(it)))
        v.addWidget(self.picker, 1)
        self.picker.viewport().installEventFilter(self)
        self.picker.verticalScrollBar().valueChanged.connect(lambda *_: self._queue_hires())
        self.status = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.status)
        sc = QShortcut(QKeySequence(Qt.Key_Space), self.picker)
        sc.activated.connect(self.toggle_selected)
        sc = QShortcut(QKeySequence(Qt.Key_Return), self.picker)
        sc.activated.connect(lambda: self.picker.currentRow() >= 0 and self.open_large(self.picker.currentRow()))
        self._apply_size()

    # ---------- nạp file ----------
    def clear(self):
        self._stop()
        self._drop_conv()
        self.item = None
        self.picker.clear()
        self.title.setText("Xem trước")
        self.info.setText("Bấm một file trong khay để xem trước các trang.")
        self.status.setText("")

    def load(self, item, out_start: int | None = None):
        self._stop()
        self._drop_conv()
        self.item = item
        self.out_start = out_start
        self._cache = {}
        self._hires = {}
        try:
            d = _open(item)
            self._ref_px = d.page_size_pt(0)[0] * 96 / 72
            d.close()
        except Exception:
            self._ref_px = 794.0
        self.title.setText(f"Xem trước: {item.name}")
        self.picker.blockSignals(True)
        self.picker.clear()
        chosen = self.kept_set()
        n = min(item.page_count, MAX_PAGES)
        w = self.size_slider.value()
        blank = QPixmap(w, int(w * 1.414))
        blank.fill(QColor("#ffffff"))
        for i in range(n):
            li = QListWidgetItem(QIcon(blank), self._label(i, i in chosen))
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Checked if i in chosen else Qt.Unchecked)
            li.setTextAlignment(Qt.AlignHCenter)
            self.picker.addItem(li)
        self.picker.blockSignals(False)
        self._relabel()
        self._queue = list(range(n))
        QTimer.singleShot(0, self, self._render_some)

    def set_out_start(self, start: int | None):
        self.out_start = start
        self._relabel()

    def kept_set(self) -> set:
        it = self.item
        if it is None:
            return set()
        try:
            return set(range(it.page_count)) if it.whole else set(parse_ranges(it.ranges, it.page_count))
        except ValueError:
            return set()

    def kept(self) -> list[int]:
        return [i for i in range(self.picker.count()) if self.picker.item(i).checkState() == Qt.Checked]

    def _label(self, i: int, keep: bool, pos: dict | None = None) -> str:
        """pos: {trang: thứ tự trong các trang giữ} – để ghi "→ trang x trong file ghép"."""
        t = f"Trang {i + 1}"
        m = self.mode_of(i)
        if m != "color":
            from .colormode import MODE_SHORT
            t += f" · {MODE_SHORT[m]}"
        if not keep:
            return t + " · bỏ"
        if self.out_start is not None and pos is not None and i in pos:
            return f"{t} → {self.out_start + pos[i]}"
        return t

    def _relabel(self):
        kept = self.kept()
        pos = {p: k for k, p in enumerate(kept)}
        self.picker.blockSignals(True)
        for i in range(self.picker.count()):
            li = self.picker.item(i)
            li.setText(self._label(i, li.checkState() == Qt.Checked, pos))
        self.picker.blockSignals(False)
        for i in list(self._cache):
            self._set_icon(i)
        self._update_status()

    def _update_status(self):
        if self.item is None:
            return
        k = len(self.kept())
        n = self.item.page_count
        self.info.setText(f"{n} trang · giữ {k} · bỏ {n - k}" +
                          (f" · trong file ghép: trang {self.out_start} – {self.out_start + k - 1}"
                           if self.out_start is not None and k else ""))
        self.status.setText("Tích / bỏ tích để giữ / bỏ trang · Space: đổi các trang đang chọn · "
                            "Màu trang: chọn trang rồi bấm Màu / Chữ đen / Xám / Như máy in / Đen trắng · "
                            "Nháy đúp hoặc Enter: xem lớn · Chuột phải: thêm lựa chọn")

    # ---------- vẽ ảnh trang (dần dần, không đơ giao diện) ----------
    def _drop_conv(self):
        for d in self._conv.values():
            try:
                d.close()
            except Exception:
                pass
        self._conv = {}

    def _stop(self):
        self._queue = []
        self._hi_queue = []
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None

    def _need_px(self) -> int:
        return int(self.icon_w() * self.picker.devicePixelRatioF())

    def _render_some(self):
        if self.item is None or not (self._queue or self._hi_queue):
            self._stop()
            return
        try:
            if self._doc is None:
                self._doc = _open(self.item)
            for _ in range(2):
                if self._hi_queue:                 # ưu tiên vẽ nét các trang đang nhìn thấy
                    i = self._hi_queue.pop(0)
                    need = self._need_px()
                    if need <= CACHE_W or (i in self._hires and self._hires[i].width() >= need * 0.95):
                        continue
                    d = self._doc_for(i)
                    w, _h = d.page_size_pt(i)
                    self._hires[i] = to_qimage(d.render(i, need / w))
                    while len(self._hires) > HIRES_KEEP:
                        far = max(self._hires, key=lambda k: abs(k - i))
                        self._hires.pop(far)
                    self._set_icon(i)
                elif self._queue:
                    i = self._queue.pop(0)
                    d = self._doc_for(i)
                    w, _h = d.page_size_pt(i)
                    self._cache[i] = to_qimage(d.render(i, CACHE_W / w))
                    self._set_icon(i)
                    if not self._queue:
                        self._queue_hires()
        except (PasswordRequired, Exception):
            self._queue = []
            self._hi_queue = []
        QTimer.singleShot(0, self, self._render_some)

    # ---------- màu từng trang (10c, 10e) ----------
    def mode_of(self, i: int) -> str:
        if self.item is None:
            return "color"
        m = self.item.mode_of(i, self.default_color)
        if m == "auto":                               # tự nhận trang có màu thật
            import os
            from .colormode import resolve_auto
            from .merge import AUTO_CACHE
            try:
                if self._doc is None:
                    self._doc = _open(self.item)
                m = resolve_auto(self._doc.pdf, [i], AUTO_CACHE,
                                 (self.item.path, os.path.getmtime(self.item.path)))[i]
            except Exception:
                m = "color"
        return m

    def _doc_for(self, i: int):
        """Tài liệu để vẽ trang i: bản gốc, hoặc bản đã chuyển màu theo chế độ của trang (xem trước đúng kết quả)."""
        m = self.mode_of(i)
        if m == "color":
            return self._doc
        d = self._conv.get(m)
        if d is None:
            from .colormode import convert_bytes
            data = convert_bytes(self._doc.to_bytes(), {k: m for k in range(self._doc.page_count)})
            d = self._conv[m] = PdfDocument(data=data)
        return d

    def set_default_color(self, mode: str):
        self.default_color = mode or "color"
        if self.item is not None:
            self._rerender(range(self.picker.count()))

    def _rerender(self, pages):
        pages = [i for i in pages if 0 <= i < self.picker.count()]
        for i in pages:
            self._cache.pop(i, None)
            self._hires.pop(i, None)
        self._relabel()
        idle = not self._queue and not self._hi_queue
        self._queue = sorted(set(self._queue) | set(pages))
        if idle:
            QTimer.singleShot(0, self, self._render_some)

    def set_page_colors(self, pages, mode: str):
        it = self.item
        if it is None:
            return
        base = it.color or self.default_color
        for i in pages:
            if mode == base:
                it.page_colors.pop(str(i), None)
            else:
                it.page_colors[str(i)] = mode
        self._rerender(pages)
        self.colorsChanged.emit()

    def set_color_selected(self, mode: str):
        if self.item is None:
            return
        rows = sorted({self.picker.row(li) for li in self.picker.selectedItems()})
        if not rows:                                  # chưa chọn trang nào -> cả file
            self.item.page_colors.clear()
            self.item.color = mode
            self._rerender(range(self.picker.count()))
            self.colorsChanged.emit()
            return
        self.set_page_colors(rows, mode)

    def _visible_rows(self) -> list[int]:
        out = []
        vp = self.picker.viewport().rect()
        for i in range(self.picker.count()):
            if self.picker.visualItemRect(self.picker.item(i)).intersects(vp):
                out.append(i)
        return out

    def _queue_hires(self):
        """Cỡ lớn hơn ảnh nền: vẽ lại nét các trang đang nhìn thấy (và vài trang kế tiếp)."""
        if self.item is None or self._need_px() <= CACHE_W:
            return
        rows = self._visible_rows()
        if rows:
            rows = list(range(max(0, rows[0] - 2), min(self.picker.count(), rows[-1] + 3)))
        need = self._need_px()
        todo = [i for i in rows if not (i in self._hires and self._hires[i].width() >= need * 0.95)]
        if not todo:
            return
        idle = not self._queue and not self._hi_queue
        self._hi_queue = todo
        if idle:
            QTimer.singleShot(0, self, self._render_some)

    def _set_icon(self, i: int):
        img = self._hires.get(i) or self._cache.get(i)
        if img is None or i >= self.picker.count():
            return
        li = self.picker.item(i)
        m = self.mode_of(i)
        if m != "color":
            from .colormode import MODE_SHORT
            img = color_badge(img, MODE_SHORT[m])
        if li.checkState() != Qt.Checked:
            img = dropped_overlay(img)
        dpr = self.picker.devicePixelRatioF()
        pm = QPixmap.fromImage(img.scaledToWidth(max(1, int(self.icon_w() * dpr)), Qt.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self.picker.blockSignals(True)
        li.setIcon(QIcon(pm))
        self.picker.blockSignals(False)

    # ---------- cỡ ảnh trang: thanh Cỡ, Vừa khung, Ctrl + lăn chuột ----------
    def fit_width(self) -> int:
        """Bề rộng ảnh khi "Vừa khung": chiếm hết bề ngang ô (trừ thanh cuộn, lề)."""
        vw = self.picker.viewport().width()
        sb = self.picker.verticalScrollBar()
        if not sb.isVisible():
            vw -= sb.sizeHint().width()
        return max(MIN_W, vw - 44)

    def icon_w(self) -> int:
        return self.fit_width() if self.btn_fit.isChecked() else self.size_slider.value()

    def zoom_percent(self) -> int:
        return round(self.icon_w() * 100 / max(1.0, self._ref_px))

    def _apply_size(self):
        w = self.icon_w()
        h = int(w * 1.42)
        self.picker.setIconSize(QSize(w, h))
        # chia đều bề ngang cho các cột -> các trang nằm giữa, không dồn về góc trái
        vw = max(1, self.picker.viewport().width() - 4)
        cols = max(1, vw // (w + 24))
        self.picker.setGridSize(QSize(max(w + 24, vw // cols), h + 36))
        self.lbl_zoom.setText(f"{self.zoom_percent()}%")

    def _resize_icons(self, *_):
        self._apply_size()
        for i in list(self._cache):
            self._set_icon(i)
        self._queue_hires()

    def _slider_moved(self, *_):
        if self.btn_fit.isChecked():
            self.btn_fit.blockSignals(True)
            self.btn_fit.setChecked(False)
            self.btn_fit.blockSignals(False)
        self._resize_icons()

    def _fit_toggled(self, on: bool):
        if on:
            self.size_slider.blockSignals(True)
            self.size_slider.setValue(min(MAX_W, self.fit_width()))
            self.size_slider.blockSignals(False)
        self._resize_icons()

    def zoom_step(self, up: bool):
        w = self.icon_w()
        self.size_slider.setValue(int(min(MAX_W, max(MIN_W, w * (1.15 if up else 1 / 1.15)))))

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if obj is self.picker.viewport():
            if e.type() == QEvent.Wheel and e.modifiers() & Qt.ControlModifier:
                self.zoom_step(e.angleDelta().y() > 0)
                return True
            if e.type() == QEvent.Resize and abs(e.size().width() - getattr(self, "_last_vw", -99)) > 2:
                self._last_vw = e.size().width()
                QTimer.singleShot(0, self, self._resize_icons)
        return super().eventFilter(obj, e)

    # ---------- giữ / bỏ ----------
    def _item_changed(self, li):
        self.changed.emit()
        self._relabel()

    def set_kept(self, pages):
        keep = set(pages)
        self.picker.blockSignals(True)
        for i in range(self.picker.count()):
            self.picker.item(i).setCheckState(Qt.Checked if i in keep else Qt.Unchecked)
        self.picker.blockSignals(False)
        self.changed.emit()
        self._relabel()

    def quick(self, key: str):
        if self.item is None:
            return
        n = self.picker.count()
        if key == "invert":
            cur = set(self.kept())
            self.set_kept([i for i in range(n) if i not in cur])
        else:
            self.set_kept(parse_ranges(key, self.item.page_count) if key else [])

    def toggle_selected(self):
        rows = sorted({self.picker.row(li) for li in self.picker.selectedItems()})
        if not rows:
            return
        cur = set(self.kept())
        # nếu tất cả đang giữ -> bỏ; ngược lại -> giữ
        drop = all(r in cur for r in rows)
        self.set_kept((cur - set(rows)) if drop else (cur | set(rows)))

    def _menu(self, pos):
        li = self.picker.itemAt(pos)
        m = QMenu(self)
        rows = sorted({self.picker.row(x) for x in self.picker.selectedItems()}) or \
            ([self.picker.row(li)] if li else [])
        if rows:
            cur = set(self.kept())
            m.addAction(f"Giữ {len(rows)} trang đang chọn", lambda: self.set_kept(cur | set(rows)))
            m.addAction(f"Bỏ {len(rows)} trang đang chọn", lambda: self.set_kept(cur - set(rows)))
            m.addAction("Chỉ giữ các trang đang chọn", lambda: self.set_kept(rows))
            m.addSeparator()
            from .colormode import MODES
            sub = m.addMenu(f"Màu cho {len(rows)} trang đang chọn")
            for key, text in MODES:
                sub.addAction(text, lambda k=key: self.set_page_colors(rows, k))
            m.addSeparator()
        if li:
            m.addAction(f"Xem lớn trang {self.picker.row(li) + 1}…", lambda: self.open_large(self.picker.row(li)))
        m.exec(self.picker.viewport().mapToGlobal(pos))

    def open_large(self, i: int):
        if self.item is None or i < 0:
            return None
        dlg = PagePreviewDialog(self, self.item, i, self)
        self._large = dlg
        dlg.exec()
        return dlg


class PagePreviewDialog(QDialog):
    """Xem lớn một trang của file trong khay: lật trang (◀ ▶, PgUp/PgDn, ←/→), phóng to, cuộn,
    tích "Giữ trang này" (đồng bộ với bảng xem trước)."""

    def __init__(self, parent, item, page: int, panel: TrayPreview | None = None):
        super().__init__(parent)
        self.item, self.panel = item, panel
        self.page = page
        self.zoom = 0.0                            # 0 = vừa khung
        self.doc = _open(item)
        self.setWindowTitle(f"Xem trước – {item.name}")
        self.resize(820, 960)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        bar = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Trang trước")
        self.btn_next = QPushButton("Trang sau ▶")
        for b in (self.btn_prev, self.btn_next):
            b.setAutoDefault(False)
            b.setDefault(False)
        self.lbl_page = QLabel("", objectName="h")
        self.lbl_page.setAlignment(Qt.AlignCenter)
        self.chk_keep = QCheckBox("Giữ trang này khi ghép")
        self.btn_zout = QToolButton(text="−", toolTip="Thu nhỏ")
        self.btn_zin = QToolButton(text="+", toolTip="Phóng to")
        self.btn_fit = QToolButton(text="Vừa khung", toolTip="Vừa khung")
        bar.addWidget(self.btn_prev)
        bar.addWidget(self.lbl_page, 1)
        bar.addWidget(self.chk_keep)
        for b in (self.btn_zout, self.btn_fit, self.btn_zin):
            bar.addWidget(b)
        bar.addWidget(self.btn_next)
        v.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.view)
        v.addWidget(self.scroll, 1)
        self.scroll.viewport().installEventFilter(self)
        self.btn_prev.clicked.connect(lambda: self.go(self.page - 1))
        self.btn_next.clicked.connect(lambda: self.go(self.page + 1))
        self.btn_zin.clicked.connect(lambda: self.set_zoom((self.zoom or self._fit_scale()) * 1.25))
        self.btn_zout.clicked.connect(lambda: self.set_zoom((self.zoom or self._fit_scale()) / 1.25))
        self.btn_fit.clicked.connect(lambda: self.set_zoom(0.0))
        self.chk_keep.toggled.connect(self._keep_toggled)
        for keys, fn in ((("Left", "PgUp"), lambda: self.go(self.page - 1)),
                         (("Right", "PgDown"), lambda: self.go(self.page + 1)),
                         (("Home",), lambda: self.go(0)), (("End",), lambda: self.go(self.doc.page_count - 1)),
                         (("Space",), lambda: self.chk_keep.toggle())):
            for k in keys:
                QShortcut(QKeySequence(k), self, activated=fn)
        self.go(page)

    def _fit_scale(self) -> float:
        w, h = self.doc.page_size_pt(self.page)
        vw = max(200, self.scroll.viewport().width() - 20)
        vh = max(200, self.scroll.viewport().height() - 20)
        return min(vw / w, vh / h)

    def set_zoom(self, z: float):
        self.zoom = max(0.2, min(z, 6.0)) if z else 0.0
        self._render()

    def go(self, i: int):
        if not 0 <= i < self.doc.page_count:
            return
        self.page = i
        self.btn_prev.setEnabled(i > 0)
        self.btn_next.setEnabled(i < self.doc.page_count - 1)
        keep = True
        if self.panel is not None and i < self.panel.picker.count():
            keep = self.panel.picker.item(i).checkState() == Qt.Checked
        self.chk_keep.blockSignals(True)
        self.chk_keep.setChecked(keep)
        self.chk_keep.blockSignals(False)
        self._render()

    def _render(self):
        s = self.zoom or self._fit_scale()
        img = to_qimage(self.doc.render(self.page, s))
        if not self.chk_keep.isChecked():
            img = dropped_overlay(img)
        self.view.setPixmap(QPixmap.fromImage(img))
        self.view.resize(img.width(), img.height())
        keep = "giữ" if self.chk_keep.isChecked() else "BỎ khi ghép"
        self.lbl_page.setText(f"Trang {self.page + 1} / {self.doc.page_count} · {keep} · {round(s * 100)}%")

    def _keep_toggled(self, on: bool):
        if self.panel is not None and self.page < self.panel.picker.count():
            self.panel.picker.item(self.page).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self._render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.zoom:
            QTimer.singleShot(0, self, self._render)

    def eventFilter(self, obj, e):
        """Cuộn chuột hết trang -> sang trang sau / trang trước (như đọc tài liệu liền mạch)."""
        from PySide6.QtCore import QEvent
        if obj is self.scroll.viewport() and e.type() == QEvent.Wheel and not (e.modifiers() & Qt.ControlModifier):
            sb = self.scroll.verticalScrollBar()
            dy = e.angleDelta().y()
            if dy < 0 and sb.value() >= sb.maximum() and self.page < self.doc.page_count - 1:
                self.go(self.page + 1)
                sb.setValue(0)
                return True
            if dy > 0 and sb.value() <= sb.minimum() and self.page > 0:
                self.go(self.page - 1)
                sb.setValue(sb.maximum())
                return True
        return super().eventFilter(obj, e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom((self.zoom or self._fit_scale()) * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15))
            e.accept()
            return
        super().wheelEvent(e)

    def done(self, r):
        try:
            self.doc.close()
        except Exception:
            pass
        super().done(r)
