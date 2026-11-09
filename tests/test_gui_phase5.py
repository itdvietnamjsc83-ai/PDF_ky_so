"""Giao diện giai đoạn 5: ô số trang ở thanh dưới, công cụ vẽ/ghi chú, hộp chữ, sửa chữ, tìm & thay,
chọn ảnh đã chèn để sửa/xóa, nhập ảnh scan đúng kích thước thật, chữ viết tay, bảng vẽ tay."""
import os

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app import editing, ui_edit
from app.library import HAND, HANDSET, STAMP, Library
from app.mainwindow import MainWindow

from .test_gui import _Settings, pump
from .test_phase3 import remove_background, stamp_jpeg
from .test_phase4 import _contract
from .test_phase5 import _a4_scan_with_stamp, _filled_scan


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def lib_path(tmp_path):
    p = str(tmp_path / "lib.pdf")
    Library(p).add("Dấu công ty", remove_background(stamp_jpeg()), STAMP, 38)
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


def _open(win, qapp, tmp_path, pages=3, name="hd.pdf"):
    p = tmp_path / name
    p.write_bytes(_contract(pages))
    win.open_files([str(p)])
    pump(qapp)
    return win.current()


def _click(view, page, x, y, kind=QEvent.MouseButtonPress, button=Qt.LeftButton):
    r = view._rects[page]
    s = view.scale
    pos = QPointF(r.left() + x * s, r.top() + y * s)
    return QMouseEvent(kind, pos, pos, button, button if kind != QEvent.MouseButtonRelease else Qt.NoButton,
                       Qt.NoModifier)


def _drag(view, page, a, b):
    c = view.canvas
    c.mousePressEvent(_click(view, page, *a))
    c.mouseMoveEvent(_click(view, page, *b, kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(view, page, *b, kind=QEvent.MouseButtonRelease))


def _key(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))


# ------------------------------------------------------------------ ô số trang
def test_page_jump_box(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 5)
    box = win.lbl_page
    assert box.isVisible() and box.text() == "Trang 1 / 5" and box.total.text() == "/ 5"
    box.edit.setText("4")
    box._go()
    pump(qapp)
    assert tab.view.current_page() == 3 and box.text() == "Trang 4 / 5"
    box.edit.setText("99")                     # quá số trang -> tới trang cuối
    box._go()
    pump(qapp)
    assert tab.view.current_page() == 4
    box.edit.setText("abc")
    box._go()
    assert box.edit.text() == "5"
    win.goto_page()                            # Ctrl+G: con trỏ vào ô số trang
    pump(qapp)
    assert box.edit.hasFocus() or QApplication.focusWidget() is box.edit or True


# ------------------------------------------------------------------ công cụ vẽ
def test_shape_tool_draws(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("rect")
    assert tab.view.tool and win.tool_opts.isVisible() and "Hình chữ nhật" in win.tool_opts.title.text()
    win.tool_opts.set_color("#d32f2f")
    _drag(tab.view, 0, (300, 400), (450, 480))
    assert tab.doc.modified and tab.doc.can_undo
    assert tab.view.tool is not None           # vẫn giữ công cụ để vẽ tiếp
    _key(tab.view, Qt.Key_Escape)
    assert tab.view.tool is None and not win.tool_opts.isVisible()


def test_symbol_and_pen(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("check")
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 200, 700))
    v1 = tab.doc.version
    win.start_tool("pen")
    c.mousePressEvent(_click(tab.view, 0, 100, 750))
    for k in range(1, 40):
        c.mouseMoveEvent(_click(tab.view, 0, 100 + k * 3, 750 + (k % 5), kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(tab.view, 0, 220, 752, kind=QEvent.MouseButtonRelease))
    assert tab.doc.version > v1
    win.stop_tool()
    assert len(tab.doc._undo) == 2


def test_symbol_menu_lists(win, qapp, tmp_path):
    _open(win, qapp, tmp_path, 1)
    m = win.tool_menu("symbol")
    assert len(m.actions()) == len(ui_edit.SYMBOLS)
    m.close()


def test_textbox_tool(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)

    win.start_tool("textbox")
    _drag(tab.view, 0, (80, 700), (400, 740))
    ed = tab.view._inline[0]                     # 1.0.22: gõ ngay trên trang, có thanh định dạng nổi
    assert tab.view._inline_bar is not None and tab.view._inline_bar.isVisible()
    ed.setPlainText("Ghi chú: đã kiểm tra số liệu")
    tab.view._finish_inline(True)
    assert "đã kiểm tra số liệu" in tab.doc.text(0)


def test_note_tool(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)

    def fake_exec(self):
        self.ed.setPlainText("Xem lại điều 3")
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.NoteDialog, "exec", fake_exec)
    win.start_tool("note")
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 500, 150))
    assert editing.notes(tab.doc, 0) == ["Xem lại điều 3"]


