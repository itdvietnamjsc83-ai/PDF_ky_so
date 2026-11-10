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
    assert p.picker.item(0).text() == "Trang 1\nlà trang 7 của file ghép" and p.picker.item(2).text().endswith("trang 9 của file ghép")
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
    assert p.picker.item(1).text().startswith("Trang 2\n(bỏ") and p.picker.item(2).text() == "Trang 3\nlà trang 2 của file ghép"
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


def test_duplicate_file_for_reuse_in_several_parts(tray, qapp, tmp_path):
    """1 file dùng ở nhiều đoạn: nhân bản dòng, mỗi bản chọn trang riêng, xen file khác ở giữa."""
    from app.merge import merge
    a, b = files(tmp_path, [6, 2])
    tray.add_paths([a, b])
    tray.table.selectRow(0)
    assert tray.duplicate_selected() == 1
    assert [it.path for it in tray.items] == [tray.items[0].path] * 2 + [tray.items[2].path]
    assert tray.items[0] is not tray.items[1]
    tray.items[0].whole, tray.items[0].ranges = False, "1-2"
    tray.items[1].whole, tray.items[1].ranges = False, "5-6"
    tray.move_rows([1], 3)                                          # bản sao xuống sau file b
    assert [it.ranges for it in tray.items if not it.whole] == ["1-2", "5-6"]
    tray.cb_duplex.setChecked(False)
    tray.refresh()
    assert "6 trang" in tray.lbl_total.text()                       # 2 + 2 + 2


def test_page_number_badge_on_thumbnails(tray, qapp, tmp_path):
    from PySide6.QtGui import QImage
    from app.tray_preview import page_badge
    img = QImage(120, 170, QImage.Format_ARGB32)
    img.fill(0xffffffff)
    out = page_badge(img, 12)
    assert out.pixelColor(8, 8).blue() > 150 and out.pixelColor(8, 8).red() < 60   # nhãn số trang góc trên-trái


def _show(tray, qapp, r):
    tray.table.selectRow(r)
    pump(qapp, 200)
    return tray.preview


def test_cut_segment_at_page_and_undo_redo(tray, qapp, tmp_path):
    a, b = files(tmp_path, [6, 2])
    tray.add_paths([a, b])
    p = _show(tray, qapp, 0)
    p.picker.setCurrentRow(3)
    p.picker.item(3).setSelected(True)
    p.btn_cut.click()                                               # (1) cắt tại trang 4
    assert [(it.name, it.ranges) for it in tray.items[:2]] == [(tray.items[0].name, "1-3"), (tray.items[0].name, "4-6")]
    assert len(tray.items) == 3 and tray._picker_row == 1
    assert tray.undo() and len(tray.items) == 2 and tray.items[0].whole     # (9) Ctrl+Z
    assert tray.redo() and len(tray.items) == 3 and tray.items[1].ranges == "4-6"
    tray.move_rows([1], 3)
    tray._persist()
    assert tray.undo() and tray.items[1].ranges == "4-6"


def test_live_range_typing_updates_preview_and_flags_errors(tray, qapp, tmp_path):
    (a,) = files(tmp_path, [6])
    tray.add_paths([a])
    tray._set(tray.items[0], whole=False)
    p = _show(tray, qapp, 0)
    ed = tray.table.cellWidget(0, 5)
    ed.setText("1-2, 5")
    ed.textEdited.emit("1-2, 5")                                    # (3) đang gõ: ảnh tích theo ngay
    assert p.kept() == [0, 1, 4] and "border" not in ed.styleSheet()
    ed.setText("1-9")
    ed.textEdited.emit("1-9")
    assert "e53935" in ed.styleSheet() and "chưa đúng" in tray.lbl_total.text()


def test_page_edits_rotate_blank_paper_go_into_merge(tray, qapp, tmp_path):
    from app.merge import merge
    (a,) = files(tmp_path, [3])
    tray.add_paths([a])
    tray.cb_duplex.setChecked(False)
    tray.cb_rotate.setChecked(False)
    p = _show(tray, qapp, 0)
    p.rotate_selected(90, [0])                                      # (5) xoay, chèn trang trắng, đổi khổ
    p.add_blank_selected(1, [1])
    p.set_paper_selected("A3", [2])
    it = tray.items[0]
    assert it.page_rot == {"0": 90} and it.page_blank == {"1": 1} and it.page_paper == {"2": "A3"}
    assert "xoay 90°" in p.picker.item(0).text() and "+1 trắng" in p.picker.item(1).text()
    assert "4 trang" in tray.lbl_total.text() and tray.table.item(0, 6).text() == "1 – 4"
    d = merge(tray.items, tray.opts)
    assert d.page_count == 4
    assert d.page(0).get_rotation() == 90
    assert d.text(2).strip() == ""                                  # trang trắng sau trang 2
    w, h = d.page_size_pt(3)
    assert abs(max(w, h) - 1190.55) < 3                             # A3
    assert tray.undo() and tray.items[0].page_paper == {}


def test_file_colors_and_merge_warnings(tray, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.merge import check_plan
    a, b = files(tmp_path, [4, 2])
    tray.add_paths([a, b])
    tray.table.selectRow(0)
    tray.duplicate_selected()
    c = [tray.file_color(it) for it in tray.items]
    assert c[0] == c[1] != c[2]                                     # (7) cùng file cùng màu
    assert tray.table.item(0, 1).background().color().name() == c[0]
    p = _show(tray, qapp, 0)
    assert p.file_tint == c[0]
    tray.items[0].whole, tray.items[0].ranges = False, "1-3"
    tray.items[1].whole, tray.items[1].ranges = False, "3-4"
    w = check_plan(tray.items, tray.opts)                           # (8) trang 3 dùng 2 lần
    assert any("lặp lại" in x and "trang 3" in x for x in w)
    asked = []
    tray.quiet = False
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    assert tray.do_merge(False) is None and asked and "lặp lại" in asked[0]
    tray.quiet = True
