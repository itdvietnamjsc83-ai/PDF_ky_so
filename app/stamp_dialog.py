"""1.0.22 – hộp thoại con dấu chữ tùy biến (Đã duyệt, Sao y bản chính…): nội dung, dòng phụ, chữ chạy vòng,
hình dạng (chữ nhật, bo góc, bầu dục, tròn, lục giác, không khung), viền, màu, độ đậm, cỡ (mm), góc xoay.
Xem trước ngay trong hộp thoại; đóng xong dấu nằm nổi trên trang, bấm vào để kéo / xoay / đổi cỡ,
nháy đúp để mở lại hộp thoại này mà sửa."""
from __future__ import annotations

import json
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from . import items
from .widgets import SliderSpin

MM = 72 / 25.4
COLORS = [("Đỏ", "#d32f2f"), ("Xanh", "#0d47a1"), ("Tím", "#6a1b9a"), ("Xanh lá", "#2e7d32"), ("Đen", "#1b1b1b")]
RECENT_KEY = "stamp/recent"


def default_size_mm(shape: str, lines: int = 1, sub: bool = False) -> tuple[int, int]:
    if shape == "circle":
        return 40, 40
    w = 55
    h = 14 + 8 * max(0, lines - 1) + (6 if sub else 0)
    if shape == "ellipse":
        w, h = 60, int(h * 1.45)
    elif shape == "hexagon":
        h = int(h * 1.2)
    return w, h


