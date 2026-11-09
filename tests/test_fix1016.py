"""1.0.16 – sửa lỗi khách báo:
1) Đang gõ sửa chữ (nháy đúp hộp chữ / công cụ Sửa chữ) mà bấm vào bảng bên phải (cỡ, đậm, màu...) thì ô sửa
   biến mất, không đổi được gì.
2) Tẩy: vùng đỏ hiện trên trang nhưng không tẩy / không lưu (bấm ra ngoài, lưu, đổi công cụ = bỏ)."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest

from app import editing, items
from app.document import PdfDocument

from .test_gui import pump
from .test_gui_phase5 import _click, _drag, _key, _open, lib_path, qapp, win  # noqa: F401


def _stroke(view, page, pts):
    c = view.canvas
    c.mousePressEvent(_click(view, page, *pts[0]))
    for p in pts[1:]:
        c.mouseMoveEvent(_click(view, page, *p, kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(view, page, *pts[-1], kind=QEvent.MouseButtonRelease))


def _textbox(win, qapp, tab):
    items.add_item(tab.doc, 0, items.text_spec(100, 100, 200, "Xin chào", None, 12, "#000000"))
    tab.refresh()
    pump(qapp)
    win._select_item(tab, 0, items.find_items(tab.doc, 0)[0])
    pump(qapp)


def test_textbox_panel_while_inline_editing(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _textbox(win, qapp, tab)
    o = win.tool_opts
    QTest.mouseClick(o.sp_size, Qt.LeftButton)            # đang chọn (chưa gõ): bảng vẫn dùng được
    pump(qapp)
    assert o.isVisible() and tab.view.placement is not None
    win._inline_edit_selected()                           # nháy đúp: gõ sửa ngay trên trang
    pump(qapp)
    assert tab.view._inline is not None
    o.sp_size.setFocus()                                  # bấm sang ô cỡ chữ: ô sửa KHÔNG được đóng
    pump(qapp)
    pump(qapp)
    assert tab.view._inline is not None and o.isVisible()
    o.sp_size.setValue(24)
    o.sl_opacity.setValue(60)
    pump(qapp)
    ed = tab.view._inline[0]
    assert ed._style["size"] == 24 and ed.font().pixelSize() == round(24 * tab.view.scale)
    ed.setPlainText("Xin chào bạn")
    tab.view._finish_inline(True)
    pump(qapp)
    sp = items.find_items(tab.doc, 0)[0].spec
    assert sp["text"] == "Xin chào bạn" and sp["size"] == 24 and sp["opacity"] == 60
    assert not o.isVisible()


def test_inline_closes_when_focus_leaves_panel(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _textbox(win, qapp, tab)
    win._inline_edit_selected()
    pump(qapp)
    win.search.setFocus()
    pump(qapp)
    pump(qapp)
    assert tab.view._inline is None                      # bấm hẳn ra chỗ khác: xong như trước


def test_edittext_panel_bold_size(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    run = editing.text_runs(tab.doc, 0)[0]
    win.start_tool("edittext")
    pump(qapp)
    win._edit_text(tab, 0, (run.rect[0] + run.rect[2]) / 2, (run.rect[1] + run.rect[3]) / 2)
    pump(qapp)
    o = win.tool_opts
    o.sp_size.setFocus()
    pump(qapp)
    pump(qapp)
    assert tab.view._inline is not None
    o.sp_size.setValue(18)
    o.btn_bold.setChecked(True)
    pump(qapp)
    ed = tab.view._inline[0]
    assert ed.font().bold() and ed._style["size"] == 18
    assert ed._style["color"] != "#d32f2f"               # đổi cỡ / đậm không được tô đỏ chữ
    old_text = ed.toPlainText()
    tab.view._finish_inline(True)                         # chữ giữ nguyên, chỉ đổi kiểu -> vẫn áp dụng
    pump(qapp)
    assert "Đã sửa chữ" in win.lbl_msg.text()
    assert any(r.bold for r in editing.text_runs(tab.doc, 0) if r.text.strip() and r.text.strip() in old_text)
    win.stop_tool()


def test_brush_eraser_applies_immediately_and_removes_strokes(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("pen:ball")
    pump(qapp)
    _stroke(tab.view, 0, [(100 + k * 5, 400) for k in range(30)])
    pump(qapp)
    win.start_tool("erase")
    o = win.tool_opts
    o.cb_erase_shape.setCurrentIndex(o.cb_erase_shape.findData("brush"))
    o.chk_erase_preview.setChecked(True)
    pump(qapp)
    _stroke(tab.view, 0, [(150, 380), (150, 400), (150, 420)])
    pump(qapp)
    assert tab.view.placement is None                    # không chờ Enter
    assert items.find_items(tab.doc, 0) == []
    out = tmp_path / "o.pdf"
    tab.doc.save(str(out))
    assert items.find_items(PdfDocument(str(out)), 0) == []
    tab.doc.undo()
    assert len(items.find_items(tab.doc, 0)) == 1        # 1 bước hoàn tác
    o.cb_erase_shape.setCurrentIndex(0)
    win.stop_tool()


def test_erase_preview_commits_on_outside_click_and_save(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("erase")
    o = win.tool_opts
    o.cb_erase_shape.setCurrentIndex(o.cb_erase_shape.findData("rect"))
    o.cb_erase_fill.setCurrentIndex(o.cb_erase_fill.findData("white"))
    o.chk_erase_preview.setChecked(True)
    n = tab.doc.text(0).count("Điều khoản")
    _drag(tab.view, 0, (60, 125), (560, 165))
    assert tab.view.placement is not None
    c = tab.view.canvas                                   # bấm ra chỗ khác trên trang -> tẩy luôn
    c.mousePressEvent(_click(tab.view, 0, 300, 700))
    c.mouseReleaseEvent(_click(tab.view, 0, 300, 700, kind=QEvent.MouseButtonRelease))
    pump(qapp)
    assert tab.doc.text(0).count("Điều khoản") == n - 2
    tab.doc.undo()
    _drag(tab.view, 0, (60, 125), (560, 165))             # còn khung đỏ mà bấm Lưu -> tẩy rồi lưu
    assert tab.view.placement is not None
    monkeypatch.setattr(win, "license_ok", lambda: True)
    assert win.save()
    assert PdfDocument(tab.doc.path).text(0).count("Điều khoản") == n - 2
    win.stop_tool()
