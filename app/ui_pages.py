"""Hộp thoại thao tác trang: chèn trang trắng, xóa trang (nhiều cách chọn, xem trước), tự xoay (xem trước, xoay nhanh)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QTransform
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout)

from .document import BLANK, format_ranges, parse_ranges
from .viewer import to_qimage

THUMB = 96


def _thumb(doc, i: int, w: int = THUMB):
    pw, _ = doc.page_size_pt(i)
    return to_qimage(doc.render(i, w / max(pw, 1)))


def _thumb_list(height: int = 150) -> QListWidget:
    lst = QListWidget()
    lst.setViewMode(QListView.IconMode)
    lst.setFlow(QListView.LeftToRight)
    lst.setWrapping(False)
    lst.setMovement(QListView.Static)
    lst.setIconSize(QSize(THUMB, int(THUMB * 1.42)))
    lst.setFixedHeight(height)
    lst.setSpacing(4)
    return lst


# ------------------------------------------------------------------ trang trắng
class BlankPagesDialog(QDialog):
    """Chèn trang trắng: trước/sau trang hiện tại, đầu/cuối file, sau trang số N; số lượng."""

    def __init__(self, parent, page_count: int, current: int):
        super().__init__(parent)
        self.setWindowTitle("Chèn trang trắng")
        self.page_count, self.current = page_count, current
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Vị trí chèn:", objectName="h"))
        self.group = QButtonGroup(self)
        self.opts = {}
        for key, text in (("before", f"Trước trang hiện tại (trang {current + 1})"),
                          ("after", f"Sau trang hiện tại (trang {current + 1})"),
                          ("start", "Đầu file"), ("end", f"Cuối file (sau trang {page_count})")):
            rb = QRadioButton(text)
            self.group.addButton(rb)
            self.opts[key] = rb
            v.addWidget(rb)
        row = QHBoxLayout()
        rb = QRadioButton("Sau trang số")
        self.group.addButton(rb)
        self.opts["number"] = rb
        self.sp_after = QSpinBox(minimum=1, maximum=max(1, page_count), value=current + 1)
        self.sp_after.valueChanged.connect(lambda *_: rb.setChecked(True))
        row.addWidget(rb)
        row.addWidget(self.sp_after)
        row.addStretch()
        v.addLayout(row)
        row = QHBoxLayout()
        rb = QRadioButton("Sau mỗi")
        self.group.addButton(rb)
        self.opts["every"] = rb
        self.sp_every = QSpinBox(minimum=1, maximum=max(1, page_count), value=1, suffix=" trang")
        self.sp_every.valueChanged.connect(lambda *_: rb.setChecked(True))
        row.addWidget(rb)
        row.addWidget(self.sp_every)
        row.addWidget(QLabel("(1 = xen sau mọi trang: in 2 mặt để trống mặt sau)", objectName="lbl"))
        row.addStretch()
        v.addLayout(row)
        self.opts["after"].setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("Số trang trắng:"))
        self.sp_count = QSpinBox(minimum=1, maximum=100, value=1)
        row.addWidget(self.sp_count)
        row.addSpacing(16)
        row.addWidget(QLabel("Khổ giấy:"))
        from PySide6.QtWidgets import QComboBox
        self.cb_size = QComboBox()
        self.cb_size.addItem("Cùng khổ trang liền trước", None)
        for k in ("A4", "A5", "A3", "Letter"):
            self.cb_size.addItem(k, k)
        row.addWidget(self.cb_size)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(QLabel("Mặc định trang trắng cùng khổ giấy, cùng hướng với trang liền trước (chèn lên đầu: theo "
                           "trang 1).", objectName="lbl", wordWrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Chèn")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def mode(self) -> str:
        return next(k for k, rb in self.opts.items() if rb.isChecked())

    def values(self) -> tuple[int, int]:
        """(chèn sau trang có chỉ số này – -1 là lên đầu, số lượng). Chế độ "every": xem every()."""
        after = {"before": self.current - 1, "after": self.current, "start": -1, "end": self.page_count - 1,
                 "number": self.sp_after.value() - 1, "every": -2}[self.mode()]
        return after, self.sp_count.value()

    def every(self) -> int:
        return self.sp_every.value()

    def size(self):
        from .document import PAPER_SIZES, PT_TO_MM
        k = self.cb_size.currentData()
        if not k:
            return None
        w, h = PAPER_SIZES[k]
        return w / PT_TO_MM, h / PT_TO_MM


# ------------------------------------------------------------------ xóa trang
class DeletePagesDialog(QDialog):
    """Xóa trang: hiện tại / đã chọn / nhập dải / lẻ / chẵn / trang trắng / trang trùng lặp; xem trước trang sẽ xóa."""
    MODES = [("current", "Trang hiện tại"), ("selected", "Các trang đang chọn"), ("range", "Nhập các trang:"),
             ("odd", "Tất cả trang lẻ"), ("even", "Tất cả trang chẵn"), ("blank", "Trang trắng (tự nhận biết)"),
             ("nearblank", "Trang gần trắng (scan có bụi, vết bẩn) – mực dưới"),
             ("text", "Trang có chứa cụm chữ:"),
             ("dup", "Trang trùng lặp (giữ lại trang đầu tiên)")]

    def __init__(self, parent, doc, current: int, selected: list[int], preset: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Xóa trang")
        self.resize(640, 560)
        self.doc, self.current, self.selected = doc, current, sorted(set(selected)) or [current]
        self._dups = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Tài liệu có {doc.page_count} trang. Chọn các trang cần xóa:", objectName="h"))
        self.group = QButtonGroup(self)
        self.opts = {}
        for key, text in self.MODES:
            if key == "current":
                text += f" (trang {current + 1})"
            if key == "selected":
                text += f" ({format_ranges(self.selected)})"
            rb = QRadioButton(text)
            self.group.addButton(rb)
            self.opts[key] = rb
            if key == "range":
                row = QHBoxLayout()
                row.addWidget(rb)
                self.ed_range = QLineEdit(placeholderText="vd: 2, 5-7, 10-")
                self.ed_range.textEdited.connect(lambda *_: (self.opts["range"].setChecked(True), self._update()))
                row.addWidget(self.ed_range, 1)
                v.addLayout(row)
            elif key == "nearblank":
                from PySide6.QtWidgets import QDoubleSpinBox
                row = QHBoxLayout()
                row.addWidget(rb)
                self.sp_ink = QDoubleSpinBox(minimum=0.05, maximum=10, value=0.5, singleStep=0.1, suffix=" %",
                                             decimals=2)
                self.sp_ink.setToolTip("Trang có ít mực hơn mức này được coi là trang trắng")
                self.sp_ink.valueChanged.connect(lambda *_: (self.opts["nearblank"].setChecked(True), self._update()))
                row.addWidget(self.sp_ink)
                row.addStretch()
                v.addLayout(row)
            elif key == "text":
                from PySide6.QtWidgets import QCheckBox
                row = QHBoxLayout()
                row.addWidget(rb)
                self.ed_text = QLineEdit(placeholderText="vd: BẢN NHÁP, Trang để trống")
                self.ed_text.textEdited.connect(lambda *_: (self.opts["text"].setChecked(True), self._update()))
                row.addWidget(self.ed_text, 1)
                self.chk_case = QCheckBox("Phân biệt hoa/thường")
                self.chk_case.toggled.connect(lambda *_: self._update())
                row.addWidget(self.chk_case)
                v.addLayout(row)
            else:
                v.addWidget(rb)
        self.group.buttonToggled.connect(lambda *_: self._update())
        self.lbl_sum = QLabel("", objectName="h")
        v.addWidget(self.lbl_sum)
        self.preview = _thumb_list(160)
        v.addWidget(self.preview, 1)
        self.lbl_err = QLabel("", wordWrap=True)
        self.lbl_err.setStyleSheet("color:#B8322A")
        v.addWidget(self.lbl_err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        start = preset or ("selected" if len(self.selected) > 1 else "current")
        self.opts[start].setChecked(True)
        self._update()

    def mode(self) -> str:
        return next(k for k, rb in self.opts.items() if rb.isChecked())

    def pages(self) -> list[int]:
        n = self.doc.page_count
        m = self.mode()
        if m == "current":
            return [self.current]
        if m == "selected":
            return self.selected
        if m == "range":
            t = self.ed_range.text().strip()
            return parse_ranges(t, n) if t else []
        if m == "odd":
            return list(range(0, n, 2))
        if m == "even":
            return list(range(1, n, 2))
        if m == "blank":
            return [i for i in range(n) if self.doc.page_kind(i) == BLANK]
        if m == "nearblank":
            key = round(self.sp_ink.value(), 3)
            cache = self.__dict__.setdefault("_ink", {})
            thr = key / 100
            out = []
            for i in range(n):
                if self.doc.page_kind(i) == BLANK:
                    out.append(i)
                    continue
                if len(self.doc.text(i).strip()) > 40:     # trang có nhiều chữ thật -> không phải trang trắng
                    continue
                if i not in cache:
                    cache[i] = self.doc.ink_ratio(i)
                if cache[i] < thr:
                    out.append(i)
            return out
        if m == "text":
            return self.doc.pages_with_text(self.ed_text.text(), self.chk_case.isChecked())
        if m == "dup":
            if self._dups is None:
                seen, dups = {}, []
                for i in range(n):
                    sig = self.doc.page_signature(i)
                    if sig in seen:
                        dups.append(i)
                    else:
                        seen[sig] = i
                self._dups = dups
            return self._dups
        return []

    def _update(self):
        self.lbl_err.setText("")
        try:
            pages = self.pages()
        except ValueError as e:
            pages = []
            self.lbl_err.setText(str(e))
        n = self.doc.page_count
        if pages and len(set(pages)) >= n:
            self.lbl_err.setText("Không thể xóa hết tất cả các trang – phải giữ lại ít nhất 1 trang.")
        ok = bool(pages) and len(set(pages)) < n
        self.btn_ok.setEnabled(ok)
        self.btn_ok.setText(f"Xóa {len(pages)} trang" if pages else "Xóa")
        self.lbl_sum.setText(f"Sẽ xóa {len(pages)} trang: {format_ranges(pages)}" if pages else
                             "Chưa có trang nào được chọn để xóa.")
        self._fill_preview(pages)

    def _fill_preview(self, pages):
        from .tray_preview import dropped_overlay
        self.preview.clear()
        self._todo = list(pages[:200])
        for i in self._todo:
            pm = QPixmap(THUMB, int(THUMB * 1.42))
            pm.fill(QColor("#ffffff"))
            it = QListWidgetItem(QIcon(pm), f"Trang {i + 1}")
            it.setData(Qt.UserRole, i)
            self.preview.addItem(it)
        self._overlay = dropped_overlay
        QTimer.singleShot(0, self, self._render_some)

    def _render_some(self):
        for _ in range(6):
            if not self._todo:
                return
            i = self._todo.pop(0)
            for k in range(self.preview.count()):
                it = self.preview.item(k)
                if it.data(Qt.UserRole) == i:
                    it.setIcon(QIcon(QPixmap.fromImage(self._overlay(_thumb(self.doc, i)))))
                    break
        QTimer.singleShot(0, self, self._render_some)


# ------------------------------------------------------------------ tự xoay
class AutoRotateDialog(QDialog):
    """Xem trước các trang sẽ xoay (ảnh trước → sau), bỏ tích trang không muốn xoay; xoay nhanh trang ngang, lẻ, chẵn."""

    def __init__(self, parent, doc, pages: list[int] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Tự xoay đúng hướng")
        self.resize(720, 600)
        self.doc = doc
        self.scope = list(range(doc.page_count)) if not pages else sorted(set(pages))
        fix, self.unknown = doc.rotation_candidates(self.scope)
        self.auto = dict(fix)                      # trang chữ bị xoay (tự nhận biết)
        self.plan: dict[int, int] = dict(fix)      # trang -> góc sẽ đặt
        v = QVBoxLayout(self)
        scope = "cả tài liệu" if not pages else f"các trang {format_ranges(self.scope)}"
        v.addWidget(QLabel(f"Kiểm tra hướng {scope}:", objectName="h"))
        self.lbl_auto = QLabel("", wordWrap=True)
        v.addWidget(self.lbl_auto)
        self.lbl_scan = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.lbl_scan)
        row = QHBoxLayout()
        row.addWidget(QLabel("Xoay nhanh:", objectName="lbl"))
        for text, fn in (("Trang ngang → dọc", self.landscape_to_portrait), ("Trang lẻ 180°", lambda: self.flip(0)),
                         ("Trang chẵn 180°", lambda: self.flip(1)), ("Bỏ các lựa chọn xoay nhanh", self.reset)):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setFlow(QListView.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setIconSize(QSize(2 * THUMB + 24, int(THUMB * 1.42)))
        self.list.setSpacing(6)
        self.list.itemChanged.connect(self._toggled)
        v.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._rebuild()

    # ---- các cách chọn
    def landscape_to_portrait(self):
        for i in self.scope:
            w, h = self.doc.page_size_pt(i)
            if w > h:
                self.plan[i] = (self.doc.page(i).get_rotation() + 90) % 360
        self._rebuild()

    def flip(self, parity: int):
        for i in self.scope:
            if i % 2 == parity:
                self.plan[i] = (self.doc.page(i).get_rotation() + 180) % 360
        self._rebuild()

    def reset(self):
        self.plan = dict(self.auto)
        self._rebuild()

    # ---- danh sách trước → sau
    def _pair_icon(self, i: int, target: int) -> QIcon:
        from PySide6.QtGui import QPainter
        before = _thumb(self.doc, i)
        delta = (target - self.doc.page(i).get_rotation()) % 360
        after = before.transformed(QTransform().rotate(delta), Qt.SmoothTransformation)
        H = int(THUMB * 1.42)
        W = 2 * THUMB + 24
        pm = QPixmap(W, H)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        for k, img in enumerate((before, after)):
            img = img.scaled(THUMB, H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = k * (THUMB + 24) + (THUMB - img.width()) // 2
            p.drawImage(x, (H - img.height()) // 2, img)
        p.setPen(QColor("#B8322A"))
        p.drawText(THUMB, 0, 24, H, Qt.AlignCenter, "→")
        p.end()
        return QIcon(pm)

    def _rebuild(self):
        self.list.blockSignals(True)
        self.list.clear()
        for i in sorted(self.plan):
            it = QListWidgetItem(self._pair_icon(i, self.plan[i]), f"Trang {i + 1} · xoay "
                                 f"{(self.plan[i] - self.doc.page(i).get_rotation()) % 360}°")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, i)
            self.list.addItem(it)
        self.list.blockSignals(False)
        n_auto = len(self.auto)
        self.lbl_auto.setText(f"✔ Tự nhận biết {n_auto} trang bị xoay (cả trang chữ và trang scan): "
                              f"{format_ranges(sorted(self.auto))}."
                              if n_auto else "✔ Các trang đều đã đúng hướng.")
        self.lbl_scan.setText(
            f"⚠ {len(self.unknown)} trang scan ({format_ranges(self.unknown)}) chưa nhận biết chắc được hướng (trang ít chữ, "
            "chủ yếu hình ảnh/bảng biểu). Dùng Xoay nhanh ở trên, hoặc di chuột lên ảnh thu nhỏ trang và bấm ⟲ ⟳."
            if self.unknown else "")
        self._toggled()

    def _toggled(self, *_):
        n = len(self.chosen())
        self.btn_ok.setEnabled(n > 0)
        self.btn_ok.setText(f"Xoay {n} trang" if n else "Không có trang nào cần xoay")

    def chosen(self) -> dict:
        out = {}
        for k in range(self.list.count()):
            it = self.list.item(k)
            if it.checkState() == Qt.Checked:
                i = it.data(Qt.UserRole)
                out[i] = self.plan[i]
        return out


# ------------------------------------------------------------------ chèn trang (17)
INSERT_SOURCES_FILTER = ("PDF, Word, Excel, PowerPoint, ảnh (*.pdf *.doc *.docx *.docm *.rtf *.odt *.xls *.xlsx *.xlsm "
                         "*.xlsb *.ods *.ppt *.pptx *.odp *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp);;"
                         "Tất cả (*.*)")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")


class InsertPagesDialog(QDialog):
    """Chèn trang: nguồn (file PDF / Word / Excel / ảnh, trang trắng, tab đang mở, trang trong khay ghép),
    chọn trang nguồn (tất cả / dải / một trang / lẻ / chẵn, tích trên ảnh thu nhỏ), vị trí (trước/sau trang hiện tại,
    đầu, cuối, sau trang N), cách chèn (liền khối, xen kẽ mặt trước/mặt sau, lặp mỗi N trang), khổ trang."""

    def __init__(self, parent, doc, current: int, tabs=None, tray_items=None, open_source=None, path: str | None = None):
        """tabs: [(tên, PdfDocument)] các tab khác đang mở · tray_items: [TrayItem] trong khay ghép ·
        open_source(path) -> PdfDocument | None: mở file bất kỳ (Word/Excel qua Office, ảnh -> trang)."""
        from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox
        super().__init__(parent)
        self.setWindowTitle("Chèn trang")
        self.resize(760, 640)
        self.doc, self.current = doc, current
        self.tabs = tabs or []
        self.tray_items = tray_items or []
        self.open_source = open_source
        self.src = None                    # PdfDocument nguồn
        self._own_src = False
        self._thumb_done = 0
        v = QVBoxLayout(self)
        # --- nguồn
        g = QGroupBox("1. Lấy trang từ đâu")
        gl = QVBoxLayout(g)
        row = QHBoxLayout()
        self.cb_source = QComboBox()
        self.cb_source.addItem("File trên máy (PDF, Word, Excel, ảnh…)", ("file", None))
        self.cb_source.addItem("Trang trắng", ("blank", None))
        for k, (title, _d) in enumerate(self.tabs):
            self.cb_source.addItem(f"Tab đang mở: {title}", ("tab", k))
        for k, it in enumerate(self.tray_items):
            self.cb_source.addItem(f"Khay ghép: {it.name}", ("tray", k))
        self.btn_browse = QPushButton("Chọn file…")
        self.btn_browse.clicked.connect(self.browse)
        row.addWidget(self.cb_source, 1)
        row.addWidget(self.btn_browse)
        gl.addLayout(row)
        brow = QHBoxLayout()
        self.lbl_blank = QLabel("Số trang trắng:")
        self.sp_blank = QSpinBox(minimum=1, maximum=500, value=1)
        brow.addWidget(self.lbl_blank)
        brow.addWidget(self.sp_blank)
        brow.addStretch()
        gl.addLayout(brow)
        self.lbl_src = QLabel("Chưa chọn nguồn.", objectName="lbl", wordWrap=True)
        gl.addWidget(self.lbl_src)
        v.addWidget(g)
        # --- trang nguồn
        g2 = QGroupBox("2. Trang nguồn")
        g2l = QVBoxLayout(g2)
        prow = QHBoxLayout()
        self.cb_pages = QComboBox()
        for k, lbl in (("all", "Tất cả"), ("range", "Dải trang"), ("one", "Một trang"), ("odd", "Trang lẻ"),
                       ("even", "Trang chẵn"), ("pick", "Tự tích chọn bên dưới")):
            self.cb_pages.addItem(lbl, k)
        self.ed_range = QLineEdit(placeholderText="vd. 1-3, 5, 8-10")
        self.sp_one = QSpinBox(minimum=1, maximum=1)
        prow.addWidget(self.cb_pages)
        prow.addWidget(self.ed_range, 1)
        prow.addWidget(self.sp_one)
        g2l.addLayout(prow)
        self.lst = _thumb_list(170)
        self.lst.itemChanged.connect(self._item_toggled)
        g2l.addWidget(self.lst)
        v.addWidget(g2)
        # --- vị trí & cách chèn
        g3 = QGroupBox("3. Chèn vào đâu, như thế nào")
        f = QFormLayout(g3)
        pos_row = QHBoxLayout()
        self.cb_pos = QComboBox()
        n = doc.page_count
        for k, lbl in (("after", f"Sau trang hiện tại (trang {current + 1})"),
                       ("before", f"Trước trang hiện tại (trang {current + 1})"),
                       ("start", "Đầu file"), ("end", f"Cuối file (sau trang {n})"), ("number", "Sau trang số")):
            self.cb_pos.addItem(lbl, k)
        self.sp_pos = QSpinBox(minimum=1, maximum=max(1, n), value=current + 1)
        self.sp_pos.valueChanged.connect(lambda *_: self.cb_pos.setCurrentIndex(self.cb_pos.findData("number")))
        pos_row.addWidget(self.cb_pos, 1)
        pos_row.addWidget(self.sp_pos)
        f.addRow("Vị trí:", pos_row)
        mode_row = QHBoxLayout()
        self.cb_mode = QComboBox()
        for k, lbl in (("block", "Chèn liền một khối"), ("interleave", "Xen kẽ từng trang (ghép mặt trước / mặt sau)"),
                       ("repeat", "Chèn lặp lại sau mỗi N trang")):
            self.cb_mode.addItem(lbl, k)
        self.sp_every = QSpinBox(minimum=1, maximum=999, value=1, prefix="N = ")
        mode_row.addWidget(self.cb_mode, 1)
        mode_row.addWidget(self.sp_every)
        f.addRow("Cách chèn:", mode_row)
        self.chk_reverse = QCheckBox("Đảo ngược thứ tự trang nguồn (mặt sau scan từ trang cuối lên)")
        f.addRow("", self.chk_reverse)
        self.cb_size = QComboBox()
        self.cb_size.addItem("Giữ nguyên khổ trang gốc", "keep")
        self.cb_size.addItem("Đưa về khổ trang hiện tại (co vừa, giữ nội dung vector)", "fit")
        f.addRow("Khổ trang:", self.cb_size)
        v.addWidget(g3)
        self.lbl_sum = QLabel("", objectName="h", wordWrap=True)
        v.addWidget(self.lbl_sum)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Chèn")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._timer = QTimer(self, singleShot=True, interval=10, timeout=self._render_some)
        self.cb_source.currentIndexChanged.connect(self._source_changed)
        self.cb_pages.currentIndexChanged.connect(self._pages_mode_changed)
        self.ed_range.textChanged.connect(self._pages_mode_changed)
        self.sp_one.valueChanged.connect(self._pages_mode_changed)
        self.sp_blank.valueChanged.connect(self._source_changed)
        for w in (self.cb_pos, self.cb_mode, self.sp_every, self.chk_reverse, self.cb_size):
            (w.currentIndexChanged if hasattr(w, "currentIndexChanged") else
             w.toggled if hasattr(w, "toggled") else w.valueChanged).connect(self._update)
        self._source_changed()
        if path:
            self.load_path(path)

    # ---------- nguồn ----------
    def _set_src(self, doc, own: bool, label: str):
        if self.src is not None and self._own_src and self.src is not doc:
            try:
                self.src.close()
            except Exception:
                pass
        self.src, self._own_src = doc, own
        self.lbl_src.setText(label)
        self.lst.blockSignals(True)
        self.lst.clear()
        if doc is not None:
            self.sp_one.setMaximum(max(1, doc.page_count))
            ph = QPixmap(THUMB, int(THUMB * 1.42))
            ph.fill(QColor("#f0f0f0"))
            for i in range(doc.page_count):
                it = QListWidgetItem(QIcon(ph), f"{i + 1}")
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                self.lst.addItem(it)
            self._thumb_done = 0
            self._timer.start()
        self.lst.blockSignals(False)
        self._pages_mode_changed()

    def _source_changed(self, *_):
        kind, k = self.cb_source.currentData() or ("file", None)
        self.btn_browse.setVisible(kind == "file")
        self.lbl_blank.setVisible(kind == "blank")
        self.sp_blank.setVisible(kind == "blank")
        if kind == "blank":
            from .document import blank_document
            size = self.doc.page_size_pt(self.current) if self.doc.page_count else (595.28, 841.89)
            self._set_src(blank_document(self.sp_blank.value(), size), True,
                          f"{self.sp_blank.value()} trang trắng cùng khổ trang hiện tại.")
        elif kind == "tab":
            title, d = self.tabs[k]
            self._set_src(d, False, f"Tab “{title}” – {d.page_count} trang.")
        elif kind == "tray":
            it = self.tray_items[k]
            from .document import PdfDocument
            try:
                d = PdfDocument(it.path, password=it.password) if it.password else PdfDocument(it.path)
            except Exception as e:
                self._set_src(None, False, f"Không mở được {it.name}: {e}")
                return
            self._set_src(d, True, f"Khay ghép: {it.name} – {d.page_count} trang.")
            if not it.whole and (it.ranges or "").strip():
                self.cb_pages.setCurrentIndex(self.cb_pages.findData("range"))
                self.ed_range.setText(it.ranges)
        elif kind == "file" and not getattr(self, "_file_path", None):
            self._set_src(None, False, "Bấm “Chọn file…” để chọn PDF, Word, Excel hoặc ảnh.")
        elif kind == "file":
            self._set_src(self._file_doc, False, self._file_label)

    def browse(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn file để chèn trang", "", INSERT_SOURCES_FILTER)
        if paths:
            self.load_path(paths[0] if len(paths) == 1 else paths)

    def load_path(self, path):
        import os
        from .document import PdfDocument
        paths = path if isinstance(path, list) else [path]
        try:
            if all(p.lower().endswith(IMAGE_EXT) for p in paths):
                fit = self.doc.page_size_pt(self.current) if self.cb_size.currentData() == "fit" else None
                d = PdfDocument.from_images(paths, fit)
            elif self.open_source is not None:
                d = self.open_source(paths[0])
            else:
                d = PdfDocument(paths[0])
        except Exception as e:
            QMessageBox.warning(self, "Chèn trang", f"Không mở được file:\n{e}")
            return
        if d is None:
            return
        self._file_path = paths[0]
        self._file_doc = d
        self._file_label = (f"{os.path.basename(paths[0])}" + (f" (+{len(paths) - 1} ảnh)" if len(paths) > 1 else "")
                            + f" – {d.page_count} trang.")
        self.cb_source.blockSignals(True)
        self.cb_source.setCurrentIndex(0)
        self.cb_source.blockSignals(False)
        self._set_src(d, False, self._file_label)

    # ---------- chọn trang ----------
    def _pages_mode_changed(self, *_):
        mode = self.cb_pages.currentData()
        self.ed_range.setVisible(mode == "range")
        self.sp_one.setVisible(mode == "one")
        if self.src is None:
            self._update()
            return
        n = self.src.page_count
        if mode == "pick":
            self._update()
            return
        chosen = set(self._pages_by_mode(mode, n))
        self.lst.blockSignals(True)
        for i in range(self.lst.count()):
            self.lst.item(i).setCheckState(Qt.Checked if i in chosen else Qt.Unchecked)
        self.lst.blockSignals(False)
        self._update()

    def _pages_by_mode(self, mode, n):
        if mode == "all":
            return list(range(n))
        if mode == "range":
            try:
                return parse_ranges(self.ed_range.text(), n) if self.ed_range.text().strip() else []
            except ValueError:
                return []
        if mode == "one":
            return [min(n, self.sp_one.value()) - 1]
        if mode == "odd":
            return list(range(0, n, 2))
        if mode == "even":
            return list(range(1, n, 2))
        return [i for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.Checked]

    def _item_toggled(self, _it):
        if self.cb_pages.currentData() != "pick":
            self.cb_pages.blockSignals(True)
            self.cb_pages.setCurrentIndex(self.cb_pages.findData("pick"))
            self.cb_pages.blockSignals(False)
            self.ed_range.setVisible(False)
            self.sp_one.setVisible(False)
        self._update()

    def _render_some(self):
        if self.src is None:
            return
        n = min(self.lst.count(), self.src.page_count)
        end = min(n, self._thumb_done + 6)
        self.lst.blockSignals(True)                # đổi ảnh thu nhỏ không phải là người dùng tích/bỏ tích
        try:
            for i in range(self._thumb_done, end):
                try:
                    self.lst.item(i).setIcon(QIcon(QPixmap.fromImage(_thumb(self.src, i))))
                except Exception:
                    pass
        finally:
            self.lst.blockSignals(False)
        self._thumb_done = end
        if end < n:
            self._timer.start()

    # ---------- kết quả ----------
    def src_pages(self) -> list[int]:
        if self.src is None:
            return []
        return [i for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.Checked]

    def index(self) -> int:
        k = self.cb_pos.currentData()
        n = self.doc.page_count
        return {"after": self.current + 1, "before": self.current, "start": 0, "end": n,
                "number": self.sp_pos.value()}[k]

    def values(self) -> dict:
        return {"src": self.src, "pages": self.src_pages(), "index": self.index(), "mode": self.cb_mode.currentData(),
                "every": self.sp_every.value(), "reverse": self.chk_reverse.isChecked(),
                "fit": self.cb_size.currentData() == "fit", "own": self._own_src}

    def _update(self, *_):
        mode = self.cb_mode.currentData()
        self.sp_every.setVisible(mode == "repeat")
        self.cb_pos.setEnabled(mode == "block")
        self.sp_pos.setEnabled(mode == "block")
        pages = self.src_pages()
        n = self.doc.page_count
        m = len(pages)
        if not m:
            self.lbl_sum.setText("Chưa có trang nào được chọn để chèn.")
            self.btn_ok.setEnabled(False)
            return
        self.btn_ok.setEnabled(True)
        if mode == "block":
            at = self.index()
            where = "đầu file" if at == 0 else (f"cuối file" if at >= n else f"sau trang {at}")
            txt = f"Sẽ chèn {m} trang ({format_ranges(pages)}) vào {where}"
            total = n + m
        elif mode == "interleave":
            txt = f"Sẽ xen kẽ {m} trang nguồn với {n} trang hiện có (1, 1’, 2, 2’…)"
            total = n + m
        else:
            e = self.sp_every.value()
            reps = max(1, n // e)
            txt = f"Sẽ chèn khối {m} trang sau mỗi {e} trang ({reps} lần)"
            total = n + m * reps
        self.lbl_sum.setText(f"{txt} → tổng {total} trang.")

    def done(self, r):
        if r != QDialog.Accepted and self.src is not None and self._own_src:
            try:
                self.src.close()
            except Exception:
                pass
            self.src = None
        if r != QDialog.Accepted and getattr(self, "_file_doc", None) is not None and self._file_doc is not self.src:
            pass
        super().done(r)
