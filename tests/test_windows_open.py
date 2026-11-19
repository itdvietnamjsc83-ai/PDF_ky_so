"""1.0.22 – nhớ vị trí cửa sổ; nhiều cửa sổ: hỏi mở file vào cửa sổ nào; mở file không làm cửa sổ đổi cỡ."""
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.mainwindow import MainWindow
from .test_gui import _Settings, pump
from .test_phase4 import _contract


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def st(monkeypatch):
    s = _Settings()
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: s)
    return s


def _pdf(tmp_path, name, n=2):
    p = tmp_path / name
    p.write_bytes(_contract(n))
    return str(p)


def test_geometry_remembered(qapp, st, tmp_path):
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    assert not w.restore_window_state()                    # lần đầu: vừa màn hình
    w.show()
    w.resize(720, 500)
    w.move(30, 20)
    pump(qapp, 30)
    w.close()
    assert st.value("ui/geometry")
    w2 = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    assert w2.restore_window_state()
    assert w2.width() == 720 and w2.height() == 500
    w2.close()


def test_open_file_does_not_resize(qapp, st, tmp_path):
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(700, 600)
    w.show()
    pump(qapp, 30)
    w.receive_external([_pdf(tmp_path, "hop_dong_ten_rat_dai_de_thu_cua_so_co_bi_gian_ra_khong.pdf", 40)])
    pump(qapp, 50)
    assert w.width() == 700 and w.tabs.count() == 1
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def test_choose_window_when_two_open(qapp, st, tmp_path, monkeypatch):
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.show()
    w2 = w.open_in_new_window([_pdf(tmp_path, "a.pdf")])
    pump(qapp, 30)
    assert w2 is not None and w2.tabs.count() == 1
    picked = {}

    def ask(self, dlg):
        from PySide6.QtWidgets import QListWidget
        lst = dlg.findChild(QListWidget)
        picked["n"] = lst.count()
        lst.setCurrentRow(1)                                   # chọn cửa sổ thứ 2
        return QDialog.Accepted
    monkeypatch.setattr(MainWindow, "_ask_window_dialog", ask)
    w.receive_external([_pdf(tmp_path, "b.pdf")])
    pump(qapp, 30)
    assert picked["n"] == 3                                    # 2 cửa sổ + "cửa sổ mới"
    assert w2.tabs.count() == 2 and w.tabs.count() == 0
    for x in (w2, w):
        for i in range(x.tabs.count()):
            x.tabs.widget(i).doc.modified = False
        x.close()


def test_drag_tab_out_and_back(qapp, st, tmp_path):
    from PySide6.QtCore import QPoint
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(700, 500)
    w.move(0, 0)
    w.show()
    w.open_files([_pdf(tmp_path, "a.pdf"), _pdf(tmp_path, "b.pdf")])
    pump(qapp, 30)
    far = QPoint(w.frameGeometry().right() + 400, 300)        # thả ra ngoài cửa sổ -> tách cửa sổ mới
    w._tab_dropped(1, far)
    pump(qapp, 30)
    w2 = [x for x in w.all_windows() if x is not w][0]
    assert w.tabs.count() == 1 and w2.tabs.count() == 1 and w2.current().doc.name == "b.pdf"
    w2.move(800, 0)
    pump(qapp, 10)
    # kéo tab của cửa sổ phụ thả vào cửa sổ chính -> ghép cạnh tab đang có, cửa sổ phụ tự đóng
    w2._tab_dropped(0, w.frameGeometry().center())
    pump(qapp, 30)
    assert w.tabs.count() == 2 and len(w.all_windows()) == 1      # cửa sổ phụ đã tự đóng
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()
