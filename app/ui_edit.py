"""Giao diện giai đoạn 5: tùy chọn công cụ, hộp chữ, sửa chữ, ghi chú, tìm & thay,
chữ viết tay (phông viết tay / bộ chữ tay của chính mình), bảng vẽ tay."""
from __future__ import annotations

import io
import math
import os

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, fonts
from .theme import ui_color, ui_is_dark

PEN_COLORS = [("Đỏ", "#d32f2f"), ("Xanh", "#0d47a1"), ("Đen", "#1b1b1b"), ("Xanh lá", "#2e7d32"),
              ("Cam", "#ef6c00"), ("Tím", "#6a1b9a")]
INK_COLORS = [("Xanh bút bi", "#1a3fa8"), ("Đen", "#1b1b1b"), ("Tím mực", "#4a148c"), ("Đỏ", "#c62828")]
SYMBOLS = [("check", "✓ Dấu tích"), ("cross", "✗ Dấu nhân"), ("dot", "● Chấm tròn"), ("circle", "○ Vòng tròn"),
           ("box", "☐ Ô trống"), ("boxcheck", "☑ Ô đã tích")]
SHAPES = [("rect", "Hình chữ nhật"), ("ellipse", "Hình elip"), ("line", "Đường thẳng"), ("arrow", "Mũi tên"),
          ("highlight", "Bút dạ quang")]


def text_fonts() -> list[tuple[str, str]]:
    """(tên hiển thị, đường dẫn) – phông hệ thống có trên máy + phông viết tay đóng gói."""
    out = []
    for fam, label in fonts.FAMILY_LABEL.items():
        try:
            p = fonts.system_font(fam)
        except FileNotFoundError:
            continue
        if fam not in ("serif", "sans") and not os.path.basename(p).lower().startswith(fam[:4]):
            continue                     # máy không có đúng phông này -> bỏ, tránh trùng lặp
        out.append((label, p))
    for name in fonts.HANDWRITING:
        p = fonts.handwriting_path(name)
        if os.path.exists(p):
            out.append((name, p))
    return out


_QT_FAMILIES: dict[str, str] = {}


class WrapCheck(QWidget):
    """Ô tích có chữ tự xuống dòng (QCheckBox không xuống dòng -> chữ dài làm bảng bên phải bị cắt mất một phần).
    Dùng như QCheckBox: isChecked / setChecked / toggled / text / click; bấm vào chữ cũng tích được."""

    def __init__(self, text: str = "", parent=None, checked: bool = False):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        from PySide6.QtWidgets import QSizePolicy as _SP
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.box = QCheckBox()
        self.box.setChecked(checked)
        self.label = QLabel(text, wordWrap=True)
        self.label.setSizePolicy(_SP.Preferred, _SP.Preferred)
        self.label.setMinimumWidth(40)
        self.label.mousePressEvent = lambda ev: self.box.isEnabled() and self.box.toggle()
        h.addWidget(self.box, 0, Qt.AlignTop)
        h.addWidget(self.label, 1)
        self.toggled = self.box.toggled
        self.stateChanged = self.box.stateChanged
        self.clicked = self.box.clicked

    def isChecked(self) -> bool:
        return self.box.isChecked()

    def setChecked(self, on: bool):
        self.box.setChecked(on)

    def checkState(self):
        return self.box.checkState()

    def toggle(self):
        self.box.toggle()

    def click(self):
        self.box.click()

    def text(self) -> str:
        return self.label.text()

    def setText(self, t: str):
        self.label.setText(t)

    def setToolTip(self, t: str):
        super().setToolTip(t)
        self.box.setToolTip(t)
        self.label.setToolTip(t)


def fit_side_panel(root, width: int | None = None):
    """Bảng bên phải rộng cố định: cho ô chọn, ô số co lại được, dòng biểu mẫu tự xuống dòng khi hẹp
    (phông chữ Windows / màn hình phóng to làm chữ rộng hơn -> trước đây bảng bị cắt mất bên phải)."""
    from PySide6.QtWidgets import QAbstractSpinBox, QFormLayout, QSizePolicy as _SP
    for cb in root.findChildren(QComboBox):
        cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(4)
        cb.setSizePolicy(_SP.Expanding, cb.sizePolicy().verticalPolicy())
    for sp in root.findChildren(QAbstractSpinBox):
        sp.setMinimumWidth(min(sp.minimumSizeHint().width(), 72))
        sp.setSizePolicy(_SP.Expanding, sp.sizePolicy().verticalPolicy())
    for lay in root.findChildren(QFormLayout):
        lay.setRowWrapPolicy(QFormLayout.WrapLongRows)
        lay.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    for lb in root.findChildren(QLabel):
        if lb.wordWrap():
            lb.setMinimumWidth(0)


def qt_family(path: str) -> str:
    """Nạp phông vào Qt để xem trước đúng như trong PDF."""
    if path not in _QT_FAMILIES:
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _QT_FAMILIES[path] = fams[0] if fams else "Sans Serif"
    return _QT_FAMILIES[path]


