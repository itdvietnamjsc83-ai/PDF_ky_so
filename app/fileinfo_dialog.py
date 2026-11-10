"""Hộp thoại "Thông tin file": xem thông tin chung, xem / sửa / xóa các trường thông tin nằm trong file PDF."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import fileinfo as fi


class FileInfoDialog(QDialog):
    """values() -> (fields {khóa: chữ | None (xóa)}, xóa XMP?) khi bấm Áp dụng."""

    def __init__(self, parent, doc, data: bytes, readonly: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Thông tin file")
        self.resize(640, 720)
        self.info = fi.read_info(data)
        self.readonly = readonly
        v = QVBoxLayout(self)

        v.addWidget(QLabel("<b>Thông tin chung</b>"))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        for k, val in fi.file_facts(doc) + [("Phiên bản PDF", self.info["version"])]:
            lb = QLabel(val, wordWrap=True)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(k + ":", lb)
        v.addLayout(form)

        v.addWidget(QLabel("<b>Các trường thông tin nằm trong file</b>"))
        v.addWidget(QLabel("Người nhận file xem được các thông tin này (Thuộc tính tài liệu). Bấm đúp để sửa, "
                           "chọn dòng rồi bấm Xóa để bỏ trường đó.", objectName="lbl", wordWrap=True))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Trường", "Giá trị"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers if readonly else
                                   QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.SelectedClicked)
        fields = self.info["fields"]
        keys = [k for k in fi.STD_KEYS] + sorted(k for k in fields if k not in fi.STD_KEYS)
        for k in keys:
            self._add_row(k, fields.get(k, ""))
        self.table.setMinimumHeight(260)
        v.addWidget(self.table, 1)

        self.chk_xmp = QCheckBox("Xóa cả gói thông tin XMP (bản lặp lại tác giả, phần mềm, ngày tháng)")
        self.chk_xmp.setVisible(self.info["xmp"])
        v.addWidget(self.chk_xmp)

        row = QHBoxLayout()
        self.btn_del = QPushButton("Xóa trường đã chọn")
        self.btn_del.clicked.connect(self.clear_selected)
        self.btn_all = QPushButton("Xóa hết thông tin (trước khi gửi)")
        self.btn_all.setToolTip("Xóa tác giả, phần mềm, ngày tạo / sửa, các trường riêng và gói XMP")
        self.btn_all.clicked.connect(self.clear_all)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_all)
        row.addStretch()
        v.addLayout(row)
        if readonly:
            for w in (self.btn_del, self.btn_all, self.chk_xmp):
                w.setEnabled(False)
            v.addWidget(QLabel("File được bảo vệ – chỉ xem được, không sửa / xóa được thông tin.", objectName="lbl"))
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(self.reject)
        else:
            v.addWidget(QLabel("Bấm Áp dụng rồi Lưu (hoặc Lưu thành…) để ghi vào file. Ctrl+Z để hoàn tác.",
                               objectName="lbl", wordWrap=True))
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.button(QDialogButtonBox.Ok).setText("Áp dụng")
            bb.button(QDialogButtonBox.Cancel).setText("Hủy")
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _add_row(self, key: str, raw: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(fi.LABEL.get(key, key.lstrip("/")))
        name.setFlags(name.flags() & ~Qt.ItemIsEditable)
        name.setData(Qt.UserRole, key)
        name.setToolTip(key)
        self.table.setItem(r, 0, name)
        is_date = key in fi.DATE_KEYS
        val = QTableWidgetItem(fi.date_text(raw) if is_date else raw)
        val.setData(Qt.UserRole, raw)
        if is_date:                                  # ngày: chỉ xóa được, không gõ tay (giữ đúng định dạng PDF)
            val.setFlags(val.flags() & ~Qt.ItemIsEditable)
            val.setToolTip("Ngày tháng chỉ xóa được")
        self.table.setItem(r, 1, val)

    def clear_selected(self):
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 1)
            it.setText("")
            it.setData(Qt.UserRole, "")

    def clear_all(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 1)
            it.setText("")
            it.setData(Qt.UserRole, "")
        if self.info["xmp"]:
            self.chk_xmp.setChecked(True)

    def values(self) -> tuple[dict, bool]:
        old = self.info["fields"]
        out = {}
        for r in range(self.table.rowCount()):
            key = self.table.item(r, 0).data(Qt.UserRole)
            it = self.table.item(r, 1)
            if key in fi.DATE_KEYS:
                new = it.data(Qt.UserRole) or ""
            else:
                new = it.text().strip()
            if new != old.get(key, ""):
                out[key] = new or None
        return out, self.chk_xmp.isChecked()

    def changed(self) -> bool:
        f, x = self.values()
        return bool(f) or x


__all__ = ["FileInfoDialog"]
