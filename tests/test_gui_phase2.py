"""Giao diện giai đoạn 2: khay ghép, kéo thả trang, menu trang, chèn ảnh, đổi khổ, tách, máy in ảo."""
import os
import shutil

import pymupdf
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.mainwindow import MainWindow

from .conftest import _font_page
from .test_gui import _Settings, pump


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


@pytest.fixture
def win(qapp, monkeypatch):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow()
    w.resize(1440, 900)
    w.show()
    qapp.processEvents()
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    if getattr(w, "_tray", None):
        w._tray.close()
    w.close()


def files(tmp_path, counts):
    out = []
    for k, n in enumerate(counts):
        d = pymupdf.open()
        for _ in range(n):
            _font_page(d, lines=4)
        p = tmp_path / f"hs{k}.pdf"
        d.save(p)
        out.append(str(p))
    return out


def test_tray_flow(win, qapp, tmp_path):
    a, b, c = files(tmp_path, [3, 5, 8])
    tray = win.show_tray()
    assert tray.add_paths([a, b, c, str(tmp_path / "khong-co.pdf")]) == 3
    assert tray.table.rowCount() == 3
    assert tray.lbl_total.text() == "Tổng: 18 trang (2 trang trắng) từ 3 file"
    tray._set(tray.items[1], whole=False, ranges="1-3, 5")
    assert tray.lbl_total.text() == "Tổng: 16 trang (1 trang trắng) từ 3 file"
    assert "8 tờ" in tray.lbl_sub.text()
    tray.move(2, -1)                                   # đưa file 8 trang lên trên
    assert [it.page_count for it in tray.items] == [3, 8, 5]
    tray.cb_duplex.setChecked(False)
    assert tray.lbl_total.text() == "Tổng: 15 trang từ 3 file"
    tray.ed_dir.setText(str(tmp_path / "ra"))
    doc = tray.do_merge(False)
    pump(qapp)
    assert doc.page_count == 15
    # 1.0.11: lưu luôn vào thư mục đã chọn, tên theo file đầu tiên
    assert doc.path and doc.path.startswith(str(tmp_path / "ra")) and "hs0_ghep_3file_" in doc.path
    assert os.path.exists(doc.path) and win.tabs.count() == 1 and not win.tabs.tabText(0).startswith("●")
    tray.quiet = True                                  # trùng tên -> tự thêm số (không hỏi)
    d2 = tray.do_merge(True)
    assert d2.path.endswith(" (2).pdf")
    assert win.mode_group.checkedId() == 3            # chuyển sang nhóm Ký & Đóng dấu


def test_tray_bad_range_rejected(win, qapp, tmp_path, monkeypatch):
    (a,) = files(tmp_path, [4])
    msgs = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: msgs.append(a[2]))
    tray = win.show_tray()
    tray.add_paths([a])
    tray._set(tray.items[0], whole=False, ranges="1-9")
    assert msgs and tray.items[0].ranges != "1-9"


def test_tray_page_picker(win, qapp, tmp_path):
    (a,) = files(tmp_path, [6])
    tray = win.show_tray()
    tray.add_paths([a])
    tray._load_picker(0)
    pump(qapp, 300)
    tray._quick_pick("lẻ")
    assert not tray.items[0].whole and tray.items[0].ranges == "1, 3, 5"
    tray.picker.item(1).setCheckState(Qt.Checked)
    assert tray.items[0].ranges == "1-3, 5"
    tray._quick_pick("all")
    assert tray.items[0].whole


def test_tray_persists_between_sessions(qapp, tmp_path, monkeypatch):
    store = _Settings()
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: store)
    a, b = files(tmp_path, [1, 2])
    w1 = MainWindow()
    w1.show_tray().add_paths([a, b])
    w1._tray.close()
    w1.close()
    w2 = MainWindow()
    assert [it.page_count for it in w2.show_tray().items] == [1, 2]
    w2._tray.close()
    w2.close()


def test_drag_reorder_pages_and_undo(win, qapp, samples, tmp_path):
    src = tmp_path / "m.pdf"
    shutil.copy(samples["mixed"], src)
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    kinds = [tab.doc.page_kind(i) for i in range(4)]
    win.move_pages([3], 0)                             # kéo trang scan lên đầu
    assert tab.doc.page_kind(0) == "scan"
    assert [tab.doc.page_kind(i) for i in range(1, 4)] == kinds[:3]
    win.run("undo")
    assert [tab.doc.page_kind(i) for i in range(4)] == kinds


def test_page_context_menu(win, qapp, samples, monkeypatch):
    win.open_files([samples["text"]])
    pump(qapp)
    m = win.build_page_menu()
    seen = [a.text() for a in m.actions()]
    assert "Xóa trang…" in seen and "Chèn trang trắng…" in seen and "Thêm file này vào khay ghép" in seen
    next(a for a in m.actions() if a.text() == "Xoay trái 90°").trigger()
    assert win.current().doc.page_info(0).landscape