def render_text_image(text: str, font_path: str, size_pt: float, color: str, dpi: int = 200) -> QImage:
    """Ảnh xem trước của chữ (nền trong suốt), tỉ lệ đúng với kích thước sẽ chèn."""
    lines = text.split("\n") or [""]
    w_pt = max(fonts.measure(font_path, l, size_pt) for l in lines) + 2
    asc, desc = fonts.metrics(font_path)
    h_pt = (len(lines) - 1) * size_pt * 1.25 + (asc + desc) * size_pt + 2
    k = dpi / 72
    img = QImage(max(1, int(w_pt * k)), max(1, int(h_pt * k)), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    f = QFont(qt_family(font_path))
    f.setPixelSize(max(1, int(size_pt * k)))
    p.setFont(f)
    p.setPen(QColor(color))
    for i, line in enumerate(lines):
        p.drawText(QPointF(1 * k, (asc * size_pt + i * size_pt * 1.25 + 1) * k), line)
    p.end()
    return img


def pil_to_qimage(im) -> QImage:
    b = io.BytesIO()
    im.save(b, "PNG")
    q = QImage()
    q.loadFromData(b.getvalue(), "PNG")
    return q


# ------------------------------------------------------------------ tùy chọn công cụ / thuộc tính (panel phải)
from .items import DASHES, HEADS, PENS, PEN_DEFAULT_WIDTH   # noqa: E402

ERASE_SHAPES = [("rect", "Chữ nhật"), ("ellipse", "Elip"), ("lasso", "Tự do (khoanh)"), ("brush", "Cục tẩy (cọ)")]
ERASE_FILLS = [("white", "Phủ trắng"), ("sample", "Lấy màu nền giấy"), ("none", "Không phủ (chỉ gỡ)")]
ERASE_FILTERS = [("all", "Tất cả"), ("text", "Chỉ chữ"), ("image", "Chỉ ảnh"), ("path", "Chỉ hình vẽ, đường kẻ")]
ERASE_SCOPES = [("page", "Trang này"), ("all", "Mọi trang (cùng vị trí)"), ("odd", "Các trang lẻ"),
                ("even", "Các trang chẵn"), ("selected", "Các trang đang chọn")]
ALIGNS = [("left", "Trái"), ("center", "Giữa"), ("right", "Phải")]


class _WidthPreview(QWidget):
    """Xem trước nét (màu, độ dày, độ mờ, kiểu nét, loại bút)."""

    def __init__(self, opts):
        super().__init__()
        self.opts = opts
        self.setFixedHeight(26)
        self.setMinimumWidth(50)

    def paintEvent(self, ev):
        o = self.opts
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        c = QColor(o.color)
        pen_kind = o.pen
        alpha = o.opacity / 100
        if pen_kind == "highlighter":
            alpha *= 0.45
        elif pen_kind == "pencil":
            alpha *= 0.72
        c.setAlphaF(max(0.05, min(1.0, alpha)))
        w = max(0.6, o.width * 96 / 72)
        path = QPainterPath(QPointF(8, self.height() / 2 + 4))
        path.cubicTo(QPointF(self.width() * .35, 2), QPointF(self.width() * .6, self.height() - 2),
                     QPointF(self.width() - 8, self.height() / 2 - 3))
        style = {"dash": Qt.DashLine, "dot": Qt.DotLine, "dashdot": Qt.DashDotLine}.get(o.dash, Qt.SolidLine)
        if pen_kind:
            style = Qt.SolidLine
        p.setPen(QPen(c, w, style, Qt.SquareCap if pen_kind == "highlighter" else Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.end()


class ToolOptions(QFrame):
    """Bảng tùy chọn bên phải: dùng chung cho công cụ đang vẽ và cho nội dung đang chọn (bảng thuộc tính).
    Chỉ hiện những dòng phù hợp ngữ cảnh (show_for(..., rows={...}))."""
    changed = Signal()
    closeRequested = Signal()
    zRequested = Signal(str)           # "front" | "back"
    deleteRequested = Signal()
    styleApplied = Signal(dict)        # 14e: bấm một kiểu hình đã lưu

    ALL_ROWS = ("colors", "width", "size", "opacity", "dash", "heads", "fill", "shadow", "radius", "pen",
                "smooth", "styles", "erase", "grid", "angle", "zorder", "font", "align", "delete", "editscope", "fmt")

    def __init__(self, settings=None):
        super().__init__(objectName="card")
        self.settings = settings
        self._quiet = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel("Công cụ", objectName="h")
        head.addWidget(self.title)
        head.addStretch()
        self.btn_close = QToolButton(text="✕", autoRaise=True, toolTip="Tắt công cụ (Esc)")
        head.addWidget(self.btn_close)
        v.addLayout(head)
        self.hint = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.hint)
        self.rows: dict[str, QWidget] = {}

        def row(key, *widgets, label=None):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            if label:
                lb = QLabel(label)
                lb.setMinimumWidth(58)
                h.addWidget(lb)
            for x in widgets:
                if x == "stretch":
                    h.addStretch()
                else:
                    h.addWidget(x)
            v.addWidget(w)
            self.rows[key] = w
            return w

        # bút (15a)
        self.cb_pen = QComboBox()
        for k, lbl in PENS:
            self.cb_pen.addItem(lbl, k)
        row("pen", self.cb_pen, label="Loại bút:")
        # 15d, 15e: làm mượt, tự nắn hình
        from .items import SMOOTH_LEVELS
        self.cb_smooth = QComboBox()
        for k, lbl in SMOOTH_LEVELS:
            self.cb_smooth.addItem(lbl, k)
        self.cb_smooth.setCurrentIndex(1)
        self.chk_recognize = QCheckBox("Tự nắn hình")
        self.chk_recognize.setToolTip("Vẽ tay hình tròn, chữ nhật, tam giác, đường thẳng, mũi tên -> tự thành hình chuẩn")
        sw = row("smooth", self.cb_smooth, label="Làm mượt:")
        sw.setToolTip("Giữ Shift khi vẽ tay để kẻ thẳng (thêm Alt: bắt góc 45°)")
        sw.layout().removeWidget(self.cb_smooth)          # 2 dòng: bảng bên phải hẹp, 1 dòng sẽ bị cắt
        grid = QVBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        grid.addWidget(self.cb_smooth)
        grid.addWidget(self.chk_recognize)
        sw.layout().addLayout(grid, 1)
        # màu (15b): bảng màu + chọn màu tùy ý
        self.color_btns = []
        from PySide6.QtWidgets import QGridLayout
        cw = QWidget()
        grid = QGridLayout(cw)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        palette = PEN_COLORS + [("Vàng", "#fbc02d"), ("Trắng", "#ffffff")]
        for k, (name, col) in enumerate(palette):
            b = QToolButton(toolTip=name, checkable=True, autoRaise=True)
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"QToolButton{{background:{col};border-radius:11px;border:1px solid #9e9e9e}}"
                            f"QToolButton:checked{{border:2px solid #005fb8}}")
            b.clicked.connect(lambda _=False, c=col: self.set_color(c))
            grid.addWidget(b, k // 5, k % 5)
            self.color_btns.append((b, col))
        self.btn_color = QToolButton(text="Màu khác…", toolTip="Chọn màu bất kỳ")
        self.btn_color.clicked.connect(self.pick_color)
        grid.addWidget(self.btn_color, 0, 5, 2, 1)
        grid.setColumnStretch(6, 1)
        row("colors", cw)
        # độ dày + xem trước
        self.sp_width = QDoubleSpinBox(minimum=0.3, maximum=40, singleStep=0.5, value=1.5, suffix=" pt")
        self.preview = _WidthPreview(self)
        row("width", self.sp_width, self.preview, label="Nét:")
        self.sp_size = QDoubleSpinBox(minimum=4, maximum=200, value=12, suffix=" pt")
        self.lbl_size = QLabel("Cỡ:")
        self.lbl_size.setMinimumWidth(58)
        self.lbl_size.setWordWrap(True)
        w = row("size", self.sp_size, "stretch")
        w.layout().insertWidget(0, self.lbl_size)
        from PySide6.QtWidgets import QSlider
        self.sl_opacity = QSlider(Qt.Horizontal, minimum=10, maximum=100, value=100)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setMinimumWidth(36)
        row("opacity", self.sl_opacity, self.lbl_opacity, label="Độ đậm:")
        self.cb_dash = QComboBox()
        for k, lbl in DASHES:
            self.cb_dash.addItem(lbl, k)
        row("dash", self.cb_dash, label="Kiểu nét:")
        self.cb_heads = QComboBox()
        for k, lbl in HEADS:
            self.cb_heads.addItem(lbl, k)
        row("heads", self.cb_heads, label="Đầu mũi tên:")
        self.chk_fill = QCheckBox("Tô màu")
        self.btn_fill = QToolButton(toolTip="Màu tô")
        self.btn_fill.setFixedSize(26, 22)
        self.btn_fill.clicked.connect(self.pick_fill)
        self.sl_fill = QSlider(Qt.Horizontal, minimum=0, maximum=100, value=40, toolTip="Độ đậm màu tô")
        row("fill", self.chk_fill, self.btn_fill, self.sl_fill)
        self.chk_shadow = QCheckBox("Bóng đổ")
        self.sp_radius = QDoubleSpinBox(minimum=0, maximum=60, value=0, suffix=" pt")
        row("shadow", self.chk_shadow, "stretch")
        row("radius", self.sp_radius, "stretch", label="Bo góc:")
        # 14e: kiểu hình đã lưu
        stw = QWidget()
        self._styles_lay = QHBoxLayout(stw)
        self._styles_lay.setContentsMargins(0, 0, 0, 0)
        self._styles_lay.setSpacing(3)
        self.btn_save_style = QToolButton(text="+", toolTip="Lưu kiểu hiện tại (màu, nét, tô, bóng…) để dùng lại")
        self.btn_save_style.clicked.connect(self.save_style)
        row("styles", stw, label="Kiểu đã lưu:")
        self.style_buttons = []
        # văn bản
        self.cb_font = QComboBox()
        for lbl, path in text_fonts():
            self.cb_font.addItem(lbl, path)
        row("font", self.cb_font, label="Phông:")
        self.cb_align = QComboBox()
        for k, lbl in ALIGNS:
            self.cb_align.addItem(lbl, k)
        row("align", self.cb_align, label="Canh lề:")
        # 11b, 11c, 11d: sửa chữ có sẵn
        self.cb_scope = QComboBox()
        for k, lbl in (("run", "Mảnh chữ"), ("line", "Cả dòng"), ("para", "Cả đoạn")):
            self.cb_scope.addItem(lbl, k)
        self.cb_scope.setCurrentIndex(1)
        self.chk_fit = WrapCheck("Chữ dài hơn thì tự co cho vừa chỗ cũ", checked=True)
        self.chk_fit.setToolTip("Chữ mới dài hơn chỗ cũ thì tự thu nhỏ cỡ chữ cho vừa (tránh đè lên chữ bên cạnh)")
        ew2 = QWidget()
        ev2 = QVBoxLayout(ew2)
        ev2.setContentsMargins(0, 0, 0, 0)
        ev2.setSpacing(4)
        r1 = QHBoxLayout()
        lb = QLabel("Sửa:")
        lb.setMinimumWidth(58)
        r1.addWidget(lb)
        r1.addWidget(self.cb_scope, 1)
        ev2.addLayout(r1)
        ev2.addWidget(self.chk_fit)
        v.addWidget(ew2)
        self.rows["editscope"] = ew2
        self.cb_family = QComboBox()
        self.cb_family.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_family.setMinimumContentsLength(6)
        self.cb_family.addItem("Giữ phông gốc", "")
        for fam, lbl in fonts.FAMILY_LABEL.items():
            self.cb_family.addItem(lbl, fam)
        self.btn_bold = QToolButton(text="B", checkable=True, toolTip="Đậm")
        self.btn_bold.setStyleSheet("QToolButton{font-weight:bold}")
        self.btn_bold.setFixedWidth(26)
        self.btn_italic = QToolButton(text="I", checkable=True, toolTip="Nghiêng")
        self.btn_italic.setStyleSheet("QToolButton{font-style:italic}")
        self.btn_italic.setFixedWidth(26)
        row("fmt", self.cb_family, self.btn_bold, self.btn_italic, label="Kiểu chữ:")
        # tẩy vùng (16)
        ew = QWidget()
        ef = QFormLayout(ew)
        ef.setContentsMargins(0, 0, 0, 0)
        self.cb_erase_shape = QComboBox()
        for k, lbl in ERASE_SHAPES:
            self.cb_erase_shape.addItem(lbl, k)
        self.sp_brush = QDoubleSpinBox(minimum=2, maximum=120, value=14, suffix=" pt", toolTip="Cỡ cục tẩy")
        self.cb_erase_fill = QComboBox()
        for k, lbl in ERASE_FILLS:
            self.cb_erase_fill.addItem(lbl, k)
        self.cb_erase_filter = QComboBox()
        for k, lbl in ERASE_FILTERS:
            self.cb_erase_filter.addItem(lbl, k)
        self.cb_erase_scope = QComboBox()
        for k, lbl in ERASE_SCOPES:
            self.cb_erase_scope.addItem(lbl, k)
        self.cb_erase_scope.setToolTip("Tẩy cùng một vùng trên nhiều trang – xóa logo, số trang, dấu cũ lặp lại")
        self.chk_erase_preview = WrapCheck("Xem trước vùng khoanh (đỏ mờ) để chỉnh trước khi tẩy")
        self.chk_magnifier = WrapCheck("Kính lúp khi khoanh vùng")
        ef.addRow("Hình tẩy:", self.cb_erase_shape)
        ef.addRow("Cỡ cọ:", self.sp_brush)
        self._erase_form = ef
        ef.addRow("Màu phủ:", self.cb_erase_fill)
        ef.addRow("Gỡ đối tượng:", self.cb_erase_filter)
        ef.addRow("Áp dụng cho:", self.cb_erase_scope)
        ef.addRow(self.chk_erase_preview)
        ef.addRow(self.chk_magnifier)
        v.addWidget(ew)
        self.rows["erase"] = ew
        # lưới (14c)
        self.chk_grid = QCheckBox("Bắt lưới")
        self.sp_grid = QDoubleSpinBox(minimum=1, maximum=50, value=5, suffix=" mm")
        self.chk_show_grid = QCheckBox("Hiện lưới")
        row("grid", self.chk_grid, self.sp_grid, self.chk_show_grid)
        for cb in self.findChildren(QComboBox):          # bảng hẹp (300 px): hộp chọn co theo chỗ
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        # xoay, lớp, xóa (13e)
        self.sp_angle = QDoubleSpinBox(minimum=-360, maximum=360, value=0, suffix="°", wrapping=True)
        row("angle", self.sp_angle, "stretch", label="Xoay:")
        self.btn_front = QPushButton("Lên trên", toolTip="Đưa lên trên cùng (che lên chữ, hình khác)")
        self.btn_back = QPushButton("Xuống dưới", toolTip="Đưa xuống dưới cùng (nằm dưới chữ của trang)")
        self.btn_front.clicked.connect(lambda: self.zRequested.emit("front"))
        self.btn_back.clicked.connect(lambda: self.zRequested.emit("back"))
        row("zorder", self.btn_front, self.btn_back)
        self.btn_delete = QPushButton("Xóa nội dung này")
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        row("delete", self.btn_delete, "stretch")

        self._color = PEN_COLORS[0][1]
        self._fill = "#90caf9"
        st = settings
        if st is not None:
            self._color = st.value("tool/color", self._color) or self._color
            self._fill = st.value("tool/fill", self._fill) or self._fill

            def f(key, default):
                try:
                    return float(st.value(key, default))
                except (TypeError, ValueError):
                    return default
            self.sp_width.setValue(f("tool/width", 1.5))
            self.sp_size.setValue(f("tool/size", 14))
            self.sl_opacity.setValue(int(f("tool/opacity", 100)))
            self.sl_fill.setValue(int(f("tool/fill_opacity", 40)))
            self.sp_brush.setValue(f("erase/brush", 14))
            self.sp_grid.setValue(f("tool/grid_mm", 5))
            self.sp_radius.setValue(f("tool/radius", 0))
            for cb, key in ((self.cb_dash, "tool/dash"), (self.cb_heads, "tool/heads"), (self.cb_pen, "tool/pen"),
                            (self.cb_erase_shape, "erase/shape"), (self.cb_erase_fill, "erase/fill"),
                            (self.cb_erase_filter, "erase/filter")):
                k = cb.findData(st.value(key, ""))
                if k >= 0:
                    cb.setCurrentIndex(k)
            self.chk_fill.setChecked(str(st.value("tool/fill_on", "false")).lower() == "true")
            self.chk_shadow.setChecked(str(st.value("tool/shadow", "false")).lower() == "true")
            self.chk_erase_preview.setChecked(str(st.value("erase/preview", "true")).lower() == "true")
            self.chk_magnifier.setChecked(str(st.value("erase/magnifier", "true")).lower() == "true")
            self.chk_grid.setChecked(str(st.value("tool/grid", "false")).lower() == "true")
            self.chk_show_grid.setChecked(str(st.value("tool/show_grid", "false")).lower() == "true")
        else:
            self.chk_erase_preview.setChecked(True)
            self.chk_magnifier.setChecked(True)
        self._paint_fill_btn()
        self.set_color(self._color)
        if st is not None:
            try:
                self.cb_smooth.setCurrentIndex(max(0, self.cb_smooth.findData(int(float(st.value("tool/smooth", 1))))))
            except (TypeError, ValueError):
                pass
            self.chk_recognize.setChecked(str(st.value("tool/recognize", "false")).lower() == "true")
        self._rebuild_styles()
        for sig in (self.sp_width.valueChanged, self.sp_size.valueChanged, self.sl_opacity.valueChanged,
                    self.cb_dash.currentIndexChanged, self.cb_heads.currentIndexChanged, self.chk_fill.toggled,
                    self.sl_fill.valueChanged, self.chk_shadow.toggled, self.sp_radius.valueChanged,
                    self.cb_pen.currentIndexChanged, self.cb_erase_shape.currentIndexChanged,
                    self.cb_erase_fill.currentIndexChanged, self.cb_erase_filter.currentIndexChanged,
                    self.chk_erase_preview.toggled, self.chk_magnifier.toggled, self.sp_brush.valueChanged,
                    self.chk_grid.toggled, self.sp_grid.valueChanged, self.chk_show_grid.toggled,
                    self.sp_angle.valueChanged, self.cb_font.currentIndexChanged, self.cb_align.currentIndexChanged,
                    self.cb_smooth.currentIndexChanged, self.chk_recognize.toggled, self.cb_scope.currentIndexChanged,
                    self.chk_fit.toggled, self.cb_family.currentIndexChanged, self.btn_bold.toggled,
                    self.btn_italic.toggled):
            sig.connect(self._save)
        self.cb_pen.currentIndexChanged.connect(self._pen_changed)
        self.btn_close.clicked.connect(self.closeRequested.emit)
        self.setVisible(False)

    # ---------- màu ----------
    def set_color(self, col: str):
        self._color = col
        for b, c in self.color_btns:
            b.setChecked(c.lower() == (col or "").lower())
        self.btn_color.setStyleSheet("" if any(b.isChecked() for b, _ in self.color_btns) else
                                     f"QToolButton{{background:{col};color:{'#000' if QColor(col).lightness() > 150 else '#fff'};border:2px solid #005fb8}}")
        self._save()

    def pick_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self._color), self, "Chọn màu")
        if c.isValid():
            self.set_color(c.name())

    def pick_fill(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self._fill), self, "Chọn màu tô")
        if c.isValid():
            self._fill = c.name()
            self._paint_fill_btn()
            self.chk_fill.setChecked(True)
            self._save()

    def _paint_fill_btn(self):
        self.btn_fill.setStyleSheet(f"QToolButton{{background:{self._fill};border:1px solid #9e9e9e}}")

    def _pen_changed(self, *_):
        if self._quiet:
            return
        pen = self.pen
        if pen:
            self._quiet = True
            self.sp_width.setValue(PEN_DEFAULT_WIDTH.get(pen, 1.2))
            if pen == "highlighter" and self._color.lower() not in ("#fbc02d", "#ffe600"):
                self.set_color("#fbc02d")
            self._quiet = False
            self._save()

    def _save(self, *_):
        self.lbl_opacity.setText(f"{self.sl_opacity.value()}%")
        brush = self.cb_erase_shape.currentData() == "brush"
        if hasattr(self._erase_form, "setRowVisible"):
            self._erase_form.setRowVisible(self.sp_brush, brush)
        else:
            self.sp_brush.setVisible(brush)
        self.preview.update()
        if self._quiet:
            return
        if self.settings is not None and not getattr(self, "_item_mode", False):
            st = self.settings
            st.setValue("tool/color", self._color)
            st.setValue("tool/width", self.sp_width.value())
            st.setValue("tool/size", self.sp_size.value())
            st.setValue("tool/opacity", self.sl_opacity.value())
            st.setValue("tool/fill", self._fill)
            st.setValue("tool/fill_on", self.chk_fill.isChecked())
            st.setValue("tool/fill_opacity", self.sl_fill.value())
            st.setValue("tool/dash", self.cb_dash.currentData())
            st.setValue("tool/heads", self.cb_heads.currentData())
            st.setValue("tool/shadow", self.chk_shadow.isChecked())
            st.setValue("tool/radius", self.sp_radius.value())
            st.setValue("tool/pen", self.cb_pen.currentData())
            st.setValue("erase/shape", self.cb_erase_shape.currentData())
            st.setValue("erase/fill", self.cb_erase_fill.currentData())
            st.setValue("erase/filter", self.cb_erase_filter.currentData())
            st.setValue("erase/preview", self.chk_erase_preview.isChecked())
            st.setValue("erase/magnifier", self.chk_magnifier.isChecked())
            st.setValue("erase/brush", self.sp_brush.value())
            st.setValue("tool/grid", self.chk_grid.isChecked())
            st.setValue("tool/grid_mm", self.sp_grid.value())
            st.setValue("tool/show_grid", self.chk_show_grid.isChecked())
            st.setValue("tool/smooth", self.cb_smooth.currentData())
            st.setValue("tool/recognize", self.chk_recognize.isChecked())
        self.changed.emit()

    # ---------- 14e: kiểu hình đã lưu ----------
    STYLE_KEYS = ("stroke", "width", "opacity", "dash", "heads", "fill", "fill_opacity", "shadow", "radius")

    def saved_styles(self) -> list[dict]:
        if self.settings is None:
            return getattr(self, "_mem_styles", [])
        import json
        try:
            return json.loads(self.settings.value("shape/styles", "") or "[]")
        except Exception:
            return []

    def _store_styles(self, lst):
        import json
        if self.settings is None:
            self._mem_styles = lst
        else:
            self.settings.setValue("shape/styles", json.dumps(lst[:10]))
        self._rebuild_styles()

    def current_style(self) -> dict:
        st = self.style()
        return {k: st.get(k) for k in self.STYLE_KEYS}

    def save_style(self):
        cur = self.current_style()
        lst = [x for x in self.saved_styles() if x != cur]
        self._store_styles([cur] + lst)

    def remove_style(self, k: int):
        lst = self.saved_styles()
        if 0 <= k < len(lst):
            lst.pop(k)
            self._store_styles(lst)

    def apply_style(self, st: dict):
        self._quiet = True
        if st.get("stroke"):
            self.set_color(st["stroke"])
        self.sp_width.setValue(float(st.get("width") or 1.5))
        self.sl_opacity.setValue(int(st.get("opacity") or 100))
        self.cb_dash.setCurrentIndex(max(0, self.cb_dash.findData(st.get("dash") or "solid")))
        if st.get("heads"):
            self.cb_heads.setCurrentIndex(max(0, self.cb_heads.findData(st["heads"])))
        self.chk_fill.setChecked(bool(st.get("fill")))
        if st.get("fill"):
            self._fill = st["fill"]
            self._paint_fill_btn()
        self.sl_fill.setValue(int(st.get("fill_opacity") or 40))
        self.chk_shadow.setChecked(bool(st.get("shadow")))
        self.sp_radius.setValue(float(st.get("radius") or 0))
        self._quiet = False
        self._save()
        self.styleApplied.emit(st)

    def _rebuild_styles(self):
        lay = self._styles_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None and w is not self.btn_save_style:
                w.deleteLater()
        self.style_buttons = []
        for k, st in enumerate(self.saved_styles()[:6]):
            b = QToolButton(toolTip="Bấm: dùng kiểu này · Chuột phải: xóa")
            b.setFixedSize(26, 22)
            pm = QPixmap(22, 16)
            pm.fill(Qt.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.Antialiasing)
            c = QColor(st.get("fill") or "#ffffff")
            c.setAlpha(int(255 * (st.get("fill_opacity") or 40) / 100) if st.get("fill") else 0)
            pp.setBrush(c)
            style = {"dash": Qt.DashLine, "dot": Qt.DotLine, "dashdot": Qt.DashDotLine}.get(st.get("dash"), Qt.SolidLine)
            pp.setPen(QPen(QColor(st.get("stroke") or "#000000"), max(1.0, min(4.0, float(st.get("width") or 1.5))),
                           style))
            pp.drawRoundedRect(2, 2, 18, 12, float(st.get("radius") or 0) / 3, float(st.get("radius") or 0) / 3)
            pp.end()
            b.setIcon(QIcon(pm))
            b.setIconSize(pm.size())
            b.clicked.connect(lambda _=False, st=st: self.apply_style(st))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, k=k: self.remove_style(k))
            lay.addWidget(b)
            self.style_buttons.append(b)
        lay.addWidget(self.btn_save_style)
        lay.addStretch()

    # ---------- giá trị ----------
    @property
    def color(self) -> str:
        return self._color

    @property
    def width(self) -> float:
        return self.sp_width.value()

    @property
    def size(self) -> float:
        return self.sp_size.value()

    @property
    def opacity(self) -> int:
        return self.sl_opacity.value()

    @property
    def dash(self) -> str:
        return self.cb_dash.currentData() or "solid"

    @property
    def pen(self) -> str:
        return self.cb_pen.currentData() if self.rows["pen"].isVisibleTo(self) else ""

    @property
    def grid_pt(self) -> float:
        return self.sp_grid.value() / 25.4 * 72 if self.chk_grid.isChecked() else 0.0

    def style(self) -> dict:
        """Kiểu nét / tô hiện tại cho hình vẽ."""
        return {"stroke": self._color, "width": self.sp_width.value(), "opacity": self.sl_opacity.value(),
                "dash": self.dash, "heads": self.cb_heads.currentData(),
                "fill": self._fill if self.chk_fill.isChecked() else None, "fill_opacity": self.sl_fill.value(),
                "shadow": self.chk_shadow.isChecked(), "radius": self.sp_radius.value()}

    def erase_opts(self) -> dict:
        return {"shape": self.cb_erase_shape.currentData(), "fill": self.cb_erase_fill.currentData(),
                "scope": self.cb_erase_scope.currentData(),
                "filter": self.cb_erase_filter.currentData(), "preview": self.chk_erase_preview.isChecked(),
                "magnifier": self.chk_magnifier.isChecked(), "size": self.sp_brush.value()}

    def _state(self) -> dict:
        return {"color": self._color, "fill": self._fill, "width": self.sp_width.value(), "size": self.sp_size.value(),
                "opacity": self.sl_opacity.value(), "dash": self.cb_dash.currentIndex(),
                "heads": self.cb_heads.currentIndex(), "fill_on": self.chk_fill.isChecked(),
                "fill_op": self.sl_fill.value(), "shadow": self.chk_shadow.isChecked(),
                "radius": self.sp_radius.value(), "pen": self.cb_pen.currentIndex(), "angle": self.sp_angle.value(),
                "smooth": self.cb_smooth.currentIndex(), "font": self.cb_font.currentIndex(),
                "lbl_size": self.lbl_size.text()}

    def _restore(self, st: dict):
        self._quiet = True
        self._fill = st["fill"]
        self._paint_fill_btn()
        self.set_color(st["color"])
        self.sp_width.setValue(st["width"])
        self.sp_size.setValue(st["size"])
        self.sl_opacity.setValue(st["opacity"])
        self.cb_dash.setCurrentIndex(st["dash"])
        self.cb_heads.setCurrentIndex(st["heads"])
        self.chk_fill.setChecked(st["fill_on"])
        self.sl_fill.setValue(st["fill_op"])
        self.chk_shadow.setChecked(st["shadow"])
        self.sp_radius.setValue(st["radius"])
        self.cb_pen.setCurrentIndex(st["pen"])
        self.sp_angle.setValue(st["angle"])
        self.cb_smooth.setCurrentIndex(st.get("smooth", 1))
        self.cb_font.setCurrentIndex(st.get("font", 0))
        self.lbl_size.setText(st["lbl_size"])
        self._quiet = False

    def show_for(self, title: str, hint: str, width: bool = True, size: bool = False, rows=None):
        """rows: tập các dòng cần hiện (xem ALL_ROWS). Không truyền: màu + nét/cỡ như trước."""
        saved = getattr(self, "_tool_state", None)
        if saved is not None:                  # vừa sửa nội dung đã chọn -> trả lại tùy chọn của công cụ
            self._tool_state = None
            self._restore(saved)
        self._item_mode = False
        self.title.setText(title)
        self.hint.setText(hint)
        self.btn_close.setToolTip("Tắt công cụ (Esc)")
        if rows is None:
            rows = {"colors"} | ({"width"} if width else set()) | ({"size"} if size else set())
        for k, w in self.rows.items():
            w.setVisible(k in rows)
        self.sp_width.setVisible("width" in rows)
        self.sp_size.setVisible("size" in rows)
        self.lbl_size.setVisible("size" in rows)
        self.setVisible(True)

    def show_item(self, spec: dict, label: str):
        """Bảng thuộc tính của nội dung đang chọn (13e)."""
        from .items import LINE_SHAPES, SYMBOL_SHAPES
        if getattr(self, "_tool_state", None) is None:
            self._tool_state = self._state()
        self._quiet = True
        self._item_mode = True
        kind = spec.get("kind")
        rows = {"angle", "zorder", "delete", "opacity"}
        if kind == "text":
            rows |= {"colors", "size", "font", "align"}
            self.set_color(spec.get("color", "#000000"))
            self.sp_size.setValue(float(spec.get("size", 12)))
            self.lbl_size.setText("Cỡ chữ:")
            k = self.cb_font.findData(spec.get("font", ""))
            if k < 0 and spec.get("font"):
                import os
                self.cb_font.addItem(os.path.basename(spec["font"]), spec["font"])
                k = self.cb_font.count() - 1
            if k >= 0:
                self.cb_font.setCurrentIndex(k)
            self.cb_align.setCurrentIndex(max(0, self.cb_align.findData(spec.get("align", "left"))))
        elif kind == "ink":
            rows |= {"colors", "width", "pen", "smooth"}
            self.cb_smooth.setCurrentIndex(max(0, self.cb_smooth.findData(int(spec.get("smooth", 1)))))
            self.set_color(spec.get("stroke", "#0d47a1"))
            self.sp_width.setValue(float(spec.get("width", 1.2)))
            self.cb_pen.setCurrentIndex(max(0, self.cb_pen.findData(spec.get("pen", "ball"))))
        else:
            shape = spec.get("shape", "")
            rows |= {"colors", "width", "dash"}
            if shape in LINE_SHAPES:
                rows |= {"heads", "styles"}
            elif shape not in SYMBOL_SHAPES and shape not in ("check", "cross", "highlight"):
                rows |= {"fill", "shadow", "radius", "styles", "size", "font"}
                self.sp_size.setValue(float(spec.get("text_size", 11)))
                self.lbl_size.setText("Cỡ chữ trong hình:")
                k = self.cb_font.findData(spec.get("font", ""))
                self.cb_font.setCurrentIndex(max(0, k))
            if shape == "highlight":
                rows = {"colors", "opacity", "zorder", "delete", "angle"}
            self.set_color(spec.get("stroke") or spec.get("fill") or "#d32f2f")
            self.sp_width.setValue(float(spec.get("width", 1.5)))
            self.cb_dash.setCurrentIndex(max(0, self.cb_dash.findData(spec.get("dash", "solid"))))
            self.cb_heads.setCurrentIndex(max(0, self.cb_heads.findData(spec.get("heads", "none"))))
            self.chk_fill.setChecked(bool(spec.get("fill")))
            if spec.get("fill"):
                self._fill = spec["fill"]
                self._paint_fill_btn()
            self.sl_fill.setValue(int(spec.get("fill_opacity", 40)))
            self.chk_shadow.setChecked(bool(spec.get("shadow")))
            self.sp_radius.setValue(float(spec.get("radius", 0) or 0))
        self.sl_opacity.setValue(int(spec.get("opacity", 100)))
        self.sp_angle.setValue(float(spec.get("angle", 0) or 0))
        self.title.setText(label)
        self.hint.setText("Kéo để di chuyển, kéo góc đổi cỡ, núm tròn để xoay. "
                          + ("Nháy đúp để sửa chữ ngay trên trang. " if kind == "text" else "")
                          + "Delete: xóa · Enter/bấm ra ngoài: xong · Esc: bỏ thay đổi.")
        self.btn_close.setToolTip("Xong")
        for k, w in self.rows.items():
            w.setVisible(k in rows)
        self.sp_width.setVisible("width" in rows)
        self.sp_size.setVisible("size" in rows)
        self.lbl_size.setVisible("size" in rows)
        self.setVisible(True)
        self._quiet = False

    def apply_to(self, spec: dict) -> dict:
        """Spec mới theo các giá trị trên bảng thuộc tính."""
        s = dict(spec)
        kind = s.get("kind")
        s["opacity"] = self.sl_opacity.value()
        s["angle"] = self.sp_angle.value() % 360
        if kind == "text":
            s["color"] = self._color
            s["size"] = self.sp_size.value()
            s["font"] = self.cb_font.currentData() or s.get("font", "")
            s["align"] = self.cb_align.currentData()
        elif kind == "ink":
            s["stroke"] = self._color
            old_w = float(spec.get("width", 1.2))
            s["width"] = self.sp_width.value()
            s["pen"] = self.cb_pen.currentData()
            s["smooth"] = self.cb_smooth.currentData()
            if s.get("widths") and old_w > 0 and abs(old_w - s["width"]) > 1e-6:
                k = s["width"] / old_w
                s["widths"] = [[w * k for w in ws] for ws in s["widths"]]
        else:
            if s.get("shape") == "highlight":
                s["fill"] = self._color
            else:
                s["stroke"] = self._color
                s["width"] = self.sp_width.value()
                s["dash"] = self.dash
                if self.rows["heads"].isVisibleTo(self):
                    s["heads"] = self.cb_heads.currentData()
                if self.rows["fill"].isVisibleTo(self):
                    s["fill"] = self._fill if self.chk_fill.isChecked() else None
                    s["fill_opacity"] = self.sl_fill.value()
                    s["shadow"] = self.chk_shadow.isChecked()
                    s["radius"] = self.sp_radius.value()
                if self.rows["size"].isVisibleTo(self):          # chữ trong hình
                    s["text_size"] = self.sp_size.value()
                    s["font"] = self.cb_font.currentData() or s.get("font", "")
        return s


