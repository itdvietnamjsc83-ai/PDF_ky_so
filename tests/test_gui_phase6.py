"""Giao diện giai đoạn 6: lưu có bảo vệ + mẫu, file bảo vệ chỉ xem, gỡ bảo vệ, nén, so sánh, dấu chữ,
ký hàng loạt, luồng ký, tạo hàng loạt từ Excel, lịch sử phiên bản, sao lưu, thư mục tự xử lý."""
import json
import os

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from app import protect, signing, ui_sign, ui_tools
from app.document import PdfDocument
from app.library import STAMP, Library
from app.mainwindow import MainWindow

from .test_gui import _Settings, pump
from .test_gui_phase4 import _patch_dialog
from .test_phase3 import remove_background, stamp_jpeg
from .test_phase4 import _contract, _soft_signer
from .test_phase6 import _scan_pdf, _template, _xlsx
from .pki import CA


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ca():
    return CA()


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    p = str(tmp_path / "lib.pdf")
    Library(p).add("Dấu công ty", remove_background(stamp_jpeg()), STAMP, 38)
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=p)
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def _open(win, qapp, path_or_bytes, tmp_path, name="hd.pdf"):
    if isinstance(path_or_bytes, bytes):
        p = tmp_path / name
        p.write_bytes(path_or_bytes)
        path_or_bytes = str(p)
    win.open_files([path_or_bytes])
    pump(qapp)
    return win.current()


def _save_to(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


# ------------------------------------------------------------------ bảo vệ
def test_protect_flow_and_presets(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, _contract(3), tmp_path)

    def fake_exec(self):
        self.rb["low"].setChecked(True)
        self.ed_owner.setText("chu123")
        self.save_preset("Gửi khách hàng")
        self._accept()
        return self.result()
    monkeypatch.setattr(ui_tools.ProtectDialog, "exec", fake_exec)
    out = tmp_path / "hd_bao_ve.pdf"
    _save_to(monkeypatch, out)
    win.run("protect")
    perms = protect.permissions(out.read_bytes())
    assert perms["encrypted"] and perms["print_low"] and not perms["print_high"] and perms["layers"]
    presets = json.loads(win.settings["protect/presets"])
    assert presets[0]["name"] == "Gửi khách hàng" and presets[0]["options"]["owner_password"] == ""
    dlg = ui_tools.ProtectDialog(win, win.settings, 3)          # mở lại: có mẫu người dùng, nhớ lựa chọn
    assert dlg.cb_preset.findText("★ Gửi khách hàng") > 0 and dlg.rb["low"].isChecked()
    assert "KB/trang" in dlg.lbl_size.text()


def test_protected_file_is_read_only(win, qapp, tmp_path, monkeypatch):
    out, _ = protect.protect_pdf(_contract(2), protect.ProtectOptions(printing="none", owner_password="chu"))
    tab = _open(win, qapp, out, tmp_path, "baove.pdf")
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    for cmd in ("rotate", "delete", "textbox", "stamptext"):
        win.run(cmd)
    assert not tab.doc.modified and len(shown) == 4 and "bảo vệ" in shown[0]
    win.print_doc(tab)
    assert "không cho phép in" in shown[-1]


def test_remove_protection_flow(win, qapp, tmp_path, monkeypatch):
    out, _ = protect.protect_pdf(_contract(1), protect.ProtectOptions(owner_password="chu"))
    _open(win, qapp, out, tmp_path, "bv.pdf")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("chu", True))
    dst = tmp_path / "bv_go_bao_ve.pdf"
    _save_to(monkeypatch, dst)
    win.run("password")
    assert dst.exists() and not PdfDocument(str(dst)).encrypted
    assert win.current().doc.can_modify


