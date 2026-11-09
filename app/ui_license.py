"""Màn hình kích hoạt bản quyền và Giới thiệu."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout)

from . import APP_NAME, __version__, branding
from . import license as L


class ActivateDialog(QDialog):
    def __init__(self, parent=None, reason: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Bản quyền – {APP_NAME}")
        self.setMinimumWidth(600)
        self.status = L.status()
        v = QVBoxLayout(self)
        if reason:
            r = QLabel(reason, wordWrap=True)
            r.setStyleSheet("color:#b3261e;font-weight:600")
            v.addWidget(r)
        self.lbl_state = QLabel("", wordWrap=True, objectName="h")
        v.addWidget(self.lbl_state)
        box = QFrame(objectName="card")
        b = QVBoxLayout(box)
        b.addWidget(QLabel("Mã máy của máy này (gửi cho nhà cung cấp để nhận mã kích hoạt):", objectName="lbl"))
        row = QHBoxLayout()
        self.ed_code = QLineEdit(L.machine_code(), readOnly=True)
        self.ed_code.setStyleSheet("font-size:18px;font-weight:600;letter-spacing:2px")
        row.addWidget(self.ed_code, 1)
        bt = QPushButton("Sao chép")
        bt.clicked.connect(lambda: (QApplication.clipboard().setText(self.ed_code.text()), bt.setText("Đã chép ✓")))
        row.addWidget(bt)
        b.addLayout(row)
        v.addWidget(box)
        v.addWidget(QLabel("Mã kích hoạt:", objectName="lbl"))
        self.ed_key = QPlainTextEdit()
        self.ed_key.setPlaceholderText("Dán mã kích hoạt nhận được vào đây")
        self.ed_key.setMaximumHeight(90)
        v.addWidget(self.ed_key)
        row = QHBoxLayout()
        self.btn_file = QPushButton("Mở file bản quyền (.lic)…")
        self.btn_file.clicked.connect(self.open_file)
        row.addWidget(self.btn_file)
        self.btn_packs = QPushButton("Các gói phần mềm…")
        self.btn_packs.setToolTip("So sánh tính năng gói Tiêu chuẩn / Chuyên nghiệp / Doanh nghiệp")
        self.btn_packs.clicked.connect(lambda: show_packages(self))
        row.addWidget(self.btn_packs)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(QLabel("Liên hệ mua bản quyền:<br>" + "<br>".join(branding.contact_lines()) +
                           f"<br><i>{branding.PRICE_NOTE}</i>", wordWrap=True, objectName="lbl",
                           textInteractionFlags=Qt.TextSelectableByMouse))
        self.bb = QDialogButtonBox()
        self.btn_act = self.bb.addButton("Kích hoạt", QDialogButtonBox.AcceptRole)
        self.btn_trial = self.bb.addButton("Dùng thử 15 ngày", QDialogButtonBox.ActionRole)
        self.btn_close = self.bb.addButton("Đóng", QDialogButtonBox.RejectRole)
        self.btn_act.clicked.connect(self.do_activate)
        self.btn_trial.clicked.connect(self.do_trial)
        self.btn_close.clicked.connect(self.reject)
        v.addWidget(self.bb)
        self._refresh()

    def _refresh(self):
        s = self.status = L.status()
        colors = {L.ACTIVE: "#1e7e34", L.TRIAL: "#b26a00"}
        self.lbl_state.setText(s.short)
        self.lbl_state.setStyleSheet(f"color:{colors.get(s.kind, '#b3261e')}")
        self.btn_trial.setVisible(s.kind in (L.NEW, L.TRIAL))
        self.btn_trial.setText("Bắt đầu dùng thử 15 ngày" if s.kind == L.NEW else f"Tiếp tục dùng thử ({s.days_left} ngày)")

    def open_file(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file bản quyền", "", "Bản quyền (*.lic *.txt)")
            if not path:
                return
        try:
            self.ed_key.setPlainText(L.read_license_file(path))
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.do_activate()

    def do_activate(self):
        try:
            lic = L.activate(self.ed_key.toPlainText())
        except L.LicenseError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self._refresh()
        QMessageBox.information(self, APP_NAME, f"Kích hoạt thành công!\n{lic.describe()}")
        self.accept()

    def do_trial(self):
        L.start_trial()
        self._refresh()
        self.accept()


THIRD_PARTY = [
    ("Qt 6 / PySide6", "LGPL-3.0", "Giao diện. Dùng dạng thư viện liên kết động (các file DLL Qt đi kèm có thể thay thế)."),
    ("PDFium / pypdfium2", "Apache-2.0 / BSD-3", "Đọc, hiển thị, chỉnh sửa PDF."),
    ("qpdf / pikepdf", "Apache-2.0 / MPL-2.0", "Tối ưu, mã hóa PDF."),
    ("pyHanko", "MIT", "Ký số PAdES."),
    ("python-pkcs11", "MIT", "Kết nối USB token chuẩn PKCS#11."),
    ("cryptography", "Apache-2.0 / BSD", "Mật mã."),
    ("Pillow", "MIT-CMU", "Xử lý ảnh."),
    ("fontTools", "MIT", "Rút gọn phông chữ."),
    ("Patrick Hand, Pangolin, Mali, Charm, Dancing Script", "SIL OFL 1.1", "Phông chữ viết tay."),
]


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Giới thiệu – {APP_NAME}")
        self.resize(560, 520)
        v = QVBoxLayout(self)
        t = QTextBrowser()
        t.setOpenExternalLinks(True)
        st = L.status()
        rows = "".join(f"<tr><td><b>{n}</b></td><td>{lic}</td><td>{d}</td></tr>" for n, lic, d in THIRD_PARTY)
        t.setHtml(f"<h2>{APP_NAME}</h2><p>Phiên bản {__version__}</p>"
                  f"<p><b>Bản quyền:</b> {st.short}<br><b>Mã máy:</b> {L.machine_code()}</p>"
                  f"<h3>Nhà phát triển</h3><p>{'<br>'.join(branding.contact_lines())}</p><p>{branding.COPYRIGHT}</p>"
                  f"<h3>Thành phần mã nguồn mở</h3><table cellspacing=6>{rows}</table>")
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Bản quyền…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: ActivateDialog(self).exec())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class DeveloperDialog(QDialog):
    """Bảng thông tin nhà phát triển – hiện mỗi lần mở phần mềm (và từ nút ⓘ trên thanh điều hướng).
    Nội dung lấy từ app/branding.py."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .icons import seal
        self.setWindowTitle(f"{APP_NAME} – Nhà phát triển")
        self.setMinimumWidth(500)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 16)
        v.setSpacing(0)
        head = QFrame(objectName="drop")
        head.setStyleSheet("QFrame#drop { border-radius: 0; }")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(seal(128).pixmap(64, 64))
        hl.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        t = QLabel(branding.PRODUCT)
        t.setStyleSheet("font-size: 22px; font-weight: 800;")
        tv.addWidget(t)
        tv.addWidget(QLabel(f"Phiên bản {__version__} · Ký số, đóng dấu, chỉnh sửa PDF", objectName="dropsub"))
        hl.addLayout(tv, 1)
        v.addWidget(head)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 8)
        body.setSpacing(8)
        body.addWidget(QLabel("NHÀ PHÁT TRIỂN", objectName="cap"))
        self.lbl_dev = QLabel(branding.DEVELOPER, objectName="h")
        self.lbl_dev.setStyleSheet("font-size: 16px;")
        self.lbl_dev.setWordWrap(True)
        body.addWidget(self.lbl_dev)
        rows = []
        for k, val in (("Điện thoại / Zalo", branding.PHONE), ("Email", branding.EMAIL),
                       ("Website", branding.WEBSITE), ("Địa chỉ", branding.ADDRESS)):
            if val:
                rows.append(f"<tr><td style='padding:2px 14px 2px 0'><span style='opacity:.7'>{k}</span></td>"
                            f"<td style='padding:2px 0'><b>{val}</b></td></tr>")
        self.lbl_contact = QLabel(f"<table>{''.join(rows)}</table>", textInteractionFlags=Qt.TextSelectableByMouse)
        body.addWidget(self.lbl_contact)
        st = L.status()
        self.lbl_lic = QLabel(f"Bản quyền: {st.short}", objectName="lbl", wordWrap=True)
        body.addSpacing(4)
        body.addWidget(self.lbl_lic)
        body.addWidget(QLabel(branding.COPYRIGHT, objectName="lbl"))
        v.addLayout(body)

        row = QHBoxLayout()
        row.setContentsMargins(24, 8, 24, 0)
        b = QPushButton("Bản quyền…")
        b.setAutoDefault(False)
        b.clicked.connect(lambda: ActivateDialog(self).exec())
        row.addWidget(b)
        row.addStretch()
        self.btn_ok = QPushButton("Bắt đầu sử dụng")
        self.btn_ok.setDefault(True)
        self.btn_ok.setAutoDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_ok)
        v.addLayout(row)


def show_packages(parent=None):
    """Bảng so sánh 3 gói (đánh dấu gói đang dùng)."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout
    from . import editions
    try:
        level = editions.current()
    except Exception:
        level = None
    dlg = QDialog(parent)
    dlg.setWindowTitle("Các gói phần mềm PDF Ký Số")
    dlg.resize(760, 620)
    v = QVBoxLayout(dlg)
    tb = QTextBrowser()
    tb.setHtml("<p>Dùng thử 15 ngày: đủ tính năng gói <b>Doanh nghiệp</b>. Nâng cấp gói chỉ cần nhập mã kích hoạt "
               "mới, không phải cài lại.</p>" + editions.compare_html(level))
    v.addWidget(tb)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    dlg.exec()
    return dlg