# ------------------------------------------------------------------ tùy chọn ảnh khi chèn / sửa
IMAGE_LAYERS = [("top", "Nổi trên chữ"), ("multiply", "Hòa trộn như mực thật"), ("behind", "Chìm dưới chữ")]
IMAGE_SCOPES = [("current", "Trang hiện tại"), ("selected", "Các trang đang chọn"), ("all", "Tất cả các trang"),
                ("but_last", "Mọi trang trừ trang cuối (ký nháy)"), ("odd", "Các trang lẻ"), ("even", "Các trang chẵn")]


class ImageOptions(QFrame):
    """Bảng tùy chọn ảnh (bên phải) khi đang đặt ảnh, con dấu, chữ ký, chữ viết tay lên trang:
    lớp (nổi trên / hòa trộn / chìm dưới chữ), độ đậm, góc xoay, xóa nền trắng, đóng lên nhiều trang."""
    changed = Signal()

    def __init__(self, settings=None):
        super().__init__(objectName="card")
        from PySide6.QtWidgets import QSlider
        self.settings = settings
        self._edit = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel("Tùy chọn ảnh", objectName="h")
        head.addWidget(self.title)
        head.addStretch()
        v.addLayout(head)
        f = QFormLayout()
        f.setSpacing(6)
        self.cb_layer = QComboBox()
        for k, lab in IMAGE_LAYERS:
            self.cb_layer.addItem(lab, k)
        self.cb_layer.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_layer.setMinimumContentsLength(12)
        self.cb_layer.setToolTip("Nổi trên chữ: ảnh che chữ bên dưới.\n"
                                 "Hòa trộn: chữ đen vẫn hiện xuyên qua mực – giống dấu đóng thật (khuyên dùng cho dấu).\n"
                                 "Chìm dưới chữ: ảnh nằm dưới chữ, hình, bảng (trang văn bản).")
        f.addRow("Lớp:", self.cb_layer)
        row = QHBoxLayout()
        self.sl_opacity = QSlider(Qt.Horizontal, minimum=10, maximum=100, value=100)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setFixedWidth(34)
        row.addWidget(self.sl_opacity, 1)
        row.addWidget(self.lbl_opacity)
        self.lbl_op_cap = QLabel("Độ đậm:")
        f.addRow(self.lbl_op_cap, row)
        self.sp_angle = QDoubleSpinBox(minimum=-180, maximum=180, singleStep=1, decimals=0, suffix="°")
        self.sp_angle.setWrapping(True)
        self.lbl_angle = QLabel("Xoay:")
        f.addRow(self.lbl_angle, self.sp_angle)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.btn_left = QToolButton(text="⟲90°", toolTip="Xoay trái 90°")
        self.btn_right = QToolButton(text="⟳90°", toolTip="Xoay phải 90°")
        self.btn_tilt = QToolButton(text="Nghiêng", toolTip="Nghiêng nhẹ ngẫu nhiên như dấu đóng tay thật")
        self.btn_zero = QToolButton(text="0°", toolTip="Về thẳng")
        for b in (self.btn_left, self.btn_right, self.btn_tilt, self.btn_zero):
            b.setStyleSheet("padding: 2px 5px;")
            row.addWidget(b)
        row.addStretch()
        self.rot_row = QWidget()
        self.rot_row.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        v.addLayout(f)
        v.addWidget(self.rot_row)
        f = QFormLayout()
        f.setSpacing(6)
        self.cb_scope = QComboBox()
        for k, lab in IMAGE_SCOPES:
            self.cb_scope.addItem(lab, k)
        self.cb_scope.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_scope.setMinimumContentsLength(12)
        self.lbl_scope = QLabel("Đóng lên:")
        for lab in (self.lbl_scope, self.lbl_angle, self.lbl_op_cap):
            lab.setMinimumWidth(64)
        f.addRow(self.lbl_scope, self.cb_scope)
        v.addLayout(f)
        self.chk_bg = WrapCheck("Xóa nền trắng (ảnh chụp/scan)")
        self.chk_bg.setToolTip("Làm nền giấy trắng/xám nhạt của ảnh chụp, ảnh scan con dấu, chữ ký thành trong suốt")
        v.addWidget(self.chk_bg)
        self.hint = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.hint)
        if settings is not None:
            k = settings.value("img/layer", "top") or "top"
            i = self.cb_layer.findData(k)
            self.cb_layer.setCurrentIndex(max(i, 0))
            try:
                self.sl_opacity.setValue(int(float(settings.value("img/opacity", 100) or 100)))
            except (TypeError, ValueError):
                pass
        self.lbl_opacity.setText(f"{self.sl_opacity.value()}%")
        self.cb_layer.currentIndexChanged.connect(self._on_change)
        self.sl_opacity.valueChanged.connect(self._on_change)
        self.sp_angle.valueChanged.connect(self._on_change)
        self.cb_scope.currentIndexChanged.connect(self._on_change)
        self.chk_bg.toggled.connect(self._on_change)
        self.btn_left.clicked.connect(lambda: self.rotate_by(-90))
        self.btn_right.clicked.connect(lambda: self.rotate_by(90))
        self.btn_zero.clicked.connect(lambda: self.sp_angle.setValue(0))
        self.btn_tilt.clicked.connect(self.tilt)
        self._update_hint()
        self.setVisible(False)

    # ---- giá trị
    @property
    def layer(self) -> str:
        k = self.cb_layer.currentData()
        return getattr(self, "_current_layer", "top") if k == "keep" else k

    @property
    def opacity(self) -> int:
        return self.sl_opacity.value()

    @property
    def angle(self) -> float:
        return float(self.sp_angle.value())

    @property
    def scope(self) -> str:
        return self.cb_scope.currentData()

    @property
    def remove_bg(self) -> bool:
        return self.chk_bg.isVisible() and self.chk_bg.isChecked()

    def rotate_by(self, deg: float):
        a = self.sp_angle.value() + deg
        while a > 180:
            a -= 360
        while a <= -180:
            a += 360
        self.sp_angle.setValue(a)

    def set_angle(self, a: float):
        """Góc từ khung trên trang (vừa kéo núm xoay) -> ô Xoay, đưa về (-180, 180]."""
        a = float(a) % 360
        if a > 180:
            a -= 360
        self.sp_angle.setValue(round(a))

    def tilt(self):
        import random
        a = random.choice([-1, 1]) * random.uniform(3, 9)
        self.sp_angle.setValue(round(a))

    def _update_hint(self):
        self.lbl_opacity.setText(f"{self.sl_opacity.value()}%")
        hints = {"keep": "",
                 "top": "Ảnh che chữ bên dưới (phần nền trong suốt vẫn thấy chữ).",
                 "multiply": "Chữ đen vẫn hiện xuyên qua mực, giống dấu đóng thật. Dùng được cả trang scan.",
                 "behind": "Ảnh nằm dưới chữ, hình vẽ, ô bảng có màu nền. Trang scan hoặc file đã ký số sẽ tự "
                           "dùng “Hòa trộn” (nhìn giống hệt)."}
        extra = "" if not self._edit else ("\nẢnh đã chèn: đổi lớp, độ đậm (100% = như hiện tại) rồi Enter để "
                                           "áp dụng.")
        self.hint.setText(hints.get(self.cb_layer.currentData(), hints.get(self.layer, "")) + extra)

    def _on_change(self, *_):
        self._update_hint()
        if self.settings is not None and not self._edit:
            self.settings.setValue("img/layer", self.layer)
            self.settings.setValue("img/opacity", self.opacity)
        self.changed.emit()

    def show_for(self, title: str, scope: bool = True, remove_bg: bool = False, edit: bool = False,
                 current_layer: str | None = None, angle: float = 0.0, rotate: bool = True):
        """Hiện bảng khi bắt đầu đặt ảnh. edit=True: sửa ảnh đã chèn (không nhân trang).
        rotate=False: ẩn ô xoay (ảnh có sẵn bị lật/xô nghiêng)."""
        self._edit = edit
        for w in (self.sp_angle, self.sp_angle, self.btn_left, self.btn_right, self.btn_tilt, self.btn_zero,
                  self.lbl_angle, self.cb_scope, self.lbl_scope, self.chk_bg):
            w.blockSignals(True)
        a = float(angle or 0) % 360
        self.sp_angle.setValue(round(a - 360 if a > 180 else a))
        self.cb_scope.setCurrentIndex(0)
        self.chk_bg.setChecked(False)
        for w in (self.sp_angle, self.rot_row, self.lbl_angle):
            w.setVisible(rotate)
        self.cb_scope.setVisible(scope and not edit)
        self.lbl_scope.setVisible(scope and not edit)
        self.chk_bg.setVisible(remove_bg and not edit)
        for w in (self.sp_angle, self.btn_left, self.btn_right, self.btn_tilt, self.btn_zero, self.lbl_angle,
                  self.cb_scope, self.lbl_scope, self.chk_bg):
            w.blockSignals(False)
        self.cb_layer.blockSignals(True)
        self.sl_opacity.blockSignals(True)
        if self.cb_layer.findData("keep") >= 0:
            self.cb_layer.removeItem(self.cb_layer.findData("keep"))
        if edit:                                   # sửa ảnh đã chèn: mặc định giữ nguyên, 100% = như hiện tại
            self._saved_state = (self.layer, self.opacity)
            known = dict(IMAGE_LAYERS).get(current_layer or "")
            self.cb_layer.insertItem(0, f"Giữ nguyên ({known.lower()})" if known else "Giữ nguyên lớp hiện tại",
                                     "keep")
            self.cb_layer.setCurrentIndex(0)
            self.sl_opacity.setValue(100)
            self._edit_start = ("keep", 100)
            self._current_layer = current_layer or "top"
        elif getattr(self, "_saved_state", None):
            lay, op = self._saved_state
            self.cb_layer.setCurrentIndex(max(0, self.cb_layer.findData(lay)))
            self.sl_opacity.setValue(op)
            self._saved_state = None
        self.cb_layer.blockSignals(False)
        self.sl_opacity.blockSignals(False)
        self.lbl_op_cap.setText("Độ đậm:")
        self.title.setText(title)
        self._update_hint()
        self.setVisible(True)

    def edit_changed(self) -> bool:
        return self._edit and (self.cb_layer.currentData(), self.opacity) != getattr(self, "_edit_start", (None, None))