def test_insert_image_by_placement(win, qapp, samples, tmp_path):
    win.open_files([samples["scan"]])                 # chèn ảnh được cả trên file scan
    pump(qapp)
    tab = win.current()
    png = tmp_path / "dau.png"
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    for x in range(40, 160):
        for y in range(40, 160):
            img.setPixelColor(x, y, QColor(200, 30, 30))
    img.save(str(png))
    win.insert_image(tab, str(png))
    v = tab.view
    assert v.placement is not None
    v.placement.rect = QRectF(-50, -50, 100, 100)      # kéo ra ngoài mép -> tự kẹp lại trong trang
    v._clamp_placement()
    assert v.placement.rect.left() == 0 and v.placement.rect.top() == 0
    v.placement.rect = QRectF(100, 100, 120, 120)
    v.commit_placement()
    assert tab.doc.modified and v.placement is None
    bm = tab.doc.render(0, 1.0)
    buf = bytes(bm.buffer)
    x, y = 160, 160                                    # giữa ô đỏ
    r, g, b = buf[y * bm.stride + x * 3: y * bm.stride + x * 3 + 3]
    bm.close()
    assert r > 150 and g < 80
    win.run("undo")
    assert not tab.doc.can_undo


def test_placement_keyboard(win, qapp, samples, tmp_path):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    img = QImage(50, 50, QImage.Format_RGB32)
    img.fill(QColor("black"))
    p = tmp_path / "k.png"
    img.save(str(p))
    win.insert_image(tab, str(p))
    v = tab.view
    x0 = v.placement.rect.left()
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.ShiftModifier))
    assert v.placement.rect.left() == pytest.approx(x0 + 10)
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert v.placement is None and not tab.doc.modified


