"""Widget dùng chung (1.0.22)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSlider, QSpinBox, QWidget


class SliderSpin(QWidget):
    """Thanh kéo + ô nhập số đi kèm (vd. 10–400 %): kéo hay gõ số đều được, hai bên luôn khớp nhau.
    Dùng cho mọi chỗ có tỉ lệ / phóng to – thu nhỏ / độ đậm."""
    valueChanged = Signal(int)

    def __init__(self, minimum: int = 0, maximum: int = 100, value: int = 0, suffix: str = "%",
                 slider_width: int | None = None, step: int = 1, parent=None, tooltip: str = ""):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal, minimum=minimum, maximum=maximum, value=value)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(max(step, (maximum - minimum) // 10))
        if slider_width:
            self.slider.setFixedWidth(slider_width)
        self.spin = QSpinBox(minimum=minimum, maximum=maximum, value=value, suffix=suffix)
        self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)        # gõ xong (Enter / rời ô) mới áp dụng
        self.spin.setAccelerated(True)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setFixedWidth(80 if maximum < 1000 and len(suffix) <= 2 else 96)
        if tooltip:
            self.slider.setToolTip(tooltip)
            self.spin.setToolTip(tooltip + " – gõ số rồi Enter")
        h.addWidget(self.slider, 0 if slider_width else 1)
        h.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v):
        if self.spin.value() != v:
            self.spin.blockSignals(True)
            self.spin.setValue(v)
            self.spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        if self.slider.value() != v:
            self.slider.blockSignals(True)
            self.slider.setValue(v)
            self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        v = int(round(v))
        self.slider.setValue(v)                      # -> spin theo, phát valueChanged một lần
        if self.spin.value() != self.slider.value():
            self.spin.blockSignals(True)
            self.spin.setValue(self.slider.value())
            self.spin.blockSignals(False)

    def setRange(self, lo: int, hi: int):
        self.slider.setRange(lo, hi)
        self.spin.setRange(lo, hi)

    def minimum(self) -> int:
        return self.slider.minimum()

    def maximum(self) -> int:
        return self.slider.maximum()

    def blockSignals(self, b: bool) -> bool:        # chặn cả hai con (đặt giá trị mà không báo đổi)
        self.slider.blockSignals(b)
        self.spin.blockSignals(b)
        return super().blockSignals(b)


__all__ = ["SliderSpin"]
