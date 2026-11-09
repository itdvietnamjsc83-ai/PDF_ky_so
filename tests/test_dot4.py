"""Đợt 4: sửa chữ tại chỗ / cả dòng / cả đoạn / trên scan, tìm & thay xem trước; xuất, ẩn, in ghi chú; chọn nhiều,
sao chép, dán; chữ trong hình; kiểu hình đã lưu; tẩy nét, vẽ thẳng, tự nắn hình; tẩy nhiều trang; kéo file vào cột
ảnh; trang trắng sau mỗi N trang; xóa trang theo cụm chữ / gần trắng; ký theo cụm chữ; ký nháy nhiều trang;
khay: kéo sắp thứ tự, thư mục, xem trước, sheet Excel, tự nhận trang màu, đếm trang màu, bản đen trắng."""
import io
import math
import os
import zipfile

import pikepdf
import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QDialog

from app import colormode as CM
from app import editing, items, notes, office, ui_edit, ui_import, ui_pages
from app.document import PdfDocument, blank_document
from app.merge import MergeOptions, TrayItem, color_stats, merge

from .test_dot2 import _external_notes_pdf
from .test_dot3 import RED_TXT, _sat, color_pdf
from .test_gui import pump
from .test_gui_phase5 import _click, _drag, _key, _open, lib_path, qapp, win  # noqa: F401
from .test_phase4 import _contract


# ================================================================== 11: sửa chữ
def test_line_and_paragraph_replace():
    d = PdfDocument(data=_contract(1))
    runs = editing.text_runs(d, 0)
    para = editing.paragraph_of(runs, runs[3])
    assert len(para) >= 5                                              # các dòng đều nhau cùng lề -> một đoạn
    info = editing.replace_group(d, 0, para, "Đoạn văn mới ngắn gọn thay cho cả đoạn cũ.")
    t = d.text(0)
    assert "Đoạn văn mới ngắn gọn" in t and not info["overflow"]
    assert t.count("Điều khoản thỏa thuận") < 10


def test_line_replace_shrinks_long_text():
    d = PdfDocument(data=_contract(1))
    runs = editing.text_runs(d, 0)
    info = editing.replace_group(d, 0, [editing.line_of(runs, runs[1])], "Dòng mới dài hơn hẳn dòng cũ một chút")
    assert info["shrunk"] and info["size"] < 11


def test_styled_font_bold_italic():
    d = PdfDocument(data=_contract(1))
    run = editing.text_runs(d, 0)[1]
    p = editing.styled_font(run, None, True, True).lower()
    assert "bi" in os.path.basename(p) or "bold" in p or "z" in os.path.basename(p)


def test_find_hits_and_selective_replace():
    d = PdfDocument(data=_contract(2))
    hits = editing.find_hits(d, "Điều khoản")
    assert len(hits) == 20 and all(h.replaceable for h in hits)
    assert editing.replace_hits(d, hits[:3], "Mục") == 3
    assert d.text(0).count("Mục") == 3 and d.can_undo


def test_find_dialog_selective(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    dlg = ui_edit.FindReplaceDialog(win, tab.doc, tab.view.go_to)
    dlg.ed_find.setText("Điều khoản")
    assert dlg.find() == 10 and dlg.list.count() == 10
    dlg._check_all(False)
    dlg.list.item(0).setCheckState(Qt.Checked)
    dlg.list.item(2).setCheckState(Qt.Checked)
    dlg.ed_repl.setText("Mục")
    assert dlg.replace_selected() == 2 and tab.doc.text(0).count("Mục") == 2


def test_gui_edit_paragraph_inline(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("edittext")
    o = win.tool_opts
    o.cb_scope.setCurrentIndex(o.cb_scope.findData("para"))
    o.btn_bold.setChecked(True)
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 175))
    ed = tab.view._inline[0]
    assert ed.toPlainText().count("Điều khoản") >= 5
    ed.setPlainText("Nội dung đoạn đã sửa.")
    tab.view._finish_inline(True)
    assert "Nội dung đoạn đã sửa." in tab.doc.text(0)
    win.stop_tool()


def test_gui_scan_edit(win, qapp, samples):
    win.open_files([samples["scan"]])
    pump(qapp)
    tab = win.current()
    win.start_tool("scanedit")
    _drag(tab.view, 0, (100, 200), (300, 222))
    ed = tab.view._inline[0]
    ed.setPlainText("Chữ mới trên scan")
    tab.view._finish_inline(True)
    assert "Chữ mới trên scan" in tab.doc.text(0) and len(items.find_items(tab.doc, 0)) == 1
    tab.doc.undo()
    assert "Chữ mới trên scan" not in tab.doc.text(0)
    win.stop_tool()