def test_resize_and_split_dialogs(win, qapp, samples, tmp_path, monkeypatch):
    from app import pagetools
    win.open_files([samples["mixed"]])
    pump(qapp)
    tab = win.current()
    monkeypatch.setattr(pagetools.ResizeDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(pagetools.ResizeDialog, "values", lambda self: dict(
        all_pages=True, paper="A5", custom_mm=None, orientation="keep", mode="fit", margin_mm=0))
    win.run("resize")
    assert {tab.doc.page_info(i).paper for i in range(4)} == {"A5"}

    out = tmp_path / "tach"
    monkeypatch.setattr(pagetools.SplitDialog, "exec", lambda self: QDialog.Accepted)
    orig_init = pagetools.SplitDialog.__init__

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        self.r_single.setChecked(True)
        self.ed_folder.setText(str(out))
    monkeypatch.setattr(pagetools.SplitDialog, "__init__", init)
    win.run("split")
    assert len(os.listdir(out)) == 4


def test_spool_watcher(win, qapp, samples, tmp_path):
    root = tmp_path / "spool"
    win.start_spool(str(root))
    got = []
    win.spool.fileArrived.connect(lambda k, p: got.append((k, p)))
    # file đang ghi dở: chưa được lấy
    partial = root / "tray" / "ban_in.pdf"
    partial.write_bytes(b"%PDF-1.7\n")
    win.spool.scan()
    assert not got
    shutil.copy(samples["text"], partial)
    for _ in range(3):
        win.spool.scan()
        pump(qapp, 50)
    assert got and got[0][0] == "tray" and os.path.dirname(got[0][1]) == str(root / "inbox")
    assert win._tray.items[-1].path == got[0][1]
    shutil.copy(samples["scan"], root / "sign" / "ban_in.pdf")
    for _ in range(3):
        win.spool.scan()
        pump(qapp, 50)
    assert win.tabs.count() == 1 and win.mode_group.checkedId() == 3


def test_toolbar_every_button_responds(win, qapp, samples, monkeypatch):
    """Bấm lần lượt mọi nút trên thanh công cụ: không được lỗi hay treo."""
    from PySide6.QtWidgets import QFileDialog
    from app import pagetools
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(pagetools.SplitDialog, "exec", lambda self: QDialog.Rejected)
    monkeypatch.setattr(pagetools.ResizeDialog, "exec", lambda self: QDialog.Rejected)
    monkeypatch.setattr("app.mainwindow.MainWindow.print_doc", lambda *a: None)
    monkeypatch.setattr("app.mainwindow.MainWindow.library_menu", lambda *a: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    from app import ui_sign
    monkeypatch.setattr(ui_sign.SignDialog, "load", lambda self, *a, **k: self.set_certs([]))
    monkeypatch.setattr(ui_sign.SignDialog, "exec", lambda self: QDialog.Rejected)
    monkeypatch.setattr(ui_sign.VerifyDialog, "exec", lambda self: QDialog.Rejected)
    from app import ui_edit
    for cls in (ui_edit.FindReplaceDialog, ui_edit.HandDialog, ui_edit.TextDialog, ui_edit.NoteDialog,
                ui_edit.EditTextDialog):
        monkeypatch.setattr(cls, "exec", lambda self: QDialog.Rejected)
    from app import ui_tools
    for name in ("ProtectDialog", "CompressDialog", "StampTextDialog", "CompareDialog", "BatchSignDialog",
                 "FlowDialog", "BatchExcelDialog", "HistoryDialog", "AutoFolderDialog", "ClearHistoryDialog"):
        monkeypatch.setattr(getattr(ui_tools, name), "exec", lambda self: QDialog.Rejected)
    from app import ui_pages
    for cls in (ui_pages.BlankPagesDialog, ui_pages.DeletePagesDialog, ui_pages.AutoRotateDialog,
                ui_pages.InsertPagesDialog):
        monkeypatch.setattr(cls, "exec", lambda self: QDialog.Rejected)
    from app import ui_import
    for cls in (ui_import.ImportOptionsDialog, ui_import.ImportSettingsDialog, ui_import.ColorModeDialog):
        monkeypatch.setattr(cls, "exec", lambda self: QDialog.Rejected)
    from app import ui_license
    for cls in (ui_license.ActivateDialog, ui_license.AboutDialog, ui_license.DeveloperDialog):
        monkeypatch.setattr(cls, "exec", lambda self: QDialog.Rejected)
    win.open_files([samples["mixed"]])
    pump(qapp)
    for b, ic, cmd, primary in win.tool_buttons:
        if cmd in ("delete",):
            continue
        b.click()
        qapp.processEvents()
        tab = win.current()
        if tab and tab.view.placement:
            tab.view.cancel_placement()
        if tab and tab.view.tool:
            tab.view.set_tool(None)
        if getattr(win, "_last_menu", None):
            win._last_menu.close()
    if win._tray:
        win._tray.close()
    assert win.current().doc.page_count >= 4


class _Ev:
    def __init__(self, x, y):
        from PySide6.QtCore import QPointF
        self._p = QPointF(x, y)

    def position(self):
        return self._p

    def button(self):
        return Qt.LeftButton


@pytest.mark.parametrize("corner", [0, 1, 2, 3])
def test_placement_drag_move_and_corner_resize(win, qapp, samples, tmp_path, corner):
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    img = QImage(100, 50, QImage.Format_RGB32)
    img.fill(QColor("black"))
    p = tmp_path / "r.png"
    img.save(str(p))
    win.insert_image(tab, str(p))
    v = tab.view
    v.set_zoom(100)
    v.placement.rect = QRectF(200, 300, 100, 50)
    sr = v._placement_screen_rect()
    # di chuyển
    c = sr.center()
    v._place_press(_Ev(c.x(), c.y()))
    v._place_move(_Ev(c.x() + 40, c.y() + 20))
    v._place_release(None)
    s = v.scale
    assert v.placement.rect.left() == pytest.approx(200 + 40 / s, abs=0.5)
    # kéo góc ra ngoài 30 px: to ra, giữ tỉ lệ 2:1, góc đối diện đứng yên
    before = QRectF(v.placement.rect)
    sr = v._placement_screen_rect()
    pt = (sr.topLeft(), sr.topRight(), sr.bottomLeft(), sr.bottomRight())[corner]
    out = (-30, 30)[corner in (1, 3)]
    v._place_press(_Ev(pt.x(), pt.y()))
    v._place_move(_Ev(pt.x() + out, pt.y()))
    r = v.placement.rect
    assert r.width() > before.width() and r.width() / r.height() == pytest.approx(2, rel=0.01)
    opposite = (before.bottomRight(), before.bottomLeft(), before.topRight(), before.topLeft())[corner]
    now = (r.bottomRight(), r.bottomLeft(), r.topRight(), r.topLeft())[corner]
    assert (now.x(), now.y()) == pytest.approx((opposite.x(), opposite.y()), abs=0.5)
    v.cancel_placement()


def test_spool_page_report(tmp_path):
    import pymupdf
    d = pymupdf.open()
    d.new_page(width=595, height=842)
    d.new_page(width=842, height=595)
    p = tmp_path / "a4.pdf"
    d.save(str(p))
    text, letter = MainWindow.spool_page_report(str(p))
    assert "A4 dọc: 1 trang" in text and "A4 ngang: 1 trang" in text and not letter
    d = pymupdf.open()
    d.new_page(width=612, height=792)
    p2 = tmp_path / "letter.pdf"
    d.save(str(p2))
    assert MainWindow.spool_page_report(str(p2))[1]