class StampDialog(QDialog):
    """Tạo mới (spec=None: có thêm Kiểu watermark và Đóng lên trang nào) hoặc sửa dấu đã đóng (spec)."""

    def __init__(self, parent, settings=None, spec: dict | None = None, has_selection: bool = False,
                 page=None):
        """page = (ảnh trang QImage, (rộng, cao) pt, (x, y) tâm dấu pt | None): xem nhanh dấu trên trang."""
        super().__init__(parent)
        self.page = page
        self.settings = settings
        self.editing = spec is not None
        self.setWindowTitle("Sửa con dấu" if self.editing else "Con dấu chữ")
        self._color = "#d32f2f"
        self._auto_h = not self.editing
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 1)
        f = QFormLayout()
        f.setHorizontalSpacing(12)

        self.cb_recent = QComboBox()
        self.cb_recent.addItem("— Chọn mẫu đã dùng —", None)
        for js in self._recent():
            try:
                sp = json.loads(js)
            except ValueError:
                continue
            self.cb_recent.addItem(self._recent_label(sp), sp)
        if self.cb_recent.count() > 1 and not self.editing:
            f.addRow("Mẫu của tôi:", self.cb_recent)

        if not self.editing:
            self.cb_style = QComboBox()
            self.cb_style.addItem("Con dấu – đặt tự do trên trang, sửa lại được", "stamp")
            self.cb_style.addItem("Chữ chìm chéo trang, mờ (watermark) – cũng sửa lại được", "watermark")
            f.addRow("Kiểu:", self.cb_style)

        self.cb_text = QComboBox(editable=True)
        self.cb_text.addItems(items.STAMP_PRESETS)
        self.cb_text.setToolTip("Chọn có sẵn hoặc gõ chữ của mình. Muốn xuống dòng: gõ dấu | (vd. SAO Y|BẢN CHÍNH)")
        f.addRow("Nội dung:", self.cb_text)

        sub_row = QWidget()
        h = QHBoxLayout(sub_row)
        h.setContentsMargins(0, 0, 0, 0)
        self.ed_sub = QLineEdit(placeholderText="Dòng nhỏ bên dưới (tùy chọn): ngày, tên người, phòng ban…")
        self.btn_today = QPushButton("Ngày hôm nay")
        self.btn_today.clicked.connect(lambda: self.ed_sub.setText(f"Ngày {date.today():%d/%m/%Y}"))
        h.addWidget(self.ed_sub, 1)
        h.addWidget(self.btn_today)
        f.addRow("Dòng phụ:", sub_row)

        self.cb_shape = QComboBox()
        for k, t in items.STAMP_SHAPES:
            self.cb_shape.addItem(t, k)
        f.addRow("Hình dạng:", self.cb_shape)
        self.ed_arc = QLineEdit(placeholderText="Chữ chạy vòng theo mép (vd. tên đơn vị) – chỉ với dấu tròn")
        self.lbl_arc = QLabel("Chữ vòng:")
        f.addRow(self.lbl_arc, self.ed_arc)

        self.cb_border = QComboBox()
        for k, t in items.STAMP_BORDERS:
            self.cb_border.addItem(t, k)
        f.addRow("Viền:", self.cb_border)
        self.cb_family = QComboBox()
        for k, t in items.STAMP_FONTS:
            self.cb_family.addItem(t, k)
        f.addRow("Phông chữ:", self.cb_family)

        col_row = QWidget()
        h = QHBoxLayout(col_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.color_btns = []
        for t, c in COLORS:
            b = QPushButton()
            b.setFixedSize(26, 22)
            b.setToolTip(t)
            b.setCheckable(True)
            b.setStyleSheet(f"QPushButton{{background:{c};border:1px solid #888;border-radius:4px}}"
                            f"QPushButton:checked{{border:3px solid #005fb8}}")
            b.clicked.connect(lambda _=False, c=c: self.set_color(c))
            h.addWidget(b)
            self.color_btns.append((c, b))
        more = QPushButton("Màu khác…")
        more.clicked.connect(self._pick_color)
        h.addWidget(more)
        h.addStretch()
        f.addRow("Màu:", col_row)
        self.sl_op = SliderSpin(10, 100, 100, tooltip="Độ đậm của mực")
        f.addRow("Độ đậm:", self.sl_op)
        self.sl_w = SliderSpin(10, 250, 55, suffix=" mm", tooltip="Chiều rộng con dấu")
        f.addRow("Rộng:", self.sl_w)
        self.sl_h = SliderSpin(6, 250, 16, suffix=" mm", tooltip="Chiều cao con dấu")
        f.addRow("Cao:", self.sl_h)
        self.sl_angle = SliderSpin(-180, 180, 0, suffix="°", tooltip="Góc xoay (trên trang kéo núm tròn cũng được)")
        f.addRow("Xoay:", self.sl_angle)

        if not self.editing:
            self.cb_scope = QComboBox()
            self.cb_scope.addItem("Trang đang đặt (bấm vào trang khác để chuyển dấu sang đó)", "current")
            if has_selection:
                self.cb_scope.addItem("Các trang đang chọn (cùng vị trí)", "selected")
            self.cb_scope.addItem("Tất cả các trang (cùng vị trí)", "all")
            f.addRow("Đóng lên:", self.cb_scope)
        left.addLayout(f)
        hint = ("Bấm OK: dấu hiện nổi trên trang – kéo đến chỗ bất kỳ, bấm sang trang khác để chuyển, kéo góc "
                "đổi cỡ, núm tròn để xoay. Đã đóng rồi vẫn bấm vào để sửa, nháy đúp để mở lại hộp này.")
        left.addWidget(QLabel(hint, objectName="lbl", wordWrap=True))
        left.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Áp dụng" if self.editing else "Đặt lên trang")
        bb.button(QDialogButtonBox.Cancel).setText("Hủy")
        bb.accepted.connect(lambda: self._text() and self.accept())
        bb.rejected.connect(self.reject)
        left.addWidget(bb)

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Xem trước</b>"))
        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setFixedSize(260, 220)
        self.preview.setStyleSheet("QLabel{background:#ffffff;border:1px solid #c8c8c8;border-radius:6px}")
        right.addWidget(self.preview)
        self.page_preview = QLabel(alignment=Qt.AlignCenter)        # 1.0.22: xem nhanh dấu trên trang
        self.page_preview.setFixedSize(260, 260)
        self.page_preview.setStyleSheet("QLabel{background:#e9e9e9;border:1px solid #c8c8c8;border-radius:6px}")
        self.lbl_page = QLabel("<b>Trên trang</b> (đúng tỉ lệ)")
        right.addWidget(self.lbl_page)
        right.addWidget(self.page_preview)
        self.lbl_page.setVisible(page is not None)
        self.page_preview.setVisible(page is not None)
        right.addStretch()
        root.addLayout(right)

        self._timer = QTimer(self, singleShot=True, interval=60)
        self._timer.timeout.connect(self._render)
        if spec:
            self.load(spec)
        else:
            self.set_color("#d32f2f")
            self.cb_border.setCurrentIndex(1)
            self._auto_size()
        for sig in (self.cb_text.currentTextChanged, self.ed_sub.textChanged, self.ed_arc.textChanged,
                    self.cb_border.currentIndexChanged, self.cb_family.currentIndexChanged,
                    self.sl_op.valueChanged, self.sl_angle.valueChanged, self.sl_w.valueChanged):
            sig.connect(self._changed)
        self.sl_h.valueChanged.connect(self._h_typed)
        self.cb_shape.currentIndexChanged.connect(self._shape_changed)
        self.cb_text.currentTextChanged.connect(lambda _t: self._auto_size())
        self.ed_sub.textChanged.connect(lambda _t: self._auto_size())
        self.cb_recent.currentIndexChanged.connect(self._use_recent)
        if not self.editing:
            self.cb_style.currentIndexChanged.connect(self._style_changed)
        self._shape_changed()

    # ---------- giá trị ----------
    def _text(self) -> str:
        return "\n".join(p.strip() for p in self.cb_text.currentText().split("|") if p.strip())

    def set_color(self, c: str):
        self._color = c
        for cc, b in self.color_btns:
            b.setChecked(cc.lower() == c.lower())
        self._changed()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Màu con dấu")
        if c.isValid():
            self.set_color(c.name())

    def style(self) -> str:
        return "stamp"                                 # 1.0.22: chữ chìm cũng là con dấu sửa lại được

    def spec(self, rect=None) -> dict:
        w, hh = self.sl_w.value() * MM, self.sl_h.value() * MM
        if self.cb_shape.currentData() == "circle":
            hh = w
        r = rect or (0, 0, w, hh)
        return items.stamp_spec(self._text(), self.cb_shape.currentData(), r, sub=self.ed_sub.text().strip(),
                                arc=self.ed_arc.text().strip(), border=self.cb_border.currentData(),
                                family=self.cb_family.currentData(), color=self._color, opacity=self.sl_op.value(),
                                angle=self.sl_angle.value() % 360)

    def values(self) -> dict:
        """Cho kiểu watermark (giữ như trước) + phạm vi."""
        return {"text": self._text().replace("\n", " "), "style": self.style(), "color": self._color,
                "opacity": self.sl_op.value() / 100,
                "scope": "current" if self.editing else self.cb_scope.currentData(), "spec": self.spec()}

    def load(self, sp: dict):
        for w in (self.cb_text, self.ed_sub, self.ed_arc, self.cb_shape, self.cb_border, self.cb_family,
                  self.sl_op, self.sl_w, self.sl_h, self.sl_angle):
            w.blockSignals(True)
        try:
            self.cb_text.setCurrentText((sp.get("text") or "").replace("\n", "|"))
            self.ed_sub.setText(sp.get("sub") or "")
            self.ed_arc.setText(sp.get("arc") or "")
            self.cb_shape.setCurrentIndex(max(0, self.cb_shape.findData(sp.get("shape", "rect"))))
            self.cb_border.setCurrentIndex(max(0, self.cb_border.findData(sp.get("border", "double"))))
            self.cb_family.setCurrentIndex(max(0, self.cb_family.findData(sp.get("family", "sans"))))
            self.sl_op.setValue(int(sp.get("opacity", 100)))
            x0, y0, x1, y1 = items.spec_rect(sp)
            self.sl_w.setValue(round((x1 - x0) / MM))
            self.sl_h.setValue(round((y1 - y0) / MM))
            a = float(sp.get("angle", 0) or 0) % 360
            self.sl_angle.setValue(a - 360 if a > 180 else a)
        finally:
            for w in (self.cb_text, self.ed_sub, self.ed_arc, self.cb_shape, self.cb_border, self.cb_family,
                      self.sl_op, self.sl_w, self.sl_h, self.sl_angle):
                w.blockSignals(False)
        self._auto_h = False
        self.set_color(sp.get("color", "#d32f2f"))
        self._shape_changed()

    # ---------- phản hồi ----------
    def _auto_size(self):
        if not self._auto_h:
            return
        t = self._text()
        w, h = default_size_mm(self.cb_shape.currentData(), max(1, t.count("\n") + 1), bool(self.ed_sub.text().strip()))
        self.sl_w.blockSignals(True)
        self.sl_h.blockSignals(True)
        self.sl_w.setValue(w)
        self.sl_h.setValue(h)
        self.sl_w.blockSignals(False)
        self.sl_h.blockSignals(False)
        self._changed()

    def _h_typed(self, _v):
        self._auto_h = False                          # người dùng tự chỉnh chiều cao -> thôi tự tính
        self._changed()

    def _shape_changed(self, *_):
        circ = self.cb_shape.currentData() == "circle"
        self.ed_arc.setEnabled(circ)
        self.lbl_arc.setEnabled(circ)
        self.sl_h.setEnabled(not circ)
        self.cb_border.setEnabled(self.cb_shape.currentData() != "none")
        if self._auto_h:
            self._auto_size()
        self._changed()

    def _style_changed(self, *_):
        """Chữ chìm chéo trang = con dấu không khung, chữ lớn, mờ, xoay chéo (mọi ô vẫn chỉnh được)."""
        wm = self.cb_style.currentData() == "watermark"
        self._auto_h = False
        for w in (self.cb_shape, self.cb_border, self.sl_op, self.sl_w, self.sl_h, self.sl_angle, self.ed_sub):
            w.blockSignals(True)
        try:
            if wm:
                self.cb_shape.setCurrentIndex(self.cb_shape.findData("none"))
                self.sl_op.setValue(25)
                self.sl_w.setValue(170)
                self.sl_h.setValue(40)
                self.sl_angle.setValue(-45)
            else:
                self.cb_shape.setCurrentIndex(self.cb_shape.findData("rect"))
                self.sl_op.setValue(100)
                self.sl_angle.setValue(0)
                self._auto_h = True
        finally:
            for w in (self.cb_shape, self.cb_border, self.sl_op, self.sl_w, self.sl_h, self.sl_angle, self.ed_sub):
                w.blockSignals(False)
        self._shape_changed()

    def _use_recent(self, k):
        sp = self.cb_recent.itemData(k)
        if sp:
            self.load(sp)

    def _changed(self, *_):
        self._timer.start()

    def _render(self):
        from .ui_edit import pil_to_qimage
        sp = self.spec()
        if not sp["text"] and not sp["sub"] and not sp["arc"]:
            self.preview.clear()
            return
        sp = dict(sp)
        sp["rect"] = [0, 0, items.spec_rect(sp)[2], items.spec_rect(sp)[3]]
        try:
            img, _m = items.render_preview(sp, scale=3.0)
        except Exception as e:
            self.preview.setText(str(e))
            return
        q = pil_to_qimage(img)
        pm = QPixmap.fromImage(q)
        if sp.get("angle"):
            from PySide6.QtGui import QTransform
            pm = pm.transformed(QTransform().rotate(float(sp["angle"])), Qt.SmoothTransformation)
        self.preview.setPixmap(pm.scaled(244, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._render_page(q, sp, _m)

    def _render_page(self, stamp_img, sp, m):
        """Ảnh trang thu nhỏ + con dấu đúng cỡ, đúng góc, đặt ở tâm dấu (hoặc giữa trang)."""
        if not self.page:
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter
        img, (pw, ph), center = self.page
        W, H = 256, 256
        k = min(W / pw, H / ph)                                 # pixel / pt
        canvas = QPixmap(int(pw * k), int(ph * k))
        canvas.fill(Qt.white)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(canvas.rect(), img)
        x0, y0, x1, y1 = items.spec_rect(sp)
        sw, sh = (x1 - x0 + 2 * m) * k, (y1 - y0 + 2 * m) * k
        cx, cy = center or (pw / 2, ph / 2)
        p.translate(QPointF(cx * k, cy * k))
        p.rotate(float(sp.get("angle", 0) or 0))
        from PySide6.QtCore import QRectF
        p.drawImage(QRectF(-sw / 2, -sh / 2, sw, sh), stamp_img)
        p.end()
        self.page_preview.setPixmap(canvas)

    # ---------- mẫu đã dùng ----------
    def _recent(self) -> list[str]:
        if self.settings is None:
            return []
        v = self.settings.value(RECENT_KEY, [])
        if isinstance(v, str):
            v = [v]
        return list(v or [])

    @staticmethod
    def _recent_label(sp) -> str:
        shape = dict(items.STAMP_SHAPES).get(sp.get("shape"), "")
        t = (sp.get("text") or "").replace("\n", " ")
        return f"{t} · {shape}" + (f" · {sp['sub']}" if sp.get("sub") else "")

    def remember(self):
        """Lưu kiểu dấu vừa dùng vào 'Mẫu của tôi' (12 mẫu gần nhất)."""
        if self.settings is None:
            return
        sp = self.spec()
        sp.pop("id", None)
        sp["angle"] = 0
        key = json.dumps({k: v for k, v in sp.items() if k != "rect"}, ensure_ascii=True, sort_keys=True)
        out, seen = [json.dumps(sp, ensure_ascii=True)], {key}
        for js in self._recent():
            try:
                o = json.loads(js)
            except ValueError:
                continue
            o["angle"] = 0
            k = json.dumps({kk: vv for kk, vv in o.items() if kk not in ("rect", "id")}, ensure_ascii=True,
                           sort_keys=True)
            if k not in seen:
                seen.add(k)
                out.append(js)
        self.settings.setValue(RECENT_KEY, out[:12])


__all__ = ["StampDialog", "MM", "default_size_mm"]
