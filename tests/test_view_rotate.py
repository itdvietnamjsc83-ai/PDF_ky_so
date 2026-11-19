"""1.0.22 – xoay nhanh khi xem: chỉ đổi cách hiển thị, không sửa file, không hỏi lưu khi đóng."""
import pytest
from PySide6.QtWidgets import QApplication

from app.mainwindow import MainWindow
from .test_gui import _Settings, pump
from .test_phase4 import _contract


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(1200, 860)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def test_view_rotation_does_not_modify(win, qapp, tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(_contract(3))
    win.open_files([str(p)])
    pump(qapp)
    tab = win.current()
    v = tab.view
    w0, h0 = v._rects[0].width(), v._rects[0].height()
    ver = tab.doc.version
    win.btn_vrotr.click()
    pump(qapp, 30)
    assert v.view_rot == 90
    assert v._rects[0].width() == pytest.approx(h0) and v._rects[0].height() == pytest.approx(w0)
    img = v.canvas.grab()                                  # vẽ được trang đã xoay
    assert not img.isNull()
    assert not tab.doc.modified and tab.doc.version == ver   # không đổi file -> đóng không hỏi lưu
    assert v.page_at(v._rects[0].center()) is None           # đang xoay: chỉ xem
    win.btn_vrotl.click()
    win.btn_vrotl.click()
    assert v.view_rot == 270
    v.set_zoom(400)                                          # zoom lớn: vẽ theo ô (tile) khi đang xoay
    pump(qapp, 30)
    assert not v.canvas.grab().isNull()
    win.run("textbox")                                       # chọn công cụ sửa -> về hướng gốc
    assert v.view_rot == 0 and v.page_at(v._rects[0].center()) is not None
    win.rotate_view(180)
    win.rotate_view(0)
    assert v.view_rot == 0 and not tab.doc.modified
