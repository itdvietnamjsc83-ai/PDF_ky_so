"""Đợt 3 – bảng tùy chọn khi mở / kéo thả / thêm file vào khay: tích chọn file, chọn Màu / Xám / Đen trắng
cho từng file, mở từng tab hay gộp thành một file, "Không hỏi lại"."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .colormode import MODES

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")


def file_kind(path: str) -> str:
    from .office import EXCEL_EXT, POWERPOINT_EXT, WORD_EXT
    p = path.lower()
    if p.endswith(".pdf"):
        return "PDF"
    if p.endswith(WORD_EXT):
        return "Word"
    if p.endswith(EXCEL_EXT):
        return "Excel"
    if p.endswith(POWERPOINT_EXT):
        return "PowerPoint"
    if p.endswith(IMAGE_EXT):
        return "Ảnh"
    return "Khác"


def openable(path: str) -> bool:
    from .office import is_office_file
    return path.lower().endswith(".pdf") or is_office_file(path) or path.lower().endswith(IMAGE_EXT)


class ExcelOptionsDialog(QDialog):
    """8c, 8d – Excel: chọn sheet cần xuất, vừa trang, hướng giấy."""

    FITS = [("", "Theo thiết lập in trong Excel"), ("width", "Vừa bề ngang 1 trang"), ("page", "Cả sheet vừa 1 trang")]
    ORIENTS = [("", "Theo thiết lập in trong Excel"), ("portrait", "Dọc"), ("landscape", "Ngang")]

    def __init__(self, parent, path: str, opts: dict | None = None):
        from PySide6.QtWidgets import QFormLayout, QListWidget, QListWidgetItem
        from .office import excel_sheets
        super().__init__(parent)
        opts = opts or {}
        self.setWindowTitle(f"Xuất Excel – {os.path.basename(path)}")
        self.resize(420, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Sheet cần xuất:", objectName="h"))
        self.names = excel_sheets(path)
        self.lst = QListWidget()
        chosen = set(opts.get("sheets") or self.names)
        for n in self.names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if n in chosen else Qt.Unchecked)
            self.lst.addItem(it)
        if not self.names:
            v.addWidget(QLabel("Định dạng này không liệt kê được sheet – sẽ xuất cả sổ làm việc.", objectName="lbl",
                               wordWrap=True))
            self.lst.setVisible(False)
        v.addWidget(self.lst, 1)
        f = QFormLayout()
        self.cb_fit = QComboBox()
        for k, lbl in self.FITS:
            self.cb_fit.addItem(lbl, k)
        self.cb_fit.setCurrentIndex(max(0, self.cb_fit.findData(opts.get("fit", ""))))
        self.cb_orient = QComboBox()
        for k, lbl in self.ORIENTS:
            self.cb_orient.addItem(lbl, k)
        self.cb_orient.setCurrentIndex(max(0, self.cb_orient.findData(opts.get("orientation", ""))))
        f.addRow("Co giãn:", self.cb_fit)
        f.addRow("Hướng giấy:", self.cb_orient)
        v.addLayout(f)
        v.addWidget(QLabel("Chỉ áp dụng khi xuất, file Excel gốc không bị thay đổi.", objectName="lbl"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _ok(self):
        if self.names and not self.sheets():
            return
        self.accept()

    def sheets(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.Checked]

    def values(self) -> dict:
        sh = self.sheets()
        return {"sheets": [] if len(sh) == len(self.names) else sh, "fit": self.cb_fit.currentData(),
                "orientation": self.cb_orient.currentData()}


IMAGE_PAGES = [("image", "Vừa khít ảnh (không lề trắng)"), ("A4", "A4"), ("A5", "A5"), ("A3", "A3"),
               ("Letter", "Letter")]
IMAGE_QUALITY = [("keep", "Giữ nguyên ảnh gốc"), ("high", "Cao – 200 dpi"), ("medium", "Vừa – 150 dpi (gửi email)"),
                 ("low", "Nhẹ – 100 dpi (file nhỏ nhất)")]
QUALITY_ARGS = {"keep": (None, None), "high": (200, 85), "medium": (150, 75), "low": (100, 60)}


def image_args(opts: dict | None) -> dict:
    """Tùy chọn trang ảnh -> tham số PdfDocument.from_images."""
    from .document import PAPER_SIZES, PT_TO_MM
    o = opts or {}
    size = None
    if o.get("page") and o["page"] != "image":
        wmm, hmm = PAPER_SIZES[o["page"]]
        size = (wmm / PT_TO_MM, hmm / PT_TO_MM)
    max_dpi, q = QUALITY_ARGS.get(o.get("quality", "keep"), (None, None))
    return {"page_size": size, "margin_pt": float(o.get("margin_mm", 0) or 0) / PT_TO_MM, "max_dpi": max_dpi,
            "quality": q, "fit": o.get("fit", "fit")}


class ImagePageDialog(QDialog):
    """9c, 9f – ảnh thành trang PDF: khổ giấy, lề, co vừa / phóng vừa, chất lượng ảnh."""

    def __init__(self, parent, opts: dict | None = None, settings=None):
        from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout
        super().__init__(parent)
        o = dict(opts or {})
        if not o and settings is not None:
            try:
                import json
                o = json.loads(settings.value("import/image_opts", "") or "{}")
            except Exception:
                o = {}
        self.settings = settings
        self.setWindowTitle("Tùy chọn trang ảnh")
        f = QFormLayout(self)
        self.cb_page = QComboBox()
        for k, lbl in IMAGE_PAGES:
            self.cb_page.addItem(lbl, k)
        self.cb_page.setCurrentIndex(max(0, self.cb_page.findData(o.get("page", "image"))))
        self.sp_margin = QDoubleSpinBox(minimum=0, maximum=50, value=float(o.get("margin_mm", 0)), suffix=" mm")
        self.cb_fit = QComboBox()
        self.cb_fit.addItem("Co vừa khổ (ảnh nhỏ giữ nguyên cỡ)", "fit")
        self.cb_fit.addItem("Phóng to vừa khổ", "fill")
        self.cb_fit.setCurrentIndex(max(0, self.cb_fit.findData(o.get("fit", "fit"))))
        self.cb_quality = QComboBox()
        for k, lbl in IMAGE_QUALITY:
            self.cb_quality.addItem(lbl, k)
        self.cb_quality.setCurrentIndex(max(0, self.cb_quality.findData(o.get("quality", "keep"))))
        f.addRow("Khổ giấy:", self.cb_page)
        f.addRow("Lề:", self.sp_margin)
        f.addRow("Cỡ ảnh:", self.cb_fit)
        f.addRow("Chất lượng:", self.cb_quality)
        f.addRow(QLabel("Khổ tự xoay dọc / ngang theo hướng ảnh. Chất lượng thấp hơn: file nhẹ hơn để gửi email.",
                        objectName="lbl", wordWrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.cb_page.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        self.cb_fit.setEnabled(self.cb_page.currentData() != "image")

    def values(self) -> dict:
        return {"page": self.cb_page.currentData(), "margin_mm": self.sp_margin.value(),
                "fit": self.cb_fit.currentData(), "quality": self.cb_quality.currentData()}

    def accept(self):
        if self.settings is not None:
            import json
            self.settings.setValue("import/image_opts", json.dumps(self.values()))
        super().accept()


def image_summary(o: dict | None) -> str:
    if not o:
        return "Vừa khít ảnh"
    parts = [dict(IMAGE_PAGES).get(o.get("page"), "")]
    if o.get("page") == "image":
        parts = ["Vừa khít ảnh"]
    if o.get("margin_mm"):
        parts.append(f"lề {o['margin_mm']:g} mm")
    if o.get("quality", "keep") != "keep":
        parts.append({"high": "200 dpi", "medium": "150 dpi", "low": "100 dpi"}[o["quality"]])
    return ", ".join(parts)


def excel_summary(opts: dict | None) -> str:
    if not opts or not any(opts.values()):
        return "Tất cả sheet"
    parts = []
    if opts.get("sheets"):
        parts.append(f"{len(opts['sheets'])} sheet")
    parts.append({"width": "vừa ngang", "page": "vừa 1 trang"}.get(opts.get("fit"), ""))
    parts.append({"portrait": "dọc", "landscape": "ngang"}.get(opts.get("orientation"), ""))
    return ", ".join(p for p in parts if p) or "Tất cả sheet"


class ImportOptionsDialog(QDialog):
    """purpose: "open" (mở / kéo thả vào phần mềm) | "tray" (thêm vào khay ghép)."""

    def __init__(self, parent, paths: list[str], settings=None, purpose: str = "open"):
        super().__init__(parent)
        self.settings = settings
        self.purpose = purpose
        self.paths = list(paths)
        self.setWindowTitle("Thêm vào khay ghép" if purpose == "tray" else "Mở file")
        self.resize(720, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Tích chọn file cần " + ("thêm vào khay" if purpose == "tray" else "mở") +
                           " và chọn xuất màu, xám hay đen trắng cho từng file:", objectName="h", wordWrap=True))
        key = "tray/office_color" if purpose == "tray" else "import/color"
        default = (settings.value(key, "color") if settings is not None else "color") or "color"
        top = QHBoxLayout()
        top.addWidget(QLabel("Áp dụng cho tất cả:"))
        self.cb_all = QComboBox()
        for k, lbl in MODES:
            self.cb_all.addItem(lbl, k)
        self.cb_all.setCurrentIndex(max(0, self.cb_all.findData(default)))
        self.cb_all.currentIndexChanged.connect(self._apply_all)
        top.addWidget(self.cb_all)
        top.addStretch()
        self.lbl_count = QLabel("", objectName="lbl")
        top.addWidget(self.lbl_count)
        v.addLayout(top)
        self.excel_opts: dict[str, dict] = {}
        self.image_opts: dict[str, dict] = {}
        try:
            import json
            saved_img = json.loads(settings.value("import/image_opts", "") or "{}") if settings is not None else {}
        except Exception:
            saved_img = {}
        self.table = QTableWidget(len(self.paths), 5)
        self.table.setHorizontalHeaderLabels(["", "Tên file", "Loại", "Xuất", "Tùy chọn"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 150)
        self.checks, self.combos = [], []
        for r, p in enumerate(self.paths):
            cb = QCheckBox(checked=True)
            cb.toggled.connect(self._count)
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(10, 0, 0, 0)
            lay.addWidget(cb)
            self.table.setCellWidget(r, 0, w)
            it = QTableWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            self.table.setItem(r, 1, it)
            self.table.setItem(r, 2, QTableWidgetItem(file_kind(p)))
            combo = QComboBox()
            for k, lbl in MODES:
                combo.addItem(lbl, k)
            combo.setCurrentIndex(max(0, combo.findData(default if file_kind(p) != "PDF" or purpose == "tray"
                                                        else "color")))
            self.table.setCellWidget(r, 3, combo)
            if file_kind(p) == "Ảnh":
                from PySide6.QtWidgets import QPushButton
                if saved_img:
                    self.image_opts[p] = dict(saved_img)
                b = QPushButton(image_summary(self.image_opts.get(p)))
                b.setToolTip("Khổ giấy, lề, chất lượng ảnh")
                b.clicked.connect(lambda _=False, p=p, b=b: self.edit_image(p, b))
                self.table.setCellWidget(r, 4, b)
            if file_kind(p) == "Excel":
                from PySide6.QtWidgets import QPushButton
                b = QPushButton("Tất cả sheet")
                b.setToolTip("Chọn sheet cần xuất, vừa trang, hướng giấy")
                b.clicked.connect(lambda _=False, p=p, b=b: self.edit_excel(p, b))
                self.table.setCellWidget(r, 4, b)
            self.checks.append(cb)
            self.combos.append(combo)
        v.addWidget(self.table, 1)
        self.rb_tabs = QRadioButton("Mở mỗi file một tab")
        self.rb_merge = QRadioButton("Gộp các file đã chọn thành một file PDF (theo thứ tự trên)")
        if purpose == "open":
            merge = str(settings.value("import/merge", "false")).lower() == "true" if settings is not None else False
            (self.rb_merge if merge and len(self.paths) > 1 else self.rb_tabs).setChecked(True)
            self.rb_merge.setEnabled(len(self.paths) > 1)
            v.addWidget(self.rb_tabs)
            v.addWidget(self.rb_merge)
        v.addWidget(QLabel("Chữ đen: mọi chữ màu thành chữ đen, ảnh / logo / nền màu giữ nguyên. Xám: cả trang thang xám. "
                           "Như máy in đen trắng: chữ màu thành đen, ô tô màu / hình / ảnh thành xám đậm nhạt theo màu gốc. "
                           "Đen trắng: chữ và nét đen, nền tô nhạt, ảnh 1-bit – tiết kiệm mực, file nhỏ. "
                           "Chữ luôn là chữ thật (tìm, sao chép được).", objectName="lbl", wordWrap=True))
        self.chk_dont_ask = QCheckBox("Không hỏi lại – lần sau dùng luôn lựa chọn chung này "
                                      "(bật lại trong Công cụ → Tùy chọn mở file)" if purpose == "open" else
                                      "Không hỏi lại – lần sau thêm Word/Excel vào khay dùng luôn lựa chọn chung này")
        v.addWidget(self.chk_dont_ask)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Thêm vào khay" if purpose == "tray" else "Mở")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._count()

    def edit_image(self, path, button=None):
        dlg = ImagePageDialog(self, self.image_opts.get(path), self.settings)
        self._image_dlg = dlg
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            for p in self.paths:                       # áp cho mọi ảnh trong danh sách (thường chọn chung)
                if file_kind(p) == "Ảnh":
                    self.image_opts[p] = dict(v)
            for r, p in enumerate(self.paths):
                w = self.table.cellWidget(r, 4)
                if file_kind(p) == "Ảnh" and w is not None:
                    w.setText(image_summary(v))

    def edit_excel(self, path, button=None):
        dlg = ExcelOptionsDialog(self, path, self.excel_opts.get(path))
        self._excel_dlg = dlg
        if dlg.exec() == QDialog.Accepted:
            self.excel_opts[path] = dlg.values()
            if button is not None:
                button.setText(excel_summary(self.excel_opts[path]))

    def _apply_all(self, *_):
        m = self.cb_all.currentData()
        for c in self.combos:
            c.setCurrentIndex(c.findData(m))

    def _count(self, *_):
        n = sum(1 for c in self.checks if c.isChecked())
        self.lbl_count.setText(f"Đã chọn {n} / {len(self.paths)} file")
        self.btn_ok.setEnabled(n > 0)

    def chosen(self) -> list[tuple[str, str]]:
        return [(p, self.combos[k].currentData()) for k, p in enumerate(self.paths) if self.checks[k].isChecked()]

    def merge(self) -> bool:
        return self.purpose == "open" and self.rb_merge.isChecked() and len(self.chosen()) > 1

    def accept(self):
        st = self.settings
        if st is not None:
            key = "tray/office_color" if self.purpose == "tray" else "import/color"
            st.setValue(key, self.cb_all.currentData())
            if self.purpose == "open":
                st.setValue("import/merge", self.rb_merge.isChecked())
                if self.chk_dont_ask.isChecked():
                    st.setValue("import/ask", False)
            elif self.chk_dont_ask.isChecked():
                st.setValue("tray/ask_office", False)
        super().accept()


__all__ = ["ImportOptionsDialog", "ExcelOptionsDialog", "openable", "file_kind", "IMAGE_EXT"]


class ImportSettingsDialog(QDialog):
    """Công cụ → Tùy chọn mở file: bật lại bảng hỏi, lựa chọn mặc định."""

    def __init__(self, parent, settings):
        from PySide6.QtWidgets import QFormLayout
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Tùy chọn mở file")
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.chk_ask = QCheckBox("Hiện bảng tùy chọn khi mở / kéo thả Word, Excel, ảnh hoặc nhiều file")
        self.chk_ask.setChecked(str(settings.value("import/ask", "true")).lower() == "true")
        v.addWidget(self.chk_ask)
        self.cb_color = QComboBox()
        self.cb_tray = QComboBox()
        for cb in (self.cb_color, self.cb_tray):
            for k, lbl in MODES:
                cb.addItem(lbl, k)
        self.cb_color.setCurrentIndex(max(0, self.cb_color.findData(settings.value("import/color", "color"))))
        self.cb_tray.setCurrentIndex(max(0, self.cb_tray.findData(settings.value("tray/office_color", "color"))))
        f.addRow("Mặc định khi mở Word/Excel/ảnh:", self.cb_color)
        self.chk_merge = QCheckBox("Mở nhiều file cùng lúc: gộp thành một file")
        self.chk_merge.setChecked(str(settings.value("import/merge", "false")).lower() == "true")
        f.addRow("", self.chk_merge)
        self.chk_tray = QCheckBox("Hỏi Màu / Chữ đen / Xám / Như máy in / Đen trắng khi thêm Word/Excel vào khay ghép")
        self.chk_tray.setChecked(str(settings.value("tray/ask_office", "true")).lower() == "true")
        f.addRow("", self.chk_tray)
        f.addRow("Mặc định khi thêm vào khay:", self.cb_tray)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def accept(self):
        st = self.settings
        st.setValue("import/ask", self.chk_ask.isChecked())
        st.setValue("import/color", self.cb_color.currentData())
        st.setValue("import/merge", self.chk_merge.isChecked())
        st.setValue("tray/ask_office", self.chk_tray.isChecked())
        st.setValue("tray/office_color", self.cb_tray.currentData())
        super().accept()


class ColorModeDialog(QDialog):
    """9h – Chuyển trang của file đang mở sang Chữ đen / Xám / Đen trắng."""

    def __init__(self, parent, page_count: int, current: int, selected: list[int]):
        from PySide6.QtWidgets import QButtonGroup, QLineEdit
        from .colormode import MODE_TIP
        super().__init__(parent)
        self.setWindowTitle("Chuyển màu trang")
        self.n, self.current, self.selected = page_count, current, sorted(set(selected))
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Chuyển sang:", objectName="h"))
        self.group_mode = QButtonGroup(self)
        self.modes = {}
        for k, lbl in MODES:
            if k == "color":
                continue
            rb = QRadioButton(f"{lbl} – {MODE_TIP[k]}")
            self.group_mode.addButton(rb)
            self.modes[k] = rb
            v.addWidget(rb)
        self.modes["blacktext"].setChecked(True)
        v.addWidget(QLabel("Áp dụng cho:", objectName="h"))
        self.group = QButtonGroup(self)
        self.scope = {}
        for k, lbl in (("all", f"Tất cả {page_count} trang"), ("current", f"Trang hiện tại ({current + 1})"),
                       ("selected", f"Các trang đang chọn ({len(self.selected)})")):
            rb = QRadioButton(lbl)
            self.group.addButton(rb)
            self.scope[k] = rb
            v.addWidget(rb)
        self.scope["selected"].setEnabled(len(self.selected) > 1)
        row = QHBoxLayout()
        rb = QRadioButton("Các trang:")
        self.group.addButton(rb)
        self.scope["range"] = rb
        self.ed_range = QLineEdit(placeholderText="vd. 1-3, 5, 8-")
        self.ed_range.textEdited.connect(lambda *_: rb.setChecked(True))
        row.addWidget(rb)
        row.addWidget(self.ed_range, 1)
        v.addLayout(row)
        self.scope["all"].setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Chuyển")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def mode(self) -> str:
        return next(k for k, rb in self.modes.items() if rb.isChecked())

    def pages(self) -> list[int]:
        from .document import parse_ranges
        if self.scope["current"].isChecked():
            return [self.current]
        if self.scope["selected"].isChecked():
            return self.selected
        if self.scope["range"].isChecked():
            try:
                return parse_ranges(self.ed_range.text(), self.n)
            except ValueError:
                return []
        return list(range(self.n))
