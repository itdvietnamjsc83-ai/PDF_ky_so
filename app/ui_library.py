"""Giao diện thư viện con dấu & chữ ký: panel bên phải, nhập ảnh (tách nền), quản lý, giáp lai."""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout)

from .icons import icon
from .library import HAND, HANDSET, KIND_LABEL, KINDS, SIGNATURE, STAMP, Library, LibraryLocked, data_dir

MIME = "application/x-pdfkyso-lib"
MM = 72 / 25.4


def qimage_from_png(png: bytes) -> QImage:
    img = QImage()
    img.loadFromData(QByteArray(png), "PNG")
    return img


def looks_like_signature(name: str) -> bool:
    """Đoán loại theo tên file: "chu-ky-GD", "chữ ký", "signature" -> chữ ký; còn lại coi là con dấu."""
    import re
    import unicodedata
    n = unicodedata.normalize("NFD", name.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn").replace("đ", "d")
    if re.search(r"(\bdau\b|\bmoc\b|stamp|seal)", n):
        return False
    return bool(re.search(r"(chu[\s_\-.]*ky|signature|\bsign\b|\bky\b)", n))


def checker(size: QSize) -> QPixmap:
    """Nền ô bàn cờ để nhìn rõ phần trong suốt."""
    pm = QPixmap(size)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    c = QColor("#e8e8e8")
    s = 10
    for y in range(0, size.height(), s):
        for x in range((y // s) % 2 * s, size.width(), 2 * s):
            p.fillRect(x, y, s, s, c)
    p.end()
    return pm


def unlock_if_needed(parent, lib: Library) -> bool:
    if not lib.locked:
        return True
    for _ in range(3):
        pw, ok = QInputDialog.getText(parent, "Thư viện dấu đang khóa", "Nhập mật khẩu thư viện:",
                                      QLineEdit.Password)
        if not ok:
            return False
        if lib.unlock(pw):
            return True
        QMessageBox.warning(parent, "Thư viện dấu", "Sai mật khẩu.")
    return False


# ------------------------------------------------------------------ danh sách ô
class LibraryList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(72, 56))
        self.setGridSize(QSize(112, 92))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setWordWrap(True)
        self.setFixedHeight(190)

    def startDrag(self, actions):
        it = self.currentItem()
        if not it:
            return
        md = QMimeData()
        md.setData(MIME, it.data(Qt.UserRole).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(it.icon().pixmap(72, 56))
        drag.exec(Qt.CopyAction)


class LibraryPanel(QFrame):
    """Thẻ “Thư viện dấu & chữ ký” trong panel bên phải."""
    itemActivated = Signal(str)             # id mẫu được bấm
    changed = Signal()

    SCOPES = [("Trang hiện tại", "current"), ("Các trang đang chọn", "selected"), ("Tất cả các trang", "all")]

    def __init__(self, lib: Library, colors: dict):
        super().__init__(objectName="card")
        self.lib = lib
        self.colors = colors
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("Thư viện dấu & chữ ký", objectName="h"))
        row.addStretch()
        self.btn_lock = QPushButton()
        self.btn_lock.setFlat(True)
        self.btn_lock.clicked.connect(self._toggle_lock)
        row.addWidget(self.btn_lock)
        v.addLayout(row)
        self.filter = QComboBox()
        self.filter.addItems(["Tất cả", "Con dấu", "Chữ ký", "Chữ viết tay"])
        self.filter.currentIndexChanged.connect(self.refresh)
        v.addWidget(self.filter)
        self.list = LibraryList()
        self.list.itemClicked.connect(lambda it: self.itemActivated.emit(it.data(Qt.UserRole)))
        v.addWidget(self.list)
        self.hint = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.hint)
        h = QHBoxLayout()
        h.addWidget(QLabel("Đóng lên:", objectName="lbl"))
        self.scope = QComboBox()
        self.scope.addItems([t for t, _ in self.SCOPES])
        h.addWidget(self.scope, 1)
        v.addLayout(h)
        h = QHBoxLayout()
        b = QPushButton(icon("plus", colors["text"]), "Thêm ảnh…")
        b.clicked.connect(self.import_image)
        h.addWidget(b)
        b = QPushButton("Vẽ tay…")
        b.setToolTip("Ký hoặc viết tay trực tiếp bằng chuột / bút cảm ứng")
        b.clicked.connect(self.draw)
        h.addWidget(b)
        v.addLayout(h)
        b = QPushButton("Quản lý thư viện…")
        b.clicked.connect(self.manage)
        v.addWidget(b)
        self._auto_lock = QTimer(self, singleShot=True, interval=15 * 60 * 1000, timeout=self._lock_now)
        self.refresh()

    def scope_value(self) -> str:
        return self.SCOPES[self.scope.currentIndex()][1]

    def refresh(self):
        self.list.clear()
        if self.lib.locked:
            self.btn_lock.setText("Mở khóa")
            self.btn_lock.setVisible(True)
            self.hint.setText("Thư viện đang khóa. Bấm Mở khóa và nhập mật khẩu để dùng dấu.")
            return
        self.btn_lock.setText("Khóa lại" if self.lib.encrypted else "")
        self.btn_lock.setVisible(self.lib.encrypted)
        kind = [None, STAMP, SIGNATURE, HAND][self.filter.currentIndex()]
        items = [it for it in self.lib.of_kind(None)
                 if kind is None or it.kind == kind or (kind == HAND and it.kind == HANDSET)]
        bg = checker(QSize(72, 56))
        for it in items:
            img = qimage_from_png(self.lib.image(it.id))
            pm = QPixmap(bg)
            p = QPainter(pm)
            sc = img.scaled(QSize(68, 52), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawImage((72 - sc.width()) // 2, (56 - sc.height()) // 2, sc)
            p.end()
            li = QListWidgetItem(QIcon(pm), it.name)
            li.setData(Qt.UserRole, it.id)
            li.setToolTip(f"{it.name}\nBộ chữ tay – bấm để viết chữ bằng nét chữ của bạn" if it.kind == HANDSET else
                          f"{it.name}\n{KIND_LABEL.get(it.kind, '')} · rộng {it.width_mm:.0f} mm\n"
                          "Bấm để đặt lên trang hoặc kéo thả vào trang")
            self.list.addItem(li)
        self.hint.setText("Chưa có mẫu nào. Bấm “Thêm ảnh…” để nhập ảnh chụp/scan con dấu, chữ ký."
                          if not items else "Bấm hoặc kéo thả vào trang để đóng dấu.")
        if self.lib.encrypted:
            self._auto_lock.start()          # tự khóa sau 15 phút không dùng

    def _toggle_lock(self):
        if self.lib.locked:
            if unlock_if_needed(self, self.lib):
                self.refresh()
        else:
            self._lock_now()

    def _lock_now(self):
        self.lib.lock()
        self.refresh()

    def import_image(self, path: str | None = None):
        if not unlock_if_needed(self, self.lib):
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh con dấu / chữ ký", "",
                                                  "Ảnh (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        dlg = ImportDialog(self, path)
        if dlg.exec() == QDialog.Accepted:
            r = dlg.result_values()
            self.lib.add(r["name"], r["png"], r["kind"], r["width_mm"])
            self.refresh()
            self.changed.emit()

    def draw(self):
        from .ui_edit import DrawDialog
        if not unlock_if_needed(self, self.lib):
            return None
        dlg = DrawDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return None
        v = dlg.values()
        if not v["png"]:
            return None
        it = self.lib.add(v["name"], v["png"], v["kind"], v["width_mm"])
        self.refresh()
        self.changed.emit()
        return it

    def manage(self):
        if not unlock_if_needed(self, self.lib):
            return
        ManageDialog(self, self.lib).exec()
        self.refresh()
        self.changed.emit()


# ------------------------------------------------------------------ nhập ảnh, tách nền
class ImportDialog(QDialog):
    def __init__(self, parent, path: str):
        super().__init__(parent)
        from . import imaging
        self.imaging = imaging
        self.setWindowTitle("Nhập ảnh con dấu / chữ ký")
        self.resize(820, 560)
        with open(path, "rb") as f:
            self.raw = f.read()
        self.already_clear = imaging.has_transparency(self.raw)
        self.png = b""
        v = QVBoxLayout(self)
        imgs = QHBoxLayout()
        self.lbl_src = QLabel(alignment=Qt.AlignCenter)
        self.lbl_out = QLabel(alignment=Qt.AlignCenter)
        for lbl, cap in ((self.lbl_src, "Ảnh gốc"), (self.lbl_out, "Sau khi tách nền (nền ô cờ = trong suốt)")):
            box = QVBoxLayout()
            lbl.setFixedSize(380, 320)
            lbl.setStyleSheet("border: 1px solid #c8c8c8; border-radius: 6px;")
            box.addWidget(lbl)
            box.addWidget(QLabel(cap, objectName="lbl", alignment=Qt.AlignCenter))
            imgs.addLayout(box)
        v.addLayout(imgs)
        f = QFormLayout()
        base = os.path.splitext(os.path.basename(path))[0]
        self.ed_name = QLineEdit(base)
        f.addRow("Tên mẫu:", self.ed_name)
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems([KIND_LABEL[k] for k in KINDS])
        if looks_like_signature(base):
            self.cmb_kind.setCurrentIndex(1)
        self.cmb_kind.currentIndexChanged.connect(self._kind_changed)
        f.addRow("Loại:", self.cmb_kind)
        self.cb_remove = QCheckBox("Tách nền trắng", checked=not self.already_clear)
        f.addRow("", self.cb_remove)
        self.sl_thr = QSlider(Qt.Horizontal, minimum=120, maximum=245, value=200)
        self.cb_auto = QCheckBox("Tự động", checked=True, toolTip="Tự tìm mức tách nền theo bản scan")
        thr_row = QHBoxLayout()
        thr_row.addWidget(self.sl_thr, 1)
        thr_row.addWidget(self.cb_auto)
        f.addRow("Độ mạnh tách nền:", thr_row)
        # 1.0.22: tách dấu từ bản scan / ảnh chụp sạch hơn
        self.cb_flat = QCheckBox("Làm phẳng nền (bóng tay, giấy ngả vàng, ảnh chụp điện thoại)", checked=True)
        f.addRow("", self.cb_flat)
        self.cb_color = QCheckBox("Chỉ giữ màu mực của dấu (bỏ chữ đen in sẵn, đường kẻ đè lên dấu)")
        f.addRow("", self.cb_color)
        self.cb_clean = QCheckBox("Lọc chấm nhiễu li ti của bản scan", checked=True)
        f.addRow("", self.cb_clean)
        self.cb_boost = QCheckBox("Làm đậm nét mực", checked=True)
        f.addRow("", self.cb_boost)
        self.cmb_ink = QComboBox()
        self.cmb_ink.addItems(["Giữ màu gốc", "Đỏ (con dấu)", "Xanh (bút ký)", "Đen", "Màu chủ đạo – đều màu (dấu mờ, loang)"])
        f.addRow("Màu mực:", self.cmb_ink)
        self.sp_w = QDoubleSpinBox(minimum=5, maximum=200, value=38, suffix=" mm", decimals=1)
        f.addRow("Chiều rộng khi đóng:", self.sp_w)
        self.real_mm = imaging.ink_width_mm(self.raw)      # scan có DPI (vd. 600 dpi) -> đúng kích thước thật
        self.lbl_real = QLabel("", objectName="lbl", wordWrap=True)
        f.addRow("", self.lbl_real)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lưu vào thư viện")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._timer = QTimer(self, singleShot=True, interval=120, timeout=self._process)
        for w in (self.cb_remove, self.cb_boost, self.cb_auto, self.cb_flat, self.cb_color, self.cb_clean):
            w.toggled.connect(self._timer.start)
        self.sl_thr.valueChanged.connect(self._timer.start)
        self.cmb_ink.currentIndexChanged.connect(self._timer.start)
        src = QImage()
        src.loadFromData(QByteArray(self.raw))
        self.lbl_src.setPixmap(QPixmap.fromImage(src.scaled(376, 316, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        self._kind_changed(self.cmb_kind.currentIndex())
        self._process()

    def _kind_changed(self, k):
        self.cb_color.setChecked(KINDS[k] == STAMP)          # con dấu: mặc định chỉ giữ màu mực dấu
        if self.real_mm and 5 <= self.real_mm <= 200:
            self.sp_w.setValue(round(self.real_mm, 1))
            dpi = self.imaging.scan_dpi(self.raw)
            self.lbl_real.setText(f"Kích thước thật theo bản scan {dpi:.0f} dpi: rộng {self.real_mm:.1f} mm "
                                  "(đóng lên trang đúng bằng kích thước này).")
        else:
            self.sp_w.setValue([38, 45, 50][k])
            self.lbl_real.setText("Ảnh không có thông tin độ phân giải (ảnh chụp điện thoại…): hãy nhập chiều "
                                  "rộng thật của con dấu/chữ ký.")

    def _process(self):
        ink = ["keep", "red", "blue", "black", "auto"][self.cmb_ink.currentIndex()]
        on = self.cb_remove.isChecked()
        if on:
            self.png = self.imaging.remove_background(
                self.raw, None if self.cb_auto.isChecked() else self.sl_thr.value(), boost=self.cb_boost.isChecked(),
                ink=ink, flatten=self.cb_flat.isChecked(), keep="color" if self.cb_color.isChecked() else "all",
                clean=self.cb_clean.isChecked())
        else:
            self.png = self.imaging.normalize_png(self.raw)
        self.sl_thr.setEnabled(on and not self.cb_auto.isChecked())
        for w in (self.cb_auto, self.cb_flat, self.cb_color, self.cb_clean):
            w.setEnabled(on)
        img = qimage_from_png(self.png)
        pm = checker(QSize(376, 316))
        p = QPainter(pm)
        sc = img.scaled(QSize(360, 300), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((376 - sc.width()) // 2, (316 - sc.height()) // 2, sc)
        p.end()
        self.lbl_out.setPixmap(pm)

    def _accept(self):
        if self._timer.isActive():
            self._timer.stop()
            self._process()
        if not self.ed_name.text().strip():
            self.ed_name.setFocus()
            return
        self.accept()

    def result_values(self) -> dict:
        return dict(name=self.ed_name.text().strip(), png=self.png,
                    kind=KINDS[self.cmb_kind.currentIndex()], width_mm=self.sp_w.value())


# ------------------------------------------------------------------ quản lý
class ManageDialog(QDialog):
    def __init__(self, parent, lib: Library):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle("Quản lý thư viện dấu & chữ ký")
        self.resize(560, 480)
        v = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 40))
        self.list.currentRowChanged.connect(self._sel)
        v.addWidget(self.list, 1)
        f = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_name.editingFinished.connect(lambda: self._upd(name=self.ed_name.text().strip() or "Không tên"))
        f.addRow("Tên:", self.ed_name)
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems([KIND_LABEL[k] for k in KINDS])
        self.cmb_kind.activated.connect(lambda k: self._upd(kind=KINDS[k]))
        f.addRow("Loại:", self.cmb_kind)
        self.sp_w = QDoubleSpinBox(minimum=5, maximum=200, suffix=" mm")
        self.sp_w.editingFinished.connect(lambda: self._upd(width_mm=self.sp_w.value()))
        f.addRow("Chiều rộng khi đóng:", self.sp_w)
        v.addLayout(f)
        h = QHBoxLayout()
        for text, fn in (("Lên", lambda: self._move(-1)), ("Xuống", lambda: self._move(1)), ("Xóa", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        sec = QFrame(objectName="card")
        sl = QVBoxLayout(sec)
        sl.addWidget(QLabel("Bảo mật", objectName="h"))
        self.lbl_sec = QLabel("", objectName="lbl", wordWrap=True)
        sl.addWidget(self.lbl_sec)
        h = QHBoxLayout()
        b = QPushButton("Đặt / đổi mật khẩu…")
        b.clicked.connect(self._set_pw)
        h.addWidget(b)
        b = QPushButton("Bỏ mật khẩu")
        b.clicked.connect(self._clear_pw)
        h.addWidget(b)
        b = QPushButton("Mở nhật ký dùng dấu")
        b.clicked.connect(self._open_log)
        h.addWidget(b)
        sl.addLayout(h)
        v.addWidget(sec)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        v.addWidget(bb)
        self._reload()

    def _reload(self, keep: str | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for it in self.lib.items:
            img = qimage_from_png(self.lib.image(it.id)).scaled(56, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            li = QListWidgetItem(QIcon(QPixmap.fromImage(img)),
                                 f"{it.name}  ·  {KIND_LABEL.get(it.kind, '')}" + (f"  ·  {it.width_mm:.0f} mm" if it.kind != HANDSET else ""))
            li.setData(Qt.UserRole, it.id)
            self.list.addItem(li)
        self.list.blockSignals(False)
        ids = [it.id for it in self.lib.items]
        self.list.setCurrentRow(ids.index(keep) if keep in ids else (0 if ids else -1))
        self._sel(self.list.currentRow())
        self.lbl_sec.setText("Thư viện được mã hóa AES-256; cần mật khẩu khi mở phần mềm, tự khóa sau 15 phút "
                             "không dùng." if self.lib.encrypted else
                             "Chưa đặt mật khẩu: ai dùng máy này cũng đóng được dấu. Nên đặt mật khẩu.")

    def _cur(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _sel(self, _row):
        iid = self._cur()
        for w in (self.ed_name, self.cmb_kind, self.sp_w):
            w.setEnabled(iid is not None)
        if iid:
            it = self.lib.get(iid)
            self.ed_name.setText(it.name)
            self.cmb_kind.setEnabled(it.kind in KINDS)
            if it.kind in KINDS:
                self.cmb_kind.setCurrentIndex(KINDS.index(it.kind))
            self.sp_w.setValue(it.width_mm)

    def _upd(self, **kw):
        iid = self._cur()
        if iid:
            self.lib.update(iid, **kw)
            self._reload(iid)

    def _move(self, d):
        iid = self._cur()
        if iid:
            self.lib.move(iid, d)
            self._reload(iid)

    def _delete(self):
        iid = self._cur()
        if iid and QMessageBox.question(self, "Xóa mẫu", f"Xóa “{self.lib.get(iid).name}” khỏi thư viện?") \
                == QMessageBox.Yes:
            self.lib.remove(iid)
            self._reload()

    def _set_pw(self):
        pw, ok = QInputDialog.getText(self, "Mật khẩu thư viện", "Mật khẩu mới (ít nhất 6 ký tự):", QLineEdit.Password)
        if not ok:
            return
        if len(pw) < 6:
            QMessageBox.warning(self, "Mật khẩu", "Mật khẩu cần ít nhất 6 ký tự.")
            return
        pw2, ok = QInputDialog.getText(self, "Mật khẩu thư viện", "Nhập lại mật khẩu:", QLineEdit.Password)
        if not ok or pw2 != pw:
            QMessageBox.warning(self, "Mật khẩu", "Hai lần nhập không khớp.")
            return
        self.lib.set_password(pw)
        self._reload(self._cur())

    def _clear_pw(self):
        if self.lib.encrypted and QMessageBox.question(self, "Bỏ mật khẩu",
                                                       "Bỏ mật khẩu thư viện dấu?") == QMessageBox.Yes:
            self.lib.set_password(None)
            self._reload(self._cur())

    def _open_log(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = os.path.join(data_dir(), "nhat_ky_dung_dau.csv")
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Nhật ký", "Chưa có lần đóng dấu nào.")


# ------------------------------------------------------------------ giáp lai
class SeamDialog(QDialog):
    POS = [("Giữa trang", 0.5), ("Phần trên", 0.25), ("Phần dưới", 0.75)]

    def __init__(self, parent, lib: Library, page_count: int, selected: list[int]):
        super().__init__(parent)
        self.setWindowTitle("Đóng dấu giáp lai")
        self.lib = lib
        f = QFormLayout(self)
        self.cmb_stamp = QComboBox()
        for it in lib.of_kind(STAMP):
            self.cmb_stamp.addItem(it.name, it.id)
        f.addRow("Con dấu:", self.cmb_stamp)
        self.cmb_pages = QComboBox()
        self.cmb_pages.addItem(f"Tất cả {page_count} trang", "all")
        if len(selected) >= 2:
            self.cmb_pages.addItem(f"Các trang đang chọn ({len(selected)})", "selected")
        f.addRow("Các trang:", self.cmb_pages)
        self.sp_d = QDoubleSpinBox(minimum=15, maximum=80, value=38, suffix=" mm")
        f.addRow("Đường kính dấu:", self.sp_d)
        self.cmb_pos = QComboBox()
        self.cmb_pos.addItems([t for t, _ in self.POS])
        f.addRow("Vị trí theo chiều dọc:", self.cmb_pos)
        self.cmb_edge = QComboBox()
        self.cmb_edge.addItems(["Mép phải", "Mép trái"])
        f.addRow("Mép đóng:", self.cmb_edge)
        self.cb_rev = QCheckBox("Đảo thứ tự mảnh (trang cuối nhận mảnh đầu)")
        f.addRow("", self.cb_rev)
        # 1.0.22: như đóng dấu thật
        self.cmb_style = QComboBox()
        self.cmb_style.addItem("Tự nhiên – như xếp giấy so le rồi đóng tay", "natural")
        self.cmb_style.addItem("Gọn đều – các mảnh bằng nhau, thẳng hàng", "even")
        f.addRow("Kiểu đóng:", self.cmb_style)
        self.sp_angle = QDoubleSpinBox(minimum=-30, maximum=30, value=0, suffix="°", decimals=0)
        self.sp_angle.setToolTip("Dấu đóng tay thường hơi nghiêng vài độ")
        f.addRow("Nghiêng dấu:", self.sp_angle)
        self.sp_group = QSpinBox(minimum=0, maximum=50, value=0, specialValueText="Tất cả trang một dấu")
        self.sp_group.setSuffix(" trang / dấu")
        self.sp_group.setToolTip("Tập dày: mỗi dấu chỉ đóng qua tối đa N trang (thường 5–10) để mảnh dấu không quá mỏng")
        f.addRow("Mỗi dấu qua:", self.sp_group)
        self.sp_margin = QDoubleSpinBox(minimum=0, maximum=15, value=0, suffix=" mm", decimals=1)
        f.addRow("Cách mép giấy:", self.sp_margin)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        f.addRow(self.preview)
        self.lbl = QLabel("", objectName="lbl", wordWrap=True)
        f.addRow(self.lbl)
        self.n_total, self.n_sel = page_count, len(selected)
        if page_count > 12:                                  # tập dày: gợi ý mỗi dấu qua 8 trang
            self.sp_group.setValue(8)
        for w in (self.cmb_pages, self.sp_d, self.cmb_style, self.sp_angle, self.sp_group, self.cmb_edge,
                  self.cmb_pos, self.cb_rev, self.sp_margin):
            for sig in ("currentIndexChanged", "valueChanged", "toggled"):
                if hasattr(w, sig):
                    getattr(w, sig).connect(self._info)
                    break
        self.cmb_stamp.currentIndexChanged.connect(self._stamp_changed)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Đóng giáp lai")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._stamp_changed()

    def _stamp_changed(self, *_):
        iid = self.cmb_stamp.currentData()
        if iid:
            self.sp_d.setValue(self.lib.get(iid).width_mm)
        self._info()

    def _groups(self, n):
        g = self.sp_group.value()
        if g >= 2 and n > g:
            k = -(-n // g)
            return [n // k + (1 if i < n % k else 0) for i in range(k)]
        return [n]

    def _info(self, *_):
        n = self.n_total if self.cmb_pages.currentData() == "all" else self.n_sel
        groups = self._groups(n)
        per = max(groups)
        txt = (f"Dấu được chia thành {n} mảnh, mỗi trang một mảnh rộng khoảng "
               f"{self.sp_d.value() / max(per, 1):.1f} mm sát mép giấy." if len(groups) == 1 else
               f"Đóng {len(groups)} dấu, mỗi dấu qua {min(groups)}–{per} trang (mảnh rộng khoảng "
               f"{self.sp_d.value() / max(per, 1):.1f} mm).")
        if self.sp_d.value() / max(per, 1) < 2.5:
            txt += " ⚠ Mảnh quá mỏng, khó nhìn: nên chọn mỗi dấu qua ít trang hơn."
        self.lbl.setText(txt)
        self._draw_preview(groups)

    def _draw_preview(self, groups):
        """Hình minh họa: mép các trang xếp so le với mảnh dấu trên từng trang."""
        iid = self.cmb_stamp.currentData()
        if not iid:
            return
        try:
            img = qimage_from_png(self.lib.image(iid))
        except Exception:
            return
        from PySide6.QtGui import QPen, QTransform
        if self.sp_angle.value():
            img = img.transformed(QTransform().rotate(self.sp_angle.value()), Qt.SmoothTransformation)
        W, H = 420, 120
        pm = QPixmap(W, H)
        pm.fill(QColor("#f3f3f3"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        n = groups[0]
        d = 90                                            # đường kính dấu trên hình minh họa
        step = d / n
        x_edge = W / 2 + d / 2
        natural = self.cmb_style.currentData() == "natural"
        sh = img.scaled(int(d), int(d * img.height() / max(1, img.width())), Qt.KeepAspectRatio,
                        Qt.SmoothTransformation)
        for k in range(n):                                # trang k: mép phải lùi vào k*step (xếp so le)
            right = x_edge - (n - 1 - k) * step
            p.setPen(QPen(QColor("#9e9e9e"), 1))
            p.setBrush(QColor("white"))
            p.drawRect(int(right - 150), 8 + k * 2, 150, H - 16)
        for k in range(n):
            part = (n - 1 - k) if self.cb_rev.isChecked() else k
            right = x_edge - (n - 1 - k) * step
            sx = int(part * sh.width() / n)
            sw = max(1, int((part + 1) * sh.width() / n) - sx)
            if natural:
                p.setOpacity(0.82 + 0.18 * ((k * 37) % 10) / 10)
            p.drawImage(int(right - sw), int((H - sh.height()) / 2 + (k % 2) * (1 if natural else 0)), sh, sx, 0, sw,
                        sh.height())
            p.setOpacity(1.0)
        p.end()
        if self.cmb_edge.currentIndex() == 1:
            pm = QPixmap.fromImage(pm.toImage().mirrored(True, False))
        self.preview.setPixmap(pm)

    def values(self) -> dict:
        return dict(item_id=self.cmb_stamp.currentData(), scope=self.cmb_pages.currentData(),
                    diameter_pt=self.sp_d.value() * MM, center_y=self.POS[self.cmb_pos.currentIndex()][1],
                    edge="right" if self.cmb_edge.currentIndex() == 0 else "left",
                    reverse=self.cb_rev.isChecked(), natural=self.cmb_style.currentData() == "natural",
                    angle=self.sp_angle.value(), group_size=self.sp_group.value(),
                    margin_pt=self.sp_margin.value() * MM)


__all__ = ["LibraryPanel", "ImportDialog", "ManageDialog", "SeamDialog", "MIME", "qimage_from_png",
           "unlock_if_needed", "LibraryLocked"]