def test_sign_protected_file_asks_owner(win, qapp, tmp_path, monkeypatch, ca):
    out, _ = protect.protect_pdf(_contract(1), protect.ProtectOptions(printing="high", owner_password="chu"))
    _, soft = _soft_signer(ca)
    cert = signing.parse_cert(soft.signing_cert.dump(), backend=signing.WINDOWS)
    monkeypatch.setattr(signing, "open_signer", lambda c, pin=None, hwnd=0: (soft, lambda: None))
    _patch_dialog(monkeypatch, [cert], ui_sign.LAYOUT_HIDDEN)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("chu", True))
    _open(win, qapp, out, tmp_path, "bvky.pdf")
    win.run("digisign")
    pump(qapp)
    signed = (tmp_path / "bvky_da_ky.pdf").read_bytes()
    assert signing.verify_pdf(signed, [ca.asn1()])[0].valid and protect.permissions(signed)["encrypted"]


# ------------------------------------------------------------------ nén, so sánh, dấu chữ
def test_compress_flow(win, qapp, tmp_path, monkeypatch):
    _open(win, qapp, _scan_pdf(2), tmp_path, "scan.pdf")
    monkeypatch.setattr(ui_tools.CompressDialog, "exec", lambda self: (self.sp_mb.setValue(0.3), QDialog.Accepted)[1])
    dst = tmp_path / "scan_nen.pdf"
    _save_to(monkeypatch, dst)
    win.run("compress")
    assert dst.exists() and dst.stat().st_size < (tmp_path / "scan.pdf").stat().st_size
    assert "Đã nén" in win.lbl_msg.text()


def test_compare_flow(win, qapp, tmp_path, monkeypatch):
    from app import editing
    old = tmp_path / "cu.pdf"
    old.write_bytes(_contract(2))
    tab = _open(win, qapp, _contract(2), tmp_path, "moi.pdf")
    editing.add_text(tab.doc, 1, 72, 500, "Điều khoản bổ sung mới", size=12)
    got = {}

    def fake_exec(self):
        got["rows"] = self.list.count()
        got["text"] = self.view.toPlainText()
        return QDialog.Rejected
    monkeypatch.setattr(ui_tools.CompareDialog, "exec", fake_exec)
    win.compare_doc(tab, str(old))
    diffs, summary = win.last_compare
    assert got["rows"] == 1 and diffs[0].page == 1 and "bổ sung" in got["text"]


def test_stamp_text_flow(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, _contract(3), tmp_path)
    monkeypatch.setattr(ui_tools.StampTextDialog, "exec",
                        lambda self: (self.cb_text.setCurrentText("MẬT"), QDialog.Accepted)[1])
    win.run("stamptext")
    assert all("MẬT" in tab.doc.text(i) for i in range(3))