def process_image(img: QImage, opacity: int = 100, remove_bg: bool = False) -> QImage:
    """Ảnh sau khi xóa nền trắng / giảm độ đậm (chưa xoay). Trả về ARGB32."""
    out = img
    if remove_bg:
        from .imaging import remove_background
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        try:
            out = QImage.fromData(remove_background(bytes(buf.data()), None, trim=False, flatten=True, clean=True))
        except Exception:
            out = img
    out = out.convertToFormat(QImage.Format_ARGB32)
    if opacity < 100:
        res = QImage(out.size(), QImage.Format_ARGB32)
        res.fill(Qt.transparent)
        p = QPainter(res)
        p.setOpacity(opacity / 100)
        p.drawImage(0, 0, out)
        p.end()
        out = res
    return out


def rotate_image(img: QImage, angle: float) -> QImage:
    """Ảnh xem trước đã xoay (khung bao mở rộng, nền trong suốt)."""
    if not angle:
        return img
    from PySide6.QtGui import QTransform
    return img.convertToFormat(QImage.Format_ARGB32).transformed(QTransform().rotate(angle), Qt.SmoothTransformation)


# ------------------------------------------------------------------ hộp chữ
class TextDialog(QDialog):
    def __init__(self, parent, text: str = "", size: float = 12, color: str = "#1b1b1b", font_label: str | None = None,
                 title: str = "Hộp chữ", fonts_list=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 420)
        v = QVBoxLayout(self)
        self.ed = QPlainTextEdit(text)
        self.ed.setPlaceholderText("Nhập nội dung…")
        v.addWidget(self.ed, 1)
        f = QFormLayout()
        self.cb_font = QComboBox()
        self.fonts = fonts_list or text_fonts()
        for label, _ in self.fonts:
            self.cb_font.addItem(label)
        if font_label:
            k = self.cb_font.findText(font_label)
            if k >= 0:
                self.cb_font.setCurrentIndex(k)
        f.addRow("Phông chữ:", self.cb_font)
        row = QHBoxLayout()
        self.sp_size = QDoubleSpinBox(minimum=4, maximum=96, value=size, suffix=" pt")
        row.addWidget(self.sp_size)
        self.cb_color = QComboBox()
        for name, col in [("Đen", "#1b1b1b")] + [c for c in PEN_COLORS if c[0] != "Đen"]:
            self.cb_color.addItem(name, col)
        k = self.cb_color.findData(color)
        self.cb_color.setCurrentIndex(max(0, k))
        row.addWidget(QLabel("Màu:"))
        row.addWidget(self.cb_color)
        row.addStretch()
        f.addRow("Cỡ chữ:", row)
        v.addLayout(f)
        self.preview = QLabel(alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self.preview.setMinimumHeight(70)
        self.preview.setStyleSheet("background:#ffffff;border:1px solid #d0d0d0;border-radius:6px;padding:6px")
        v.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.cb_font, self.cb_color):
            w.currentIndexChanged.connect(self._preview)
        self.sp_size.valueChanged.connect(self._preview)
        self.ed.textChanged.connect(self._preview)
        self._preview()

    def font_path(self) -> str:
        return self.fonts[self.cb_font.currentIndex()][1]

    def _preview(self, *_):
        t = self.ed.toPlainText() or "Xem trước"
        img = render_text_image(t[:300], self.font_path(), min(self.sp_size.value(), 28), self.cb_color.currentData(), 110)
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(QSize(480, 120), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                               if img.width() > 480 or img.height() > 120 else QPixmap.fromImage(img))

    def _accept(self):
        t = self.ed.toPlainText()
        if not t.strip():
            self.ed.setFocus()
            return
        miss = fonts.missing_chars(self.font_path(), t)
        if miss:
            QMessageBox.warning(self, APP_NAME, f"Phông “{self.cb_font.currentText()}” không có ký tự: {miss}\n"
                                "Hãy chọn phông khác.")
            return
        self.accept()

    def values(self) -> dict:
        return {"text": self.ed.toPlainText(), "font_path": self.font_path(), "font_label": self.cb_font.currentText(),
                "size": self.sp_size.value(), "color": self.cb_color.currentData()}


