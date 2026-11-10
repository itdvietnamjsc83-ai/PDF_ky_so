"""Giao diện "Ấn triện" (1.0.6): thanh điều hướng trái, ẩn/hiện dải công cụ, màn hình bắt đầu + file gần đây,
thẻ chứng thư số, bảng thông tin nhà phát triển, phông giao diện."""
import json
import os
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import theme
from app.mainwindow import MODES, MainWindow

from .test_gui import _Settings, pump


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    return _Settings()


@pytest.fixture
def win(qapp, monkeypatch, store):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: store)
    w = MainWindow()
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def test_ui_font_bundled_and_loaded(qapp):
    from app.fonts import assets_dir
    d = os.path.join(assets_dir(), "fonts", "ui")
    files = sorted(f for f in os.listdir(d) if f.endswith(".ttf"))
    assert len(files) == 6 and "BeVietnamPro-Light.ttf" in files and os.path.exists(os.path.join(d, "OFL.txt"))
    assert theme.load_fonts() == "Be Vietnam Pro"
    assert "Be Vietnam Pro" in QFontDatabase.families()
    assert '"Be Vietnam Pro"' in theme.stylesheet(theme.LIGHT)


def test_palette_an_trien():
    assert theme.LIGHT["accent"] == "#B8322A" and theme.LIGHT["bg"] == "#F3F0E8"
    assert theme.LIGHT["rail"] == "#16203A"
    for c in (theme.LIGHT, theme.DARK):
        assert set(theme.LIGHT) == set(c)
        css = theme.stylesheet(c)
        assert "QPushButton:default" in css and "QFrame#rail" in css


def test_rail_modes(win, qapp):
    assert win.rail.width() == win.RAIL_W == 60                         # 1.0.22: thu gọn (trước 88)
    win.rail_btn.click()                                                 # nút ngay trên thanh: chỉ còn biểu tượng
    assert win.rail_compact() and win.rail.width() == win.RAIL_W_COMPACT
    assert win.mode_buttons[0][0].toolButtonStyle() == Qt.ToolButtonIconOnly
    win.rail_btn.click()
    assert not win.rail_compact() and win.rail.width() == 60
    assert len(win.mode_buttons) == len(MODES) == win.toolbars.count()
    win.mode_group.button(3).click()
    pump(qapp, 20)
    assert win.toolbars.currentIndex() == 3 and win.lbl_title.text() == "Ký & Đóng dấu"
    primary = [cmd for b, ic, cmd, p in win.tool_buttons if p]
    assert "digisign" in primary


def test_ribbon_toggle_persists(win, qapp, store, monkeypatch):
    assert win.ribbon_visible()
    win.ribbon_btn.click()                          # nút ở góc phải hàng tiêu đề
    pump(qapp, 20)
    assert not win.ribbon_visible() and store["ui/ribbon"] is False
    assert "Ctrl+F1" in win.ribbon_btn.toolTip()
    QTest.keyClick(win, Qt.Key_F1, Qt.ControlModifier)
    pump(qapp, 20)
    assert win.ribbon_visible() and store["ui/ribbon"] is True
    win.toggle_ribbon()
    assert not win.ribbon_visible()
    win.mode_group.button(1).click()                 # bấm một nhóm bên trái -> hiện lại
    pump(qapp, 20)
    assert win.ribbon_visible() and win.toolbars.currentIndex() == 1
    # lần mở sau nhớ trạng thái ẩn
    win.set_ribbon_visible(False)
    w2 = MainWindow()
    try:
        assert not w2.ribbon_visible()
    finally:
        w2.close()


def test_start_page_quick_and_recent(win, qapp, samples, monkeypatch, tmp_path):
    assert win.stack.currentIndex() == 0 and win.empty.no_recent.isVisibleTo(win.empty)
    ran = []
    monkeypatch.setattr(win, "run", lambda c: ran.append(c))
    win.empty.command.disconnect()
    win.empty.command.connect(win.run)
    for b, ic, cmd in win.empty.quick_buttons:
        b.click()
    assert ran == ["open", "digisign", "stamp", "tray", "protect", "compress"]
    # file gần đây (file trong thư mục tạm không được ghi nhớ -> thêm trực tiếp)
    win.add_recent(samples["text"])
    win.add_recent(samples["mixed"])
    win.add_recent(samples["text"])                  # mở lại -> lên đầu, không trùng
    assert win.recent_files() == [os.path.abspath(samples["text"]), os.path.abspath(samples["mixed"])]
    assert win.empty.recent.count() == 2 and not win.empty.no_recent.isVisibleTo(win.empty)
    win.empty.recent.itemClicked.emit(win.empty.recent.item(1))
    pump(qapp)
    assert win.current() and win.current().doc.path == os.path.abspath(samples["mixed"])
    for k in range(20):
        win.add_recent(str(tmp_path / f"f{k}.pdf"))
    assert len(win.recent_files()) == 12


