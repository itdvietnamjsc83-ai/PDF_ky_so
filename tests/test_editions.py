"""1.0.20 – phân gói Tiêu chuẩn / Chuyên nghiệp / Doanh nghiệp theo "Gói phần mềm cung cấp"."""
import datetime as dt
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app import editions
from app import license as L
try:
    from tools import keygen
except ImportError:                       # kho mã không kèm bộ tạo key
    from . import _keygen_demo as keygen

from .test_phase6b import DEMO_PASS, iso  # noqa: F401


@pytest.fixture
def activate(iso):  # noqa: F811
    priv = keygen.derive_private(DEMO_PASS)

    def go(edition):
        L.activate(L.sign_key(priv, L.machine_code(), dt.date.today() + dt.timedelta(days=30), edition=edition))
        return L.status()
    return go


def test_table_matches_document():
    s, p, e = editions.STANDARD, editions.PRO, editions.ENTERPRISE
    # gói Tiêu chuẩn có cả chức năng sửa (yêu cầu thêm của nhà cung cấp)
    for cmd in ("open", "print", "blank", "rotate", "split", "note", "textbox", "shape", "pen", "erase",
                "edittext", "find", "insertpdf"):
        assert editions.required(cmd) == s, cmd
    for cmd in ("digisign", "spool", "tray", "colormode", "protect", "compress", "compare", "hand", "stamptext",
                "notes_export"):
        assert editions.required(cmd) == p, cmd
    for cmd in ("verify", "stamp", "sigimg", "seam", "library", "tray_advanced", "autorotate", "batchsign", "flow",
                "batchxl", "autofolder", "backup", "history"):
        assert editions.required(cmd) == e, cmd


def test_current_level(iso, activate):  # noqa: F811
    assert editions.current(L.start_trial()) == editions.ENTERPRISE          # dùng thử: đủ tính năng
    assert editions.current(activate(1)) == 1
    assert editions.current(activate(2)) == 2
    assert editions.current(L.status(time.time() + 60 * 86400)) == 1           # hết hạn -> thấp nhất


def test_window_blocks_by_edition(iso, activate, monkeypatch, tmp_path):  # noqa: F811
    from app.mainwindow import MainWindow
    from .test_gui import _Settings
    from .test_phase4 import _contract
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    activate(1)
    shown = []

    def fake_exec(box):
        shown.append(box.text())
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    p = tmp_path / "a.pdf"
    p.write_bytes(_contract(1))
    w.open_files([str(p)])
    w.license_status(fresh=True)
    w.apply_edition_ui()
    assert w.edition_level() == 1
    assert w.edition_ok("edittext") and w.edition_ok("rotate")
    w.run("digisign")
    assert shown and "Chuyên nghiệp" in shown[-1] and "Tiêu chuẩn" in shown[-1]
    w.run("batchsign")
    assert "Doanh nghiệp" in shown[-1]
    btn = next(b for b, _ic, cmd, _p in w.tool_buttons if cmd == "digisign")
    assert "Thuộc gói Chuyên nghiệp" in btn.toolTip()
    btn2 = next(b for b, _ic, cmd, _p in w.tool_buttons if cmd == "edittext")
    assert "Thuộc gói" not in btn2.toolTip()
    w.current().doc.modified = False
    w.close()


def test_tray_advanced_locked_for_pro(iso, activate, monkeypatch, tmp_path):  # noqa: F811
    from app.mainwindow import MainWindow
    from .test_gui import _Settings
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    activate(2)
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.license_status(fresh=True)
    t = w.show_tray()
    assert not t.cb_cover.isEnabled() and not t.cb_duplex.isChecked() and not t.btn_tpl_save.isEnabled()
    assert not t.opts.duplex and not t.opts.page_numbers
    assert "Doanh nghiệp" in t.cb_toc.toolTip()
    t.apply_edition(3)
    assert t.cb_cover.isEnabled() and t.btn_tpl_open.isEnabled()
    t.close()
    w.close()


def test_packages_dialog(monkeypatch):
    from PySide6.QtWidgets import QDialog
    from app.ui_license import show_packages
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    html = editions.compare_html(2)
    assert "Chuyên nghiệp (đang dùng)" in html and "Sửa chữ có sẵn" in html
    assert show_packages().windowTitle().startswith("Các gói")