class EditTextDialog(QDialog):
    """Sửa một dòng chữ có sẵn (PDF từ Word/Excel)."""

    def __init__(self, parent, run, font_label: str):
        super().__init__(parent)
        self.setWindowTitle("Sửa chữ")
        self.resize(560, 180)
        v = QVBoxLayout(self)
        self.ed = QLineEdit(run.text)
        self.ed.selectAll()
        v.addWidget(self.ed)
        style = ("đậm " if run.bold else "") + ("nghiêng " if run.italic else "")
        info = QLabel(f"Cỡ {run.size:g} pt {style}· phông gốc: {run.font_name.split('+')[-1] or '(không tên)'} "
                      f"→ thay bằng: {font_label}", objectName="lbl", wordWrap=True)
        v.addWidget(info)
        v.addWidget(QLabel("Chữ mới giữ nguyên vị trí, cỡ chữ và màu. Để trống rồi bấm OK để xóa dòng này.",
                           objectName="lbl", wordWrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def text(self) -> str:
        return self.ed.text()


class NoteDialog(QDialog):
    """Thêm / sửa ghi chú: nội dung, người ghi, màu, biểu tượng, độ mờ, đã xử lý, trả lời, xóa."""

    def __init__(self, parent, author: str = "", note=None, reply_mode: bool = False, settings=None,
                 readonly: bool = False):
        from PySide6.QtWidgets import QSlider
        from .notes import NOTE_COLORS, NOTE_ICONS
        super().__init__(parent)
        self.note = note
        self.action = "save"
        kind = getattr(note, "kind_label", "Ghi chú") if note is not None else "Ghi chú"
        self.setWindowTitle("Trả lời ghi chú" if reply_mode else
                            (f"{kind} – chỉ đọc" if readonly else (f"Sửa {kind.lower()}" if note else "Ghi chú")))
        self.resize(460, 420 if note and not reply_mode else 300)
        v = QVBoxLayout(self)
        if note is not None and reply_mode:
            q = QLabel(f"<b>{note.author or 'Không tên'}</b> ({note.date_text}): {note.text}", wordWrap=True)
            from .theme import ui_is_dark
            q.setStyleSheet("background:#4a4220;color:#f5f0dc;padding:6px;border-radius:4px" if ui_is_dark() else
                            "background:#fff8d6;color:#1b1b1b;padding:6px;border-radius:4px")
            v.addWidget(q)
        self.ed = QPlainTextEdit()
        self.ed.setPlaceholderText("Nội dung trả lời…" if reply_mode else
                                   "Nội dung ghi chú (người nhận bấm vào biểu tượng để đọc)…")
        if note is not None and not reply_mode:
            self.ed.setPlainText(note.text)
        v.addWidget(self.ed, 1)
        f = QFormLayout()
        self.ed_author = QLineEdit(author if (note is None or reply_mode) else note.author)
        f.addRow("Người ghi:", self.ed_author)
        self._color = (note.color if note is not None and not reply_mode else
                       (settings.value("note/color", NOTE_COLORS[0][1]) if settings is not None else NOTE_COLORS[0][1]))
        cw = QWidget()
        ch = QHBoxLayout(cw)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(4)
        self.color_btns = []
        for name, col in NOTE_COLORS:
            b = QToolButton(toolTip=name, checkable=True, autoRaise=True)
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"QToolButton{{background:{col};border-radius:11px;border:1px solid #9e9e9e}}"
                            f"QToolButton:checked{{border:2px solid #005fb8}}")
            b.clicked.connect(lambda _=False, c=col: self._set_color(c))
            ch.addWidget(b)
            self.color_btns.append((b, col))
        ch.addStretch()
        self.cb_icon = QComboBox()
        for k, lbl in NOTE_ICONS:
            self.cb_icon.addItem(lbl, k)
        self.sl_opacity = QSlider(Qt.Horizontal, minimum=20, maximum=100, value=100)
        self.chk_done = QCheckBox("Đã xử lý")
        sticky = note is None or getattr(note, "is_sticky", True)
        if note is not None and not reply_mode:
            info = QLabel(f"{kind} · {note.author or 'Không tên'}" + (f" · {note.date_text}" if note.date_text else "")
                          + f" · trang {note.page + 1}", objectName="lbl")
            v.insertWidget(0, info)
        if not reply_mode:
            if sticky:
                f.addRow("Màu:", cw)
                f.addRow("Biểu tượng:", self.cb_icon)
                f.addRow("Độ đậm:", self.sl_opacity)
            if note is not None:
                f.addRow("", self.chk_done)
        v.addLayout(f)
        if note is not None and not reply_mode:
            self.cb_icon.setCurrentIndex(max(0, self.cb_icon.findData(note.icon)))
            self.sl_opacity.setValue(int(note.opacity))
            self.chk_done.setChecked(note.done)
            if note.replies:
                lst = QLabel("<br>".join(f"↳ <b>{r.author or 'Không tên'}</b> ({r.date_text}): {r.text}"
                                         for r in note.replies), wordWrap=True)
                from .theme import ui_is_dark
                lst.setStyleSheet("background:#25304a;color:#e6ebf5;padding:6px;border-radius:4px" if ui_is_dark()
                                  else "background:#f3f6fb;color:#1b1b1b;padding:6px;border-radius:4px")
                v.addWidget(QLabel("Các câu trả lời:"))
                v.addWidget(lst)
            self.ed_reply = QLineEdit(placeholderText="Viết trả lời (tùy chọn)…")
            v.addWidget(self.ed_reply)
        else:
            self.ed_reply = None
            if settings is not None and not reply_mode:
                self.cb_icon.setCurrentIndex(max(0, self.cb_icon.findData(settings.value("note/icon", "comment"))))
        self._set_color(self._color)
        if readonly:
            self.ed.setReadOnly(True)
            self.ed_author.setReadOnly(True)
            for w in (cw, self.cb_icon, self.sl_opacity, self.chk_done):
                w.setEnabled(False)
            if self.ed_reply is not None:
                self.ed_reply.setVisible(False)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            v.addWidget(QLabel("File được bảo vệ – chỉ đọc được ghi chú, không sửa được.", objectName="lbl"))
            bb.rejected.connect(self.reject)
            v.addWidget(bb)
            return
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if note is not None and not reply_mode:
            self.btn_delete = bb.addButton("Xóa ghi chú", QDialogButtonBox.DestructiveRole)
            self.btn_delete.clicked.connect(self._delete)
        bb.accepted.connect(lambda: (self.ed.toPlainText().strip() or (note is not None and not reply_mode))
                            and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _set_color(self, c):
        self._color = c
        for b, col in self.color_btns:
            b.setChecked(col == c)

    def _delete(self):
        self.action = "delete"
        self.accept()

    def values(self) -> dict:
        return {"text": self.ed.toPlainText(), "author": self.ed_author.text(), "color": self._color,
                "icon": self.cb_icon.currentData(), "opacity": self.sl_opacity.value(),
                "done": self.chk_done.isChecked(), "reply": self.ed_reply.text().strip() if self.ed_reply else "",
                "action": self.action}


# ------------------------------------------------------------------ danh sách ghi chú (panel phải)
class NotesPanel(QFrame):
    """12b – Danh sách ghi chú: lọc theo người / ngày, bấm để tới trang, trả lời, đánh dấu đã xử lý."""
    gotoRequested = Signal(int, str)            # (trang, nm)
    replyRequested = Signal(int, str)
    toggleDoneRequested = Signal(int, str)
    editRequested = Signal(int, str)
    deleteRequested = Signal(int, str)
    closeRequested = Signal()
    exportRequested = Signal(str)               # "xlsx" | "pdf"
    showToggled = Signal(bool)                  # hiện / ẩn biểu tượng ghi chú trên trang
    printToggled = Signal(bool)                 # in kèm ghi chú

    DATES = [("all", "Mọi ngày"), ("today", "Hôm nay"), ("7", "7 ngày qua"), ("30", "30 ngày qua")]

    def __init__(self):
        from PySide6.QtWidgets import QTreeWidget
        super().__init__(objectName="card")
        self._notes = []
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel("Danh sách ghi chú", objectName="h")
        head.addWidget(self.title)
        head.addStretch()
        self.btn_close = QToolButton(text="✕", autoRaise=True, toolTip="Đóng danh sách")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        head.addWidget(self.btn_close)
        v.addLayout(head)
        fl = QHBoxLayout()
        self.cb_author = QComboBox()
        self.cb_date = QComboBox()
        for k, lbl in self.DATES:
            self.cb_date.addItem(lbl, k)
        fl.addWidget(self.cb_author, 1)
        fl.addWidget(self.cb_date, 1)
        v.addLayout(fl)
        self.chk_hide_done = QCheckBox("Ẩn ghi chú đã xử lý")
        v.addWidget(self.chk_hide_done)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(180)
        self.tree.setWordWrap(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._emit(self.editRequested, it))
        v.addWidget(self.tree, 1)
        from PySide6.QtWidgets import QGridLayout
        bl = QGridLayout()
        self.btn_reply = QPushButton("Trả lời…")
        self.btn_done = QPushButton("Đã xử lý ✓")
        self.btn_edit = QPushButton("Mở / sửa…")
        self.btn_del = QPushButton("Xóa")
        for k, (b, sig) in enumerate(((self.btn_reply, self.replyRequested), (self.btn_done, self.toggleDoneRequested),
                                      (self.btn_edit, self.editRequested), (self.btn_del, self.deleteRequested))):
            b.clicked.connect(lambda _=False, s=sig: self._emit(s, self.tree.currentItem()))
            bl.addWidget(b, k // 2, k % 2)
        v.addLayout(bl)
        for cb in (self.cb_author, self.cb_date):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        self.lbl = QLabel("", objectName="lbl", wordWrap=True)
        v.addWidget(self.lbl)
        erow = QHBoxLayout()
        self.btn_xlsx = QPushButton("Xuất Excel…")
        self.btn_pdf = QPushButton("Xuất PDF…")
        self.btn_xlsx.setToolTip("Tổng hợp ghi chú (đang lọc) ra bảng Excel")
        self.btn_pdf.setToolTip("Tổng hợp ghi chú (đang lọc) ra file PDF để gửi / in")
        self.btn_xlsx.clicked.connect(lambda: self.exportRequested.emit("xlsx"))
        self.btn_pdf.clicked.connect(lambda: self.exportRequested.emit("pdf"))
        erow.addWidget(self.btn_xlsx)
        erow.addWidget(self.btn_pdf)
        v.addLayout(erow)
        self.chk_show = WrapCheck("Hiện biểu tượng ghi chú trên trang", checked=True)
        self.chk_show.toggled.connect(self.showToggled.emit)
        self.chk_print = WrapCheck("In kèm biểu tượng ghi chú")
        self.chk_print.toggled.connect(self.printToggled.emit)
        v.addWidget(self.chk_show)
        v.addWidget(self.chk_print)
        self.cb_author.currentIndexChanged.connect(self._fill)
        self.cb_date.currentIndexChanged.connect(self._fill)
        self.chk_hide_done.toggled.connect(self._fill)
        self.setVisible(False)

    def _emit(self, sig, it):
        if it is None:
            return
        d = it.data(0, Qt.UserRole)
        if d:
            sig.emit(d[0], d[1])

    def _clicked(self, it, _col):
        self._emit(self.gotoRequested, it)

    def set_notes(self, notes):
        self._notes = list(notes)
        cur = self.cb_author.currentData()
        self.cb_author.blockSignals(True)
        self.cb_author.clear()
        self.cb_author.addItem("Mọi người ghi", None)
        for a in sorted({n.author or "Không tên" for n in self._notes} |
                        {r.author or "Không tên" for n in self._notes for r in n.replies}):
            self.cb_author.addItem(a, a)
        k = self.cb_author.findData(cur)
        self.cb_author.setCurrentIndex(max(0, k))
        self.cb_author.blockSignals(False)
        self._fill()

    def filtered(self):
        from datetime import datetime, timedelta
        who = self.cb_author.currentData()
        dk = self.cb_date.currentData()
        now = datetime.now()
        since = None
        if dk == "today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif dk in ("7", "30"):
            since = now - timedelta(days=int(dk))
        out = []
        for n in self._notes:
            if self.chk_hide_done.isChecked() and n.done:
                continue
            people = [n] + list(n.replies)
            if who and not any((x.author or "Không tên") == who for x in people):
                continue
            if since and not any(x.date and x.date >= since for x in people):
                continue
            out.append(n)
        return out

    def _fill(self, *_):
        from PySide6.QtWidgets import QTreeWidgetItem
        self.tree.clear()
        shown = self.filtered()
        for n in shown:
            kind = "" if getattr(n, "is_sticky", True) else f"{n.kind_label} · "
            head = f"{'✓ ' if n.done else ''}Trang {n.page + 1} · {kind}{n.author or 'Không tên'}" + \
                (f" · {n.date_text}" if n.date_text else "")
            it = QTreeWidgetItem([f"{head}\n{n.text}"])
            it.setData(0, Qt.UserRole, (n.page, n.nm))
            it.setToolTip(0, n.text)
            from .theme import ui_is_dark
            if ui_is_dark():                       # giao diện tối: chữ sáng dễ đọc
                it.setForeground(0, QColor("#81c784") if n.done else QColor(n.color).lighter(150))
            else:
                it.setForeground(0, QColor("#2e7d32") if n.done else QColor(n.color).darker(170))
            for r in n.replies:
                c = QTreeWidgetItem([f"↳ {r.author or 'Không tên'} · {r.date_text}\n{r.text}"])
                c.setData(0, Qt.UserRole, (n.page, n.nm))
                it.addChild(c)
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        total = len(self._notes)
        done = sum(1 for n in self._notes if n.done)
        self.lbl.setText(f"{len(shown)} / {total} ghi chú · {done} đã xử lý" if total else
                         "Chưa có ghi chú nào. Dùng công cụ Ghi chú để thêm.")


# ------------------------------------------------------------------ thư viện hình / bút (popup)
def shape_icon(kind: str, px: int = 30, color: str | None = None) -> QIcon:
    from . import items
    from .theme import ui_color
    color = color or ui_color("text")             # giao diện tối: nét sáng (trước đây nét đen trên nền tối)
    img = QPixmap(px, px)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor(0, 95, 184, 40))
    m = 4
    w = h = px - 2 * m
    if kind in ("line", "arrow", "darrow"):
        p.drawLine(QPointF(m, px - m), QPointF(px - m, m))
        if kind in ("arrow", "darrow"):
            for tip, frm in (((px - m, m), (m, px - m)),) + ((((m, px - m), (px - m, m)),) if kind == "darrow" else ()):
                tri, _ = items.arrow_head(tip, frm, 1.4)
                path = QPainterPath(QPointF(*tri[0]))
                for q in tri[1:]:
                    path.lineTo(QPointF(*q))
                path.closeSubpath()
                p.setBrush(QColor(color))
                p.drawPath(path)
    elif kind in ("curve", "carrow"):
        c1, c2 = items.curve_ctrl((m, px - m), (px - m, m))
        path = QPainterPath(QPointF(m, px - m))
        path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(px - m, m))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    elif kind in ("polyline", "freeform", "polygon"):
        pts = [(m, px - m), (px * .35, m + 2), (px * .6, px * .7), (px - m, m)] if kind != "freeform" else None
        p.setBrush(Qt.NoBrush if kind != "polygon" else QColor(0, 95, 184, 40))
        path = QPainterPath()
        if kind == "freeform":
            path.moveTo(m, px * .6)
            path.cubicTo(px * .3, m, px * .45, px - m, px - m, px * .35)
        else:
            path.moveTo(*pts[0])
            for q in pts[1:]:
                path.lineTo(*q)
            if kind == "polygon":
                path.closeSubpath()
        p.drawPath(path)
    else:
        try:
            subs = items.shape_paths(kind, w, h * (0.75 if kind.startswith(("barrow_l", "barrow_r")) else 1))
        except ValueError:
            subs = []
        if kind in ("check", "cross"):
            p.setPen(QPen(QColor(color), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if kind == "highlight":
            p.setBrush(QColor(255, 230, 0, 150))
            p.setPen(Qt.NoPen)
        path = QPainterPath()
        oy = m + (h * 0.125 if kind.startswith(("barrow_l", "barrow_r")) else 0)
        for sub in subs:
            for seg in sub:
                if seg[0] == "M":
                    path.moveTo(m + seg[1][0], oy + seg[1][1])
                elif seg[0] == "L":
                    path.lineTo(m + seg[1][0], oy + seg[1][1])
                elif seg[0] == "C":
                    path.cubicTo(m + seg[1][0], oy + seg[1][1], m + seg[2][0], oy + seg[2][1], m + seg[3][0], oy + seg[3][1])
                else:
                    path.closeSubpath()
        p.drawPath(path)
    p.end()
    return QIcon(img)


class ShapeGallery(QWidget):
    """14a – Bảng thư viện hình kiểu Word: đường, hình cơ bản, mũi tên khối, lưu đồ, chú thích, khung, ✓ ✗."""
    picked = Signal(str)

    def __init__(self, parent=None, groups=None, cols: int = 8):
        from PySide6.QtWidgets import QGridLayout
        from . import items
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        self.buttons = {}
        for title, lst in (groups or items.SHAPE_GROUPS):
            lb = QLabel(title)
            from .theme import ui_color
            lb.setStyleSheet(f"font-weight:600;color:{ui_color('text2')}")
            v.addWidget(lb)
            g = QGridLayout()
            g.setSpacing(2)
            for k, (kind, label) in enumerate(lst):
                b = QToolButton(toolTip=label, autoRaise=True)
                b.setIcon(shape_icon(kind))
                b.setIconSize(QSize(26, 26))
                b.setFixedSize(34, 34)
                b.clicked.connect(lambda _=False, kk=kind: self.picked.emit(kk))
                g.addWidget(b, k // cols, k % cols)
                self.buttons[kind] = b
            v.addLayout(g)


def pen_icon(pen: str, color: str = "#1a3fa8", px: int = 30) -> QIcon:
    img = QPixmap(px, px)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    from .theme import ui_is_dark
    dark = ui_is_dark()
    if dark and color == "#1a3fa8":               # mực xanh mặc định: sáng hơn trên nền tối
        color = "#8ab4ff"
    c = QColor("#fbc02d" if pen == "highlighter" else (("#b0b0b0" if dark else "#555555") if pen == "pencil" else color))
    if pen == "highlighter":
        c.setAlpha(150)
    w = {"ball": 1.4, "sign": 2.4, "marker": 3.4, "pencil": 1.2, "brush": 4.5, "highlighter": 7}.get(pen, 1.5)
    path = QPainterPath(QPointF(4, px * .7))
    path.cubicTo(QPointF(px * .35, px * .1), QPointF(px * .6, px * .95), QPointF(px - 4, px * .3))
    if pen in ("sign", "brush"):
        for k in range(8):                                    # nét to nhỏ
            t0, t1 = k / 8, (k + 1) / 8
            pa, pb = path.pointAtPercent(t0), path.pointAtPercent(t1)
            p.setPen(QPen(c, w * (0.35 + 0.65 * math.sin(math.pi * (t0 + 0.06))), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pa, pb)
    else:
        p.setPen(QPen(c, w, Qt.SolidLine, Qt.SquareCap if pen == "highlighter" else Qt.RoundCap))
        p.drawPath(path)
    p.end()
    return QIcon(img)


class FindReplaceDialog(QDialog):
    """Tìm & thay – 11f: danh sách từng chỗ tìm thấy (kèm ngữ cảnh), tích chọn chỗ cần thay, bấm để tới trang."""

    def __init__(self, parent, doc, on_goto=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget
        from . import editing
        self.editing = editing
        self.doc = doc
        self.on_goto = on_goto
        self.hits = []
        self.setWindowTitle("Tìm & thay")
        self.resize(620, 480)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.ed_find = QLineEdit()
        self.ed_repl = QLineEdit()
        f.addRow("Tìm:", self.ed_find)
        f.addRow("Thay bằng:", self.ed_repl)
        self.chk_case = QCheckBox("Phân biệt chữ hoa/thường")
        f.addRow("", self.chk_case)
        v.addLayout(f)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._goto)
        v.addWidget(self.list, 1)
        self.lbl = QLabel("Chỉ thay được trên trang văn bản (PDF xuất từ Word/Excel). Bấm Tìm để xem từng chỗ, "
                          "bỏ tích chỗ không muốn thay.", objectName="lbl", wordWrap=True)
        v.addWidget(self.lbl)
        row = QHBoxLayout()
        self.btn_check = QPushButton("Tích hết")
        self.btn_uncheck = QPushButton("Bỏ tích hết")
        self.btn_check.clicked.connect(lambda: self._check_all(True))
        self.btn_uncheck.clicked.connect(lambda: self._check_all(False))
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_uncheck)
        row.addStretch()
        self.btn_find = QPushButton("Tìm")
        self.btn_sel = QPushButton("Thay chỗ đã tích")
        self.btn_all = QPushButton("Thay tất cả")
        row.addWidget(self.btn_find)
        row.addWidget(self.btn_sel)
        row.addWidget(self.btn_all)
        b = QPushButton("Đóng")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        v.addLayout(row)
        self.btn_find.clicked.connect(self.find)
        self.btn_sel.clicked.connect(self.replace_selected)
        self.btn_all.clicked.connect(self.replace_all)
        self.ed_find.returnPressed.connect(self.find)
        self.replaced = 0
        self.btn_sel.setEnabled(False)

    def find(self) -> int:
        from PySide6.QtWidgets import QListWidgetItem
        q = self.ed_find.text()
        self.list.clear()
        self.hits = []
        if not q:
            return 0
        self.hits = self.editing.find_hits(self.doc, q, self.chk_case.isChecked())
        pages = sorted({h.page for h in self.hits})
        for h in self.hits:
            it = QListWidgetItem(f"Trang {h.page + 1}: {h.context}")
            if h.replaceable:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
            else:
                it.setForeground(QColor("#9e9e9e"))
                it.setToolTip("Cụm chữ bị tách thành nhiều đoạn trong file – dùng công cụ Sửa chữ (cả dòng) để sửa")
            self.list.addItem(it)
        total = len(self.hits)
        if total:
            n_ok = sum(1 for h in self.hits if h.replaceable)
            self.lbl.setText(f"Tìm thấy {total} chỗ trên {len(pages)} trang – thay được {n_ok} chỗ. Bấm một dòng để "
                             "tới trang đó; bỏ tích chỗ không muốn thay.")
            if self.on_goto:
                self.on_goto(pages[0])
        else:
            self.lbl.setText("Không tìm thấy.")
        self.btn_sel.setEnabled(any(h.replaceable for h in self.hits))
        return total

    def _goto(self, it):
        k = self.list.row(it)
        if 0 <= k < len(self.hits) and self.on_goto:
            self.on_goto(self.hits[k].page)

    def _check_all(self, on: bool):
        for k in range(self.list.count()):
            it = self.list.item(k)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def chosen_hits(self):
        return [h for k, h in enumerate(self.hits) if h.replaceable and self.list.item(k).checkState() == Qt.Checked]

    def replace_selected(self) -> int:
        sel = self.chosen_hits()
        if not sel:
            self.lbl.setText("Chưa tích chỗ nào để thay.")
            return 0
        n = self.editing.replace_hits(self.doc, sel, self.ed_repl.text())
        self.replaced += n
        skipped = sum(1 for h in self.hits if h.replaceable) - len(sel)
        self.find()
        self.lbl.setText(f"Đã thay {n} chỗ" + (f", bỏ qua {skipped} chỗ" if skipped else "") + ". Ctrl+Z để hoàn tác.")
        return n

    def replace_all(self):
        q = self.ed_find.text()
        if not q:
            return
        done, left = self.editing.find_replace(self.doc, q, self.ed_repl.text(), self.chk_case.isChecked())
        self.replaced += done
        msg = f"Đã thay {done} chỗ." if done else "Không có chỗ nào thay được."
        if left:
            msg += (f" Còn {left} chỗ không thay tự động được (cụm chữ bị tách thành nhiều đoạn trong file) – "
                    "dùng công cụ Sửa chữ (cả dòng) để sửa từng chỗ.")
        self.list.clear()
        self.hits = []
        self.lbl.setText(msg)


# ------------------------------------------------------------------ chữ viết tay
class HandDialog(QDialog):
    """Viết chữ tay: chọn nét chữ (phông viết tay hoặc bộ chữ tay của mình), màu mực, cỡ chữ."""

    def __init__(self, parent, library=None, handset_id: str | None = None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Chữ viết tay")
        self.resize(640, 520)
        self.library = library
        self.settings = settings
        self._sets = {}
        v = QVBoxLayout(self)
        self.ed = QPlainTextEdit()
        self.ed.setPlaceholderText("Nhập chữ cần viết tay, ví dụ: Đã duyệt – Nguyễn Văn A")
        self.ed.setMaximumHeight(90)
        v.addWidget(self.ed)
        f = QFormLayout()
        self.cb_style = QComboBox()
        self._fill_styles(handset_id)
        f.addRow("Nét chữ:", self.cb_style)
        row = QHBoxLayout()
        self.cb_color = QComboBox()
        for name, col in INK_COLORS:
            self.cb_color.addItem(name, col)
        row.addWidget(self.cb_color)
        row.addWidget(QLabel("Cỡ chữ:"))
        self.sp_size = QDoubleSpinBox(minimum=6, maximum=60, value=16, suffix=" pt")
        row.addWidget(self.sp_size)
        row.addStretch()
        f.addRow("Màu mực:", row)
        v.addLayout(f)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setMinimumHeight(170)
        self.preview.setStyleSheet("background:#ffffff;border:1px solid #d0d0d0;border-radius:6px")
        v.addWidget(self.preview, 1)
        tools = QHBoxLayout()
        b1 = QPushButton("In phiếu mẫu chữ…")
        b1.setToolTip("Lưu phiếu mẫu (PDF A4, 2 trang ô to) để in ra, viết tay vào các ô")
        b1.clicked.connect(self.save_template)
        b2 = QPushButton("Tạo bộ chữ tay từ bản scan…")
        b2.setToolTip("Chọn ảnh scan/chụp phiếu mẫu đã viết (1 file PDF hoặc ảnh từng trang) -> xem lại từng chữ "
                      "đã cắt -> tạo nét chữ của riêng bạn")
        b2.clicked.connect(lambda: self.import_scan())
        tools.addWidget(b1)
        tools.addWidget(b2)
        tools.addStretch()
        v.addLayout(tools)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Đặt lên trang")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if settings is not None:
            self.cb_color.setCurrentIndex(max(0, self.cb_color.findData(settings.value("hand/color", INK_COLORS[0][1]))))
            last = settings.value("hand/style")
            if last and not handset_id:
                k = self.cb_style.findData(last)
                if k >= 0:
                    self.cb_style.setCurrentIndex(k)
        self.cb_style.currentIndexChanged.connect(self._preview)
        self.cb_color.currentIndexChanged.connect(self._preview)
        self.sp_size.valueChanged.connect(self._preview)
        self.ed.textChanged.connect(self._preview)
        self._preview()

    def _fill_styles(self, select_id=None):
        from .library import HANDSET
        self.cb_style.clear()
        if self.library is not None and not getattr(self.library, "locked", False):
            for it in self.library.of_kind(HANDSET):
                self.cb_style.addItem(f"✍ {it.name} (nét chữ của tôi)", "set:" + it.id)
        for name in fonts.HANDWRITING:
            self.cb_style.addItem(name, "font:" + name)
        if select_id:
            k = self.cb_style.findData("set:" + select_id)
            if k >= 0:
                self.cb_style.setCurrentIndex(k)

    def style(self) -> str:
        return self.cb_style.currentData() or ""

    def _handset(self, iid: str):
        from .handwriting import HandSet
        if iid not in self._sets:
            self._sets[iid] = HandSet(self.library.image(iid))
        return self._sets[iid]

    def render(self, text: str | None = None) -> tuple[QImage, float]:
        """(ảnh, chiều rộng pt khi đặt lên trang)."""
        text = (text if text is not None else self.ed.toPlainText()) or "Chữ viết tay"
        col = self.cb_color.currentData()
        size = self.sp_size.value()
        st = self.style()
        if st.startswith("set:"):
            hs = self._handset(st[4:])
            rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
            px_h = int(size / 0.55 * 300 / 72)                   # chữ hoa ≈ 55% chiều cao ô
            im = hs.render(text, rgb, px_h)
            return pil_to_qimage(im), im.width / 300 * 72
        path = fonts.handwriting_path(st[5:])
        img = render_text_image(text, path, size, col, 200)
        return img, img.width() / 200 * 72

    def _preview(self, *_):
        img, _ = self.render()
        pm = QPixmap.fromImage(img)
        if pm.width() > 600 or pm.height() > 160:
            pm = pm.scaled(QSize(600, 160), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)

    def save_template(self, path: str | None = None):
        from .handwriting import make_template
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Lưu phiếu mẫu chữ", "phieu_mau_chu_viet_tay.pdf", "PDF (*.pdf)")
            if not path:
                return
        make_template(path)
        from .osutil import IS_MAC, IS_WIN, open_path
        if IS_WIN or IS_MAC:
            open_path(path)                             # mở để in ngay

    def import_scan(self, path=None, name: str | None = None, review: bool | None = None):
        """Nạp phiếu mẫu đã viết (1–2 trang: ảnh từng trang hoặc 1 file PDF) -> xem lại từng chữ đã cắt
        (chỉnh khung cắt, độ tách nền, bỏ / viết lại chữ) -> lưu bộ chữ vào thư viện."""
        from .handwriting import HandSet, extract_cells, parse_scan
        from .library import HANDSET
        from .ui_library import unlock_if_needed
        if self.library is None:
            return
        if not unlock_if_needed(self, self.library):
            return
        if not path:
            paths, _ = QFileDialog.getOpenFileNames(self, "Chọn bản scan phiếu mẫu đã viết (chọn được cả 2 trang)", "",
                                                    "Ảnh / PDF (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.pdf)")
            if not paths:
                return
        else:
            paths = [path] if isinstance(path, str) else list(path)
        if review is None:
            review = name is None
        try:
            datas = []
            for p in paths:
                with open(p, "rb") as f:
                    datas.append(f.read())
            if review:
                ex = extract_cells(datas)
                dlg = HandReviewDialog(self, ex)
                if dlg.exec() != QDialog.Accepted:
                    return
                sprite = dlg.sprite()
            else:
                sprite = parse_scan(datas)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không đọc được phiếu mẫu:\n{e}")
            return
        cov = HandSet(sprite).coverage
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Bộ chữ tay", f"Đã nhận {cov:.0%} ô có chữ. Đặt tên bộ chữ:",
                                            text="Chữ tay của tôi")
            if not ok:
                return
        it = self.library.add(name or "Chữ tay của tôi", sprite, HANDSET, 0)
        self._fill_styles(it.id)
        self._preview()
        return it

    def _accept(self):
        if not self.ed.toPlainText().strip():
            self.ed.setFocus()
            return
        st = self.style()
        if st.startswith("font:"):
            miss = fonts.missing_chars(fonts.handwriting_path(st[5:]), self.ed.toPlainText())
            if miss:
                QMessageBox.warning(self, APP_NAME, f"Nét chữ này không có ký tự: {miss}")
                return
        if self.settings is not None:
            self.settings.setValue("hand/color", self.cb_color.currentData())
            self.settings.setValue("hand/style", st)
        self.accept()

    def values(self) -> dict:
        st = self.style()
        return {"text": self.ed.toPlainText(), "style": st, "color": self.cb_color.currentData(),
                "size": self.sp_size.value(),
                "font_path": fonts.handwriting_path(st[5:]) if st.startswith("font:") else None}


# ------------------------------------------------------------------ bảng vẽ tay (chữ ký / chữ viết tay)
class DrawPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 220)
        self.strokes: list[list[QPointF]] = []
        self.color = QColor("#1a3fa8")
        self.pen_width = 3.2
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#dddddd"), 1, Qt.DashLine))
        y = int(self.height() * 0.7)
        p.drawLine(20, y, self.width() - 20, y)
        self._draw(p)
        p.end()

    def _draw(self, p, scale=1.0, offset=QPointF(0, 0)):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.color, self.pen_width * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            if len(s) == 1:
                p.drawPoint((s[0] - offset) * scale)
                continue
            path = QPainterPath((s[0] - offset) * scale)
            for pt in s[1:]:
                path.lineTo((pt - offset) * scale)
            p.drawPath(path)

    def mousePressEvent(self, ev):
        self.strokes.append([ev.position()])
        self.update()

    def mouseMoveEvent(self, ev):
        if self.strokes and ev.buttons() & Qt.LeftButton:
            self.strokes[-1].append(ev.position())
            self.update()

    def clear(self):
        self.strokes = []
        self.update()

    def to_png(self, scale: float = 3.0) -> bytes | None:
        pts = [pt for s in self.strokes for pt in s]
        if not pts:
            return None
        pad = self.pen_width * 2
        x0 = min(p.x() for p in pts) - pad
        y0 = min(p.y() for p in pts) - pad
        x1 = max(p.x() for p in pts) + pad
        y1 = max(p.y() for p in pts) + pad
        img = QImage(int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self._draw(p, scale, QPointF(x0, y0))
        p.end()
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return bytes(ba)


class DrawDialog(QDialog):
    """Ký / viết tay trực tiếp bằng chuột, bút cảm ứng -> lưu vào thư viện."""

    def __init__(self, parent):
        super().__init__(parent)
        from .library import HAND, KIND_LABEL, SIGNATURE
        self.setWindowTitle("Vẽ chữ ký / chữ viết tay")
        v = QVBoxLayout(self)
        self.pad = DrawPad()
        v.addWidget(self.pad, 1)
        f = QFormLayout()
        self.ed_name = QLineEdit("Chữ ký vẽ tay")
        f.addRow("Tên mẫu:", self.ed_name)
        row = QHBoxLayout()
        self.cb_kind = QComboBox()
        self.kinds = [SIGNATURE, HAND]
        self.cb_kind.addItems([KIND_LABEL[k] for k in self.kinds])
        row.addWidget(self.cb_kind)
        self.cb_color = QComboBox()
        for name, col in INK_COLORS:
            self.cb_color.addItem(name, col)
        self.cb_color.currentIndexChanged.connect(lambda: (setattr(self.pad, "color", QColor(self.cb_color.currentData())),
                                                          self.pad.update()))
        row.addWidget(self.cb_color)
        self.sp_w = QSpinBox(minimum=10, maximum=150, value=45, suffix=" mm")
        row.addWidget(QLabel("Rộng khi đặt:"))
        row.addWidget(self.sp_w)
        f.addRow("Loại:", row)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b = bb.addButton("Vẽ lại", QDialogButtonBox.ResetRole)
        b.clicked.connect(self.pad.clear)
        bb.accepted.connect(lambda: self.pad.strokes and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self) -> dict:
        return {"name": self.ed_name.text().strip() or "Vẽ tay", "png": self.pad.to_png(),
                "kind": self.kinds[self.cb_kind.currentIndex()], "width_mm": float(self.sp_w.value())}


__all__ = ["ToolOptions", "TextDialog", "EditTextDialog", "NoteDialog", "NotesPanel", "ShapeGallery", "FindReplaceDialog", "HandDialog",
           "DrawDialog", "SYMBOLS", "SHAPES", "text_fonts", "render_text_image"]


# ------------------------------------------------------------------ 1.0.22: thanh định dạng nổi (như Word)
def _align_icon(kind: str, px: int = 18) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QColor(ui_color("text")), 1.6))
    for k, w in enumerate((14, 9, 14, 9)):
        y = 4 + k * 3.5
        x = {"left": 2, "center": (px - w) / 2, "right": px - 2 - w}[kind]
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
    p.end()
    return QIcon(pm)


class InlineFormatBar(QFrame):
    """Thanh định dạng nổi ngay trên ô gõ chữ (hộp chữ / sửa chữ có sẵn): phông, cỡ, đậm, nghiêng, màu, canh lề,
    xong / hủy. mode="textbox": phông là file (cả phông viết tay); mode="edit": "Giữ phông gốc" + họ phông."""
    changed = Signal(dict)
    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent, mode: str = "textbox"):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("fmtbar")
        self.setFrameShape(QFrame.StyledPanel)
        dark = ui_is_dark()
        self.setStyleSheet(
            "QFrame#fmtbar{background:%s;border:1px solid %s;border-radius:6px}"
            "QToolButton{border:1px solid transparent;border-radius:4px;padding:1px 3px;min-width:22px;min-height:22px}"
            "QToolButton:hover{border-color:%s}QToolButton:checked{background:%s;border-color:#005fb8}"
            % (("#2b2b2b", "#555", "#777", "#1f3b57") if dark else ("#ffffff", "#c8c8c8", "#9ab", "#d6e8fb")))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 3, 5, 3)
        lay.setSpacing(3)
        self.cb_font = QComboBox(toolTip="Phông chữ")
        self.cb_font.setMinimumContentsLength(14)
        self.cb_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        if mode == "edit":
            self.cb_font.addItem("Giữ phông gốc", "")
            for fam, lbl in fonts.FAMILY_LABEL.items():
                self.cb_font.addItem(lbl, fam)
                try:
                    self.cb_font.setItemData(self.cb_font.count() - 1, QFont(qt_family(fonts.system_font(fam))),
                                             Qt.FontRole)
                except Exception:
                    pass
        else:
            for lbl, path in text_fonts():
                self.cb_font.addItem(lbl, path)
                try:
                    f = QFont(qt_family(path))
                    f.setPointSize(11)
                    self.cb_font.setItemData(self.cb_font.count() - 1, f, Qt.FontRole)   # xem trước kiểu chữ
                except Exception:
                    pass
        self.sp_size = QDoubleSpinBox(minimum=0 if mode == "edit" else 4, maximum=200, value=12, decimals=1,
                                      suffix=" pt", toolTip="Cỡ chữ" + (" (0: giữ cỡ gốc)" if mode == "edit" else ""))
        self.sp_size.setKeyboardTracking(False)
        self.btn_bold = QToolButton(text="B", checkable=True, toolTip="Đậm (Ctrl+B)")
        self.btn_bold.setStyleSheet("QToolButton{font-weight:bold}")
        self.btn_italic = QToolButton(text="I", checkable=True, toolTip="Nghiêng (Ctrl+I)")
        self.btn_italic.setStyleSheet("QToolButton{font-style:italic;font-family:serif}")
        self.btn_color = QToolButton(toolTip="Màu chữ")
        self.btn_color.clicked.connect(self._color_menu)
        self._color = "#1b1b1b"
        self.align_btns = {}
        for k, tip in (("left", "Canh trái"), ("center", "Canh giữa"), ("right", "Canh phải")):
            b = QToolButton(checkable=True, toolTip=tip, autoExclusive=True)
            b.setIcon(_align_icon(k))
            b.clicked.connect(lambda _=False, k=k: self._emit())
            self.align_btns[k] = b
        self.btn_ok = QToolButton(text="✓", toolTip="Xong (Ctrl+Enter / bấm ra ngoài)")
        self.btn_ok.setStyleSheet("QToolButton{color:#2e7d32;font-weight:bold}")
        self.btn_cancel = QToolButton(text="✕", toolTip="Hủy (Esc)")
        self.btn_cancel.setStyleSheet("QToolButton{color:#c62828}")
        self.btn_ok.clicked.connect(self.accepted.emit)
        self.btn_cancel.clicked.connect(self.rejected.emit)
        for w in (self.cb_font, self.sp_size, self.btn_bold, self.btn_italic, self.btn_color):
            lay.addWidget(w)
        if mode != "edit":
            lay.addSpacing(4)
            for b in self.align_btns.values():
                lay.addWidget(b)
        lay.addSpacing(4)
        lay.addWidget(self.btn_ok)
        lay.addWidget(self.btn_cancel)
        self._quiet = False
        self.cb_font.currentIndexChanged.connect(self._font_changed)
        self.sp_size.valueChanged.connect(self._emit)
        self.btn_bold.toggled.connect(self._emit)
        self.btn_italic.toggled.connect(self._emit)
        for w in self.findChildren(QWidget):
            w.setFocusPolicy(Qt.NoFocus if isinstance(w, QToolButton) else Qt.ClickFocus)
        self._paint_color()

    # ----- trạng thái
    def set_state(self, st: dict):
        self._quiet = True
        try:
            key = st.get("font") if self.mode != "edit" else (st.get("family") or "")
            i = self.cb_font.findData(key)
            if i < 0 and self.mode != "edit" and key:
                for k in range(self.cb_font.count()):              # cùng họ phông (bản đậm/nghiêng của file)
                    if fonts.system_family_of_path(self.cb_font.itemData(k)) == fonts.system_family_of_path(key) \
                            and fonts.system_family_of_path(key):
                        i = k
                        break
            self.cb_font.setCurrentIndex(max(0, i))
            self.sp_size.setValue(float(st.get("size", 12) or 0))
            self.btn_bold.setChecked(bool(st.get("bold")))
            self.btn_italic.setChecked(bool(st.get("italic")))
            self._color = st.get("color") or self._color
            self.align_btns.get(st.get("align") or "left", self.align_btns["left"]).setChecked(True)
        finally:
            self._quiet = False
        self._update_variants()
        self._paint_color()

    def state(self) -> dict:
        align = next((k for k, b in self.align_btns.items() if b.isChecked()), "left")
        st = {"size": self.sp_size.value(), "bold": self.btn_bold.isChecked(), "italic": self.btn_italic.isChecked(),
              "color": self._color, "align": align}
        if self.mode == "edit":
            st["family"] = self.cb_font.currentData() or ""
        else:
            st["font"] = self.cb_font.currentData() or ""
        return st

    def _update_variants(self):
        """Phông viết tay không có bản đậm / nghiêng -> mờ nút B, I (tránh bấm mà không thấy đổi)."""
        if self.mode == "edit":
            return
        ok = fonts.has_variants(self.cb_font.currentData() or "")
        for b in (self.btn_bold, self.btn_italic):
            b.setEnabled(ok)
            if not ok:
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)

    def _font_changed(self, *_):
        self._update_variants()
        self._emit()

    def _emit(self, *_):
        if not self._quiet:
            self.changed.emit(self.state())

    def _paint_color(self):
        pm = QPixmap(18, 18)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(ui_color("text")))
        p.drawText(pm.rect().adjusted(0, -3, 0, -3), Qt.AlignCenter, "A")
        p.fillRect(2, 14, 14, 4, QColor(self._color))
        p.end()
        self.btn_color.setIcon(QIcon(pm))

    def _color_menu(self):
        from PySide6.QtWidgets import QColorDialog, QMenu
        m = QMenu(self)
        for name, col in PEN_COLORS + [("Xanh bút bi", "#1a3fa8")]:
            pm = QPixmap(14, 14)
            pm.fill(QColor(col))
            a = m.addAction(QIcon(pm), name)
            a.setData(col)
        m.addSeparator()
        other = m.addAction("Màu khác…")
        act = m.exec(self.btn_color.mapToGlobal(self.btn_color.rect().bottomLeft()))
        if act is None:
            return
        col = act.data()
        if act is other:
            c = QColorDialog.getColor(QColor(self._color), self, "Màu chữ")
            col = c.name() if c.isValid() else None
        if col:
            self.set_color(col)

    def set_color(self, col: str):
        self._color = col
        self._paint_color()
        self._emit()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.rejected.emit()
            return
        super().keyPressEvent(ev)