def test_recent_skips_temp_files(win, samples):
    win.open_files([samples["text"]])                # pytest tmp nằm trong thư mục tạm
    assert win.recent_files() == []


def test_cert_card_scan_and_remember(win, qapp, monkeypatch):
    from app import ui_sign

    class C:
        subject, organization, issuer = "Nguyễn Văn A", "CÔNG TY TNHH ABC", "Nhà cung cấp X"
        not_after, thumbprint, expired = time.time() + 100 * 86400, "AB", False
    monkeypatch.setattr(ui_sign, "busy", lambda parent, text, fn: fn())
    calls = []
    win.cert_lister = lambda **kw: (calls.append(kw), ([C()], ["lib.dll"]))[1]
    win.side.cert_card.btn_scan.click()
    assert calls and "CÔNG TY TNHH ABC" in win.side.cert_card.name.text()
    assert "còn 99 ngày" in win.side.cert_card.sub.text() or "còn 100 ngày" in win.side.cert_card.sub.text()
    assert "1 chứng thư" in win.side.cert_card.state.text()
    win.remember_cert(C())
    saved = json.loads(win.settings.value("sign/last_cert"))
    assert saved["organization"] == "CÔNG TY TNHH ABC"
    w2 = MainWindow()
    try:
        assert "CÔNG TY TNHH ABC" in w2.side.cert_card.name.text()
        assert w2.side.cert_card.state.text() == "Dùng gần nhất"
    finally:
        w2.close()
    win.cert_lister = lambda **kw: ([], [])
    win.side.cert_card.btn_scan.click()
    assert "Không thấy" in win.side.cert_card.sub.text()


def test_theme_toggle_keeps_layout(win, qapp):
    win.toggle_theme()
    pump(qapp, 20)
    win.toggle_theme()
    assert win.colors in (theme.LIGHT, theme.DARK)
    if win.layout_style() == "rail":
        assert win.rail.isVisible()
    else:                                                    # 1.0.22: kiểu tab ngang (Foxit) mặc định
        assert win.mode_tabs[0].isVisible() and not win.rail.isVisible()


def test_developer_dialog(qapp, win, monkeypatch):
    from app import branding
    from app.ui_license import DeveloperDialog
    d = DeveloperDialog(win)
    assert d.lbl_dev.text() == branding.DEVELOPER
    assert branding.EMAIL in d.lbl_contact.text()
    assert d.btn_ok.isDefault()
    d.btn_ok.click()
    assert d.result() == DeveloperDialog.Accepted
    shown = []
    monkeypatch.setattr(DeveloperDialog, "exec", lambda self: shown.append(1) or 1)
    win.dev_btn.click()
    assert shown == [1]


def test_main_shows_developer_dialog_every_start():
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"), encoding="utf-8").read()
    i = src.index("def startup_dialogs")
    block = src[i:src.index("QTimer.singleShot(300, w, startup_dialogs)")]
    assert "DeveloperDialog(w).exec()" in block
    assert block.index("DeveloperDialog") < block.index("show_license")      # trước màn hình bản quyền


# ------------------------------------------------------------------ xóa lịch sử file đã xử lý (1.0.7)
def _fill_history(samples, store):
    import logging
    from app import library, office, tools
    from app.library import LibItem, STAMP
    work = os.path.join(library.data_dir(), "..", "work_hist")
    os.makedirs(work, exist_ok=True)
    f = os.path.join(work, "hop-dong.pdf")
    with open(samples["text"], "rb") as a, open(f, "wb") as b:
        b.write(a.read())
    tools.keep_version(f)
    tools.keep_version(f)
    library.log_usage(LibItem(id="x", name="Dấu công ty", kind=STAMP, width_mm=38), f, [0])
    with open(os.path.join(office.cache_dir(), "bao-gia_abc.pdf"), "wb") as o:
        o.write(b"%PDF-1.4 tam")
    from app.stability import local_dir
    with open(os.path.join(local_dir("logs"), "app.log.1"), "w", encoding="utf-8") as lg:
        lg.write("Mở hop-dong.pdf\n")
    store["recent"] = [f, "D:/khong-con/abc.pdf"]
    return f


