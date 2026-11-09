"""Đợt 2: ghi chú (sửa, trả lời, đã xử lý, danh sách, đọc ghi chú file ngoài), chọn lại nội dung đã thêm để
sửa tiếp (di chuyển, đổi cỡ, xoay, xóa, sửa chữ tại chỗ, bảng thuộc tính), thư viện hình, bút vẽ tay,
tẩy vùng nâng cao, chèn trang nâng cao."""
import io

import pikepdf
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QDialog

from app import editing, items, notes, ui_edit, ui_pages
from app.document import PdfDocument, blank_document

from .test_gui import pump
from .test_gui_phase5 import _click, _drag, _key, _open, lib_path, qapp, win  # noqa: F401
from .test_phase4 import _contract


def _blank(n=2, size=(595, 842)):
    return blank_document(n, size)


def _external_notes_pdf() -> bytes:
    """File có ghi chú tạo từ phần mềm khác (kiểu Acrobat): ghi chú dán + popup + trả lời /IRT, tô sáng, hộp chữ."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pg = pdf.pages[0]
    D, N, A, S = pikepdf.Dictionary, pikepdf.Name, pikepdf.Array, pikepdf.String

    def annot(**kw):
        return pdf.make_indirect(D(Type=N.Annot, **kw))
    t1 = annot(Subtype=N.Text, Rect=A([100, 700, 120, 720]), Contents=S("Ghi chú từ Acrobat: xem lại điều 5"),
               T=S("Nguyễn Văn A"), M=S("D:20260920101500+07'00'"), Name=N.Comment, C=A([1, 0.8, 0]), NM=S("acro-1"))
    pop = annot(Subtype=N.Popup, Rect=A([130, 600, 330, 700]), Parent=t1, Open=False)
    t1.Popup = pop
    rep = annot(Subtype=N.Text, Rect=A([100, 700, 120, 720]), Contents=S("Đã sửa rồi nhé"), T=S("Trần B"),
                IRT=t1, RT=N.R, NM=S("acro-2"))
    hl = annot(Subtype=N.Highlight, Rect=A([100, 500, 300, 515]),
               QuadPoints=A([100, 515, 300, 515, 100, 500, 300, 500]), Contents=S("Đoạn này cần kiểm tra"),
               T=S("Lê C"), C=A([1, 1, 0]))
    ft = annot(Subtype=N.FreeText, Rect=A([100, 400, 300, 430]), Contents=S("Hộp chữ ghi chú"), T=S("Lê C"),
               DA=S("/Helv 12 Tf 0 0 1 rg"))
    pg.Annots = pdf.make_indirect(A([t1, pop, rep, hl, ft]))
    b = io.BytesIO()
    pdf.save(b)
    return b.getvalue()


# ================================================================== ghi chú (12)
def test_notes_add_update_reply_persist():
    d = _blank()
    nm = notes.add_note(d, 0, 100, 100, "Xem lại điều 3", "An", "#e53935", "help", 60)
    notes.update_note(d, 0, nm, text="Xem lại điều 3 và 4", done=True, color="#43a047", icon="check")
    notes.add_note(d, 0, 100, 100, "Đã xem", "Bình", reply_to=nm)
    d2 = PdfDocument(data=d.to_bytes())
    lst = notes.list_notes(d2)
    assert len(lst) == 1
    n = lst[0]
    assert (n.text, n.author, n.color, n.icon, n.done) == ("Xem lại điều 3 và 4", "An", "#43a047", "check", True)
    assert n.opacity == 60 and n.date is not None
    assert [r.text for r in n.replies] == ["Đã xem"]
    with pikepdf.open(io.BytesIO(d2.to_bytes())) as pk:           # trả lời có /IRT chuẩn
        assert sum(1 for a in pk.pages[0].Annots if "/IRT" in a) == 1
    assert editing.notes(d2, 0) == ["Xem lại điều 3 và 4", "Đã xem"]  # hàm cũ vẫn đọc được


def test_notes_move_delete_and_hit():
    d = _blank()
    nm = notes.add_note(d, 0, 50, 50, "A", "An")
    notes.add_note(d, 0, 50, 50, "trả lời", "B", reply_to=nm)
    assert notes.note_at(d, 0, 55, 55).nm == nm
    notes.move_note(d, 0, nm, 300, 400)
    assert notes.note_at(d, 0, 55, 55) is None
    n = notes.note_at(d, 0, 305, 405)
    assert n and abs(n.rect[0] - 300) < 0.5 and len(n.replies) == 1
    assert notes.delete_note(d, 0, nm) == 2                         # xóa kèm trả lời
    assert notes.list_notes(d) == []


def test_notes_rotated_page_icon_upright():
    d = _blank(1)
    d.rotate_pages([0], 90)
    notes.add_note(d, 0, 40, 40, "trang xoay", "An")
    n = notes.list_notes(d)[0]
    assert abs(n.rect[0] - 40) < 0.6 and abs(n.rect[1] - 40) < 0.6
    assert abs((n.rect[2] - n.rect[0]) - 20) < 0.6


def test_read_external_notes():
    d = PdfDocument(data=_external_notes_pdf())
    lst = notes.list_notes(d)
    kinds = {n.kind_label: n for n in lst}
    assert set(kinds) == {"Ghi chú", "Tô sáng", "Hộp chữ"}
    acro = kinds["Ghi chú"]
    assert acro.author == "Nguyễn Văn A" and acro.date_text.startswith("20/09/2026")
    assert [r.text for r in acro.replies] == ["Đã sửa rồi nhé"]      # luồng trả lời /IRT của Acrobat
    assert notes.note_at(d, 0, 150, 334).text == "Đoạn này cần kiểm tra"
    # sửa lời bình của tô sáng: giữ nguyên hình tô sáng (không bị thay bằng biểu tượng)
    hl = kinds["Tô sáng"]
    notes.update_note(d, 0, hl.nm, text="Đã kiểm tra", done=True)
    d2 = PdfDocument(data=d.to_bytes())
    hl2 = [n for n in notes.list_notes(d2) if n.kind_label == "Tô sáng"][0]
    assert hl2.text == "Đã kiểm tra" and hl2.done
    with pikepdf.open(io.BytesIO(d2.to_bytes())) as pk:
        a = [x for x in pk.pages[0].Annots if x.get("/Subtype") == "/Highlight"][0]
        assert "/QuadPoints" in a


def test_note_icon_image():
    for ic, _ in notes.NOTE_ICONS:
        img = notes.icon_image(ic, "#1e88e5", True, 70)
        assert img.width > 30 and img.getbbox()


def test_gui_click_note_opens_dialog_and_edits(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    nm = notes.add_note(tab.doc, 0, 400, 300, "Ghi chú cũ", "An")
    tab.refresh()
    seen = {}

    def fake_exec(self):
        seen["text"] = self.ed.toPlainText()
        self.ed.setPlainText("Ghi chú đã sửa")
        self.chk_done.setChecked(True)
        self.ed_reply.setText("Tôi đã xem")
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.NoteDialog, "exec", fake_exec)
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 405, 305))
    assert tab.view.placement is not None                           # chọn ghi chú (kéo được)
    c.mouseReleaseEvent(_click(tab.view, 0, 405, 305, kind=QEvent.MouseButtonRelease))
    assert seen["text"] == "Ghi chú cũ"                              # bấm (không kéo) -> mở ra đọc
    n = notes.list_notes(tab.doc)[0]
    assert n.text == "Ghi chú đã sửa" and n.done and [r.text for r in n.replies] == ["Tôi đã xem"]
    assert tab.view.placement is None


def test_gui_drag_note_moves(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    notes.add_note(tab.doc, 0, 400, 300, "Dời tôi", "An")
    tab.refresh()
    monkeypatch.setattr(ui_edit.NoteDialog, "exec", lambda self: QDialog.Rejected)
    _drag(tab.view, 0, (405, 305), (205, 505))
    assert tab.view.placement is not None
    _key(tab.view, Qt.Key_Return)
    n = notes.list_notes(tab.doc)[0]
    assert abs(n.rect[0] - 200) < 1.5 and abs(n.rect[1] - 500) < 1.5


def test_gui_protected_file_notes_readable(win, qapp, tmp_path, monkeypatch):
    """File bị khóa sửa vẫn bấm vào đọc được ghi chú (chỉ đọc)."""
    d = PdfDocument(data=_external_notes_pdf())
    src = tmp_path / "ext.pdf"
    src.write_bytes(d.to_bytes())
    with pikepdf.open(str(src)) as pk:
        pk.save(str(tmp_path / "locked.pdf"), encryption=pikepdf.Encryption(
            owner="chu", user="", allow=pikepdf.Permissions(modify_other=False, modify_annotation=False)))
    win.open_files([str(tmp_path / "locked.pdf")])
    pump(qapp)
    tab = win.current()
    assert not tab.doc.can_modify
    seen = {}

    def fake_exec(self):
        seen["text"], seen["ro"] = self.ed.toPlainText(), self.ed.isReadOnly()
        return QDialog.Rejected
    monkeypatch.setattr(ui_edit.NoteDialog, "exec", fake_exec)
    win.page_pressed(0, 110, 130)
    assert seen == {"text": "Ghi chú từ Acrobat: xem lại điều 5", "ro": True}


def test_notes_panel_filters_and_actions(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 3)
    a = notes.add_note(tab.doc, 0, 100, 100, "Trang 1", "An")
    notes.add_note(tab.doc, 2, 100, 100, "Trang 3", "Bình")
    tab.refresh()
    win.run("notes")
    p = win.notes_panel
    assert p.isVisible() and p.tree.topLevelItemCount() == 2
    p.cb_author.setCurrentIndex(p.cb_author.findData("Bình"))
    assert p.tree.topLevelItemCount() == 1
    p.cb_author.setCurrentIndex(0)
    p.tree.setCurrentItem(p.tree.topLevelItem(1))
    p.btn_done.click()
    assert notes.list_notes(tab.doc, [2])[0].done
    p.chk_hide_done.setChecked(True)
    assert p.tree.topLevelItemCount() == 1
    p.chk_hide_done.setChecked(False)
    win._note_goto(2, notes.list_notes(tab.doc, [2])[0].nm)
    pump(qapp)
    assert tab.view.current_page() == 2

    def fake_exec(self):
        self.ed.setPlainText("Trả lời từ bảng")
        return QDialog.Accepted
    monkeypatch.setattr(ui_edit.NoteDialog, "exec", fake_exec)
    win._note_reply(0, a)
    assert [r.text for r in notes.list_notes(tab.doc, [0])[0].replies] == ["Trả lời từ bảng"]
    win._note_delete(0, a)
    assert notes.list_notes(tab.doc, [0]) == []
    assert "1 / 1" in p.lbl.text() or p.tree.topLevelItemCount() == 1


# ================================================================== nội dung đã thêm (13, 14, 15)
def test_items_persist_find_update_delete():
    d = _blank(1)
    s = items.add_item(d, 0, items.shape_spec("star5", (100, 100, 200, 180), {"stroke": "#1565c0", "width": 2,
                                                                                 "fill": "#90caf9", "shadow": True}))
    t = items.add_item(d, 0, items.text_spec(100, 300, 200, "Xin chào Việt Nam", None, 14, "#c62828"))
    d2 = PdfDocument(data=d.to_bytes())
    found = items.find_items(d2, 0)
    assert [f.id for f in found] == [s["id"], t["id"]]
    assert items.item_at(d2, 0, 150, 140).id == s["id"]
    assert items.item_at(d2, 0, 150, 305).kind == "text"
    new = dict(found[1].spec, rect=[300, 500, 500, 520], angle=30)
    items.update_item(d2, 0, new)
    assert "Xin chào Việt Nam" in d2.text(0)
    it = items.get_item(d2, 0, t["id"])
    assert it.spec["angle"] == 30 and it.rect[0] > 280
    items.delete_item(d2, 0, s["id"])
    assert [f.id for f in items.find_items(d2, 0)] == [t["id"]]


def test_all_gallery_shapes_build():
    d = _blank(1)
    st = {"stroke": "#333333", "width": 1.5, "fill": "#ffcc80", "dash": "dash", "radius": 4}
    n = 0
    for _, lst in items.SHAPE_GROUPS:
        for k, _lbl in lst:
            if k == "freeform":
                continue
            if k in items.LINE_SHAPES or k == "polygon":
                spec = items.line_spec(k, None, None, st, [(50, 300), (120, 250), (200, 320)]) if k != "polygon" \
                    else items.shape_spec(k, (50, 250, 200, 320), st, [(50, 300), (120, 250), (200, 320)])
            else:
                spec = items.shape_spec(k, (50, 50, 150, 120), st)
            items.add_item(d, 0, spec, snapshot=False)
            n += 1
    assert len(items.find_items(d, 0)) == n


def test_pens_and_variable_width():
    d = _blank(1)
    samples = [(100 + k * 2, 100 + (k % 7), k * (0.004 if k < 30 else 0.03), None) for k in range(60)]
    for pen, _ in items.PENS:
        spec = items.ink_spec([samples], {"pen": pen, "stroke": "#1a3fa8", "width": items.PEN_DEFAULT_WIDTH[pen]})
        if pen in items.VARIABLE_PENS:
            w = spec["widths"][0]
            assert max(w) > min(w) * 1.5                 # nét to nhỏ theo tốc độ
        items.add_item(d, 0, spec, snapshot=False)
    assert len(items.find_items(d, 0)) == len(items.PENS)
    # lực nhấn bút cảm ứng
    pw = items.pen_widths([(0, 0, 0, 0.1), (1, 0, 0.01, 0.1), (2, 0, 0.02, 1.0), (3, 0, 0.03, 1.0)] * 3, 2, "sign")
    assert pw[7] > pw[1]


def test_render_preview_transparent():
    spec = items.shape_spec("ellipse", (0, 0, 80, 40), {"stroke": "#d32f2f", "width": 2})
    img, m = items.render_preview(spec)
    assert img.mode == "RGBA" and img.getpixel((2, 2))[3] == 0 and m > 0


def test_gui_select_move_rotate_delete_item(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("shape:rect")
    _drag(tab.view, 0, (300, 600), (400, 660))
    win.stop_tool()
    it = items.find_items(tab.doc, 0)[0]
    assert it.spec["shape"] == "rect"
    undo_n = len(tab.doc._undo)
    _drag(tab.view, 0, (300, 630), (200, 530))                     # bấm vào cạnh hình rồi kéo luôn
    pl = tab.view.placement
    assert pl is not None and pl.rotatable and win.tool_opts.isVisible()
    pl.angle = 45
    _key(tab.view, Qt.Key_Return)
    it = items.find_items(tab.doc, 0)[0]
    r = it.spec["rect"]
    assert abs(r[0] - 200) < 2 and abs(r[1] - 500) < 2 and it.spec["angle"] == 45
    assert len(tab.doc._undo) == undo_n + 1                         # cả thao tác là 1 bước hoàn tác
    win.page_pressed(0, 250, 530)
    assert tab.view.placement is not None
    _key(tab.view, Qt.Key_Delete)
    assert items.find_items(tab.doc, 0) == []
    tab.doc.undo()
    assert len(items.find_items(tab.doc, 0)) == 1


def test_gui_escape_restores_item(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    items.add_item(tab.doc, 0, items.shape_spec("ellipse", (300, 600, 400, 660), {"stroke": "#d32f2f", "width": 2}))
    tab.refresh()
    n = len(tab.doc._undo)
    win.page_pressed(0, 300, 630)
    assert tab.view.placement is not None and items.find_items(tab.doc, 0) == []   # tạm gỡ khi đang kéo
    _key(tab.view, Qt.Key_Escape)
    assert len(items.find_items(tab.doc, 0)) == 1 and len(tab.doc._undo) == n


def test_gui_property_panel_restyles(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    items.add_item(tab.doc, 0, items.shape_spec("rect", (300, 600, 400, 660), {"stroke": "#d32f2f", "width": 1}))
    tab.refresh()
    win.page_pressed(0, 300, 630)
    o = win.tool_opts
    assert o.rows["fill"].isVisibleTo(o) and o.rows["zorder"].isVisibleTo(o)
    o.set_color("#2e7d32")
    o.sp_width.setValue(4)
    o.chk_fill.setChecked(True)
    o.cb_dash.setCurrentIndex(o.cb_dash.findData("dot"))
    tab.view.commit_placement()
    s = items.find_items(tab.doc, 0)[0].spec
    assert (s["stroke"], s["width"], s["dash"]) == ("#2e7d32", 4, "dot") and s["fill"]
    # lớp: đưa xuống dưới cùng
    win.page_pressed(0, 300, 630)
    o.btn_back.click()
    s = items.find_items(tab.doc, 0)[0].spec
    assert s["z"] == "back" and tab.view.placement is None


def test_gui_textbox_inline_edit(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("textbox")
    _drag(tab.view, 0, (80, 700), (400, 740))
    tab.view._inline[0].setPlainText("Chữ ban đầu")
    win.stop_tool()
    assert "Chữ ban đầu" in tab.doc.text(0)
    win.page_pressed(0, 90, 708)
    pl = tab.view.placement
    assert pl is not None and pl.on_dblclick is not None
    pl.on_dblclick(pl)                                               # nháy đúp -> ô gõ chữ tại chỗ
    assert tab.view._inline is not None and tab.view.placement is None
    ed = tab.view._inline[0]
    assert ed.toPlainText() == "Chữ ban đầu"
    ed.setPlainText("Chữ đã sửa tại chỗ")
    tab.view._finish_inline(True)
    assert "Chữ đã sửa tại chỗ" in tab.doc.text(0) and "Chữ ban đầu" not in tab.doc.text(0)
    assert len(items.find_items(tab.doc, 0)) == 1


def test_gui_hover_cursor(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    items.add_item(tab.doc, 0, items.shape_spec("rect", (300, 600, 400, 660), {"stroke": "#d32f2f", "width": 2}))
    notes.add_note(tab.doc, 0, 500, 100, "x", "a")
    tab.refresh()
    assert win._hover_kind(tab, 0, 300, 630) == "item"
    assert win._hover_kind(tab, 0, 505, 105) == "note"
    assert win._hover_kind(tab, 0, 100, 95) == "text"              # chữ sửa được -> con trỏ chữ I
    assert win._hover_kind(tab, 0, 20, 820) is None


def test_gui_shape_gallery_and_shift(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    m = win.tool_menu("shape")
    gal = win._shape_gallery
    assert len(gal.buttons) >= 45
    gal.buttons["heart"].click()
    m.close()
    assert tab.view.tool.kind == "shape" and tab.view.tool.shape == "heart"
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 100, 100))
    r = tab.view._rects[0]
    s = tab.view.scale
    pos = QPointF(r.left() + 200 * s, r.top() + 150 * s)
    c.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.LeftButton, Qt.ShiftModifier))
    c.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton,
                                    Qt.ShiftModifier))
    spec = items.find_items(tab.doc, 0)[0].spec
    x0, y0, x1, y1 = spec["rect"]
    assert abs((x1 - x0) - (y1 - y0)) < 0.5                         # Shift: đúng tỉ lệ
    win.stop_tool()


def test_gui_polyline_tool(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("shape:polyline")
    c = tab.view.canvas
    for x, y in ((100, 400), (200, 350), (260, 450)):
        c.mousePressEvent(_click(tab.view, 0, x, y))
        c.mouseReleaseEvent(_click(tab.view, 0, x, y, kind=QEvent.MouseButtonRelease))
    _key(tab.view, Qt.Key_Return)
    spec = items.find_items(tab.doc, 0)[0].spec
    assert spec["shape"] == "polyline" and len(spec["pts"]) == 3
    win.stop_tool()


def test_gui_pen_menu_types(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    m = win.tool_menu("pen")
    assert len([a for a in m.actions() if not a.isSeparator()]) == len(items.PENS) + 1   # + cục tẩy nét
    m.close()
    win.start_tool("pen:sign")
    assert win.tool_opts.pen == "sign"
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 100, 750))
    for k in range(1, 30):
        c.mouseMoveEvent(_click(tab.view, 0, 100 + k * 4, 750 + (k % 5), kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(tab.view, 0, 220, 752, kind=QEvent.MouseButtonRelease))
    spec = items.find_items(tab.doc, 0)[0].spec
    assert spec["kind"] == "ink" and spec["pen"] == "sign" and spec.get("widths")
    win.stop_tool()


# ================================================================== tẩy vùng (16)
def _text_doc(pages=1):
    return PdfDocument(data=_contract(pages))


def test_erase_ellipse_lasso_brush_and_filters():
    d = _text_doc()
    before = d.text(0).count("Điều khoản")
    r = editing.erase_region(d, 0, {"shape": "ellipse", "rect": (40, 110, 580, 180)}, "white", "all")
    assert r["text"] >= 1 and r["fill"] == "#ffffff"
    d = _text_doc()
    r = editing.erase_region(d, 0, {"shape": "lasso", "pts": [(55, 120), (570, 120), (570, 170), (55, 170)]}, "none")
    assert r["text"] == 2 and r["fill"] is None and d.text(0).count("Điều khoản") == before - 2
    d = _text_doc()
    r = editing.erase_region(d, 0, {"shape": "brush", "pts": [(60, 142), (560, 142)], "size": 40}, "sample", "text")
    assert r["text"] >= 1 and r["fill"].startswith("#")
    d = _text_doc()
    r = editing.erase_region(d, 0, {"shape": "rect", "rect": (0, 0, 595, 842)}, "none", "image")
    assert r["text"] == 0                                             # chỉ ảnh -> không đụng chữ


def test_sample_paper_color_on_yellow_page():
    d = _blank(1)
    items.add_item(d, 0, items.shape_spec("rect", (0, 0, 595, 842), {"stroke": None, "fill": "#f5e9c8"}))
    c = editing.sample_paper_color(d, 0, (100, 100, 200, 200))
    assert c == "#f5e9c8"


def test_gui_erase_preview_adjust_then_apply(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("erase")
    o = win.tool_opts
    o.cb_erase_shape.setCurrentIndex(o.cb_erase_shape.findData("rect"))
    o.cb_erase_fill.setCurrentIndex(o.cb_erase_fill.findData("white"))
    o.chk_erase_preview.setChecked(True)
    n = tab.doc.text(0).count("Điều khoản")
    _drag(tab.view, 0, (60, 125), (560, 165))
    assert tab.view.placement is not None and tab.doc.text(0).count("Điều khoản") == n
    _key(tab.view, Qt.Key_Escape)                                     # bỏ -> không tẩy
    assert tab.doc.text(0).count("Điều khoản") == n and tab.view.tool is not None
    _drag(tab.view, 0, (60, 125), (560, 165))
    _key(tab.view, Qt.Key_Return)
    assert tab.doc.text(0).count("Điều khoản") == n - 2
    win.stop_tool()


# ================================================================== chèn trang (17)
def test_insert_pages_modes():
    a, b = _blank(4), _blank(3, (842, 595))
    assert a.insert_pages(b, None, 1) == [1, 2, 3] and a.page_count == 7
    a.undo()
    assert a.insert_pages(b, None, mode="interleave") == [1, 3, 5]
    a.undo()
    assert a.insert_pages(b, [0], mode="repeat", every=2) == [2, 5]
    a.undo()
    new = a.insert_pages(b, [2, 0], 0, reverse=True, fit_to=0)
    assert new == [0, 1] and all(abs(a.page_size_pt(i)[0] - 595) < 1 for i in new)


def test_images_to_pages(tmp_path):
    from PIL import Image
    p = tmp_path / "a.png"
    Image.new("RGB", (1200, 800), "red").save(p, dpi=(150, 150))
    d = PdfDocument.from_images([str(p)])
    assert d.page_count == 1 and abs(d.page_size_pt(0)[0] - 576) < 1
    d = PdfDocument.from_images([str(p)], (595, 842))
    assert tuple(round(v) for v in d.page_size_pt(0)) == (842, 595)   # ảnh ngang -> trang ngang


def test_insert_pages_dialog(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 3)
    src = tmp_path / "src.pdf"
    src.write_bytes(_blank(5, (842, 595)).to_bytes())
    dlg = ui_pages.InsertPagesDialog(win, tab.doc, 0, path=str(src))
    assert dlg.src.page_count == 5 and len(dlg.src_pages()) == 5
    dlg.cb_pages.setCurrentIndex(dlg.cb_pages.findData("odd"))
    assert dlg.src_pages() == [0, 2, 4]
    dlg.lst.item(2).setCheckState(Qt.Unchecked)                       # bỏ tích trên ảnh thu nhỏ
    assert dlg.src_pages() == [0, 4] and dlg.cb_pages.currentData() == "pick"
    dlg.cb_pos.setCurrentIndex(dlg.cb_pos.findData("end"))
    dlg.cb_size.setCurrentIndex(1)
    assert "tổng 5 trang" in dlg.lbl_sum.text()
    v = dlg.values()
    new = tab.doc.insert_pages(v["src"], v["pages"], v["index"], v["mode"], fit_to=0 if v["fit"] else None)
    assert new == [3, 4] and tab.doc.page_count == 5
    dlg.reject()
    # qua lệnh trên thanh công cụ: nguồn = trang trắng
    def fake_exec(self):
        self.cb_source.setCurrentIndex(1)            # "Trang trắng"
        self.sp_blank.setValue(2)
        self.cb_pos.setCurrentIndex(self.cb_pos.findData("start"))
        return QDialog.Accepted
    monkeypatch.setattr(ui_pages.InsertPagesDialog, "exec", fake_exec)
    win.run("insertpdf")
    assert tab.doc.page_count == 7 and tab.doc.text(0).strip() == ""
