"""Hộp thoại: tách file, đổi kích thước trang."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from .document import PAPER_SIZES, PdfDocument, format_ranges, parse_ranges


def split_groups(n: int, mode: str, value: str | int, selected: list[int]) -> list[list[int]]:
    """Tính các nhóm trang cho từng file tách ra.
    mode: 'every' (mỗi N trang) | 'ranges' ("1-3; 4-6" hoặc "1-3, 4-6" -> mỗi dải một file)
          | 'single' (mỗi trang một file) | 'selected' (các trang đang chọn -> 1 file)."""
    if mode == "single":
        return [[i] for i in range(n)]
    if mode == "every":
        k = max(1, int(value))
        return [list(range(i, min(i + k, n))) for i in range(0, n, k)]
    if mode == "selected":
        if not selected:
            raise ValueError("Chưa chọn trang nào")
        return [sorted(selected)]
    groups = []
    for part in str(value).replace(";", ",").split(","):
        part = part.strip()
        if part:
            groups.append(parse_ranges(part, n))
    if not groups:
        raise ValueError("Nhập dải trang, ví dụ: 1-3, 4-6, 7-")
    return groups


def write_split(doc: PdfDocument, groups: list[list[int]], folder: str, base: str) -> list[str]:
    os.makedirs(folder, exist_ok=True)
    out = []
    width = len(str(len(groups)))
    for k, g in enumerate(groups, 1):
        name = f"{base}_{str(k).zfill(width)}_trang_{format_ranges(g).replace(', ', '_').replace(' ', '')}.pdf"
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(doc.extract(g))
        out.append(path)
    return out


class SplitDialog(QDialog):
    def __init__(self, parent, doc: PdfDocument, selected: list[int]):
        super().__init__(parent)
        self.setWindowTitle("Tách file / trích trang")
        self.doc, self.selected = doc, selected
        v = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.r_sel = QRadioButton(f"Trích các trang đang chọn ({format_ranges(selected) or 'chưa chọn'}) ra một file")
        self.r_every = QRadioButton("Mỗi")
        self.sp_every = QSpinBox(minimum=1, maximum=max(1, doc.page_count), value=1)
        self.r_ranges = QRadioButton("Theo dải, mỗi dải một file:")
        self.ed_ranges = QLineEdit(placeholderText="vd: 1-3, 4-10, 11-")
        self.r_single = QRadioButton("Mỗi trang một file")
        for k, r in enumerate((self.r_sel, self.r_every, self.r_ranges, self.r_single)):
            self.group.addButton(r, k)
        (self.r_sel if len(selected) > 1 else self.r_every).setChecked(True)
        v.addWidget(self.r_sel)
        h = QHBoxLayout()
        h.addWidget(self.r_every)
        h.addWidget(self.sp_every)
        h.addWidget(QLabel("trang một file"))
        h.addStretch()
        v.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(self.r_ranges)
        h.addWidget(self.ed_ranges, 1)
        v.addLayout(h)
        v.addWidget(self.r_single)
        f = QFormLayout()
        base_dir = os.path.dirname(doc.path) if doc.path else os.path.expanduser("~")
        self.ed_folder = QLineEdit(base_dir)
        pick = QPushButton("Chọn…")
        pick.clicked.connect(self._pick)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.ed_folder, 1)
        rl.addWidget(pick)
        f.addRow("Lưu vào thư mục:", row)
        self.ed_base = QLineEdit(os.path.splitext(doc.name)[0])
        f.addRow("Tên file gốc:", self.ed_base)
        v.addLayout(f)
        self.lbl = QLabel("", objectName="lbl")
        v.addWidget(self.lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tách")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục", self.ed_folder.text())
        if d:
            self.ed_folder.setText(d)

    def groups(self) -> list[list[int]]:
        mode = ["selected", "every", "ranges", "single"][self.group.checkedId()]
        value = self.sp_every.value() if mode == "every" else self.ed_ranges.text()
        return split_groups(self.doc.page_count, mode, value, self.selected)


class ResizeDialog(QDialog):
    MODES = [("Co vừa (giữ tỉ lệ, thêm lề trắng)", "fit"), ("Lấp đầy (giữ tỉ lệ, cắt mép thừa)", "fill"),
             ("Giữ 100% (chỉ đổi khổ giấy, căn giữa)", "none")]
    ORIENT = [("Giữ nguyên hướng", "keep"), ("Dọc", "portrait"), ("Ngang", "landscape")]

    def __init__(self, parent, n_selected: int, n_total: int):
        super().__init__(parent)
        self.setWindowTitle("Đổi kích thước trang")
        f = QFormLayout(self)
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItems([f"Các trang đang chọn ({n_selected})", f"Toàn bộ tài liệu ({n_total})"])
        f.addRow("Áp dụng cho:", self.cmb_scope)
        self.cmb_paper = QComboBox()
        self.cmb_paper.addItems(list(PAPER_SIZES) + ["Tự nhập (mm)"])
        self.cmb_paper.setCurrentText("A4")
        f.addRow("Khổ đích:", self.cmb_paper)
        self.sp_w = QDoubleSpinBox(minimum=20, maximum=2000, value=210, suffix=" mm")
        self.sp_h = QDoubleSpinBox(minimum=20, maximum=2000, value=297, suffix=" mm")
        cw = QWidget()
        cl = QHBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.sp_w)
        cl.addWidget(QLabel("×"))
        cl.addWidget(self.sp_h)
        f.addRow("Kích thước tự nhập:", cw)
        self.cmb_orient = QComboBox()
        self.cmb_orient.addItems([t for t, _ in self.ORIENT])
        f.addRow("Hướng giấy:", self.cmb_orient)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([t for t, _ in self.MODES])
        f.addRow("Cách co giãn:", self.cmb_mode)
        self.sp_margin = QDoubleSpinBox(minimum=0, maximum=30, value=0, suffix=" mm")
        f.addRow("Lề thêm:", self.sp_margin)
        f.addRow(QLabel("Nội dung giữ dạng vector: chữ vẫn nét, vẫn tìm kiếm được.", objectName="lbl"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Đổi kích thước")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self) -> dict:
        paper = self.cmb_paper.currentText()
        custom = (self.sp_w.value(), self.sp_h.value()) if paper not in PAPER_SIZES else None
        return dict(all_pages=self.cmb_scope.currentIndex() == 1,
                    paper=paper if paper in PAPER_SIZES else "A4", custom_mm=custom,
                    orientation=self.ORIENT[self.cmb_orient.currentIndex()][1],
                    mode=self.MODES[self.cmb_mode.currentIndex()][1],
                    margin_mm=self.sp_margin.value())
