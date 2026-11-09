"""Giai đoạn 6b – bản quyền offline theo mã máy: mã máy, mã kích hoạt (Ed25519 từ cụm mật khẩu cố định),
dùng thử 15 ngày, chống sửa/đổi đồng hồ, bộ tạo key, màn hình kích hoạt, chặn chức năng khi hết hạn."""
import datetime as dt
import json
import os
import sys
import time

import pytest

from app import license as L

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))
try:
    import keygen  # noqa: E402
    HAS_KEYGEN = True
except ImportError:                       # kho mã không kèm bộ tạo key (vd. GitHub) -> chỉ bỏ qua kiểm thử của keygen
    from . import _keygen_demo as keygen  # noqa: E402
    HAS_KEYGEN = False
needs_keygen = pytest.mark.skipif(not HAS_KEYGEN, reason="không có tools/keygen.py (chỉ ở máy nhà phát triển)")

DEMO_PASS = "khoa mau pdf ky so - doi truoc khi ban"


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Trạng thái bản quyền riêng cho từng kiểm thử."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "programdata"))
    monkeypatch.setenv("PDFKYSO_REG_FILE", str(tmp_path / "registry.json"))   # thay Registry thật (Windows)
    return tmp_path


@pytest.fixture(scope="module")
def priv():
    return keygen.derive_private(DEMO_PASS)


# ------------------------------------------------------------------ mã máy, khóa
def test_machine_code_format_and_stable():
    a, b = L.machine_code(), L.machine_code()
    assert a == b and len(a) == 19 and a.count("-") == 3
    assert L.normalize_code(a.lower().replace("-", " ")) == a
    with pytest.raises(L.LicenseError):
        L.normalize_code("ABC")


def test_keypair_is_fixed_by_passphrase(priv):
    assert keygen.public_hex(priv) == keygen.public_hex(keygen.derive_private(DEMO_PASS))
    assert keygen.public_hex(priv) == keygen.current_public()        # khóa trong phần mềm = khóa mẫu
    assert keygen.public_hex(keygen.derive_private("cụm khác hẳn")) != keygen.public_hex(priv)


def test_key_verify(priv):
    code = L.machine_code()
    key = L.sign_key(priv, code, dt.date(2027, 12, 31), edition=2, serial=7)
    lic = L.verify_key(key)
    assert lic.expiry == dt.date(2027, 12, 31) and lic.edition == 2 and lic.serial == 7
    assert "31/12/2027" in lic.describe() and lic.edition_name == "Chuyên nghiệp"
    forever = L.verify_key(L.sign_key(priv, code, None))
    assert forever.expiry is None and forever.days_left() is None and "vĩnh viễn" in forever.describe()
    assert len(key) < 160                                             # đủ gọn để gửi qua Zalo/email


def test_key_other_machine_rejected(priv):
    key = L.sign_key(priv, "AAAA-BBBB-CCCC-DDDD", None)
    with pytest.raises(L.LicenseError, match="máy khác"):
        L.verify_key(key)
    assert L.verify_key(key, "aaaa bbbb cccc dddd").machine == "AAAA-BBBB-CCCC-DDDD"


def test_forged_and_tampered_keys_rejected(priv):
    code = L.machine_code()
    fake = keygen.derive_private("kẻ gian tự tạo khóa")
    with pytest.raises(L.LicenseError, match="không hợp lệ"):
        L.verify_key(L.sign_key(fake, code, None))
    key = L.sign_key(priv, code, dt.date(2026, 1, 1))
    raw = bytearray(L.parse_key(key))
    raw[9] ^= 0x01                                                   # sửa hạn dùng
    with pytest.raises(L.LicenseError):
        L.verify_key(L.format_key(bytes(raw)))
    with pytest.raises(L.LicenseError):
        L.verify_key("ABC-DEF")


# ------------------------------------------------------------------ dùng thử, kích hoạt
def test_trial_lifecycle(iso):
    t0 = time.time()
    assert L.status(t0).kind == L.NEW
    st = L.start_trial(t0)
    assert st.kind == L.TRIAL and st.days_left == 15 and st.usable
    assert L.status(t0 + 10 * 86400).days_left == 5
    over = L.status(t0 + 16 * 86400)
    assert over.kind == L.TRIAL_OVER and not over.usable
    L.start_trial(t0 + 20 * 86400)                                   # không bắt đầu lại được
    assert L.status(t0 + 20 * 86400).kind == L.TRIAL_OVER