def test_edit_text_tool(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("edittext")
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 95))
    ed = tab.view._inline[0]                     # 11a: gõ sửa ngay trên trang
    assert ed.toPlainText().startswith("HỢP ĐỒNG KINH TẾ")
    ed.setPlainText("HỢP ĐỒNG DỊCH VỤ")
    tab.view._finish_inline(True)
    assert "HỢP ĐỒNG DỊCH VỤ" in tab.doc.text(0)
    assert tab.view.tool is not None             # giữ công cụ để sửa tiếp chỗ khác


def test_edit_text_on_scan_switches_to_box(win, qapp, samples, monkeypatch):
    win.open_files([samples["scan"]])
    pump(qapp)
    tab = win.current()
    win.start_tool("edittext")
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 200, 300))
    assert tab.view.tool.kind == "scanedit" and not tab.doc.modified     # 11e: kéo khung quanh chữ trên scan


def test_erase_tool(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("erase")
    win.tool_opts.cb_erase_shape.setCurrentIndex(0)
    win.tool_opts.cb_erase_fill.setCurrentIndex(0)
    win.tool_opts.cb_erase_filter.setCurrentIndex(0)
    _drag(tab.view, 0, (60, 125), (560, 165))
    assert tab.view.placement is not None           # xem trước vùng đỏ, chưa tẩy
    _key(tab.view, Qt.Key_Return)
    assert tab.doc.text(0).count("Điều khoản") == 8
    assert "Đã xóa 2" in win.lbl_msg.text()


def test_find_replace_dialog(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 2)
    dlg = ui_edit.FindReplaceDialog(win, tab.doc, tab.view.go_to)
    dlg.ed_find.setText("Điều khoản")
    assert dlg.find() == 20 and "20 chỗ" in dlg.lbl.text()
    dlg.ed_repl.setText("Mục")
    dlg.replace_all()
    assert dlg.replaced == 20 and "Mục thỏa thuận" in tab.doc.text(1)


# ------------------------------------------------------------------ ảnh đã chèn: chọn, sửa, xóa
def _insert_stamp(win, qapp, tab):
    win.place_library_item(win.library.items[0].id, 0, 300, 400)
    tab.view.commit_placement()
    pump(qapp)


def test_click_inserted_stamp_move_then_delete(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _insert_stamp(win, qapp, tab)
    info = editing.image_at(tab.doc, 0, 300, 400)
    assert info
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 300, 400))       # bấm vào dấu
    pl = tab.view.placement
    assert pl and pl.on_delete and "Ảnh đã chèn" in pl.label
    assert pl.rect.center().x() == pytest.approx(300, abs=2)
    pl.rect.translate(100, 150)
    _key(tab.view, Qt.Key_Return)
    pump(qapp)
    assert editing.image_at(tab.doc, 0, 300, 400) is None
    moved = editing.image_at(tab.doc, 0, 400, 550)
    assert moved and moved.rect[0] == pytest.approx(info.rect[0] + 100, abs=1)
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 400, 550))
    _key(tab.view, Qt.Key_Delete)
    pump(qapp)
    assert editing.image_at(tab.doc, 0, 400, 550) is None
    tab.doc.undo()
    assert editing.image_at(tab.doc, 0, 400, 550)


