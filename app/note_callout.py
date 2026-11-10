"""Khung ghi chú nổi ngay trên trang (1.0.22), thay hộp thoại ghi chú.

Khung có mũi tên trỏ đúng chỗ bấm / đúng biểu tượng ghi chú; gõ nội dung ngay trong khung.
Các tùy chọn của ghi chú (màu, biểu tượng, độ đậm, đã xử lý) nằm ngay dưới ô gõ.
Bấm ra ngoài khung: lưu (nếu có thay đổi) · Esc: thôi, không lưu · Ctrl+Enter: lưu.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

TAIL = 16            # độ dài mũi tên (px)
RADIUS = 8
BUBBLE_W = 320


class NoteCallout(QFrame):
    """Khung ghi chú có mũi tên. note=None: ghi chú mới."""
    saveRequested = Signal(dict)
    deleteRequested = Signal()
    closeRequested = Signal()            # đóng không lưu

    def __init__(self, author: str = "", note=None, settings=None, readonly: bool = False, parent=None):
        from .notes import NOTE_COLORS, NOTE_ICONS
        from .theme import ui_is_dark
        super().__init__(parent)
        self.setObjectName("notecallout")
        self.note = note
        self.readonly = readonly
        self.side = "left"               # mũi tên ở bên trái khung (khung nằm bên phải chỗ bấm)
        self.tip_y = 24.0
        self.dark = ui_is_dark()
        sticky = note is None or getattr(note, "is_sticky", True)
        self._color = (note.color if note is not None else
                       (settings.value("note/color", NOTE_COLORS[0][1]) if settings is not None else NOTE_COLORS[0][1]))
        fg, sub = ("#e6ebf5", "#9aa7bd") if self.dark else ("#1b1b1b", "#5f6b7a")
        field = "#1d2535" if self.dark else "#ffffff"
        self.setStyleSheet(
            f"#notecallout QLabel{{color:{fg};background:transparent}}"
            f"#notecallout QLabel#ncsub{{color:{sub};font-size:11px}}"
            f"#notecallout QPlainTextEdit, #notecallout QLineEdit{{background:{field};color:{fg};"
            f"border:1px solid {'#3a4760' if self.dark else '#c9d2de'};border-radius:4px;padding:3px}}"
            f"#notecallout QCheckBox{{color:{fg};background:transparent}}")
        self.setFixedWidth(BUBBLE_W + TAIL)
        v = QVBoxLayout(self)
        v.setSpacing(6)
        self._margins()

        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_title = QLabel("<b>" + (getattr(note, "kind_label", "Ghi chú") if note is not None else
                                         "Ghi chú mới") + "</b>")
        head.addWidget(self.lbl_title)
        self.lbl_info = QLabel("", objectName="ncsub")
        if note is not None:
            self.lbl_info.setText(" · ".join(x for x in (note.date_text, f"trang {note.page + 1}") if x))
        head.addWidget(self.lbl_info, 1)
        self.btn_x = QToolButton(text="✕", autoRaise=True, toolTip="Đóng, không lưu (Esc)")
        self.btn_x.clicked.connect(self.closeRequested.emit)
        head.addWidget(self.btn_x)
        v.addLayout(head)

        self.ed_author = QLineEdit(note.author if note is not None else author, placeholderText="Người ghi")
        self.ed_author.setToolTip("Người ghi")
        v.addWidget(self.ed_author)
        self.ed = QPlainTextEdit()
        self.ed.setPlaceholderText("Gõ nội dung ghi chú…")
        if note is not None:
            self.ed.setPlainText(note.text)
        self.ed.setMinimumHeight(60)
        self.ed.setMaximumHeight(110)
        v.addWidget(self.ed)

        # tùy chọn ghi chú: ngay dưới khu vực gõ
        self.opts = QWidget()
        oh = QHBoxLayout(self.opts)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(3)
        self.color_btns = []
        for name, col in NOTE_COLORS:
            b = QToolButton(toolTip=name, checkable=True, autoRaise=True)
            b.setFixedSize(18, 18)
            b.setStyleSheet(f"QToolButton{{background:{col};border-radius:9px;border:1px solid #9e9e9e}}"
                            f"QToolButton:checked{{border:2px solid #005fb8}}")
            b.clicked.connect(lambda _=False, c=col: self._set_color(c))
            oh.addWidget(b)
            self.color_btns.append((b, col))
        oh.addSpacing(4)
        self.cb_icon = QComboBox(toolTip="Biểu tượng")
        for k, lbl in NOTE_ICONS:
            self.cb_icon.addItem(lbl, k)
        self.cb_icon.setCurrentIndex(max(0, self.cb_icon.findData(
            note.icon if note is not None else (settings.value("note/icon", "comment") if settings else "comment"))))
        oh.addWidget(self.cb_icon, 1)
        v.addWidget(self.opts)
        o2 = QHBoxLayout()
        o2.setSpacing(6)
        lbl_op = QLabel("Độ đậm", objectName="ncsub")
        o2.addWidget(lbl_op)
        self.sl_opacity = QSlider(Qt.Horizontal, minimum=20, maximum=100, value=100)
        if note is not None:
            self.sl_opacity.setValue(int(note.opacity))
        o2.addWidget(self.sl_opacity, 1)
        self.chk_done = QCheckBox("Đã xử lý")
        self.chk_done.setChecked(bool(note.done) if note is not None else False)
        self.chk_done.setVisible(note is not None)
        o2.addWidget(self.chk_done)
        self.opts2 = QWidget()
        self.opts2.setLayout(o2)
        o2.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.opts2)
        if not sticky:                                   # tô sáng / hộp chữ: không có màu – biểu tượng riêng
            self.opts.setVisible(False)
            lbl_op.setVisible(False)
            self.sl_opacity.setVisible(False)

        self.lbl_replies = None
        self.ed_reply = None
        if note is not None:
            if note.replies:
                self.lbl_replies = QLabel("<br>".join(
                    f"↳ <b>{r.author or 'Không tên'}</b> ({r.date_text}): {r.text}" for r in note.replies),
                    wordWrap=True)
                self.lbl_replies.setStyleSheet(
                    "background:#25304a;color:#e6ebf5;padding:5px;border-radius:4px" if self.dark
                    else "background:#f3f6fb;color:#1b1b1b;padding:5px;border-radius:4px")
                v.addWidget(self.lbl_replies)
            self.ed_reply = QLineEdit(placeholderText="Viết trả lời (tùy chọn)…")
            v.addWidget(self.ed_reply)

        bh = QHBoxLayout()
        bh.setSpacing(6)
        self.btn_delete = None
        if note is not None and not readonly:
            self.btn_delete = QPushButton("Xóa ghi chú")
            self.btn_delete.setStyleSheet("color:#c62828")
            self.btn_delete.clicked.connect(self.deleteRequested.emit)
            bh.addWidget(self.btn_delete)
        bh.addStretch()
        self.btn_cancel = QPushButton("Đóng" if readonly else "Hủy")
        self.btn_cancel.clicked.connect(self.closeRequested.emit)
        bh.addWidget(self.btn_cancel)
        self.btn_save = None
        if not readonly:
            self.btn_save = QPushButton("Lưu", objectName="primary", toolTip="Lưu (Ctrl+Enter)")
            self.btn_save.clicked.connect(self.request_save)
            bh.addWidget(self.btn_save)
        v.addLayout(bh)
        self._set_color(self._color)
        if readonly:
            self.ed.setReadOnly(True)
            self.ed_author.setReadOnly(True)
            for w in (self.opts, self.opts2):
                w.setEnabled(False)
            if self.ed_reply is not None:
                self.ed_reply.setVisible(False)
            v.insertWidget(v.count() - 1, QLabel("File được bảo vệ – chỉ đọc được ghi chú, không sửa được.",
                                                 objectName="ncsub", wordWrap=True))
        self._initial = self.values()
        for w in (self.ed, self.ed_author, self.ed_reply):
            if w is not None:
                w.installEventFilter(self)

    # ---------- dữ liệu ----------
    def _set_color(self, c):
        self._color = c
        for b, col in self.color_btns:
            b.setChecked(col == c)
        self.update()

    def values(self) -> dict:
        return {"text": self.ed.toPlainText(), "author": self.ed_author.text(), "color": self._color,
                "icon": self.cb_icon.currentData(), "opacity": self.sl_opacity.value(),
                "done": self.chk_done.isChecked(), "reply": self.ed_reply.text().strip() if self.ed_reply else "",
                "action": "save"}

    def is_changed(self) -> bool:
        v = self.values()
        if self.note is None:
            return bool(v["text"].strip())
        return v != self._initial

    def request_save(self):
        if self.readonly:
            self.closeRequested.emit()
            return
        if self.note is None and not self.ed.toPlainText().strip():
            self.ed.setFocus()
            return
        self.saveRequested.emit(self.values())

    def finish_outside(self):
        """Bấm ra ngoài khung: lưu nếu có thay đổi, không thì đóng."""
        if not self.readonly and self.is_changed():
            self.saveRequested.emit(self.values())
        else:
            self.closeRequested.emit()

    # ---------- phím ----------
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.closeRequested.emit()
                return True
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and (ev.modifiers() & Qt.ControlModifier
                                                              or obj is self.ed_reply):
                self.request_save()
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.closeRequested.emit()
            return
        super().keyPressEvent(ev)

    # ---------- vị trí, mũi tên ----------
    def _margins(self):
        m = 10
        if self.side == "left":
            self.layout().setContentsMargins(TAIL + m, m, m, m)
        else:
            self.layout().setContentsMargins(m, m, TAIL + m, m)

    def set_side(self, side: str, tip_y: float):
        if side != self.side:
            self.side = side
            self._margins()
        self.tip_y = float(tip_y)
        self.update()

    def bubble_rect(self) -> QRectF:
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        return r.adjusted(TAIL, 0, 0, 0) if self.side == "left" else r.adjusted(0, 0, -TAIL, 0)

    def tip(self) -> QPointF:
        """Đầu mũi tên (tọa độ trong khung)."""
        return QPointF(3.0 if self.side == "left" else self.width() - 3.0, self.tip_y)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.bubble_rect()
        path = QPainterPath()
        path.addRoundedRect(b, RADIUS, RADIUS)
        ty = min(max(self.tip_y, b.top() + RADIUS + 8), b.bottom() - RADIUS - 8)
        tail = QPainterPath()
        if self.side == "left":
            tail.moveTo(b.left() + 1, ty - 8)
            tail.lineTo(self.tip())
            tail.lineTo(b.left() + 1, ty + 8)
        else:
            tail.moveTo(b.right() - 1, ty - 8)
            tail.lineTo(self.tip())
            tail.lineTo(b.right() - 1, ty + 8)
        tail.closeSubpath()
        path = path.united(tail)
        bg = QColor("#2a3346") if self.dark else QColor("#fffdf2")
        p.setPen(QPen(QColor(self._color).darker(130), 1.4))
        p.setBrush(bg)
        p.drawPath(path)
        p.setPen(Qt.NoPen)                               # dải màu ghi chú trên cùng
        p.setBrush(QColor(self._color))
        strip = QPainterPath()
        strip.addRoundedRect(QRectF(b.left() + 1, b.top() + 1, b.width() - 2, 6), 3, 3)
        p.drawPath(strip)
        p.setBrush(QColor(self._color).darker(140))      # chấm đúng chỗ trỏ
        p.drawEllipse(self.tip(), 3, 3)
        p.end()


__all__ = ["NoteCallout", "TAIL", "BUBBLE_W"]