# ------------------------------------------------------------------ ký hàng loạt, luồng ký
def test_batch_sign_flow(win, qapp, tmp_path, monkeypatch, ca):
    _, soft = _soft_signer(ca)
    cert = signing.parse_cert(soft.signing_cert.dump(), backend=signing.WINDOWS)
    monkeypatch.setattr(signing, "open_signer", lambda c, pin=None, hwnd=0: (soft, lambda: None))
    _patch_dialog(monkeypatch, [cert])
    files = []
    for k in range(3):
        p = tmp_path / f"hs{k}.pdf"
        p.write_bytes(_contract(2))
        files.append(str(p))
    monkeypatch.setattr(ui_tools.BatchSignDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win.batch_sign(files)
    assert [e for _, e in win.last_batch] == [None, None, None]
    for k in range(3):
        rep = signing.verify_pdf((tmp_path / f"hs{k}_da_ky.pdf").read_bytes(), [ca.asn1()])
        assert rep and rep[0].valid


def test_flow_prepare_then_sign_into_field(win, qapp, tmp_path, monkeypatch, ca):
    tab = _open(win, qapp, _contract(2), tmp_path, "luong.pdf")

    def fake_exec(self):
        self.list.clear()
        from PySide6.QtWidgets import QListWidgetItem
        for n in ("Kế toán", "Giám đốc"):
            self.list.addItem(QListWidgetItem(n))
        return QDialog.Accepted
    monkeypatch.setattr(ui_tools.FlowDialog, "exec", fake_exec)
    win.run("flow")
    for _ in range(2):
        win.current().view.commit_placement()
        pump(qapp)
    data = (tmp_path / "luong.pdf").read_bytes()
    assert [f.name for f in signing.empty_fields(data)] == ["Kế toán", "Giám đốc"]
    _, soft = _soft_signer(ca)
    cert = signing.parse_cert(soft.signing_cert.dump(), backend=signing.WINDOWS)
    monkeypatch.setattr(signing, "open_signer", lambda c, pin=None, hwnd=0: (soft, lambda: None))

    def load(self, refresh=False, sync=False):
        self.set_certs([cert])
        self.cb_field.setCurrentIndex(2)                    # chọn ô "Giám đốc"
    monkeypatch.setattr(ui_sign.SignDialog, "load", load)
    monkeypatch.setattr(ui_sign.SignDialog, "exec", lambda self: QDialog.Accepted)
    win.run("digisign")
    pump(qapp)
    signed = (tmp_path / "luong_da_ky.pdf").read_bytes()
    assert [f.name for f in signing.empty_fields(signed)] == ["Kế toán"]
    assert signing.verify_pdf(signed, [ca.asn1()])[0].field == "Giám đốc"


# ------------------------------------------------------------------ Excel, lịch sử, sao lưu, tự xử lý
def test_batch_excel_flow(win, qapp, tmp_path, monkeypatch):
    _open(win, qapp, _template(), tmp_path, "mau.pdf")
    xl = tmp_path / "ds.xlsx"
    _xlsx(xl, [["Họ tên", "Đơn vị"], ["Lê Văn C", "Kho"], ["Phạm D", "Xưởng"]])

    def fake_exec(self):
        self.pick(str(xl))
        self.cb_name.setCurrentIndex(1)
        return QDialog.Accepted
    monkeypatch.setattr(ui_tools.BatchExcelDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win.run("batchxl")
    out = tmp_path / "tao_hang_loat"
    assert sorted(os.listdir(out)) == ["Lê Văn C.pdf", "Phạm D.pdf"]
    assert "Kính gửi: Phạm D" in PdfDocument(str(out / "Phạm D.pdf")).text(0)


def test_history_on_save_and_restore(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, _contract(2), tmp_path, "ls.pdf")
    tab.doc.rotate_pages([0])
    assert win.save(tab)
    from app.tools import versions
    vers = versions(str(tmp_path / "ls.pdf"))
    assert len(vers) == 1
    monkeypatch.setattr(ui_tools.HistoryDialog, "exec",
                        lambda self: (self._pick("restore"), QDialog.Accepted)[1])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    win.run("history")
    pump(qapp)
    d = PdfDocument(str(tmp_path / "ls.pdf"))
    assert d.page(0).get_rotation() == 0                    # đã về bản trước khi xoay


def test_backup_restore_gui(win, qapp, tmp_path, monkeypatch):
    win._init_library()
    win.settings.setValue("sign/reason", "Phê duyệt hợp đồng")
    z = win.do_backup(str(tmp_path / "bk.zip"))
    win.settings.setValue("sign/reason", "khác")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win.do_restore(z)
    assert win.settings.value("sign/reason") == "Phê duyệt hợp đồng"


def test_autofolder_gui(win, qapp, tmp_path, monkeypatch):
    folder = tmp_path / "hopthu"
    folder.mkdir()

    def fake_exec(self):
        self.ed_dir.setText(str(folder))
        self.chk_on.setChecked(True)
        self.cb_stamp.setCurrentText("BẢN SAO")
        return QDialog.Accepted
    monkeypatch.setattr(ui_tools.AutoFolderDialog, "exec", fake_exec)
    win.run("autofolder")
    assert win.auto_watcher and win._auto_timer.isActive()
    p = folder / "a.pdf"
    p.write_bytes(_contract(1))
    os.utime(p, (p.stat().st_mtime - 5,) * 2)
    win.auto_watcher.scan()
    win.auto_watcher.scan()
    assert (folder / "da_xu_ly" / "a.pdf").exists()


def test_unsupported(win, qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    _open(win, qapp, _contract(1), tmp_path)
    win.run("remote")
    win.run("ocr")
    assert "chưa hỗ trợ" in shown[0] and "cập nhật sau" in shown[1]
    from app.mainwindow import MODES
    assert all(c[0] != "mail" for _, _, gs in MODES for g in gs for c in g if isinstance(c, tuple))  # đã bỏ Gửi email