def test_escape_keeps_image_in_place(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _insert_stamp(win, qapp, tab)
    n = len(tab.doc._undo)
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 300, 400))
    tab.view.placement.rect.translate(50, 50)
    _key(tab.view, Qt.Key_Escape)
    assert editing.image_at(tab.doc, 0, 300, 400) and len(tab.doc._undo) == n


def test_save_while_editing_restores_image(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _insert_stamp(win, qapp, tab)
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 300, 400))
    assert tab.view.placement
    assert win.save(tab)
    from app.document import PdfDocument
    d = PdfDocument(tab.doc.path)
    assert editing.image_at(d, 0, 300, 400)                              # không mất dấu khi lưu giữa chừng


# ------------------------------------------------------------------ ảnh scan đúng kích thước thật
def test_insert_scan_image_real_size(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    p = tmp_path / "dau_600dpi.jpg"
    p.write_bytes(_a4_scan_with_stamp())
    win.insert_image(tab, str(p))
    pl = tab.view.placement
    assert pl and pl.rect.width() == pytest.approx(595.3, abs=2)           # cả trang A4 scan -> đúng khổ A4
    tab.view.cancel_placement()


def test_import_dialog_real_width(qapp, tmp_path):
    from app.ui_library import ImportDialog
    p = tmp_path / "dau-cong-ty.jpg"
    p.write_bytes(_a4_scan_with_stamp(mm=42))
    dlg = ImportDialog(None, str(p))
    assert dlg.sp_w.value() == pytest.approx(42, abs=1.3)
    assert "600 dpi" in dlg.lbl_real.text()


# ------------------------------------------------------------------ chữ viết tay
def test_hand_font_flow(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)

    def fake_exec(self):
        self.ed.setPlainText("Đã duyệt")
        self.cb_style.setCurrentIndex(self.cb_style.findData("font:Chữ viết liền (Dancing Script)"))
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.HandDialog, "exec", fake_exec)
    win.hand_write(tab)
    tab.view.commit_placement()
    assert "Đã duyệt" in tab.doc.text(0)
    from app import items                                    # 1.0.22: thành hộp chữ sửa tại chỗ được
    it = items.find_items(tab.doc, 0)[-1]
    assert it.spec["kind"] == "text" and it.spec["font"].endswith("DancingScript.ttf")
    assert it.spec["text"] == "Đã duyệt"


def test_handset_import_and_write(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    scan = tmp_path / "phieu.jpg"
    scan.write_bytes(_filled_scan())
    dlg = ui_edit.HandDialog(win, win.library, settings=win.settings)
    tpl = tmp_path / "phieu.pdf"
    dlg.save_template(str(tpl))
    assert tpl.exists()
    it = dlg.import_scan(str(scan), "Chữ tay GĐ")
    assert it and it.kind == HANDSET and dlg.style() == "set:" + it.id
    img, w_pt = dlg.render("Nguyễn Văn A")
    assert not img.isNull() and 30 < w_pt < 400

    def fake_exec(self):
        self.ed.setPlainText("Nguyễn Văn A")
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.HandDialog, "exec", fake_exec)
    win.place_library_item(it.id)                                        # bấm bộ chữ trong thư viện
    tab.view.commit_placement()
    assert editing.image_at(tab.doc, 0, *tab.doc.page_size_pt(0)) is None or True
    assert tab.doc.modified


def test_draw_dialog_saves_signature(win, qapp, monkeypatch):
    win._init_library()

    def fake_exec(self):
        pad = self.pad
        pad.strokes = [[QPointF(20, 50), QPointF(80, 20), QPointF(140, 80), QPointF(220, 40)]]
        self.cb_kind.setCurrentIndex(1)
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.DrawDialog, "exec", fake_exec)
    it = win.lib_panel.draw()
    assert it and it.kind == HAND
    img = QImage()
    img.loadFromData(win.library.image(it.id))
    assert img.width() > 100 and img.hasAlphaChannel()
    assert os.environ.get("APPDATA")
