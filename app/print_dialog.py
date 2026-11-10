"""Hộp thoại In (1.0.22) – kiểu Foxit / Adobe: chọn máy in, số bản, phạm vi trang, trang lẻ/chẵn, in ngược,
tỉ lệ in (vừa khổ / chỉ thu nhỏ / 100% / tùy chỉnh %), nhiều trang trên 1 tờ, khổ giấy, hướng giấy, tự xoay,
căn giữa, lề, đen trắng, in hai mặt, kèm ghi chú – và XEM TRƯỚC đúng như bản in."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QSlider, QSpinBox, QToolButton, QVBoxLayout,
                               QWidget)

from . import APP_NAME
from .printing import (MM, NUP_GRID, PAPERS, SCALE_MODES, PrintOptions, parse_range, plan_sheets,
                       preview_image, print_document, printer_margins_pt, select_pages, sheet_size)

PDF_TARGET = "__pdf__"
QUICK_PERCENTS = (50, 60, 70, 80, 90, 100, 110, 120, 130, 150, 200)
DUPLEX = [("none", "Một mặt"), ("long", "Hai mặt – lật cạnh dài"), ("short", "Hai mặt – lật cạnh ngắn")]


def _printer_names() -> tuple[list[str], str]:
    try:
        from PySide6.QtPrintSupport import QPrinterInfo
        names = [n for n in QPrinterInfo.availablePrinterNames()]
        default = QPrinterInfo.defaultPrinterName()
    except Exception:
        names, default = [], ""
    return names, default


class PrintDialog(QDialog):
    def __init__(self, parent, doc, current_page: int = 0, settings=None, title: str = ""):
        super().__init__(parent)
        self.doc, self.current_page, self.settings = doc, current_page, settings
        self.setWindowTitle(f"In – {title or doc.name}")
        self.resize(1060, 720)
        self._printer = None
        self._printer_for = None
        self._cache: dict = {}
        self._sheets = []
        self._timer = QTimer(self, singleShot=True, interval=120, timeout=self._refresh)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.setSpacing(8)
        root.addLayout(left, 0)

        # ----- máy in
        g = QGroupBox("Máy in")
        f = QGridLayout(g)
        self.cb_printer = QComboBox()
        names, default = _printer_names()
        for n in names:
            self.cb_printer.addItem(n, n)
        self.cb_printer.addItem("Lưu thành file PDF…", PDF_TARGET)
        last = self._get("printer", default)
        k = self.cb_printer.findData(last if last in names else default)
        self.cb_printer.setCurrentIndex(max(0, k))
        self.btn_props = QPushButton("Thuộc tính…", toolTip="Cài đặt riêng của máy in (khay giấy, chất lượng…)")
        self.btn_props.clicked.connect(self._printer_props)
        f.addWidget(QLabel("Tên:"), 0, 0)
        f.addWidget(self.cb_printer, 0, 1)
        f.addWidget(self.btn_props, 0, 2)
        self.sp_copies = QSpinBox(minimum=1, maximum=999, value=1)
        self.chk_collate = QCheckBox("Đối chiếu (in hết bộ rồi mới in bộ tiếp)", checked=True)
        f.addWidget(QLabel("Số bản:"), 1, 0)
        row = QHBoxLayout()
        row.addWidget(self.sp_copies)
        row.addWidget(self.chk_collate, 1)
        f.addLayout(row, 1, 1, 1, 2)
        self.cb_duplex = QComboBox()
        for k_, lbl in DUPLEX:
            self.cb_duplex.addItem(lbl, k_)
        f.addWidget(QLabel("Mặt in:"), 2, 0)
        f.addWidget(self.cb_duplex, 2, 1, 1, 2)
        self.chk_gray = QCheckBox("In đen trắng (thang xám)")
        self.chk_notes = QCheckBox("In kèm biểu tượng ghi chú")
        f.addWidget(self.chk_gray, 3, 0, 1, 2)
        f.addWidget(self.chk_notes, 3, 2)
        left.addWidget(g)

        # ----- phạm vi in
        g = QGroupBox("Phạm vi in")
        v = QGridLayout(g)
        self.rb_all = QRadioButton(f"Tất cả ({doc.page_count} trang)", checked=True)
        self.rb_cur = QRadioButton(f"Trang hiện tại ({current_page + 1})")
        self.rb_pages = QRadioButton("Các trang:")
        self.ed_pages = QLineEdit(placeholderText=f"ví dụ 1-3, 5, 8-{doc.page_count}")
        self.ed_pages.textEdited.connect(lambda _t: (self.rb_pages.setChecked(True), self._changed()))
        self._range_group = QButtonGroup(self)
        for b in (self.rb_all, self.rb_cur, self.rb_pages):
            self._range_group.addButton(b)
        v.addWidget(self.rb_all, 0, 0, 1, 2)
        v.addWidget(self.rb_cur, 1, 0, 1, 2)
        v.addWidget(self.rb_pages, 2, 0)
        v.addWidget(self.ed_pages, 2, 1)
        self.cb_subset = QComboBox()
        for k_, lbl in (("all", "Mọi trang trong phạm vi"), ("odd", "Chỉ trang lẻ"), ("even", "Chỉ trang chẵn")):
            self.cb_subset.addItem(lbl, k_)
        v.addWidget(QLabel("Lọc:"), 3, 0)
        v.addWidget(self.cb_subset, 3, 1)
        self.chk_reverse = QCheckBox("In ngược thứ tự (trang cuối ra trước)")
        v.addWidget(self.chk_reverse, 4, 0, 1, 2)
        left.addWidget(g)

        # ----- kích thước & bố cục
        g = QGroupBox("Kích thước và bố cục trang")
        fl = QFormLayout(g)
        self.cb_scale = QComboBox()
        for k_, lbl in SCALE_MODES:
            self.cb_scale.addItem(lbl, k_)
        fl.addRow("Cỡ in:", self.cb_scale)
        pr = QHBoxLayout()
        self.sp_percent = QDoubleSpinBox(minimum=10, maximum=400, value=100, decimals=0, singleStep=5, suffix=" %")
        self.sp_percent.setToolTip("Tỉ lệ so với kích thước thật của trang (100% = đúng cỡ)")
        pr.addWidget(self.sp_percent)
        self.btn_minus = QToolButton(text="−", toolTip="Giảm 10%")
        self.btn_plus = QToolButton(text="+", toolTip="Tăng 10%")
        self.btn_minus.clicked.connect(lambda: self._set_percent(self.sp_percent.value() - 10))
        self.btn_plus.clicked.connect(lambda: self._set_percent(self.sp_percent.value() + 10))
        pr.addWidget(self.btn_minus)
        pr.addWidget(self.btn_plus)
        pr.addStretch()
        fl.addRow("Tỉ lệ:", pr)
        quick = QGridLayout()
        quick.setSpacing(3)
        self.quick_btns = {}
        for n, pct in enumerate(QUICK_PERCENTS):
            b = QToolButton(text=f"{pct}%")
            b.setMinimumWidth(44)
            b.clicked.connect(lambda _=False, p=pct: self._set_percent(p))
            quick.addWidget(b, n // 6, n % 6)
            self.quick_btns[pct] = b
        qw = QWidget()
        qw.setLayout(quick)
        fl.addRow("", qw)
        self.cb_nup = QComboBox()
        for n in NUP_GRID:
            c, r = NUP_GRID[n]
            self.cb_nup.addItem("1 trang / tờ" if n == 1 else f"{n} trang / tờ ({c}×{r})", n)
        self.chk_border = QCheckBox("Kẻ viền từng trang")
        nr = QHBoxLayout()
        nr.addWidget(self.cb_nup, 1)
        nr.addWidget(self.chk_border)
        fl.addRow("Nhiều trang:", nr)
        self.cb_paper = QComboBox()
        self.cb_paper.addItem("Theo máy in", None)
        for name, w, h in PAPERS:
            self.cb_paper.addItem(f"{name} ({w:g} × {h:g} mm)", (w * MM, h * MM))
        fl.addRow("Khổ giấy:", self.cb_paper)
        self.cb_orient = QComboBox()
        for k_, lbl in (("auto", "Tự động theo trang"), ("portrait", "Dọc"), ("landscape", "Ngang")):
            self.cb_orient.addItem(lbl, k_)
        fl.addRow("Hướng giấy:", self.cb_orient)
        self.sp_margin = QDoubleSpinBox(minimum=0, maximum=50, value=0, decimals=1, singleStep=1, suffix=" mm")
        self.sp_margin.setToolTip("Lề thêm, ngoài phần lề tối thiểu máy in không in tới")
        fl.addRow("Lề thêm:", self.sp_margin)
        self.chk_rotate = QCheckBox("Tự xoay trang cho vừa hướng giấy", checked=True)
        self.chk_center = QCheckBox("Căn giữa trên tờ giấy", checked=True)
        fl.addRow(self.chk_rotate)
        fl.addRow(self.chk_center)
        left.addWidget(g)
        left.addStretch()

        # ----- xem trước
        right = QVBoxLayout()
        root.addLayout(right, 1)
        info = QGridLayout()
        self.lbl_zoom = QLabel()
        self.lbl_docsize = QLabel()
        self.lbl_paper = QLabel()
        for r_, (t, w_) in enumerate((("Tỉ lệ in:", self.lbl_zoom), ("Trang tài liệu:", self.lbl_docsize),
                                       ("Giấy:", self.lbl_paper))):
            info.addWidget(QLabel(t), r_, 0)
            info.addWidget(w_, r_, 1)
        info.setColumnStretch(1, 1)
        hdr = QLabel("Xem trước", objectName="h")
        right.addWidget(hdr)
        right.addLayout(info)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setMinimumSize(QSize(360, 420))
        self.preview.setFrameShape(QFrame.StyledPanel)
        self.preview.setStyleSheet("QLabel{background:#8a8f98;border-radius:6px}")
        right.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        self.btn_prev = QToolButton(text="‹", toolTip="Tờ trước")
        self.btn_next = QToolButton(text="›", toolTip="Tờ sau")
        self.slider = QSlider(Qt.Horizontal, minimum=0, maximum=0)
        self.lbl_sheet = QLabel()
        self.btn_prev.clicked.connect(lambda: self.slider.setValue(self.slider.value() - 1))
        self.btn_next.clicked.connect(lambda: self.slider.setValue(self.slider.value() + 1))
        self.slider.valueChanged.connect(lambda _v: self._draw_preview())
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.slider, 1)
        nav.addWidget(self.btn_next)
        nav.addWidget(self.lbl_sheet)
        right.addLayout(nav)
        self.lbl_warn = QLabel(wordWrap=True)
        self.lbl_warn.setStyleSheet("color:#b26a00")
        right.addWidget(self.lbl_warn)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_print = QPushButton("In", default=True)
        self.btn_print.setMinimumWidth(110)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_print.clicked.connect(self._do_print)
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_print)
        btns.addWidget(self.btn_cancel)
        right.addLayout(btns)

        self._load_settings()
        for sig in (self.cb_printer.currentIndexChanged, self.cb_scale.currentIndexChanged,
                    self.sp_percent.valueChanged, self.cb_nup.currentIndexChanged, self.cb_paper.currentIndexChanged,
                    self.cb_orient.currentIndexChanged, self.sp_margin.valueChanged, self.chk_rotate.toggled,
                    self.chk_center.toggled, self.chk_gray.toggled, self.chk_notes.toggled, self.chk_border.toggled,
                    self.cb_subset.currentIndexChanged, self.chk_reverse.toggled, self.rb_all.toggled,
                    self.rb_cur.toggled, self.rb_pages.toggled):
            sig.connect(self._changed)
        self.ed_pages.editingFinished.connect(self._changed)
        if not doc.can_print_high:
            self.lbl_warn.setText("Người gửi chỉ cho phép in chất lượng thấp (150 dpi).")
        self._refresh()

    # ----- cài đặt nhớ lần sau
    def _get(self, key, default):
        if self.settings is None:
            return default
        v = self.settings.value(f"printdlg/{key}", default)
        if isinstance(default, bool) and not isinstance(v, bool):
            return str(v).lower() in ("1", "true", "yes")
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            try:
                return type(default)(v)
            except (TypeError, ValueError):
                return default
        return v

    def _load_settings(self):
        def sel(cb, data):
            k = cb.findData(data)
            if k >= 0:
                cb.setCurrentIndex(k)
        sel(self.cb_scale, self._get("scale", "fit"))
        self.sp_percent.setValue(self._get("percent", 100.0))
        sel(self.cb_nup, self._get("nup", 1))
        sel(self.cb_orient, self._get("orient", "auto"))
        self.sp_margin.setValue(self._get("margin", 0.0))
        self.chk_rotate.setChecked(self._get("rotate", True))
        self.chk_center.setChecked(self._get("center", True))
        self.chk_gray.setChecked(self._get("gray", False))
        self.chk_border.setChecked(self._get("border", False))
        sel(self.cb_duplex, self._get("duplex", "none"))
        self.chk_notes.setChecked(str(self.settings.value("print/notes", "false")).lower() == "true"
                                  if self.settings is not None else False)
        paper = self._get("paper", "")
        for k in range(self.cb_paper.count()):
            if self.cb_paper.itemText(k).split(" ")[0] == paper:
                self.cb_paper.setCurrentIndex(k)

    def _save_settings(self):
        if self.settings is None:
            return
        st = self.settings
        st.setValue("printdlg/printer", self.cb_printer.currentData())
        st.setValue("printdlg/scale", self.cb_scale.currentData())
        st.setValue("printdlg/percent", self.sp_percent.value())
        st.setValue("printdlg/nup", self.cb_nup.currentData())
        st.setValue("printdlg/orient", self.cb_orient.currentData())
        st.setValue("printdlg/margin", self.sp_margin.value())
        st.setValue("printdlg/rotate", self.chk_rotate.isChecked())
        st.setValue("printdlg/center", self.chk_center.isChecked())
        st.setValue("printdlg/gray", self.chk_gray.isChecked())
        st.setValue("printdlg/border", self.chk_border.isChecked())
        st.setValue("printdlg/duplex", self.cb_duplex.currentData())
        st.setValue("printdlg/paper", self.cb_paper.currentText().split(" ")[0] if self.cb_paper.currentIndex() else "")
        st.setValue("print/notes", self.chk_notes.isChecked())

    # ----- giá trị
    def _set_percent(self, p):
        self.cb_scale.setCurrentIndex(self.cb_scale.findData("custom"))
        self.sp_percent.setValue(max(10, min(400, p)))

    def options(self) -> PrintOptions:
        return PrintOptions(scale_mode=self.cb_scale.currentData(), percent=self.sp_percent.value(),
                            nup=self.cb_nup.currentData(), orientation=self.cb_orient.currentData(),
                            auto_rotate=self.chk_rotate.isChecked(), center=self.chk_center.isChecked(),
                            margin_mm=self.sp_margin.value(), border=self.chk_border.isChecked(),
                            gray=self.chk_gray.isChecked(), notes=self.chk_notes.isChecked(),
                            reverse=self.chk_reverse.isChecked(), subset=self.cb_subset.currentData())

    def pages(self) -> list[int]:
        n = self.doc.page_count
        if self.rb_cur.isChecked():
            return [min(max(0, self.current_page), n - 1)]
        if self.rb_pages.isChecked():
            return parse_range(self.ed_pages.text(), n)
        return list(range(n))

    def printer(self):
        """QPrinter của máy in đang chọn (tạo lại khi đổi máy in)."""
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
        target = self.cb_printer.currentData()
        if self._printer is None or self._printer_for != target:
            p = QPrinter(QPrinter.HighResolution)
            if target == PDF_TARGET:
                p.setOutputFormat(QPrinter.PdfFormat)
            else:
                info = QPrinterInfo.printerInfo(target) if target else None
                if info is not None and not info.isNull():
                    p = QPrinter(info, QPrinter.HighResolution)
            self._printer, self._printer_for = p, target
        return self._printer

    def paper_pt(self):
        v = self.cb_paper.currentData()
        if v:
            return v
        from PySide6.QtGui import QPageLayout
        r = self.printer().pageLayout().fullRect(QPageLayout.Point)
        w, h = r.width(), r.height()
        return (w, h) if w > 10 and h > 10 else (595.0, 842.0)

    def margins_pt(self):
        if self.cb_printer.currentData() == PDF_TARGET:
            return (0.0, 0.0, 0.0, 0.0)
        return printer_margins_pt(self.printer())

    # ----- xem trước
    def _changed(self, *_):
        self.sp_percent.setEnabled(self.cb_scale.currentData() == "custom")
        self.chk_border.setEnabled(self.cb_nup.currentData() != 1)
        self.btn_props.setEnabled(self.cb_printer.currentData() != PDF_TARGET)
        self._timer.start()

    def _refresh(self):
        self._changed_state()
        pages = select_pages(self.pages(), self.options())
        sizes = [self.doc.page_size_pt(i) for i in range(self.doc.page_count)]
        self._sheets = plan_sheets(sizes, pages, self.paper_pt(), self.margins_pt(), self.options()) if pages else []
        self.slider.blockSignals(True)
        self.slider.setMaximum(max(0, len(self._sheets) - 1))
        self.slider.setValue(min(self.slider.value(), self.slider.maximum()))
        self.slider.blockSignals(False)
        self.btn_print.setEnabled(bool(self._sheets))
        copies = self.sp_copies.value()
        self.btn_print.setText(f"In {len(self._sheets)} tờ" + (f" × {copies} bản" if copies > 1 else ""))
        self._draw_preview()

    def _changed_state(self):
        self.sp_percent.setEnabled(self.cb_scale.currentData() == "custom")
        self.chk_border.setEnabled(self.cb_nup.currentData() != 1)

    def _draw_preview(self):
        if not self._sheets:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Không có trang nào để in – kiểm tra lại phạm vi trang.")
            self.lbl_sheet.setText("")
            self.lbl_zoom.setText("–")
            return
        k = self.slider.value()
        sh = self._sheets[k]
        paper = self.paper_pt()
        sw, shh = sheet_size(paper, sh)
        avail = self.preview.size() - QSize(24, 24)
        px = max(0.1, min(avail.width() / sw, avail.height() / shh))
        img = preview_image(self.doc, sh, paper, self.margins_pt(), self.options(), px, self._cache)
        self.preview.setPixmap(QPixmap.fromImage(img))
        self.lbl_sheet.setText(f"Tờ {k + 1} / {len(self._sheets)}")
        slot = sh.slots[0]
        self.lbl_zoom.setText(f"{slot.scale * 100:.0f}%" + ("  (đã xoay 90°)" if slot.rotate else ""))
        w, h = self.doc.page_size_pt(slot.page)
        self.lbl_docsize.setText(f"Trang {slot.page + 1}: {w / MM:.0f} × {h / MM:.0f} mm")
        self.lbl_paper.setText(f"{sw / MM:.0f} × {shh / MM:.0f} mm ({'ngang' if sh.landscape else 'dọc'})")
        x, y, dw, dh = slot.rect
        over = x < -0.5 or y < -0.5 or x + dw > sw + 0.5 or y + dh > shh + 0.5
        base = "" if self.doc.can_print_high else "Người gửi chỉ cho phép in chất lượng thấp (150 dpi). "
        self.lbl_warn.setText(base + ("⚠ Tỉ lệ này lớn hơn khổ giấy: phần ngoài tờ giấy sẽ bị cắt." if over else ""))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._timer.start()

    # ----- in
    def _printer_props(self):
        from PySide6.QtPrintSupport import QPrintDialog
        dlg = QPrintDialog(self.printer(), self)
        dlg.setOption(QPrintDialog.PrintPageRange, False)
        if dlg.exec() == QPrintDialog.Accepted:
            self._cache.clear()
            self._refresh()

    def _do_print(self):
        from PySide6.QtPrintSupport import QPrinter
        pr = self.printer()
        if self.cb_printer.currentData() == PDF_TARGET:
            import os
            base = os.path.splitext(self.doc.name)[0] + "_ban_in.pdf"
            path, _ = QFileDialog.getSaveFileName(self, "Lưu bản in thành PDF", base, "PDF (*.pdf)")
            if not path:
                return
            pr.setOutputFileName(path)
        pr.setCopyCount(self.sp_copies.value())
        pr.setCollateCopies(self.chk_collate.isChecked())
        pr.setDuplex({"none": QPrinter.DuplexNone, "long": QPrinter.DuplexLongSide,
                      "short": QPrinter.DuplexShortSide}[self.cb_duplex.currentData()])
        pr.setColorMode(QPrinter.GrayScale if self.chk_gray.isChecked() else QPrinter.Color)
        pr.setDocName(self.doc.name)
        try:
            self.printed = print_document(self.doc, pr, self.pages(), self.options(), self.cb_paper.currentData())
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không in được:\n{e}")
            return
        self._save_settings()
        self.accept()
