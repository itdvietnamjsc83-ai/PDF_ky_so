"""1.0.10: khay ghép – xem trước file (ảnh trang có số trang, cuộn, giữ/bỏ trang, xem lớn từng trang)."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QListView

from app.mainwindow import MainWindow
from app.tray_preview import PagePreviewDialog

from .test_gui import _Settings, pump
from .test_gui_phase2 import files


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow()
    w.show()
    t = w.show_tray()
    t.quiet = True
    yield t
    t.close()
    w.close()


def test_click_file_shows_preview_with_page_numbers(tray, qapp, tmp_path):
    a, b = files(tmp_path, [6, 3])
    tray.add_paths([a, b])
    assert tray.preview.isVisible() and "Bấm một file" in tray.preview.info.text()
    tray.table.selectRow(1)
    pump(qapp, 400)
    p = tray.preview
    assert p.item is tray.items[1] and p.picker.count() == 3
    assert p.picker.viewMode() == QListView.IconMode and p.picker.isWrapping()      # lưới cuộn dọc
    # file 1 có 6 trang, in 2 mặt -> file 2 bắt đầu ở trang 7 của file ghép
    assert p.picker.item(0).text() == "Trang 1 → 7" and p.picker.item(2).text() == "Trang 3 → 9"
    assert "3 trang · giữ 3 · bỏ 0" in p.info.text()
    assert len(p._cache) == 3                       # đã vẽ ảnh trang


def test_keep_drop_pages_updates_tray(tray, qapp, tmp_path):
    (a,) = files(tmp_path, [6])
    tray.add_paths([a])
    tray.table.selectRow(0)
    pump(qapp, 300)
    p = tray.preview
    p.picker.item(1).setCheckState(Qt.Unchecked)
    p.picker.item(4).setCheckState(Qt.Unchecked)
    it = tray.items[0]
    assert not it.whole and it.ranges == "1, 3-4, 6"
    assert p.picker.item(1).text() == "Trang 2 · bỏ" and p.picker.item(2).text() == "Trang 3 → 2"
    assert "giữ 4 · bỏ 2" in p.info.text()
    assert "4 trang" in tray.lbl_total.text()
    p.quick("invert")
    assert it.ranges == "2, 5"
    p.picker.clearSelection()
    for i in (0, 1):
        p.picker.item(i).setSelected(True)
    p.toggle_selected()                             # trang 1 đang bỏ -> giữ cả 2 trang đang chọn
    assert it.ranges == "1-2, 5"
    p.quick("all")
    assert it.whole
    p.quick("")
    assert it.ranges == "" and it.pages() == [] and "Không có trang" in tray.table.item(0, 6).text()


def test_size_slider_and_scroll(tray, qapp, tmp_path):
    (a,) = files(tmp_path, [30])
    tray.add_paths([a])
    tray.table.selectRow(0)
    pump(qapp, 800)
    p = tray.preview
    p.size_slider.setValue(250)
    assert p.picker.iconSize().width() == 250
    sb = p.picker.verticalScrollBar()
    assert sb.maximum() > 0                          # 30 trang: cuộn được
    sb.setValue(sb.maximum())
    assert sb.value() == sb.maximum()


def test_large_view_navigation_and_keep(tray, qapp, tmp_path):
    (a,) = files(tmp_path, [4])
    tray.add_paths([a])
    tray.table.selectRow(0)
    pump(qapp, 300)
    p = tray.preview
    d = PagePreviewDialog(tray, tray.items[0], 1, p)
    d.show()
    pump(qapp, 100)
    assert "Trang 2 / 4" in d.lbl_page.text() and d.chk_keep.isChecked()
    d.chk_keep.setChecked(False)                     # bỏ trang ngay trong cửa sổ xem lớn -> đồng bộ khay
    assert tray.items[0].ranges == "1, 3-4" and "BỎ" in d.lbl_page.text()
    d.go(2)
    assert "Trang 3 / 4" in d.lbl_page.text() and d.chk_keep.isChecked()
    d.btn_next.click()
    assert "Trang 4 / 4" in d.lbl_page.text() and not d.btn_next.isEnabled()
    d.btn_zin.click()
    assert d.zoom > 0
    d.btn_fit.click()
    assert d.zoom == 0
    # cuộn chuột ở cuối trang -> sang trang kế; ở đầu trang -> trang trước
    d.go(0)
    vp = d.scroll.viewport()
    ev = QWheelEvent(QPointF(10, 10), QPointF(vp.mapToGlobal(QPoint(10, 10))), QPoint(0, 0), QPoint(0, -120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    d.scroll.verticalScrollBar().setValue(d.scroll.verticalScrollBar().maximum())
    d.eventFilter(vp, ev)
    assert d.page == 1
    d.reject()


def test_double_click_opens_large_view(tray, qapp, tmp_path, monkeypatch):
    (a,) = files(tmp_path, [3])
    tray.add_paths([a])
    tray.table.selectRow(0)
    pump(qapp, 200)
    seen = []
    monkeypatch.setattr(PagePreviewDialog, "exec", lambda self: seen.append(self.page) or 0)
    tray.preview.picker.itemDoubleClicked.emit(tray.preview.picker.item(2))
    assert seen == [2]


def test_remove_file_clears_preview(tray, qapp, tmp_path):
    (a,) = files(tmp_path, [2])
    tray.add_paths([a])
    tray.table.selectRow(0)
    pump(qapp, 200)
    tray.remove_selected()
    assert tray.preview.item is None and tray.preview.picker.count() == 0