# ================================================================== 12c, 12e: ghi chú
def test_export_notes_xlsx_pdf(tmp_path):
    d = PdfDocument(data=_external_notes_pdf())
    lst = notes.list_notes(d)
    x = tmp_path / "n.xlsx"
    notes.export_xlsx(lst, str(x), "Tổng hợp")
    with zipfile.ZipFile(x) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "Ghi chú từ Acrobat" in sheet and "Đã sửa rồi nhé" in sheet
    p = tmp_path / "n.pdf"
    notes.export_pdf(lst, str(p), "Tổng hợp ghi chú")
    t = PdfDocument(str(p)).text(0)
    assert "Tổng hợp ghi chú" in t and "Đoạn này cần kiểm tra" in t


def test_hide_notes_render_only():
    d = PdfDocument(data=_external_notes_pdf())
    a = d.render(0, 0.5).to_pil()
    d.hide_notes = True
    b = d.render(0, 0.5).to_pil()
    d.hide_notes = False
    c = d.render(0, 0.5).to_pil()
    assert a.tobytes() != b.tobytes() and a.tobytes() == c.tobytes()
    assert not d.modified and len(notes.list_notes(d)) == 3


def test_notes_panel_export_and_toggle(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    notes.add_note(tab.doc, 0, 100, 100, "Cần sửa", "An")
    tab.refresh()
    win.run("notes")
    win._export_path = str(tmp_path / "x.xlsx")
    assert win.export_notes("xlsx") and os.path.exists(tmp_path / "x.xlsx")
    win.notes_panel.chk_show.setChecked(False)
    assert tab.doc.hide_notes
    win.notes_panel.chk_show.setChecked(True)
    win.notes_panel.chk_print.setChecked(True)
    assert str(win.settings.value("print/notes")).lower() == "true"


# ================================================================== 13d, 14d, 14e, 15: nội dung đã thêm
def _two_boxes(doc):
    a = items.add_item(doc, 0, items.shape_spec("rect", (100, 500, 160, 540), {"stroke": "#d32f2f", "width": 2}))
    b = items.add_item(doc, 0, items.shape_spec("ellipse", (200, 500, 260, 540), {"stroke": "#1565c0", "width": 2}))
    return a, b


def test_group_edit_move_scale():
    d = blank_document(1, (595, 842))
    a, b = _two_boxes(d)
    ge = items.GroupEdit(d, 0, items.find_items(d, 0))
    x0, y0, x1, y1 = ge.frame
    ge.commit((x0 + 50, y0 + 100, x1 + 50 + (x1 - x0), y1 + 100 + (y1 - y0)))    # dời + to gấp đôi
    got = {it.id: it.spec["rect"] for it in items.find_items(d, 0)}
    ra, rb = got[a["id"]], got[b["id"]]
    assert abs((ra[2] - ra[0]) - 120) < 1 and abs(rb[0] - ra[0] - 200) < 2 and len(d._undo) == 3


def test_paste_items_new_ids():
    d = blank_document(1, (595, 842))
    a, _ = _two_boxes(d)
    new = items.paste_items(d, 0, [a])
    assert new[0]["id"] != a["id"] and abs(new[0]["rect"][0] - 112) < 0.1 and len(items.find_items(d, 0)) == 3


def test_gui_band_select_copy_paste_delete(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    _two_boxes(tab.doc)
    tab.refresh()
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 80, 480))             # chỗ trống -> kéo khung chọn
    c.mouseMoveEvent(_click(tab.view, 0, 280, 560, kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(tab.view, 0, 280, 560, kind=QEvent.MouseButtonRelease))
    assert win._sel and win._sel.get("group") and len(win._sel["ids"]) == 2
    old_ids = set(win._sel["ids"])
    win.clipboard_action(tab, "dup")                             # nhân bản cả nhóm -> nhóm mới đang được chọn
    assert win._sel.get("group") and not (set(win._sel["ids"]) & old_ids)
    _key(tab.view, Qt.Key_Return)
    assert len(items.find_items(tab.doc, 0)) == 4
    win.page_pressed(0, 100, 520)
    _key(tab.view, Qt.Key_Delete)
    assert len(items.find_items(tab.doc, 0)) == 3


def test_gui_ctrl_click_adds_to_group(win, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    tab = _open(win, qapp, tmp_path, 1)
    _two_boxes(tab.doc)
    tab.refresh()
    win.page_pressed(0, 100, 520)
    tab.view.commit_placement()
    monkeypatch.setattr(QApplication, "keyboardModifiers", staticmethod(lambda: Qt.ControlModifier))
    win.page_pressed(0, 200, 520)
    assert win._sel and win._sel.get("group") and len(win._sel["ids"]) == 2
    tab.view.cancel_placement()


def test_shape_text_inside():
    d = blank_document(1, (595, 842))
    sp = items.shape_spec("co_round", (100, 100, 300, 200), {"stroke": "#1565c0", "width": 1.5, "fill": "#e3f2fd"})
    sp["text"] = "Chữ trong khung chú thích"
    items.add_item(d, 0, sp)
    assert "Chữ trong khung chú thích" in d.text(0)
    ts = items.shape_text_spec(sp)
    assert 100 < ts["rect"][0] and ts["rect"][3] < 200 * 0.9


def test_gui_shape_text_inline(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    items.add_item(tab.doc, 0, items.shape_spec("rect", (300, 600, 460, 680), {"stroke": "#d32f2f", "width": 2}))
    tab.refresh()
    win.page_pressed(0, 300, 640)
    pl = tab.view.placement
    pl.on_dblclick(pl)
    ed = tab.view._inline[0]
    ed.setPlainText("Ghi chú trong hình")
    tab.view._finish_inline(True)
    assert "Ghi chú trong hình" in tab.doc.text(0)
    assert items.find_items(tab.doc, 0)[0].spec["text"] == "Ghi chú trong hình"


def test_saved_styles(win, qapp):
    o = win.tool_opts
    o.set_color("#2e7d32")
    o.sp_width.setValue(3)
    o.chk_fill.setChecked(True)
    o.save_style()
    assert len(o.style_buttons) >= 1 and o.saved_styles()[0]["stroke"] == "#2e7d32"
    o.set_color("#d32f2f")
    o.style_buttons[0].click()
    assert o.color == "#2e7d32" and o.width == 3
    o.remove_style(0)


def test_ink_eraser_removes_touched_strokes_only():
    d = blank_document(1, (595, 842))
    s1 = [(100 + k * 3, 100, k * 0.01, None) for k in range(30)]
    s2 = [(100 + k * 3, 200, k * 0.01, None) for k in range(30)]
    sp = items.ink_spec([s1, s2], {"pen": "ball", "stroke": "#000000", "width": 1.5})
    items.add_item(d, 0, sp)
    n = items.erase_strokes(d, 0, [(150, 90), (150, 110)], 4)
    assert n == 1
    left = items.find_items(d, 0)[0].spec
    assert len(left["strokes"]) == 1
    assert items.erase_strokes(d, 0, [(150, 195), (150, 205)], 4) == 1 and items.find_items(d, 0) == []


@pytest.mark.parametrize("name,expect", [("circle", "ellipse"), ("rect", "rect"), ("line", "line"),
                                         ("tri", "triangle"), ("arrow", "arrow")])
def test_recognize(name, expect):
    pts = {
        "circle": [(100 + 50 * math.cos(a / 20 * math.pi), 100 + 30 * math.sin(a / 20 * math.pi)) for a in range(41)],
        "rect": [(k * 5, 0) for k in range(20)] + [(100, k * 3) for k in range(20)] +
                [(100 - k * 5, 60) for k in range(20)] + [(0, 60 - k * 3) for k in range(21)],
        "line": [(k * 3, k * 1.5 + (k % 2) * 0.5) for k in range(40)],
        "tri": [(50 + k * 2.5, k * 4) for k in range(21)] + [(100 - k * 5, 80) for k in range(21)] +
               [(k * 2.5, 80 - k * 4) for k in range(21)],
        "arrow": [(k * 4, 0) for k in range(30)] + [(116 - k * 3, -k * 3) for k in range(6)],
    }[name]
    assert items.recognize(pts)[0] == expect


def test_gui_pen_recognize_and_shift_line(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 1)
    win.start_tool("pen:ball")
    win.tool_opts.chk_recognize.setChecked(True)
    c = tab.view.canvas
    c.mousePressEvent(_click(tab.view, 0, 300, 300))
    for k in range(1, 41):
        a = k / 40 * 2 * math.pi
        c.mouseMoveEvent(_click(tab.view, 0, 250 + 50 * math.cos(a), 300 + 30 * math.sin(a) - 0.0,
                                kind=QEvent.MouseMove))
    c.mouseReleaseEvent(_click(tab.view, 0, 300, 300, kind=QEvent.MouseButtonRelease))
    sp = items.find_items(tab.doc, 0)[-1].spec
    assert sp["kind"] == "shape" and sp["shape"] == "ellipse"
    win.tool_opts.chk_recognize.setChecked(False)
    win.stop_tool()


# ================================================================== trang: 16e, 17e, 18b, 19c
def test_erase_all_pages_same_spot(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 3)
    win.start_tool("erase")
    o = win.tool_opts
    o.cb_erase_shape.setCurrentIndex(0)
    o.cb_erase_fill.setCurrentIndex(0)
    o.cb_erase_filter.setCurrentIndex(0)
    o.cb_erase_scope.setCurrentIndex(o.cb_erase_scope.findData("all"))
    o.chk_erase_preview.setChecked(False)
    _drag(tab.view, 0, (60, 75), (400, 110))
    assert all("HỢP ĐỒNG KINH TẾ" not in tab.doc.text(i) for i in range(3))
    tab.doc.undo()
    assert all("HỢP ĐỒNG KINH TẾ" in tab.doc.text(i) for i in range(3))
    o.cb_erase_scope.setCurrentIndex(0)
    o.chk_erase_preview.setChecked(True)
    win.stop_tool()


def test_drop_files_on_thumbnails(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 3)
    src = tmp_path / "chen.pdf"
    src.write_bytes(blank_document(2, (842, 595)).to_bytes())
    img = tmp_path / "anh.png"
    Image.new("RGB", (300, 200), "red").save(img)
    n = win.insert_files_at(tab, [str(src), str(img)], 1)
    assert n == 3 and tab.doc.page_count == 6
    assert tab.doc.page_size_pt(1)[0] > tab.doc.page_size_pt(1)[1]     # trang ngang chèn ở vị trí 2


def test_blank_every_n():
    d = blank_document(5, (595, 842))
    assert d.insert_blank_every(1) == 4 and d.page_count == 9
    d.undo()
    assert d.insert_blank_every(2, 1, (420, 595)) == 2 and d.page_size_pt(2) == (420.0, 595.0)


def test_blank_dialog_every(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path, 4)

    def fake_exec(self):
        self.opts["every"].setChecked(True)
        self.sp_every.setValue(1)
        return QDialog.Accepted
    monkeypatch.setattr(ui_pages.BlankPagesDialog, "exec", fake_exec)
    win.run("blank")
    assert tab.doc.page_count == 7


def test_delete_by_text_and_near_blank(tmp_path):
    d = PdfDocument(data=_contract(3))
    dlg = ui_pages.DeletePagesDialog(None, d, 0, [0])
    dlg.opts["text"].setChecked(True)
    dlg.ed_text.setText("trang 2")
    dlg._update()
    assert dlg.pages() == [1]
    # trang scan có vài chấm bụi -> gần trắng
    im = Image.new("L", (1240, 1754), 255)
    for k in range(40):
        im.putpixel((100 + k * 20, 300 + k * 5), 0)
    p = tmp_path / "bui.png"
    im.save(p, dpi=(150, 150))
    s = PdfDocument.from_images([str(p)])
    dlg2 = ui_pages.DeletePagesDialog(None, s, 0, [0])
    dlg2.opts["nearblank"].setChecked(True)
    dlg2._update()
    assert dlg2.pages() == [0]


# ================================================================== ký: 4c, 4d
def test_find_text_spot():
    d = PdfDocument(data=_contract(3))
    page, x, y, found = d.find_text_spot("trang 2")
    assert found and page == 1
    assert d.find_text_spot("KHÔNG CÓ CỤM NÀY")[3] is False


def test_scope_pages_initials(win, qapp, tmp_path):
    tab = _open(win, qapp, tmp_path, 4)
    assert win._scope_pages(tab, 0, "but_last") == [0, 1, 2]
    assert win._scope_pages(tab, 1, "odd") == [0, 2]
    assert win._scope_pages(tab, 1, "even") == [1, 3]


# ================================================================== khay: 5b, 5c, 6b, 8c, 8d, 10d, 10f, 10g, 10h
def test_tray_move_rows_and_folder(win, qapp, tmp_path):
    folder = tmp_path / "hoso"
    (folder / "con").mkdir(parents=True)
    for name in ("10.pdf", "2.pdf", "con/1.pdf"):
        (folder / name).write_bytes(blank_document(1, (595, 842)).to_bytes())
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    assert t.add_paths([str(folder)]) == 3                       # 5c: cả thư mục (cả thư mục con)
    assert [os.path.relpath(it.path, folder).replace("\\\\", "/") for it in t.items] == ["2.pdf", "10.pdf",
                                                                                        os.path.join("con", "1.pdf")]
    t.move_rows([2], 0)                                          # 5b: kéo dòng cuối lên đầu
    assert t.items[0].path.endswith("1.pdf")
    t.items.clear()
    t.refresh()
    t.close()


def test_auto_color_and_stats(tmp_path):
    a = tmp_path / "mau.pdf"
    a.write_bytes(color_pdf(1))
    b = tmp_path / "chu.pdf"
    b.write_bytes(_contract(2))
    items_ = [TrayItem(str(a), page_count=1), TrayItem(str(b), page_count=2)]
    opts = MergeOptions(duplex=False, auto_rotate=False, color="auto")
    assert color_stats(items_, opts) == (1, 2)
    doc = merge(items_, opts)
    data = doc.to_bytes()
    d = PdfDocument(data=data)
    assert _sat(d.render(0, 1).to_pil().convert("RGB"), RED_TXT) > 100   # trang màu giữ màu


def test_tray_bw_copy_and_template(win, qapp, tmp_path):
    a = tmp_path / "mau.pdf"
    a.write_bytes(color_pdf(2))
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([str(a)])
    t.items[0].page_colors = {"1": "gray"}
    t.cmb_color.setCurrentIndex(t.cmb_color.findData("auto"))
    t.ed_dir.setText(str(tmp_path))
    t.ed_name.setText("hoso")
    t.cb_bw_copy.setChecked(True)
    doc = t.do_merge(False)
    assert doc is not None and os.path.exists(tmp_path / "hoso.pdf") and os.path.exists(tmp_path / "hoso_den-trang.pdf")
    from app.merge import load_template, save_template
    p = tmp_path / "m.khay.json"
    save_template(str(p), t.items, t.opts)
    its, op = load_template(str(p))
    assert its[0].page_colors == {"1": "gray"} and op.color == "auto"
    t.items.clear()
    t.refresh()
    t.close()


def test_tray_preview_merged(win, qapp, tmp_path, monkeypatch):
    from app import tray as tray_mod
    a = tmp_path / "a.pdf"
    a.write_bytes(_contract(2))
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([str(a)])
    seen = {}

    def fake_exec(self):
        seen["pages"] = self.view.doc.page_count
        return QDialog.Rejected
    monkeypatch.setattr(tray_mod.MergedPreviewDialog, "exec", fake_exec)
    assert t.preview_merged() is None and seen["pages"] == 2
    t.items.clear()
    t.refresh()
    t.close()


def test_excel_options(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")               # chỉ để tạo file mẫu, phần mềm không cần
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Báo giá"
    for r in range(1, 50):
        for c in range(1, 16):
            ws.cell(r, c, r * c)
    wb.create_sheet("Chi tiết")["A1"] = "x"
    p = tmp_path / "bang.xlsx"
    wb.save(p)
    assert office.excel_sheets(str(p)) == ["Báo giá", "Chi tiết"]
    dlg = ui_import.ExcelOptionsDialog(None, str(p))
    dlg.lst.item(1).setCheckState(Qt.Unchecked)
    dlg.cb_fit.setCurrentIndex(dlg.cb_fit.findData("page"))
    v = dlg.values()
    assert v == {"sheets": ["Báo giá"], "fit": "page", "orientation": ""}
    assert ui_import.excel_summary(v) == "1 sheet, vừa 1 trang"
    if office.find_libreoffice():
        out, _ = office.to_pdf(str(p), str(tmp_path / "o.pdf"), v)
        assert PdfDocument(out).page_count == 1


def test_image_page_options(tmp_path):
    p = tmp_path / "anh.jpg"
    Image.new("RGB", (3000, 2000), (10, 120, 200)).save(p, dpi=(300, 300))
    base = PdfDocument.from_images([str(p)])
    a4 = PdfDocument.from_images([str(p)], **ui_import.image_args({"page": "A4", "margin_mm": 10, "quality": "low"}))
    assert [round(v) for v in a4.page_size_pt(0)] == [842, 595]
    assert len(a4.to_bytes()) < len(base.to_bytes()) / 3
    dlg = ui_import.ImagePageDialog(None, {"page": "A5", "quality": "medium"})
    assert dlg.values()["page"] == "A5" and ui_import.image_summary(dlg.values()).startswith("A5")