def test_clock_rollback_detected(iso):
    t0 = time.time()
    L.start_trial(t0)
    L.status(t0 + 5 * 86400)                                         # ghi nhận lần dùng gần nhất
    assert L.status(t0 + 1 * 86400).kind == L.CLOCK


def test_trial_survives_deleting_data_file(iso):
    t0 = time.time() - 16 * 86400
    L.start_trial(t0)
    os.remove(L._data_file())                                        # xóa file trong AppData
    assert L.status().kind == L.TRIAL_OVER                           # vẫn còn bản ở ProgramData


def test_tampered_state_file(iso):
    L.start_trial(time.time() - 20 * 86400)
    for p in (L._data_file(), L._programdata_file(), os.environ["PDFKYSO_REG_FILE"]):   # sửa cả 3 nơi lưu
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["trial_start"] = time.time()                               # sửa tay ngày bắt đầu
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
    assert L.status().kind == L.INVALID


def test_activate_and_expire(iso, priv):
    code = L.machine_code()
    L.start_trial()
    lic = L.activate(L.sign_key(priv, code, dt.date.today() + dt.timedelta(days=30)))
    st = L.status()
    assert st.kind == L.ACTIVE and st.days_left == 30 and "Đã kích hoạt" in st.short
    assert L.status(time.time() + 40 * 86400).kind == L.EXPIRED
    with pytest.raises(L.LicenseError, match="hết hạn"):
        L.activate(L.sign_key(priv, code, dt.date.today() - dt.timedelta(days=1)))
    assert lic.serial == 1


@needs_keygen
def test_keygen_issue_writes_files(iso, tmp_path, monkeypatch):
    monkeypatch.setattr(keygen, "LOG", str(tmp_path / "log.csv"))
    key, path = keygen.issue(L.machine_code(), None, 3, "Công ty Thử", DEMO_PASS, str(tmp_path / "lic"))
    assert L.read_license_file(path) == key and "Công ty Thử" in open(path, encoding="utf-8").read()
    assert L.verify_key(key).edition == 3
    key2, _ = keygen.issue(L.machine_code(), dt.date(2030, 1, 1), 1, "B", DEMO_PASS, str(tmp_path / "lic"))
    assert L.verify_key(key2).serial == 2                           # số thứ tự tăng theo nhật ký
    with pytest.raises(SystemExit, match="SAI"):
        keygen.issue(L.machine_code(), None, 1, "C", "sai cụm mật khẩu", str(tmp_path / "lic"))


@needs_keygen
def test_keygen_init_refuses_overwrite_real_key(tmp_path, monkeypatch):
    f = tmp_path / "license_key.py"
    monkeypatch.setattr(keygen, "KEY_FILE", str(f))
    keygen.write_public("ab" * 32, demo=False)
    monkeypatch.setattr(keygen, "current_public", lambda: "ab" * 32)
    import types
    fake = types.ModuleType("app.license_key")
    fake.PUBLIC_KEY, fake.DEMO = "ab" * 32, False
    monkeypatch.setitem(sys.modules, "app.license_key", fake)
    with pytest.raises(SystemExit, match="Đã có khóa chính thức"):
        keygen.main(["init", "--passphrase", "mot cum mat khau dai"])


