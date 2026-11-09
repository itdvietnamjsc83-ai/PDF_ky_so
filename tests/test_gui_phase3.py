"""Giao diện giai đoạn 3: panel thư viện, đặt dấu, kéo thả, giáp lai, khóa, nhập ảnh, khôi phục."""
import os

import pytest
from PySide6.QtCore import QMimeData, QPointF, QRectF
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from app.library import STAMP, Library
from app.mainwindow import MainWindow

from .test_gui import _Settings, pump
from .test_phase3 import remove_background, stamp_jpeg


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def lib_path(tmp_path):
    p = str(tmp_path / "lib.pdf")
    lib = Library(p)
    lib.add("Dấu công ty", remove_background(stamp_jpeg()), STAMP, 38)
    return p


@pytest.fixture
def win(qapp, monkeypatch, lib_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=lib_path)
    w.resize(1440, 900)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def test_panel_lists_library(win, qapp):
    assert win.lib_panel.list.count() == 1
    assert win.lib_panel.list.item(0).text() == "Dấu công ty"


def test_click_place_commit_all_pages(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    win.lib_panel.scope.setCurrentIndex(2)          # tất cả các trang
    iid = win.library.items[0].id
    win.place_library_item(iid)
    pl = tab.view.placement
    assert pl and pl.rect.width() == pytest.approx(38 * 72 / 25.4, abs=0.5)
    pl.rect = QRectF(400, 650, pl.rect.width(), pl.rect.height())
    tab.view.commit_placement()
    for i in range(tab.doc.page_count):
        bm = tab.doc.render(i, 0.3)
        buf = bytes(bm.buffer)
        red = sum(1 for k in range(0, len(buf) - 3, 3) if buf[k] > 150 and buf[k + 1] < 90)
        bm.close()
        assert red > 30, f"trang {i + 1} chưa có dấu"
    log = os.path.join(os.environ["APPDATA"], "PdfKySo", "nhat_ky_dung_dau.csv")
    assert "Dấu công ty" in open(log, encoding="utf-8-sig").read()
    win.run("undo")
    assert not tab.doc.can_undo


def test_drop_from_library_starts_placement_at_point(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    v = win.current().view
    v.set_zoom(100)
    pump(qapp)
    r = v._rects[0]
    pos = QPointF(r.left() + 200, r.top() + 300)
    md = QMimeData()
    md.setData("application/x-pdfkyso-lib", win.library.items[0].id.encode())

    class Ev:
        def mimeData(self):
            return md

        def position(self):
            return pos

        def acceptProposedAction(self):
            pass
    v.canvas.dropEvent(Ev())
    pl = v.placement
    s = v.scale
    assert pl and pl.page == 0
    assert pl.rect.center().x() == pytest.approx(200 / s, abs=1)
    assert pl.rect.center().y() == pytest.approx(300 / s, abs=1)
    v.cancel_placement()


def test_seam_dialog_flow(win, qapp, samples, monkeypatch):
    from app import ui_library
    win.open_files([samples["text"]])
    pump(qapp)
    monkeypatch.setattr(ui_library.SeamDialog, "exec", lambda self: QDialog.Accepted)
    win.run("seam")
    tab = win.current()
    for i in range(tab.doc.page_count):
        bm = tab.doc.render(i, 0.5)
        w, h, st = bm.width, bm.height, bm.stride
        buf = bytes(bm.buffer)
        bm.close()
        red_x = [x for y in range(0, h, 2) for x in range(0, w, 2)
                 if buf[y * st + x * 3] > 150 and buf[y * st + x * 3 + 1] < 90]
        assert red_x and min(red_x) > w * 0.95 and max(red_x) >= w - 3   # mảnh dấu đỏ nằm sát mép phải


def test_locked_library_asks_password(qapp, monkeypatch, lib_path, samples):
    Library(lib_path).set_password("matkhau123")
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=lib_path)
    pump(qapp, 50)
    assert w.library.locked and w.lib_panel.list.count() == 0
    w.open_files([samples["text"]])
    answers = iter([("sai", True), ("matkhau123", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    w.lib_panel._toggle_lock()
    assert not w.library.locked and w.lib_panel.list.count() == 1
    w._init_library()
    w.lib_panel._lock_now()
    assert w.library.locked
    w.current().doc.modified = False
    w.close()


def test_import_dialog_adds_item(win, qapp, tmp_path, monkeypatch):
    from app import ui_library
    p = tmp_path / "chu_ky.jpg"
    p.write_bytes(stamp_jpeg(ink=(30, 50, 170)))
    monkeypatch.setattr(ui_library.ImportDialog, "exec", lambda self: QDialog.Accepted)
    win.lib_panel.import_image(str(p))
    assert win.lib_panel.list.count() == 2
    it = win.library.items[-1]
    assert it.name == "chu_ky" and it.kind == "signature" and it.width_mm == 45


def test_import_dialog_live_preview(qapp, tmp_path):
    from app.ui_library import ImportDialog
    p = tmp_path / "dau.jpg"
    p.write_bytes(stamp_jpeg())
    dlg = ImportDialog(None, str(p))
    first = dlg.png
    dlg.cmb_ink.setCurrentIndex(2)
    dlg._process()
    assert dlg.png != first and dlg.lbl_out.pixmap() is not None
    dlg.cb_remove.setChecked(False)
    dlg._process()
    assert not dlg.sl_thr.isEnabled()
    dlg.close()


def test_recovery_prompt_on_start(qapp, monkeypatch, lib_path, samples, tmp_path):
    from app.document import PdfDocument
    rec_dir = tmp_path / "rec"
    rec_dir.mkdir()
    d = PdfDocument(samples["text"])
    d.rotate_pages([0])
    (rec_dir / "abc.pdf").write_bytes(d.to_bytes())
    (rec_dir / "abc.json").write_text('{"path": null, "title": "Bao gia.pdf", "time": 1}', encoding="utf-8")
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = MainWindow(library_path=lib_path)
    w.enable_recovery(str(rec_dir))
    assert w.tabs.count() == 1 and "Khôi phục" in w.tabs.tabText(0)
    assert w.current().doc.page_info(0).landscape
    assert not os.listdir(rec_dir)
    w.recovery.autosave()                              # tài liệu khôi phục chưa lưu -> được tự lưu lại
    assert len(os.listdir(rec_dir)) == 2
    w.current().doc.modified = False
    w.close_tab(0)
    assert not os.listdir(rec_dir)                     # đóng tab -> dọn bản khôi phục
    w.recovery.timer.stop()
    w.close()