def test_clear_history_functions(samples, store):
    from app import tools
    f = _fill_history(samples, store)
    summ = tools.history_summary(store)
    assert summ["recent"][0] == 2 and summ["versions"][0] >= 1 and summ["usage"][0] >= 1
    assert summ["office"][0] >= 1 and summ["logs"][0] > 0
    done = tools.clear_history(["recent", "versions", "usage", "office", "logs"], store)
    assert len(done) == 5
    after = tools.history_summary(store)
    assert all(after[k][0] == 0 for k in ("recent", "versions", "usage", "office"))
    assert tools.versions(f) == [] and store["recent"] == []
    assert os.path.exists(f)                         # file gốc không bị đụng tới


def test_clear_history_dialog_partial(win, qapp, samples, store, monkeypatch):
    from app import tools, ui_tools
    f = _fill_history(samples, store)
    win.refresh_recent()

    def fake_exec(self):
        assert self.checks["recent"].isChecked() and self.checks["versions"].isChecked()
        self.checks["usage"].setChecked(False)       # giữ lại nhật ký dùng dấu
        return ui_tools.ClearHistoryDialog.Accepted
    monkeypatch.setattr(ui_tools.ClearHistoryDialog, "exec", fake_exec)
    win.run("clearhistory")                          # dùng được cả khi hết hạn / chưa mở file
    assert win.recent_files() == [] and win.empty.recent.count() == 0
    assert tools.versions(f) == []
    assert tools.history_summary(store)["usage"][0] >= 1
    assert "Đã xóa" in win.lbl_msg.text()
    assert any(cmd == "clearhistory" for _, _, cmd, _ in win.tool_buttons)


def test_recent_remove_one_prune_clear(win, qapp, samples, store):
    a, b = os.path.abspath(samples["text"]), os.path.abspath(samples["mixed"])
    store["recent"] = [a, "D:/khong-con/abc.pdf", b]
    win.refresh_recent()
    assert win.empty.recent.count() == 3
    win.empty.recent.setCurrentRow(0)
    QTest.keyClick(win.empty.recent, Qt.Key_Delete)  # phím Delete: xóa khỏi danh sách
    assert win.recent_files() == ["D:/khong-con/abc.pdf", b]
    win.empty.command.emit("recentprune")            # bỏ các file không còn trên máy
    assert win.recent_files() == [b]
    win.empty.command.emit("recentclear")
    assert win.recent_files() == [] and win.empty.no_recent.isVisibleTo(win.empty)


def test_version_history_dialog_delete(qapp, samples, monkeypatch, tmp_path):
    from app import tools
    from app.ui_tools import HistoryDialog
    f = str(tmp_path / "hd.pdf")
    with open(samples["text"], "rb") as a, open(f, "wb") as b:
        b.write(a.read())
    for _ in range(3):
        tools.keep_version(f)
        time.sleep(1.05)                             # tên bản cũ theo giây
    d = HistoryDialog(None, f)
    n = len(d.vers)
    assert n >= 2
    d._delete_one(confirm=False)
    assert len(tools.versions(f)) == n - 1 and d.list.count() == n - 1
    d._delete_all(confirm=False)
    assert tools.versions(f) == [] and not d.btn_del.isEnabled()


def test_top_search_box_goes_to_pages(win, qapp, samples):
    win.open_files([samples["mixed"]])              # trang 1 và 3 có chữ, trang 2 trắng, trang 4 scan
    pump(qapp)
    # 1.0.22: tô vàng mọi chỗ tìm thấy, Enter tới TỪNG chỗ (như Foxit/Adobe), hết thì vòng lại
    assert win.search_doc("Hợp đồng") == 0
    view = win.current().view
    hits = win._search["hits"]
    per_page = {pg: sum(1 for p, _ in hits if p == pg) for pg, _ in hits}
    assert set(per_page) == {0, 2} and len(view.marks["search"][0]) >= per_page[0] and view.marks["search_cur"]
    assert "2 trang" in win.lbl_msg.text() and f"1/{len(hits)}" in win.lbl_msg.text()
    pages = [win.search_doc("Hợp đồng") for _ in range(len(hits) - 1)]
    assert pages[per_page[0] - 1] == 2 and pages[-1] == 2      # hết chỗ trang 1 -> sang trang 3
    assert win.search_doc("Hợp đồng") == 0            # vòng lại
    assert win.search_doc("Hợp đồng", backward=True) == 2      # Shift+Enter: chỗ trước
    win.clear_search()
    assert not view.marks
    assert win.search_doc("không-có-chữ-này") is None and "Không tìm thấy" in win.lbl_msg.text()
    win.search.setText("Tiếng Việt")
    QTest.keyClick(win.search, Qt.Key_Return)
    assert "Tiếng Việt" in win.lbl_msg.text()