# ------------------------------------------------------------------ 1.0.22: xem lại từng chữ đã cắt từ phiếu mẫu
def _pil_from_qimage(img: QImage):
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(ba))).convert("RGBA")


class _CellCrop(QWidget):
    """Ảnh ô gốc (đã nắn thẳng) phóng to + khung cắt kéo được: chỉ giữ nét bút trong khung."""
    rectChanged = Signal(tuple)
    ZOOM = 1.5

    def __init__(self):
        super().__init__()
        from .handwriting import SPRITE_H, SPRITE_W
        self.cw, self.ch = SPRITE_W, SPRITE_H
        self.setFixedSize(int(self.cw * self.ZOOM), int(self.ch * self.ZOOM))
        self.setCursor(Qt.CrossCursor)
        self.img = None
        self.rect_px = (0, 0, self.cw, self.ch)
        self._start = None

    def set_cell(self, pil_img, rect):
        self.img = pil_to_qimage(pil_img.convert("RGB")) if pil_img is not None else None
        self.rect_px = tuple(rect)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if self.img is not None:
            p.drawImage(self.rect(), self.img)
        z = self.ZOOM
        x0, y0, x1, y1 = self.rect_px
        from PySide6.QtCore import QRectF
        r = QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z)
        shade = QColor(0, 0, 0, 70)
        full = QRectF(self.rect())
        for part in (QRectF(0, 0, full.width(), r.top()), QRectF(0, r.bottom(), full.width(), full.height() - r.bottom()),
                     QRectF(0, r.top(), r.left(), r.height()), QRectF(r.right(), r.top(), full.width() - r.right(), r.height())):
            p.fillRect(part, shade)                                  # phần bị bỏ: tô tối
        p.setPen(QPen(QColor("#005fb8"), 2, Qt.DashLine))
        p.drawRect(r)
        from .handwriting import BASELINE
        p.setPen(QPen(QColor(229, 57, 53, 120), 1, Qt.DotLine))
        p.drawLine(0, int(self.height() * BASELINE), self.width(), int(self.height() * BASELINE))
        p.end()

    def _pt(self, ev):
        z = self.ZOOM
        return (min(max(ev.position().x() / z, 0), self.cw), min(max(ev.position().y() / z, 0), self.ch))

    def mousePressEvent(self, ev):
        self._start = self._pt(ev)

    def mouseMoveEvent(self, ev):
        if self._start is None:
            return
        (ax, ay), (bx, by) = self._start, self._pt(ev)
        if abs(ax - bx) > 3 and abs(ay - by) > 3:
            self.rect_px = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._start is not None:
            self._start = None
            self.rectChanged.emit(self.rect_px)


