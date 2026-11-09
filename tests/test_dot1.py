"""1.0.11 – đợt 1: chọn trang ký, kéo thả vào khay, xem trước vừa khung, lưu file ghép, trang trắng,
xóa trang, tự xoay có xem trước + nút xoay nhanh trên ảnh thu nhỏ."""
import os

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app import signing, ui_pages
from app.document import PdfDocument
from app.mainwindow import MainWindow

from .test_gui import _Settings, pump
from .test_gui_phase2 import files
from .test_phase2 import make, text_page


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    return _Settings()


@pytest.fixture
def win(qapp, monkeypatch, store, tmp_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: store)
    monkeypatch.setenv("PDFKYSO_SPOOL", str(tmp_path / "spool"))
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    if getattr(w, "_tray", None):
        w._tray.close()
    w.close()


def _open(win, qapp, path):
    win.open_files([str(path)])
    pump(qapp)
    return win.current()


# ------------------------------------------------------------------ 1a
def test_verify_wording():
    import inspect
    src = inspect.getsource(signing._verify_all)
    assert "vi phạm khóa" not in src and "nội dung trang đã bị thay đổi sau khi ký" in src


# ------------------------------------------------------------------ 4a, 4b
def test_sign_dialog_page_choice(win, qapp, store):
    from app.ui_sign import SignDialog
    d = SignDialog(win, None, store, lister=lambda **k: ([], []), page_count=8, current_page=2)
    assert d.page_row.isVisibleTo(d) and not d.sp_page.isVisibleTo(d)
    assert d.sign_page() == ("auto", -1)
    d.cb_page.setCurrentIndex(d.cb_page.findData("current"))
    assert d.sign_page() == ("current", 2)
    d.cb_page.setCurrentIndex(d.cb_page.findData("last"))
    assert d.sign_page() == ("last", 7)
    d.cb_page.setCurrentIndex(d.cb_page.findData("number"))
    assert d.sp_page.isVisibleTo(d) and d.sp_page.maximum() == 8
    d.sp_page.setValue(5)
    assert d.values()["page"] == 4 and d.values()["page_mode"] == "number"
    d.cb_layout.setCurrentIndex(3)                         # ký ẩn -> không cần chọn trang
    assert not d.page_row.isVisibleTo(d)


def test_find_sign_spot_on_given_page(samples):
    d = PdfDocument(samples["text"])
    assert d.find_sign_spot(page=1)[0] == 1
    assert d.find_sign_spot()[0] == d.page_count - 1


def test_sign_places_box_on_chosen_page(win, qapp, samples, tmp_path, monkeypatch):
    import shutil
    p = tmp_path / "hd.pdf"
    shutil.copy(samples["text"], p)
    tab = _open(win, qapp, p)
    from app import ui_sign
    monkeypatch.setattr(ui_sign.SignDialog, "load", lambda self, *a, **k: self.set_certs([]))

    def fake_exec(self):
        self.cb_page.setCurrentIndex(self.cb_page.findData("number"))
        self.sp_page.setValue(2)
        return QDialog.Accepted
    monkeypatch.setattr(ui_sign.SignDialog, "exec", fake_exec)
    monkeypatch.setattr(ui_sign.SignDialog, "appearance", lambda self: QImage(100, 40, QImage.Format_ARGB32))
    win.digital_sign(tab)
    assert tab.view.placement is not None and tab.view.placement.page == 1
    assert "bấm vào trang khác" in win.lbl_msg.text()
    tab.view.cancel_placement()


def test_placement_tip_mentions_other_page():
    import inspect
    from app import viewer
    assert "Bấm vào trang khác để chuyển sang trang đó" in inspect.getsource(viewer.PageView._paint_placement)