# ------------------------------------------------------------------ giao diện
def test_activate_dialog(iso, priv, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.ui_license import AboutDialog, ActivateDialog
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    d = ActivateDialog(None)
    assert d.ed_code.text() == L.machine_code() and d.btn_trial.text().startswith("Bắt đầu")
    d.do_trial()
    assert L.status().kind == L.TRIAL
    d = ActivateDialog(None)
    d.ed_key.setPlainText("sai")
    d.do_activate()
    assert L.status().kind == L.TRIAL
    d.ed_key.setPlainText(L.sign_key(priv, L.machine_code(), None))
    d.do_activate()
    assert L.status().kind == L.ACTIVE and d.result() == ActivateDialog.Accepted
    a = AboutDialog(None)
    from PySide6.QtWidgets import QTextBrowser
    assert L.machine_code() in a.findChild(QTextBrowser).toPlainText()
    a.close()
    d.close()


def test_main_window_blocks_when_trial_over(iso, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from app import ui_license
    from app.mainwindow import MainWindow
    from .test_gui import _Settings
    from .test_phase4 import _contract
    QApplication.instance() or QApplication([])
    L.start_trial(time.time() - 30 * 86400)
    shown = []
    monkeypatch.setattr(ui_license.ActivateDialog, "exec", lambda self: shown.append(self.status.kind))
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    p = tmp_path / "a.pdf"
    p.write_bytes(_contract(1))
    w.open_files([str(p)])                                           # mở xem vẫn được
    assert w.tabs.count() == 1
    w.run("rotate")
    assert shown == [L.TRIAL_OVER] and not w.current().doc.modified
    assert not w.save()
    w._update_state()
    assert "Chưa kích hoạt" in w.windowTitle()
    w.current().doc.modified = False
    w.close()


# ------------------------------------------------------------------ bắt buộc cài đặt
def test_install_check(tmp_path):
    from app import install_check as ic
    app_dir = tmp_path / "Program Files" / "PdfKySo"
    app_dir.mkdir(parents=True)
    ok, msg = ic.check(str(app_dir), [])
    assert not ok and "chưa được cài đặt" in msg                     # chép thư mục, chưa cài
    ok, msg = ic.check(str(tmp_path / "USB" / "PdfKySo"), [str(app_dir)])
    assert not ok and "sao chép" in msg                              # chạy bản chép ở chỗ khác
    ok, msg = ic.check(str(app_dir), [str(app_dir)])
    assert not ok and "thiếu file" in msg                            # thiếu unins000.exe
    (app_dir / "unins000.exe").write_bytes(b"MZ")
    assert ic.check(str(app_dir), ['"' + str(app_dir) + '"']) == (True, "")


def test_source_run_not_checked():
    from app import install_check as ic
    assert not ic.is_packaged({})                                    # python main.py -> không bắt cài
    assert ic.is_packaged({"__compiled__": object()})


def test_app_id_matches_installer():
    import re
    from app import install_check as ic
    root = os.path.dirname(os.path.dirname(__file__))
    iss = open(os.path.join(root, "installer", "setup.iss"), encoding="utf-8-sig").read()
    m = re.search(r"^AppId=\{(\{[0-9A-F-]+\})", iss, re.M)
    assert m and m.group(1) == ic.APP_ID


# ------------------------------------------------------------------ bản portable
def test_portable_mode(tmp_path, monkeypatch):
    from app import library, portable
    app_dir = tmp_path / "USB" / "PdfKySo"
    app_dir.mkdir(parents=True)
    monkeypatch.setattr(portable, "app_dir", lambda: str(app_dir))
    assert not portable.is_portable()
    assert portable.settings_args() == ("PdfKySo", "PdfKySo")
    (app_dir / portable.MARKER).write_text("portable")
    assert portable.is_portable()
    assert library.data_dir() == str(app_dir / "Data")                 # dữ liệu nằm cạnh .exe
    path, fmt = portable.settings_args()
    assert path.endswith("caidat.ini") and "Data" in path


def test_portable_moved_to_other_machine(iso, monkeypatch):
    """Mang thư mục portable (có trạng thái dùng thử của máy A) sang máy B: máy B được dùng thử bình thường."""
    L.start_trial(time.time() - 30 * 86400)                              # máy A đã hết dùng thử
    assert L.status().kind == L.TRIAL_OVER
    monkeypatch.setattr(L, "machine_code", lambda: "BBBB-BBBB-BBBB-BBBB")
    assert L.status().kind == L.NEW                                      # không bị coi là gian lận
    assert L.start_trial().kind == L.TRIAL


@needs_keygen
def test_keygen_window(iso, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(keygen, "LOG", str(tmp_path / "log.csv"))
    monkeypatch.setattr(keygen, "LIC_DIR", str(tmp_path / "lic"))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    w = keygen.build_window()()
    w.ed_code.setText(L.machine_code().lower().replace("-", ""))
    assert "✓" in w.lbl_code.text()
    assert w.do_issue() is None and warned                          # chưa mở khóa -> không cấp
    w.ed_pw.setText("sai cụm")
    assert not w.unlock() and "Sai" in w.lbl_pw.text()
    w.ed_pw.setText(DEMO_PASS)
    assert w.unlock() and w.ed_pw.text() == ""                     # mở khóa xong xóa ô mật khẩu
    w.ed_cus.setText("Công ty B")
    w.rb_forever.setChecked(True)
    key = w.do_issue()
    assert key and L.verify_key(key).expiry is None
    assert w.table.rowCount() == 1 and w.table.item(0, 2).text() == "Công ty B"
    w.ed_code.setText("ABC")
    assert w.do_issue() is None and "16 ký tự" in warned[-1]
    w.close()