class _CellPad(DrawPad):
    """Viết lại một chữ bằng chuột / bút cảm ứng, đúng khung ô (chân chữ chạm đường đỏ)."""

    def __init__(self):
        super().__init__()
        from .handwriting import SPRITE_H, SPRITE_W
        self.cw, self.ch = SPRITE_W, SPRITE_H
        z = _CellCrop.ZOOM
        self.setMinimumSize(0, 0)
        self.setFixedSize(int(self.cw * z), int(self.ch * z))
        self.pen_width = 6.0

    def paintEvent(self, ev):
        from .handwriting import BASELINE, V2_XHEIGHT
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        y = self.height() * BASELINE
        p.setPen(QPen(QColor(229, 57, 53, 150), 1.5))
        p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        p.setPen(QPen(QColor("#cccccc"), 1, Qt.DotLine))
        yx = y - self.height() * BASELINE * V2_XHEIGHT
        p.drawLine(QPointF(0, yx), QPointF(self.width(), yx))
        self._draw(p)
        p.end()

    def to_cell(self):
        """Ảnh RGBA đúng cỡ ô (SPRITE_W x SPRITE_H) hoặc None nếu chưa viết."""
        if not self.strokes:
            return None
        img = QImage(self.cw, self.ch, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self._draw(p, 1 / _CellCrop.ZOOM)
        p.end()
        return _pil_from_qimage(img)


class HandReviewDialog(QDialog):
    """Xem lại từng chữ đã cắt từ phiếu mẫu trước khi lưu bộ chữ: kéo lại khung cắt, đổi độ tách nền,
    bỏ chữ, viết lại chữ chưa đẹp bằng chuột / bút cảm ứng."""

    def __init__(self, parent, extracted: dict):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSlider, QStackedWidget
        from . import handwriting as hw
        self.hw = hw
        self.ex = extracted
        self.version = extracted.get("version", 2)
        self.setWindowTitle("Xem lại các chữ đã cắt")
        self.resize(980, 640)
        self.state = {}                    # ký tự -> {"rect", "thr", "drop", "drawn"}
        self.glyphs = {}
        self.order = [c for c in hw.CHARS if c in extracted["cells"]]
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.info = QLabel(wordWrap=True)
        left.addWidget(self.info)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Độ tách nền chung:"))
        self.sl_all = QSlider(Qt.Horizontal, minimum=120, maximum=230, value=175)
        self.sl_all.setToolTip("Kéo sang phải nếu nét bút bị đứt / mờ, sang trái nếu còn vết bẩn, đường kẻ")
        trow.addWidget(self.sl_all, 1)
        left.addLayout(trow)
        self.list = QListWidget(viewMode=QListWidget.IconMode, movement=QListWidget.Static,
                                resizeMode=QListWidget.Adjust, spacing=4)
        self.list.setIconSize(QSize(54, 72))
        self.list.setGridSize(QSize(70, 100))
        for ch in self.order:
            it = QListWidgetItem(hw.label(ch))
            it.setData(Qt.UserRole, ch)
            self.list.addItem(it)
        left.addWidget(self.list, 1)
        lay.addLayout(left, 3)
        right = QVBoxLayout()
        self.title = QLabel(objectName="title")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.title.setFont(f)
        right.addWidget(self.title)
        right.addWidget(QLabel("Kéo chuột trên ảnh để đặt lại khung cắt (phần tô tối bị bỏ).", wordWrap=True))
        self.stack = QStackedWidget()
        self.crop = _CellCrop()
        self.pad = _CellPad()
        self.stack.addWidget(self.crop)
        self.stack.addWidget(self.pad)
        row = QHBoxLayout()
        row.addWidget(self.stack)
        self.out = QLabel(alignment=Qt.AlignCenter)
        self.out.setFixedSize(self.crop.size())
        self.out.setToolTip("Kết quả sau khi cắt (nền ô vuông = trong suốt)")
        row.addWidget(self.out)
        right.addLayout(row)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Tách nền chữ này:"))
        self.sl_one = QSlider(Qt.Horizontal, minimum=120, maximum=230, value=175)
        r2.addWidget(self.sl_one, 1)
        right.addLayout(r2)
        r3 = QHBoxLayout()
        self.btn_reset = QPushButton("Đặt lại khung")
        self.btn_drop = QPushButton("Bỏ chữ này", checkable=True)
        self.btn_draw = QPushButton("Viết lại bằng chuột", checkable=True)
        self.btn_clear = QPushButton("Xóa nét")
        for b in (self.btn_reset, self.btn_drop, self.btn_draw, self.btn_clear):
            r3.addWidget(b)
        right.addLayout(r3)
        self.hint = QLabel("", objectName="lbl", wordWrap=True)
        right.addWidget(self.hint)
        right.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lưu bộ chữ")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 2)
        self.cur = None
        self.list.currentItemChanged.connect(self._select)
        self.crop.rectChanged.connect(self._rect_changed)
        self.sl_one.valueChanged.connect(self._thr_changed)
        self.sl_all.sliderReleased.connect(self._thr_all)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_drop.toggled.connect(self._drop)
        self.btn_draw.toggled.connect(self._draw_mode)
        self.btn_clear.clicked.connect(self._clear_pad)
        for ch in self.order:
            self.state[ch] = {"rect": self.hw.default_rect(self.version), "thr": 175, "drop": False, "drawn": None}
            self._process(ch)
        self._update_info()
        if self.order:
            first = next((i for i, c in enumerate(self.order) if self.glyphs.get(c) is None), 0)
            self.list.setCurrentRow(first)

    # ----- xử lý
    def _process(self, ch):
        st = self.state[ch]
        if st["drop"]:
            g = None
        elif st["drawn"] is not None:
            g = st["drawn"]
        else:
            g = self.hw.process_cell(self.ex["cells"][ch], st["thr"], st["rect"], self.version)
        self.glyphs[ch] = g
        it = self.list.item(self.order.index(ch))
        it.setIcon(QIcon(QPixmap.fromImage(self._thumb(g, QSize(54, 72)))))
        miss = g is None
        it.setForeground(QColor("#c62828") if miss else QColor(ui_color("text")))
        it.setText(self.hw.label(ch) + (" – trống" if miss else ""))
        return g

    def _thumb(self, g, size: QSize) -> QImage:
        img = QImage(size, QImage.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        cell = 6 if size.width() < 100 else 12
        for y in range(0, size.height(), cell):
            for x in range(0, size.width(), cell):
                if (x // cell + y // cell) % 2:
                    p.fillRect(x, y, cell, cell, QColor("#eeeeee"))
        if g is not None:
            p.drawImage(img.rect(), pil_to_qimage(g))
        else:
            p.setPen(QColor("#c62828"))
            p.drawText(img.rect(), Qt.AlignCenter, "trống")
        p.end()
        return img

    def _show(self):
        ch = self.cur
        if ch is None:
            return
        st = self.state[ch]
        self.crop.set_cell(self.ex["cells"][ch], st["rect"])
        self.out.setPixmap(QPixmap.fromImage(self._thumb(self.glyphs.get(ch), self.out.size())))

    def _update_info(self):
        ok = sum(1 for c in self.order if self.glyphs.get(c) is not None)
        miss = [self.hw.label(c) for c in self.order if self.glyphs.get(c) is None]
        pages = self.ex.get("pages", [])
        txt = f"Đã cắt được {ok}/{len(self.hw.CHARS)} chữ."
        if self.version == 2 and 2 not in pages:
            txt += " Chưa có trang 2 (chữ hoa, dấu câu): chữ hoa sẽ dùng tạm chữ thường."
        if miss:
            txt += " Ô trống: " + ", ".join(miss[:20]) + ("…" if len(miss) > 20 else "")
        self.info.setText(txt + " Bấm vào từng chữ để kiểm tra.")

    # ----- sự kiện
    def _select(self, item, _prev=None):
        if item is None:
            return
        if self.btn_draw.isChecked():
            self.btn_draw.setChecked(False)
        self.cur = item.data(Qt.UserRole)
        st = self.state[self.cur]
        self.title.setText(f"Chữ “{self.hw.label(self.cur)}”")
        for w, v in ((self.sl_one, st["thr"]), (self.btn_drop, st["drop"])):
            w.blockSignals(True)
            (w.setValue if hasattr(w, "setValue") else w.setChecked)(v)
            w.blockSignals(False)
        self.hint.setText("Đã viết lại bằng chuột." if st["drawn"] is not None else "")
        self._show()

    def _changed(self):
        self._process(self.cur)
        self._show()
        self._update_info()

    def _rect_changed(self, r):
        if self.cur is None:
            return
        self.state[self.cur]["rect"] = r
        self.state[self.cur]["drawn"] = None
        self._changed()

    def _thr_changed(self, v):
        if self.cur is None:
            return
        self.state[self.cur]["thr"] = v
        self._changed()

    def _thr_all(self):
        v = self.sl_all.value()
        for ch in self.order:
            self.state[ch]["thr"] = v
            self._process(ch)
        self.sl_one.blockSignals(True)
        self.sl_one.setValue(v)
        self.sl_one.blockSignals(False)
        self._show()
        self._update_info()

    def _reset(self):
        if self.cur is None:
            return
        self.state[self.cur].update(rect=self.hw.default_rect(self.version), drawn=None, drop=False, thr=self.sl_all.value())
        self._select(self.list.currentItem())
        self._changed()

    def _drop(self, on):
        if self.cur is None:
            return
        self.state[self.cur]["drop"] = on
        self._changed()

    def _draw_mode(self, on):
        if on:
            self.pad.clear()
            self.stack.setCurrentWidget(self.pad)
            self.btn_draw.setText("Xong viết")
            self.hint.setText("Viết chữ vào khung bên trái, chân chữ chạm đường đỏ, chữ thường cao tới đường chấm. "
                              "Bấm “Xong viết” để dùng.")
            return
        self.stack.setCurrentWidget(self.crop)
        self.btn_draw.setText("Viết lại bằng chuột")
        if self.cur is not None:
            g = self.pad.to_cell()
            if g is not None:
                self.state[self.cur]["drawn"] = g
                self.state[self.cur]["drop"] = False
                self.hint.setText("Đã viết lại bằng chuột.")
                self._changed()

    def _clear_pad(self):
        if self.btn_draw.isChecked():
            self.pad.clear()
        elif self.cur is not None and self.state[self.cur]["drawn"] is not None:
            self.state[self.cur]["drawn"] = None
            self.hint.setText("")
            self._changed()

    def _accept(self):
        if self.btn_draw.isChecked():
            self.btn_draw.setChecked(False)
        n = sum(1 for g in self.glyphs.values() if g is not None)
        if n < 10:
            QMessageBox.warning(self, APP_NAME, "Bộ chữ cần ít nhất 10 chữ có nét viết.")
            return
        self.accept()

    def sprite(self) -> bytes:
        return self.hw.build_sprite({c: g for c, g in self.glyphs.items() if g is not None})