# ------------------------------------------------------------------ 5a
def test_drop_files_into_tray(win, qapp, tmp_path):
    a, b = files(tmp_path, [2, 3])
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.refresh()
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(a), QUrl.fromLocalFile(b), QUrl.fromLocalFile(str(tmp_path / "x.txt"))])
    ev = QDropEvent(QPointF(50, 50), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    assert t.acceptDrops()
    t.dropEvent(ev)
    assert [it.page_count for it in t.items] == [2, 3] and "Đã thêm 2 file" in t.lbl_saved.text()


# ------------------------------------------------------------------ 6a, 6c
def test_preview_fit_width_zoom_and_sharp(win, qapp, tmp_path):
    (a,) = files(tmp_path, [4])
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([a])
    t.resize(1500, 900)
    t.split.setSizes([700, 800])
    t.table.selectRow(0)
    pump(qapp, 500)
    p = t.preview
    assert p.lbl_zoom.text().endswith("%")
    p.btn_fit.setChecked(True)
    pump(qapp, 800)
    vw = p.picker.viewport().width()
    assert p.picker.iconSize().width() >= vw - 70              # giãn gần hết bề ngang ô
    assert p.picker.gridSize().width() >= p.picker.iconSize().width()
    assert p._hires and max(img.width() for img in p._hires.values()) > 300   # đã vẽ lại nét
    # kéo thanh Cỡ -> thôi "vừa khung"; Ctrl + lăn chuột phóng to
    p.size_slider.setValue(200)
    assert not p.btn_fit.isChecked() and p.picker.iconSize().width() == 200
    vp = p.picker.viewport()
    ev = QWheelEvent(QPointF(10, 10), QPointF(vp.mapToGlobal(QPoint(10, 10))), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
    p.eventFilter(vp, ev)
    assert p.picker.iconSize().width() > 200
    # nhiều cột: chia đều bề ngang -> trang nằm giữa
    p.size_slider.setValue(120)
    cols = max(1, (vp.width() - 4) // (120 + 24))
    assert abs(p.picker.gridSize().width() - (vp.width() - 4) // cols) <= 1


# ------------------------------------------------------------------ 7a–7d
def test_merged_file_saved_to_folder_with_name(win, qapp, tmp_path, store):
    a, b = files(tmp_path, [2, 1])
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.ed_dir.setText("")
    t.add_paths([a, b])
    assert t.out_dir() == str(tmp_path)                        # mặc định: thư mục file đầu tiên
    assert t.ed_name.text().startswith("hs0_ghep_2file_")
    t.cb_cover.setChecked(True)
    t.opts.cover_title = "HỒ SƠ THANH TOÁN ĐỢT 2"
    t.refresh()
    assert t.ed_name.text().startswith("HỒ SƠ THANH TOÁN ĐỢT 2_")
    out = tmp_path / "ket_qua"
    t.ed_dir.setText(str(out))
    doc = t.do_merge(False)
    pump(qapp)
    assert doc.path == str(out / (t.suggest_name() + ".pdf")) and os.path.exists(doc.path)
    assert store["tray/out_dir"] == str(out)
    assert t.btn_open_dir.isVisibleTo(t) and str(out) in t.lbl_saved.text()
    tab = win.current()
    assert tab.doc.path == doc.path and not tab.doc.modified and "Đã lưu" in win.lbl_msg.text()
    # tên tự sửa tay được; trùng tên -> thêm số
    t.ed_name.setText("bo-ho-so")
    t._name_manual = True
    d1 = t.do_merge(False)
    d2 = t.do_merge(False)
    assert d1.path.endswith("bo-ho-so.pdf") and d2.path.endswith("bo-ho-so (2).pdf")


def test_merge_and_sign_needs_no_save_prompt(win, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    a, = files(tmp_path, [2])
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([a])
    t.ed_dir.setText(str(tmp_path / "ky"))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    doc = t.do_merge(True)
    pump(qapp)
    tab = win.current()
    assert win._ready_to_sign(tab) and not asked                  # đã lưu -> không hỏi "Lưu ngay?"
    assert doc.path and win.mode_group.checkedId() == 3


# ------------------------------------------------------------------ 18a
@pytest.mark.parametrize("mode,expect", [("before", (1, 1)), ("after", (2, 1)), ("start", (-1, 1)),
                                         ("end", (4, 1))])
def test_blank_dialog_positions(qapp, mode, expect):
    d = ui_pages.BlankPagesDialog(None, 5, 2)
    d.opts[mode].setChecked(True)
    assert d.values() == expect


def test_blank_insert_before_current(win, qapp, samples, monkeypatch):
    tab = _open(win, qapp, samples["text"])
    tab.view.go_to(2)
    pump(qapp)

    def fake(self):
        self.opts["before"].setChecked(True)
        self.sp_count.setValue(2)
        return QDialog.Accepted
    monkeypatch.setattr(ui_pages.BlankPagesDialog, "exec", fake)
    n = tab.doc.page_count
    win.run("blank")
    assert tab.doc.page_count == n + 2
    assert tab.doc.page_kind(2) == "blank" and tab.doc.page_kind(3) == "blank" and tab.doc.page_kind(4) == "text"


# ------------------------------------------------------------------ 19a, 19b, 19d
def test_delete_dialog_modes(qapp, samples):
    d = PdfDocument(samples["mixed"])                       # trang 2 trắng
    dlg = ui_pages.DeletePagesDialog(None, d, 0, [0, 2])
    assert dlg.mode() == "selected" and dlg.pages() == [0, 2]
    dlg.opts["odd"].setChecked(True)
    assert dlg.pages() == [0, 2]
    dlg.opts["even"].setChecked(True)
    assert dlg.pages() == [1, 3]
    dlg.opts["blank"].setChecked(True)
    assert dlg.pages() == [1] and "Xóa 1 trang" == dlg.btn_ok.text()
    assert dlg.preview.count() == 1
    dlg.ed_range.setText("1-4")
    dlg.opts["range"].setChecked(True)
    dlg._update()
    assert not dlg.btn_ok.isEnabled() and "hết" in dlg.lbl_err.text()
    dlg.ed_range.setText("2, 4")
    dlg._update()
    assert dlg.pages() == [1, 3] and dlg.btn_ok.isEnabled() and dlg.preview.count() == 2


def test_delete_duplicates(qapp, samples):
    d = PdfDocument(samples["text"])                         # 5 trang giống hệt nhau
    dlg = ui_pages.DeletePagesDialog(None, d, 0, [0])
    dlg.opts["dup"].setChecked(True)
    assert dlg.pages() == [1, 2, 3, 4]


def test_delete_key_on_thumbnails(win, qapp, samples, monkeypatch):
    tab = _open(win, qapp, samples["text"])
    seen = {}

    def fake(self):
        seen["mode"] = self.mode()
        seen["pages"] = self.pages()
        return QDialog.Accepted
    monkeypatch.setattr(ui_pages.DeletePagesDialog, "exec", fake)
    tab.thumbs.clearSelection()
    tab.thumbs.item(1).setSelected(True)
    tab.thumbs.item(3).setSelected(True)
    QTest.keyClick(tab.thumbs, Qt.Key_Delete)
    assert seen == {"mode": "selected", "pages": [1, 3]} and tab.doc.page_count == 3


# ------------------------------------------------------------------ 20b, 20c, 20d
def test_auto_rotate_dialog_preview(qapp, samples):
    d = make([text_page(), text_page(rot_text=90), text_page(page_rot=180)])
    dlg = ui_pages.AutoRotateDialog(None, d)
    assert set(dlg.chosen()) == {1, 2} and "Xoay 2 trang" in dlg.btn_ok.text()
    assert "2 trang bị xoay" in dlg.lbl_auto.text() and dlg.lbl_scan.text() == ""
    dlg.list.item(0).setCheckState(Qt.Unchecked)                 # bỏ tích trang không muốn xoay
    assert list(dlg.chosen()) == [2]
    s = PdfDocument(samples["mixed"])                            # trang 3 ngang, trang 4 scan
    dlg = ui_pages.AutoRotateDialog(None, s)
    assert "1 trang scan" in dlg.lbl_scan.text() and not dlg.btn_ok.isEnabled()
    dlg.landscape_to_portrait()
    assert dlg.chosen() == {2: 90}
    dlg.flip(0)
    assert set(dlg.chosen()) == {0, 2}
    dlg.reset()
    assert dlg.chosen() == {}


def test_auto_rotate_command_applies(win, qapp, tmp_path, monkeypatch):
    d = make([text_page(), text_page(rot_text=90)])
    p = tmp_path / "xoay.pdf"
    p.write_bytes(d.to_bytes())
    tab = _open(win, qapp, p)
    monkeypatch.setattr(ui_pages.AutoRotateDialog, "exec", lambda self: QDialog.Accepted)
    win.run("autorotate")
    assert tab.doc.page(1).get_rotation() != 0 and "Đã xoay 1 trang" in win.lbl_msg.text()
    win.run("undo")
    assert tab.doc.page(1).get_rotation() == 0


def test_hover_rotate_buttons_on_thumbnails(win, qapp, samples):
    tab = _open(win, qapp, samples["text"])
    th = tab.thumbs
    r = th.visualRect(th.model().index(1, 0))
    QTest.mouseMove(th.viewport(), r.center())
    pump(qapp, 50)
    assert th._hover == 1
    left, right = th._rot_buttons(1)
    QTest.mouseClick(th.viewport(), Qt.LeftButton, Qt.NoModifier, right.center())
    assert tab.doc.page(1).get_rotation() == 90
    QTest.mouseMove(th.viewport(), th.visualRect(th.model().index(1, 0)).center())
    left, right = th._rot_buttons(1)
    QTest.mouseClick(th.viewport(), Qt.LeftButton, Qt.NoModifier, left.center())
    assert tab.doc.page(1).get_rotation() == 0


# ------------------------------------------------------------------ thiếu thư viện (lỗi "No module named 'fontTools'")
def test_missing_dependency_messages(monkeypatch):
    from app import deps
    assert deps.missing() == []                                    # máy kiểm thử cài đủ
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda m, *a: None if m == "fontTools" else real(m, *a))
    miss = deps.missing()
    assert [p for _, p, _ in miss] == ["fonttools"]
    msg = deps.missing_message(miss)
    assert "fonttools" in msg and "pip install -r requirements.txt" in msg
    hint = deps.explain(ModuleNotFoundError("No module named 'fontTools'"))
    assert "fonttools" in hint and "requirements.txt" in hint
    assert deps.explain(ValueError("khác")) == ""


def test_tray_merge_error_shows_install_hint(win, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    (a,) = files(tmp_path, [1])
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([a])

    def boom(*a, **k):
        raise ModuleNotFoundError("No module named 'fontTools'")
    monkeypatch.setattr("app.tray.merge", boom)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    assert t.do_merge(False) is None
    assert "fonttools" in shown[0] and "pip install" in shown[0]
