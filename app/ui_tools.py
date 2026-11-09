"""Giao diện giai đoạn 6: bảo vệ, mẫu bảo vệ, nén, so sánh, dấu chữ, ký hàng loạt, luồng ký,
tạo hàng loạt từ Excel, lịch sử phiên bản, thư mục tự xử lý."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSlider,
                               QTextBrowser, QVBoxLayout)

from . import APP_NAME
from .protect import PRESETS, PRINT_HIGH, PRINT_LOW, PRINT_NONE, ProtectOptions


def _mb(n: int) -> str:
    return f"{n / 1048576:.2f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


# ------------------------------------------------------------------ bảo vệ
class ProtectDialog(QDialog):
    def __init__(self, parent, settings=None, page_count: int = 1, focus: str = ""):
        super().__init__(parent)
        self.settings = settings
        self.page_count = page_count
        self.setWindowTitle("Lưu có bảo vệ")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Mẫu bảo vệ:"))
        self.cb_preset = QComboBox()
        row.addWidget(self.cb_preset, 1)
        b = QPushButton("Lưu thành mẫu…")
        b.clicked.connect(self.save_preset)
        row.addWidget(b)
        self.btn_del = QPushButton("Xóa mẫu")
        self.btn_del.clicked.connect(self.delete_preset)
        row.addWidget(self.btn_del)
        v.addLayout(row)

        g = QGroupBox("In")
        gl = QVBoxLayout(g)
        self.rb = {k: QRadioButton(t) for k, t in ((PRINT_NONE, "Không cho in"),
                                                     (PRINT_LOW, "Chỉ cho in chất lượng thấp"),
                                                     (PRINT_HIGH, "Cho in đầy đủ"))}
        self.grp = QButtonGroup(self)
        for rbt in self.rb.values():
            self.grp.addButton(rbt)
            gl.addWidget(rbt)
        low = QHBoxLayout()
        low.setContentsMargins(24, 0, 0, 0)
        self.chk_layer = QCheckBox("In ra bản mờ, xem trên máy vẫn nét")
        self.cb_dpi = QComboBox()
        for d, t in ((72, "72 dpi – rất mờ"), (100, "100 dpi – mờ vừa"), (150, "150 dpi – hơi mờ")):
            self.cb_dpi.addItem(t, d)
        self.cb_dpi.setCurrentIndex(1)
        self.chk_gray = QCheckBox("Thang xám")
        low.addWidget(self.chk_layer)
        low.addWidget(self.cb_dpi)
        low.addWidget(self.chk_gray)
        gl.addLayout(low)
        self.lbl_size = QLabel("", objectName="lbl", wordWrap=True)
        gl.addWidget(self.lbl_size)
        v.addWidget(g)

        g = QGroupBox("Quyền khác")
        gl = QVBoxLayout(g)
        self.chk_copy = QCheckBox("Cho sao chép chữ, hình ảnh")
        self.chk_edit = QCheckBox("Cho sửa nội dung, thêm/bớt trang")
        self.chk_annot = QCheckBox("Cho ghi chú, điền biểu mẫu")
        for c in (self.chk_copy, self.chk_edit, self.chk_annot):
            gl.addWidget(c)
        v.addWidget(g)

        g = QGroupBox("Mật khẩu")
        f = QFormLayout(g)
        self.ed_open = QLineEdit(echoMode=QLineEdit.Password, placeholderText="để trống: ai cũng mở xem được")
        self.ed_open2 = QLineEdit(echoMode=QLineEdit.Password, placeholderText="nhập lại")
        self.ed_owner = QLineEdit(echoMode=QLineEdit.Password,
                                  placeholderText="để gỡ bảo vệ hoặc ký số file này sau")
        f.addRow("Mật khẩu mở file:", self.ed_open)
        f.addRow("", self.ed_open2)
        f.addRow("Mật khẩu chủ sở hữu:", self.ed_owner)
        self.lbl_owner = QLabel("Không đặt mật khẩu chủ sở hữu: phần mềm tạo mật khẩu ngẫu nhiên, sau này không ai "
                                "gỡ được bảo vệ và không ký số thêm được. Muốn ký số sau thì hãy đặt.",
                                objectName="lbl", wordWrap=True)
        f.addRow("", self.lbl_owner)
        v.addWidget(g)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lưu có bảo vệ…")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self._fill_presets()
        self.cb_preset.currentIndexChanged.connect(self._preset_chosen)
        for w in list(self.rb.values()) + [self.chk_layer, self.chk_gray]:
            w.toggled.connect(self._update)
        self.cb_dpi.currentIndexChanged.connect(self._update)
        self.ed_owner.textChanged.connect(self._update)
        last = settings.value("protect/last") if settings is not None else None
        self.set_options(ProtectOptions.from_dict(json.loads(last)) if last else PRESETS[1][1])
        if focus == "password":
            self.ed_open.setFocus()

    # ---- mẫu
    def _user_presets(self) -> list:
        if self.settings is None:
            return []
        try:
            return json.loads(self.settings.value("protect/presets", "[]") or "[]")
        except ValueError:
            return []

    def _fill_presets(self, select: str | None = None):
        self.cb_preset.blockSignals(True)
        self.cb_preset.clear()
        self.cb_preset.addItem("(tự chọn)", None)
        for name, o in PRESETS:
            self.cb_preset.addItem(name, ("builtin", name, o.to_dict()))
        for p in self._user_presets():
            self.cb_preset.addItem("★ " + p["name"], ("user", p["name"], p["options"]))
        if select:
            k = self.cb_preset.findText("★ " + select)
            self.cb_preset.setCurrentIndex(max(0, k))
        self.cb_preset.blockSignals(False)
        self._update_del()

    def _update_del(self):
        d = self.cb_preset.currentData()
        self.btn_del.setEnabled(bool(d and d[0] == "user"))

    def _preset_chosen(self, *_):
        d = self.cb_preset.currentData()
        if d:
            self.set_options(ProtectOptions.from_dict(d[2]), keep_passwords=True)
        self._update_del()

    def save_preset(self, name: str | None = None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Mẫu bảo vệ", "Tên mẫu:")
            if not ok or not name.strip():
                return
        lst = [p for p in self._user_presets() if p["name"] != name.strip()]
        lst.append({"name": name.strip(), "options": self.options().to_dict()})     # không lưu mật khẩu
        if self.settings is not None:
            self.settings.setValue("protect/presets", json.dumps(lst, ensure_ascii=False))
        self._fill_presets(name.strip())

    def delete_preset(self):
        d = self.cb_preset.currentData()
        if not d or d[0] != "user":
            return
        lst = [p for p in self._user_presets() if p["name"] != d[1]]
        self.settings.setValue("protect/presets", json.dumps(lst, ensure_ascii=False))
        self._fill_presets()

    # ---- giá trị
    def set_options(self, o: ProtectOptions, keep_passwords: bool = False):
        self.rb[o.printing].setChecked(True)
        self.chk_layer.setChecked(o.lowres_layer)
        k = self.cb_dpi.findData(o.lowres_dpi)
        self.cb_dpi.setCurrentIndex(k if k >= 0 else 1)
        self.chk_gray.setChecked(o.grayscale)
        self.chk_copy.setChecked(o.allow_copy)
        self.chk_edit.setChecked(o.allow_edit)
        self.chk_annot.setChecked(o.allow_annotate)
        if not keep_passwords:
            self.ed_open.setText(o.open_password)
            self.ed_open2.setText(o.open_password)
            self.ed_owner.setText(o.owner_password)
        self._update()

    def options(self) -> ProtectOptions:
        pr = next(k for k, r in self.rb.items() if r.isChecked())
        return ProtectOptions(open_password=self.ed_open.text(), owner_password=self.ed_owner.text(), printing=pr,
                              allow_copy=self.chk_copy.isChecked(), allow_edit=self.chk_edit.isChecked(),
                              allow_annotate=self.chk_annot.isChecked(), lowres_layer=self.chk_layer.isChecked(),
                              lowres_dpi=self.cb_dpi.currentData(), grayscale=self.chk_gray.isChecked())

    def _update(self, *_):
        low = self.rb[PRINT_LOW].isChecked()
        for w in (self.chk_layer, self.cb_dpi, self.chk_gray):
            w.setEnabled(low)
        self.cb_dpi.setEnabled(low and self.chk_layer.isChecked())
        self.chk_gray.setEnabled(low and self.chk_layer.isChecked())
        if low and self.chk_layer.isChecked():
            per = {72: 12, 100: 22, 150: 45}[self.cb_dpi.currentData()] * (0.6 if self.chk_gray.isChecked() else 1)
            self.lbl_size.setText(f"Dung lượng tăng khoảng {per:.0f} KB/trang (≈ {_mb(int(per * 1024 * self.page_count))} "
                                  f"cho {self.page_count} trang). Chỉ dùng lớp in mờ khi thực sự cần.")
        elif low:
            self.lbl_size.setText("Chỉ đặt quyền in chất lượng thấp (một số phần mềm đọc PDF có thể bỏ qua).")
        else:
            self.lbl_size.setText("")
        self.lbl_owner.setVisible(not self.ed_owner.text())

    def _accept(self):
        o = self.options()
        if o.open_password != self.ed_open2.text():
            QMessageBox.warning(self, APP_NAME, "Hai lần nhập mật khẩu mở file không giống nhau.")
            return
        if o.owner_password and o.owner_password == o.open_password:
            QMessageBox.warning(self, APP_NAME, "Mật khẩu chủ sở hữu phải khác mật khẩu mở file.")
            return
        if self.settings is not None:
            self.settings.setValue("protect/last", json.dumps(o.to_dict(), ensure_ascii=False))
        self.accept()


# ------------------------------------------------------------------ nén
class CompressDialog(QDialog):
    LEVEL_LABELS = ["Nhẹ – gần như giữ nguyên chất lượng", "Vừa – bản scan in vẫn đẹp", "Vừa mạnh",
                    "Mạnh – đọc rõ trên màn hình", "Rất mạnh", "Tối đa", "Tối đa (72 dpi)"]

    def __init__(self, parent, size_bytes: int):
        super().__init__(parent)
        self.setWindowTitle("Nén theo dung lượng")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Dung lượng hiện tại: <b>{_mb(size_bytes)}</b>"))
        self.rb_target = QRadioButton("Nén tới dưới:")
        self.rb_level = QRadioButton("Mức nén:")
        self.rb_target.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.rb_target)
        self.sp_mb = QDoubleSpinBox(minimum=0.2, maximum=500, value=max(0.5, round(size_bytes / 1048576 / 2, 1)),
                                    suffix=" MB", decimals=1)
        row.addWidget(self.sp_mb)
        for mb in (2, 5, 10):
            b = QPushButton(f"{mb} MB")
            b.setToolTip("Giới hạn thường gặp của cổng dịch vụ công / email")
            b.clicked.connect(lambda _=False, m=mb: (self.sp_mb.setValue(m), self.rb_target.setChecked(True)))
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.rb_level)
        self.sl = QSlider(Qt.Horizontal, minimum=0, maximum=6, value=1)
        self.lbl_level = QLabel(self.LEVEL_LABELS[1])
        self.sl.valueChanged.connect(lambda k: (self.lbl_level.setText(self.LEVEL_LABELS[k]), self.rb_level.setChecked(True)))
        row.addWidget(self.sl, 1)
        v.addLayout(row)
        v.addWidget(self.lbl_level)
        self.chk_gray = QCheckBox("Chuyển ảnh sang thang xám (nhỏ hơn nhiều, hợp với văn bản đen trắng)")
        v.addWidget(self.chk_gray)
        v.addWidget(QLabel("Chỉ nén lại ảnh lớn (trang scan, ảnh chụp); chữ, con dấu, chữ ký giữ nguyên độ nét.",
                           objectName="lbl", wordWrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Nén")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self) -> dict:
        return {"target": int(self.sp_mb.value() * 1048576) if self.rb_target.isChecked() else None,
                "level": None if self.rb_target.isChecked() else self.sl.value(), "gray": self.chk_gray.isChecked()}


# ------------------------------------------------------------------ dấu chữ
class StampTextDialog(QDialog):
    def __init__(self, parent, has_selection: bool = False):
        super().__init__(parent)
        from .tools import STAMP_TEXTS
        self.setWindowTitle("Dấu chữ")
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.cb_text = QComboBox(editable=True)
        self.cb_text.addItems(STAMP_TEXTS)
        f.addRow("Nội dung:", self.cb_text)
        self.cb_style = QComboBox()
        self.cb_style.addItem("Khung như con dấu", "box")
        self.cb_style.addItem("Chữ lớn chéo trang, mờ (watermark)", "watermark")
        f.addRow("Kiểu:", self.cb_style)
        self.cb_pos = QComboBox()
        for t, k in (("Góc trên phải", "top-right"), ("Góc trên trái", "top-left"), ("Góc dưới phải", "bottom-right"),
                     ("Góc dưới trái", "bottom-left"), ("Giữa trang", "center")):
            self.cb_pos.addItem(t, k)
        f.addRow("Vị trí:", self.cb_pos)
        self.cb_color = QComboBox()
        for t, c in (("Đỏ", "#d32f2f"), ("Xanh", "#0d47a1"), ("Đen", "#1b1b1b"), ("Xám", "#757575")):
            self.cb_color.addItem(t, c)
        f.addRow("Màu:", self.cb_color)
        self.sl_op = QSlider(Qt.Horizontal, minimum=10, maximum=60, value=25)
        f.addRow("Độ đậm (watermark):", self.sl_op)
        self.cb_scope = QComboBox()
        self.cb_scope.addItem("Tất cả các trang", "all")
        self.cb_scope.addItem("Trang hiện tại", "current")
        if has_selection:
            self.cb_scope.addItem("Các trang đang chọn", "selected")
        f.addRow("Đóng lên:", self.cb_scope)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(lambda: self.cb_text.currentText().strip() and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.cb_style.currentIndexChanged.connect(lambda: (self.cb_pos.setEnabled(self.cb_style.currentData() == "box"),
                                                           self.sl_op.setEnabled(self.cb_style.currentData() != "box")))
        self.sl_op.setEnabled(False)

    def values(self) -> dict:
        return {"text": self.cb_text.currentText().strip(), "style": self.cb_style.currentData(),
                "position": self.cb_pos.currentData(), "color": self.cb_color.currentData(),
                "opacity": self.sl_op.value() / 100, "scope": self.cb_scope.currentData()}


# ------------------------------------------------------------------ so sánh
class CompareDialog(QDialog):
    def __init__(self, parent, diffs, summary: str, on_goto=None, on_report=None):
        super().__init__(parent)
        self.setWindowTitle("So sánh hai bản")
        self.resize(640, 480)
        self.diffs = diffs
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{summary}</b>", wordWrap=True))
        self.list = QListWidget()
        for d in diffs:
            desc = f"Trang {d.page + 1}: {len(d.boxes)} vùng khác"
            if d.removed or d.added:
                desc += f" · bỏ {len(d.removed)}, thêm {len(d.added)} đoạn chữ"
            self.list.addItem(desc)
        v.addWidget(self.list)
        self.view = QTextBrowser()
        v.addWidget(self.view, 1)
        self.list.currentRowChanged.connect(self._show)
        if on_goto:
            self.list.currentRowChanged.connect(lambda r: r >= 0 and on_goto(diffs[r].page))
        row = QHBoxLayout()
        row.addStretch()
        if on_report:
            b = QPushButton("Mở bản đánh dấu chỗ khác")
            b.clicked.connect(lambda: (on_report(), self.accept()))
            row.addWidget(b)
        b = QPushButton("Đóng")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        v.addLayout(row)
        if diffs:
            self.list.setCurrentRow(0)

    def _show(self, r):
        if r < 0:
            return
        d = self.diffs[r]
        import html
        from .theme import ui_is_dark
        red, green = ("#ff8a80", "#9be29b") if ui_is_dark() else ("#b00000", "#006400")
        parts = [f"<p style='color:{red}'>− {html.escape(t)}</p>" for t in d.removed] + \
                [f"<p style='color:{green}'>+ {html.escape(t)}</p>" for t in d.added]
        self.view.setHtml("".join(parts) or "<p>Khác về hình (dấu, chữ ký, ảnh, bố cục) – không khác chữ.</p>")


# ------------------------------------------------------------------ ký hàng loạt
class BatchSignDialog(QDialog):
    def __init__(self, parent, files=(), settings=None):
        super().__init__(parent)
        self.setWindowTitle("Ký hàng loạt")
        self.resize(620, 460)
        self.settings = settings
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Các file cần ký (cùng một chứng thư, chỉ nhập PIN một lần):"))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        for t, fn in (("Thêm file…", self.add_files), ("Thêm cả thư mục…", self.add_folder), ("Bỏ khỏi danh sách", self.remove)):
            b = QPushButton(t)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        f = QFormLayout()
        self.cb_pos = QComboBox()
        self.cb_pos.addItem("Tự tìm chỗ ký trên trang cuối mỗi file (dưới “GIÁM ĐỐC”, “(Ký, ghi rõ…)”)", "auto")
        self.cb_pos.addItem("Ô chữ ký đã chuẩn bị sẵn trong file (luồng ký), nếu có", "field")
        self.cb_pos.addItem("Ký ẩn (không hiện hình trên trang)", "hidden")
        f.addRow("Vị trí ký:", self.cb_pos)
        row = QHBoxLayout()
        self.rb_same = QRadioButton("Cùng thư mục, thêm đuôi _da_ky", checked=True)
        self.rb_dir = QRadioButton("Thư mục khác:")
        self.ed_dir = QLineEdit()
        b = QPushButton("…")
        b.clicked.connect(self._pick_dir)
        row.addWidget(self.rb_same)
        row.addWidget(self.rb_dir)
        row.addWidget(self.ed_dir, 1)
        row.addWidget(b)
        f.addRow("Lưu vào:", row)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tiếp tục – chọn chứng thư")
        bb.accepted.connect(lambda: self.files() and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.add_paths(files)

    def add_paths(self, paths):
        have = set(self.files())
        for p in paths:
            if p.lower().endswith(".pdf") and p not in have:
                self.list.addItem(QListWidgetItem(p))
                have.add(p)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn file PDF cần ký", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if d:
            self.add_paths(sorted(os.path.join(d, f) for f in os.listdir(d)
                                  if f.lower().endswith(".pdf") and not f.lower().endswith("_da_ky.pdf")))

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Lưu file đã ký vào")
        if d:
            self.ed_dir.setText(d)
            self.rb_dir.setChecked(True)

    def files(self) -> list[str]:
        return [self.list.item(k).text() for k in range(self.list.count())]

    def output_for(self, src: str) -> str:
        from .signing import default_output
        if self.rb_dir.isChecked() and self.ed_dir.text():
            os.makedirs(self.ed_dir.text(), exist_ok=True)
            return default_output(os.path.join(self.ed_dir.text(), os.path.basename(src)))
        return default_output(src)

    def position(self) -> str:
        return self.cb_pos.currentData()


# ------------------------------------------------------------------ luồng ký
class FlowDialog(QDialog):
    """Chuẩn bị ô ký cho từng người theo thứ tự; mỗi người sau đó mở file và ký đúng ô của mình."""

    def __init__(self, parent, existing=()):
        super().__init__(parent)
        self.setWindowTitle("Luồng ký – chuẩn bị ô ký cho nhiều người")
        self.resize(480, 360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Tên từng người/vai trò ký (theo thứ tự). Bấm OK rồi lần lượt đặt ô ký của từng người "
                           "lên trang.", wordWrap=True))
        self.list = QListWidget()
        for name in ("Người lập", "Kế toán trưởng", "Giám đốc"):
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("Thêm người")
        b.clicked.connect(self.add)
        row.addWidget(b)
        b = QPushButton("Bỏ")
        b.clicked.connect(lambda: self.list.takeItem(self.list.currentRow()))
        row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        if existing:
            v.addWidget(QLabel("Ô ký đã có trong file: " + ", ".join(existing), objectName="lbl", wordWrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(lambda: self.names() and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def add(self):
        it = QListWidgetItem(f"Người ký {self.list.count() + 1}")
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.list.addItem(it)
        self.list.editItem(it)

    def names(self) -> list[str]:
        out = []
        for k in range(self.list.count()):
            n = self.list.item(k).text().strip()
            if n and n not in out:
                out.append(n)
        return out


# ------------------------------------------------------------------ tạo hàng loạt từ Excel
class BatchExcelDialog(QDialog):
    def __init__(self, parent, fields: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Tạo hàng loạt từ Excel")
        self.resize(600, 420)
        self.fields = fields
        self.head, self.rows = [], []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Mẫu là file đang mở. Trong mẫu (soạn bằng Word rồi in ra PDF), chỗ cần điền viết dạng "
                           "<b>{{Tên cột}}</b>, ví dụ {{Họ tên}}, {{Số tiền}}. Mỗi dòng Excel tạo ra một file PDF.",
                           wordWrap=True))
        v.addWidget(QLabel("Chỗ cần điền tìm thấy trong mẫu: " + (", ".join(fields) if fields else "<i>chưa có</i>"),
                           wordWrap=True))
        row = QHBoxLayout()
        self.ed_xl = QLineEdit(placeholderText="file Excel (.xlsx) hoặc .csv")
        b = QPushButton("Chọn…")
        b.clicked.connect(self.pick)
        row.addWidget(self.ed_xl, 1)
        row.addWidget(b)
        v.addLayout(row)
        self.info = QTextBrowser()
        v.addWidget(self.info, 1)
        f = QFormLayout()
        self.cb_name = QComboBox()
        f.addRow("Đặt tên file theo cột:", self.cb_name)
        row = QHBoxLayout()
        self.ed_out = QLineEdit()
        b = QPushButton("…")
        b.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "Lưu các file vào")) and self.ed_out.setText(d))
        row.addWidget(self.ed_out, 1)
        row.addWidget(b)
        f.addRow("Lưu vào thư mục:", row)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tạo file")
        bb.accepted.connect(lambda: self.rows and self.ed_out.text() and self.accept())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def pick(self, path: str | None = None):
        from .tools import read_table
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file Excel", "", "Excel/CSV (*.xlsx *.csv)")
            if not path:
                return
        try:
            self.head, self.rows = read_table(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không đọc được file:\n{e}")
            return
        self.ed_xl.setText(path)
        if not self.ed_out.text():
            self.ed_out.setText(os.path.join(os.path.dirname(path), "tao_hang_loat"))
        self.cb_name.clear()
        self.cb_name.addItem("(đánh số 001, 002…)", None)
        for h in self.head:
            self.cb_name.addItem(h, h)
        ok = [f for f in self.fields if f in self.head]
        miss = [f for f in self.fields if f not in self.head]
        from .theme import ui_is_dark
        red, green = ("#ff8a80", "#9be29b") if ui_is_dark() else ("#b00000", "#006400")
        self.info.setHtml(f"<p>{len(self.rows)} dòng dữ liệu · cột: {', '.join(self.head)}</p>"
                          f"<p style='color:{green}'>Khớp: {', '.join(ok) or '—'}</p>"
                          + (f"<p style='color:{red}'>Mẫu có nhưng Excel không có cột: {', '.join(miss)}</p>" if miss else ""))

    def values(self) -> dict:
        return {"head": self.head, "rows": self.rows, "out": self.ed_out.text(), "name_col": self.cb_name.currentData()}


# ------------------------------------------------------------------ lịch sử phiên bản
class HistoryDialog(QDialog):
    def __init__(self, parent, path: str):
        super().__init__(parent)
        from .tools import versions
        self.setWindowTitle(f"Lịch sử phiên bản – {os.path.basename(path)}")
        self.resize(480, 380)
        self.vers = versions(path)
        self.choice = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Mỗi lần lưu đè, bản trước được cất lại (20 bản gần nhất).", objectName="lbl"))
        self.list = QListWidget()
        for it in self.vers:
            self.list.addItem(f"{it['label']}   ·   {_mb(it['size'])}")
        if not self.vers:
            self.list.addItem("(chưa có bản cũ nào)")
            self.list.setEnabled(False)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_del = QPushButton("Xóa bản này")
        self.btn_del.setEnabled(bool(self.vers))
        self.btn_del.clicked.connect(self._delete_one)
        row.addWidget(self.btn_del)
        self.btn_del_all = QPushButton("Xóa toàn bộ lịch sử file này")
        self.btn_del_all.setEnabled(bool(self.vers))
        self.btn_del_all.clicked.connect(self._delete_all)
        row.addWidget(self.btn_del_all)
        row.addStretch()
        self.path = path
        for t, act in (("Mở xem bản này", "open"), ("Khôi phục bản này", "restore")):
            b = QPushButton(t)
            b.setEnabled(bool(self.vers))
            b.clicked.connect(lambda _=False, a=act: self._pick(a))
            row.addWidget(b)
        b = QPushButton("Đóng")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        v.addLayout(row)
        if self.vers:
            self.list.setCurrentRow(0)

    def _pick(self, act):
        r = self.list.currentRow()
        if 0 <= r < len(self.vers):
            self.choice = (act, self.vers[r])
            self.accept()

    def _reload(self):
        from .tools import versions
        self.vers = versions(self.path)
        self.list.clear()
        for it in self.vers:
            self.list.addItem(f"{it['label']}   ·   {_mb(it['size'])}")
        if not self.vers:
            self.list.addItem("(chưa có bản cũ nào)")
            self.list.setEnabled(False)
        else:
            self.list.setCurrentRow(0)
        for b in self.findChildren(QPushButton):
            if b.text() != "Đóng":
                b.setEnabled(bool(self.vers))

    def _delete_one(self, confirm: bool = True):
        from .tools import delete_version
        r = self.list.currentRow()
        if not (0 <= r < len(self.vers)):
            return
        if confirm and QMessageBox.question(self, APP_NAME, f"Xóa hẳn bản lưu lúc {self.vers[r]['label']}?") \
                != QMessageBox.Yes:
            return
        delete_version(self.vers[r])
        self._reload()

    def _delete_all(self, confirm: bool = True):
        from .tools import clear_versions
        if confirm and QMessageBox.question(
                self, APP_NAME, f"Xóa hẳn {len(self.vers)} bản cũ của file này? Không khôi phục lại được.") \
                != QMessageBox.Yes:
            return
        clear_versions(self.path)
        self._reload()


class ClearHistoryDialog(QDialog):
    """Lịch sử & dữ liệu lưu trên máy: tích chọn từng mục / chọn tất cả để xóa, nút Xóa tất cả,
    đặt thời hạn tự xóa cho từng mục (Không lưu, 7 ngày, 30 ngày, 6 tháng, 1 năm, Vĩnh viễn)."""

    def __init__(self, parent, settings=None, library_path: str | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout
        from . import retention as R
        self.R = R
        self.setWindowTitle("Lịch sử & dữ liệu lưu trên máy")
        self.setMinimumWidth(820)
        self.settings = settings
        self.action = "selected"
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Tích chọn thông tin cần xóa, hoặc bấm “Xóa tất cả”. Cột bên phải đặt thời hạn phần mềm "
                           "tự xóa (chạy khi mở phần mềm và định kỳ khi đang chạy). File gốc của bạn không bị ảnh hưởng.",
                           objectName="lbl", wordWrap=True))
        self.chk_all = QCheckBox("Chọn tất cả")
        self.chk_all.setStyleSheet("font-weight:600")
        v.addWidget(self.chk_all)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(6)
        for col, t in enumerate(("Mục", "Đang lưu", "Tự xóa sau")):
            h = QLabel(t, objectName="cap")
            g.addWidget(h, 0, col)
        summ = R.summary(settings, library_path)
        self.checks, self.combos, self.status = {}, {}, {}
        for row, (key, label, timed, default, pre) in enumerate(R.PARTS, 1):
            n, desc = summ[key]
            cb = QCheckBox(label)
            cb.setChecked(bool(n) and pre)
            cb.setEnabled(bool(n))
            if key in R.DANGEROUS:
                cb.setToolTip("Xóa mục này sẽ mất công chuẩn bị lại – phần mềm sẽ hỏi lại trước khi xóa.")
            self.checks[key] = cb
            g.addWidget(cb, row, 0)
            st = QLabel(desc, objectName="lbl")
            self.status[key] = st
            g.addWidget(st, row, 1)
            if timed:
                combo = QComboBox()
                for days, lab in R.RETENTION_CHOICES:
                    combo.addItem(lab, days)
                cur = R.retention_days(settings, key)
                combo.setCurrentIndex(max(0, [d for d, _ in R.RETENTION_CHOICES].index(cur)
                                          if cur in [d for d, _ in R.RETENTION_CHOICES] else 5))
                self.combos[key] = combo
                g.addWidget(combo, row, 2)
            else:
                g.addWidget(QLabel("chỉ xóa khi bạn chọn", objectName="lbl"), row, 2)
        g.setColumnStretch(0, 1)
        v.addLayout(g)
        v.addWidget(QLabel("Không xóa được bằng phần mềm: các bản trước nằm ngay bên trong file PDF đã ký số (xóa sẽ "
                           "làm chữ ký mất hiệu lực) và file sao lưu .zip bạn tự lưu ở nơi khác.", objectName="lbl",
                           wordWrap=True))
        row = QHBoxLayout()
        self.btn_all = QPushButton("Xóa tất cả…")
        self.btn_all.setAutoDefault(False)
        self.btn_all.setStyleSheet("color:#B8322A;font-weight:600")
        self.btn_all.clicked.connect(self._delete_all)
        row.addWidget(self.btn_all)
        row.addStretch()
        self.btn_save = QPushButton("Lưu thời hạn")
        self.btn_save.setAutoDefault(False)
        self.btn_save.clicked.connect(self._save_only)
        row.addWidget(self.btn_save)
        self.btn_ok = QPushButton("Xóa mục đã chọn")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._delete_selected)
        row.addWidget(self.btn_ok)
        b = QPushButton("Đóng")
        b.setAutoDefault(False)
        b.clicked.connect(self.reject)
        row.addWidget(b)
        v.addLayout(row)
        self.chk_all.toggled.connect(self._toggle_all)
        for cb in self.checks.values():
            cb.toggled.connect(self._sync)
        self._sync()

    def _toggle_all(self, on):
        for cb in self.checks.values():
            if cb.isEnabled():
                cb.blockSignals(True)
                cb.setChecked(on)
                cb.blockSignals(False)
        self._sync()

    def _sync(self, *_):
        en = [cb for cb in self.checks.values() if cb.isEnabled()]
        self.btn_ok.setEnabled(any(cb.isChecked() for cb in en))
        self.chk_all.blockSignals(True)
        self.chk_all.setChecked(bool(en) and all(cb.isChecked() for cb in en))
        self.chk_all.blockSignals(False)

    def retention(self) -> dict:
        return {k: c.currentData() for k, c in self.combos.items()}

    def save_retention(self):
        if self.settings is None:
            return
        for k, days in self.retention().items():
            self.R.set_retention(self.settings, k, days)

    def _save_only(self):
        self.action = "retention"
        self.save_retention()
        self.accept()

    def _delete_selected(self):
        self.action = "selected"
        self.save_retention()
        self.accept()

    def _delete_all(self, confirm: bool = True):
        if confirm and QMessageBox.warning(
                self, APP_NAME, "Xóa TOÀN BỘ lịch sử và dữ liệu phần mềm lưu trên máy này?\n\n"
                "Gồm cả thư viện dấu, chữ ký, chữ viết tay và mọi mẫu, cấu hình đã lưu. Không khôi phục lại được.\n"
                "(File gốc của bạn không bị ảnh hưởng.)", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) \
                != QMessageBox.Yes:
            return
        self.action = "all"
        self.save_retention()
        self.accept()

    def parts(self) -> list[str]:
        if self.action == "all":
            return [k for k, *_ in self.R.PARTS]
        if self.action == "retention":
            return []
        return [k for k, cb in self.checks.items() if cb.isChecked() and cb.isEnabled()]


# ------------------------------------------------------------------ thư mục tự xử lý
class AutoFolderDialog(QDialog):
    def __init__(self, parent, cfg, settings=None):
        super().__init__(parent)
        from .tools import STAMP_TEXTS
        self.setWindowTitle("Thư mục tự xử lý")
        self.setMinimumWidth(560)
        self.settings = settings
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Thả (hoặc lưu, in) file PDF vào thư mục này: phần mềm tự xử lý và đặt bản kết quả vào thư "
                           "mục con “da_xu_ly”. File gốc giữ nguyên. Chỉ chạy khi phần mềm đang mở.", wordWrap=True))
        f = QFormLayout()
        row = QHBoxLayout()
        self.ed_dir = QLineEdit(cfg.folder)
        b = QPushButton("…")
        b.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "Chọn thư mục")) and self.ed_dir.setText(d))
        row.addWidget(self.ed_dir, 1)
        row.addWidget(b)
        f.addRow("Thư mục:", row)
        self.chk_on = QCheckBox("Bật tự xử lý", checked=cfg.enabled)
        f.addRow("", self.chk_on)
        self.cb_stamp = QComboBox(editable=True)
        self.cb_stamp.addItem("")
        self.cb_stamp.addItems(STAMP_TEXTS)
        self.cb_stamp.setCurrentText(cfg.stamp_text)
        f.addRow("Đóng dấu chữ:", self.cb_stamp)
        self.sp_mb = QDoubleSpinBox(minimum=0, maximum=500, value=cfg.compress_mb, suffix=" MB", decimals=1,
                                    specialValueText="không nén")
        f.addRow("Nén tới dưới:", self.sp_mb)
        self.cb_prot = QComboBox()
        self.cb_prot.addItem("Không bảo vệ", None)
        for name, o in PRESETS:
            self.cb_prot.addItem(name, o.to_dict())
        if cfg.protect:
            for k in range(1, self.cb_prot.count()):
                if self.cb_prot.itemData(k) == cfg.protect:
                    self.cb_prot.setCurrentIndex(k)
        f.addRow("Bảo vệ:", self.cb_prot)
        self.ed_owner = QLineEdit(cfg.owner_password, echoMode=QLineEdit.Password,
                                  placeholderText="mật khẩu chủ sở hữu (tùy chọn)")
        f.addRow("", self.ed_owner)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _accept(self):
        if self.chk_on.isChecked() and not os.path.isdir(self.ed_dir.text()):
            QMessageBox.warning(self, APP_NAME, "Hãy chọn một thư mục có thật.")
            return
        self.accept()

    def config(self):
        from .autofolder import AutoConfig
        return AutoConfig(folder=self.ed_dir.text(), enabled=self.chk_on.isChecked(),
                          stamp_text=self.cb_stamp.currentText().strip(), compress_mb=self.sp_mb.value(),
                          protect=self.cb_prot.currentData() or {}, owner_password=self.ed_owner.text())
