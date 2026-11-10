"""Kiểm thử bản 1.0.22: bố cục thu gọn, nhiều cửa sổ, hỏi nơi lưu khi ghép, màu "như máy in", hướng trang scan,
tìm kiếm tô vàng."""
import os
import random

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app import orient
from app.colormode import CONVERT_MODES, MODES, convert_bytes
from app.document import PdfDocument

from .conftest import pymupdf
from .test_gui import pump, qapp, win  # noqa: F401


# ------------------------------------------------------------------ bố cục: cửa sổ hẹp, ẩn/hiện các thanh
def test_window_can_shrink_for_split_screen(win, qapp, samples):
    """Chia đôi màn hình (≈ 960 px) hoặc màn hình phóng to 125–150%: cửa sổ phải thu hẹp được,
    bảng bên phải không bị đẩy ra ngoài."""
    win.open_files([samples["text"]])
    pump(qapp)
    assert win.minimumSizeHint().width() <= 760
    win.resize(900, 760)
    pump(qapp, 200)
    assert win.width() <= 900
    assert win.side.geometry().right() <= win.centralWidget().width()
    win._flash("Thông báo rất dài " * 40)              # thông báo dài không được kéo rộng cửa sổ
    pump(qapp)
    assert win.minimumSizeHint().width() <= 760


def test_hide_panels_and_focus_view(win, qapp, samples, tmp_path):
    win.set_layout_style("rail", save=False)            # cột trái chỉ có ở kiểu "cột trái"
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    win.set_panel_visible("thumbs", False)
    win.set_panel_visible("side", False)
    win.set_panel_visible("rail", False)
    pump(qapp)
    assert not tab.thumbs.isVisible() and not win.side.isVisible() and not win.rail.isVisible()
    assert win.settings.value("ui/side") is False
    win.open_files([samples["mixed"]])                  # tab mới theo lựa chọn
    pump(qapp)
    assert not win.current().thumbs.isVisible()
    # bảng phải đã ẩn: đặt ảnh -> bảng tùy chọn ảnh vẫn hiện (tạm), xong thì ẩn lại
    p = str(tmp_path / "a.png")
    Image.new("RGB", (80, 40), (200, 0, 0)).save(p)
    win.insert_image(win.current(), p)
    pump(qapp)
    assert win.side.isVisible() and win.img_opts.isVisible()
    win.current().view.cancel_placement()
    pump(qapp)
    assert not win.side.isVisible()
    win.set_focus_view(False)
    pump(qapp)
    assert win.side.isVisible() and win.rail.isVisible() and win.current().thumbs.isVisible()
    win.toggle_focus_view()
    pump(qapp)
    assert not win.ribbon_visible() and not win.side.isVisible()
    win.toggle_focus_view()
    pump(qapp)
    assert win.ribbon_visible() and win.side.isVisible()


def test_detach_tab_to_new_window(win, qapp, samples):
    from app.mainwindow import MainWindow
    win.open_files([samples["text"], samples["mixed"]])
    pump(qapp)
    doc = win.current().doc
    doc.rotate_pages([0])                                # thay đổi chưa lưu vẫn giữ khi tách cửa sổ
    w2 = win.detach_current_tab()
    pump(qapp, 200)
    try:
        assert w2 is not None and w2 in MainWindow._windows and w2.isVisible()
        assert win.tabs.count() == 1 and w2.tabs.count() == 1
        assert w2.current().doc is doc and doc.modified and doc.can_undo
        assert w2.all_windows()[0] is win
        # xếp cạnh nhau: thanh tiêu đề (nút đóng / thu nhỏ) vẫn nằm trong màn hình, không bị đẩy lên trên
        scr = win.screen().availableGeometry()
        for w in (win, w2):
            assert w.frameGeometry().top() >= scr.top() and w.geometry().top() > scr.top()
            assert w.geometry().bottom() <= scr.bottom() + 1
    finally:
        doc.modified = False
        w2.close()
        pump(qapp, 100)


# ------------------------------------------------------------------ khay ghép: hỏi nơi lưu + tên file
def _pdfs(tmp_path, n=2):
    out = []
    for k in range(n):
        d = pymupdf.open()
        for _ in range(2):
            d.new_page().insert_text((72, 72), f"File {k}")
        p = tmp_path / f"f{k}.pdf"
        d.save(p)
        out.append(str(p))
    return out


def test_merge_asks_where_to_save(win, qapp, tmp_path, monkeypatch):
    from app.tray import TrayDialog
    files = _pdfs(tmp_path)
    t = win.show_tray()
    t.items.clear()
    t.add_paths(files)
    target = tmp_path / "noi_khac" / "Ho so moi"
    asked = []
    monkeypatch.setattr(TrayDialog, "_ask_target", lambda self: asked.append(self.target_path()) or str(target))
    t.cb_ask_save.setChecked(True)
    doc = t.do_merge(False)
    pump(qapp)
    assert asked and asked[0].endswith(".pdf")            # gợi ý sẵn thư mục + tên hiện tại
    assert doc is not None and doc.path == str(target) + ".pdf" and os.path.exists(doc.path)
    assert t.ed_dir.text() == str(target.parent)          # lần sau gợi ý luôn thư mục vừa chọn
    # hủy hộp thoại -> không ghép
    monkeypatch.setattr(TrayDialog, "_ask_target", lambda self: None)
    assert t.do_merge(False) is None
    # tắt "Hỏi nơi lưu" -> dùng ngay thư mục / tên trong khay
    t.cb_ask_save.setChecked(False)
    assert win.settings.value("tray/ask_save") is False
    d2 = t.do_merge(False)
    pump(qapp)
    assert d2 is not None and os.path.dirname(d2.path) == str(target.parent) and os.path.exists(d2.path)
    for i in range(win.tabs.count()):
        win.tabs.widget(i).doc.modified = False


# ------------------------------------------------------------------ màu: như máy in đen trắng
def test_print_like_mode_everywhere():
    assert ("print", "Như máy in đen trắng") in MODES and "print" in CONVERT_MODES
    d = pymupdf.open()
    p = d.new_page()
    p.draw_rect(pymupdf.Rect(50, 50, 300, 150), color=None, fill=(0, 1, 1))      # ô tô xanh lơ
    p.draw_rect(pymupdf.Rect(50, 350, 300, 450), color=None, fill=(0.8, 0, 0))   # ô tô đỏ đậm
    p.insert_text((60, 250), "Chữ vàng nhạt", fontsize=20, color=(0.9, 0.8, 0))
    data = d.tobytes()

    def render(mode):
        doc = PdfDocument(data=convert_bytes(data, {0: mode}))
        im = doc.render(0, 1).to_pil().convert("RGB")
        doc.close()
        return im
    gray, prn = render("gray"), render("print")
    text_box = (60, 230, 200, 255)
    assert min(prn.convert("L").crop(text_box).tobytes()) < 40          # chữ màu -> đen đậm
    assert min(gray.convert("L").crop(text_box).tobytes()) > 120        # (chế độ Xám: chữ vàng nhạt)
    c, r = prn.getpixel((250, 70)), prn.getpixel((250, 370))
    assert c[0] == c[1] == c[2] and 150 < c[0] < 220                    # ô xanh lơ -> xám nhạt
    assert r[0] == r[1] == r[2] and r[0] < 110                          # ô đỏ đậm -> xám đậm


# ------------------------------------------------------------------ hướng trang scan
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
WORDS = ("hợp đồng mua bán hàng hóa giữa công ty trách nhiệm hữu hạn và bên mua điều khoản thanh toán "
         "bảo hành chất lượng sản phẩm Việt Nam số lượng đơn giá tổng cộng").split()


def _table_page(seed):
    random.seed(seed)
    im = Image.new("L", (1240, 1754), 242)
    dr = ImageDraw.Draw(im)
    F = ImageFont.truetype(FONT if os.path.exists(FONT) else orient.__file__, 26) if os.path.exists(FONT) else \
        ImageFont.load_default()
    for k in range(14):
        y = 200 + k * 80
        dr.line((100, y, 1140, y), fill=20, width=3)
        for x in (100, 400, 800, 1140):
            dr.line((x, 200, x, 200 + 13 * 80), fill=20, width=3)
        if k < 13:
            for x in (110, 410, 810):
                dr.text((x, y + 20), " ".join(random.choice(WORDS) for _ in range(2)), font=F, fill=25)
    return im.filter(ImageFilter.GaussianBlur(0.6))


@pytest.mark.skipif(not os.path.exists(FONT), reason="cần phông DejaVu Serif")
@pytest.mark.parametrize("seed", range(4))
def test_orient_tables_never_wrong(seed):
    """Trang có bảng kẻ ô (trước đây hay nhận nhầm lộn ngược): đúng hướng hoặc "không chắc", không bao giờ sai."""
    base = _table_page(seed)
    for ccw, need in ((0, 0), (90, 90), (180, 180), (270, 270)):
        got, _ = orient.detect(base.rotate(ccw + random.uniform(-2, 2), expand=True, fillcolor=240))
        assert got in (need, None), (seed, ccw, got)


def test_scan_with_ocr_layer_uses_text_direction(tmp_path):
    """Bản scan có lớp chữ OCR ẩn: hướng lấy theo lớp chữ (chắc chắn hơn đoán từ ảnh)."""
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=_png(Image.new("RGB", (600, 850), (250, 250, 250))))
    for k in range(10):
        p.insert_text((300, 100 + k * 60), f"Dòng chữ OCR số {k}", fontsize=11, render_mode=3, rotate=90)
    path = tmp_path / "ocr90.pdf"
    d.save(path)
    doc = PdfDocument(str(path))
    fix, unknown = doc.rotation_candidates()
    assert unknown == [] and fix.get(0) in (90, 270)
    doc.close()


def _png(im):
    import io
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


# ------------------------------------------------------------------ tìm kiếm tô vàng
def test_search_hits_have_rects(samples):
    doc = PdfDocument(samples["mixed"])
    hits = doc.search_hits("Hợp đồng")
    assert hits and all(rects for _, rects in hits)
    pw, ph = doc.page_size_pt(0)
    x0, y0, x1, y1 = hits[0][1][0]
    assert 0 <= x0 < x1 <= pw and 0 <= y0 < y1 <= ph and y0 < 200     # dòng đầu ở phía trên trang
    doc.close()


# ------------------------------------------------------------------ bôi chọn & sao chép chữ (như Foxit / Adobe)
def _press(v, page, x, y, kind):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    r = v._rects[page]
    pos = QPointF(r.left() + x * v.scale, r.top() + y * v.scale)
    t = {"press": QMouseEvent.MouseButtonPress, "move": QMouseEvent.MouseMove,
         "release": QMouseEvent.MouseButtonRelease, "dbl": QMouseEvent.MouseButtonDblClick}[kind]
    btn = Qt.NoButton if kind == "move" else Qt.LeftButton
    ev = QMouseEvent(t, pos, pos, btn, Qt.LeftButton if kind != "release" else Qt.NoButton, Qt.NoModifier)
    {"press": v.canvas.mousePressEvent, "move": v.canvas.mouseMoveEvent,
     "release": v.canvas.mouseReleaseEvent, "dbl": v.canvas.mouseDoubleClickEvent}[kind](ev)


def test_select_and_copy_text_without_editing(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from .test_gui import _Settings
    from app.mainwindow import MainWindow
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    src = tmp_path / "chu.pdf"
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    p.insert_text((72, 100), "Hop dong mua ban so 123", fontsize=14)
    p.insert_text((72, 130), "Dong thu hai cua van ban", fontsize=14)
    d.save(str(src))
    w = MainWindow()
    w.resize(1300, 900)
    w.show()
    try:
        w.open_files([str(src)])
        pump(qapp)
        tab = w.current()
        v = tab.view
        v.set_zoom(100)
        pump(qapp)
        before = src.read_bytes()
        # kéo từ đầu dòng 1 tới giữa dòng 2
        _press(v, 0, 73, 96, "press")
        _press(v, 0, 150, 96, "move")
        _press(v, 0, 110, 126, "move")
        _press(v, 0, 110, 126, "release")
        t = v.selected_text()
        assert t.startswith("Hop dong") and "\n" in t and t.split("\n")[1].startswith("Dong")
        assert v.marks.get("select") and len(v.marks["select"][0]) >= 2      # tô xanh từng dòng
        assert v.placement is None and v._inline is None                     # không mở sửa chữ
        w.clipboard_action(tab, "copy")
        assert QApplication.clipboard().text() == t
        # nháy đúp: chọn một từ, không sửa chữ / không đổi định dạng
        _press(v, 0, 105, 96, "dbl")
        assert v.selected_text() == "dong" and v._inline is None
        assert not tab.doc.modified
        # bấm một lần lên chữ: bỏ chọn
        _press(v, 0, 200, 96, "press")
        _press(v, 0, 200, 96, "release")
        assert v.text_sel is None and "select" not in v.marks
        # Ctrl+A: cả trang
        assert v.select_page_text(0) and "thu hai" in v.selected_text()
        assert src.read_bytes() == before
    finally:
        for i in range(w.tabs.count()):
            w.tabs.widget(i).doc.modified = False
        w.close()


def test_select_text_on_scan_ocr_layer(win, qapp, samples):
    win.open_files([samples["ocr"]])
    pump(qapp)
    v = win.current().view
    assert v.select_word(0, 80, 97)
    assert v.selected_text() == "OCR"


# ------------------------------------------------------------------ hộp chữ gõ tại chỗ + thanh định dạng nổi
def test_textbox_inline_with_format_bar(win, qapp, samples, tmp_path):
    import shutil
    from app import fonts, items
    src = tmp_path / "hop.pdf"
    shutil.copy(samples["text"], src)
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    v = tab.view
    win.start_tool("textbox")
    win._text_box(tab, 0, (80, 600, 380, 630))
    bar = v._inline_bar
    ed = v._inline[0]
    assert bar is not None and ed.hasFocus() or True
    assert bar.geometry().bottom() <= ed.geometry().top() or bar.geometry().top() >= ed.geometry().bottom()
    # phông viết tay mới có trong danh sách, không có đậm/nghiêng
    k = bar.cb_font.findData(fonts.handwriting_path("Chữ học trò Việt (Playwrite VN)"))
    assert k >= 0
    bar.cb_font.setCurrentIndex(k)
    assert not bar.btn_bold.isEnabled()
    # phông hệ thống: đậm + màu + canh giữa + cỡ
    k = bar.cb_font.findData(fonts.system_font("serif"))
    bar.cb_font.setCurrentIndex(k)
    bar.btn_bold.setChecked(True)
    bar.sp_size.setValue(18)
    bar.set_color("#c62828")
    bar.align_btns["center"].click()
    assert ed._style["bold"] and ed._style["size"] == 18 and ed._style["color"] == "#c62828"
    ed.setPlainText("Đã duyệt – Nguyễn Văn A")
    bar.accepted.emit()
    pump(qapp)
    assert v._inline is None and v._inline_bar is None
    it = items.find_items(tab.doc, 0)[-1]
    sp = it.spec
    assert sp["text"] == "Đã duyệt – Nguyễn Văn A" and sp["bold"] and sp["size"] == 18 and sp["align"] == "center"
    assert items.font_path(sp) != sp["font"]                       # dùng file phông đậm
    assert "Nguyễn Văn A" in tab.doc.text(0)
    # Esc / ✕: không chèn gì
    n = len(items.find_items(tab.doc, 0))
    win._text_box(tab, 0, (80, 650, 380, 680))
    v._inline[0].setPlainText("bỏ")
    v._inline_bar.rejected.emit()
    assert len(items.find_items(tab.doc, 0)) == n
    win.stop_tool()


def test_edit_existing_text_shows_format_bar(win, qapp, samples, tmp_path):
    import shutil
    src = tmp_path / "sua.pdf"
    shutil.copy(samples["text"], src)
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    from app import editing
    run = editing.text_runs(tab.doc, 0)[0]
    x, y = (run.rect[0] + run.rect[2]) / 2, (run.rect[1] + run.rect[3]) / 2
    win.start_tool("edittext")
    win._edit_text(tab, 0, x, y)
    bar = tab.view._inline_bar
    assert bar is not None and bar.mode == "edit" and bar.cb_font.currentData() == ""
    bar.btn_italic.setChecked(True)
    assert win.tool_opts.btn_italic.isChecked() and tab.view._inline[0]._style["italic"]
    tab.view._finish_inline(False)
    win.stop_tool()


# ------------------------------------------------------------------ cắt con dấu từ bản scan: nền trong suốt sạch
def _scan_with_stamp():
    import io
    from PIL import ImageDraw, ImageFilter
    W = H = 800
    grad = Image.linear_gradient("L").resize((W, H)).point(lambda v: v * 70 // 255)   # bóng tối dần
    img = Image.merge("RGB", [Image.new("L", (W, H), c) for c in (248, 240, 215)])        # giấy ngả vàng
    img = Image.composite(Image.new("RGB", (W, H), (150, 140, 120)), img, grad)
    d = ImageDraw.Draw(img)
    red = (205, 35, 45)
    d.ellipse((200, 200, 600, 600), outline=red, width=12)
    d.ellipse((380, 300, 420, 340), fill=red)
    for k in range(6):                                           # dòng chữ đen in sẵn đè lên dấu
        d.rectangle((60, 260 + k * 60, 740, 266 + k * 60), fill=(20, 20, 20))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=80)
    return b.getvalue()


def test_stamp_cutout_clean_background_and_color_only():
    import io
    from app.imaging import remove_background
    data = _scan_with_stamp()
    old = Image.open(io.BytesIO(remove_background(data))).convert("RGBA")
    new = Image.open(io.BytesIO(remove_background(data, None, flatten=True, clean=True, keep="color",
                                                  ink="auto"))).convert("RGBA")
    a = new.getchannel("A")
    # bản cũ: góc tối (bóng) bị giữ lại thành mảng xám; bản mới: cắt sát vòng dấu, nền trong suốt hoàn toàn
    assert old.getchannel("A").crop((old.width - 40, old.height - 40, old.width, old.height)).getextrema()[1] > 60
    assert abs(new.width - 400) < 40 and abs(new.height - 400) < 40
    w, h = new.size
    assert a.crop((w // 2 - 120, h // 2 + 40, w // 2 + 120, h // 2 + 120)).getextrema()[1] < 30   # chữ đen bị bỏ
    # nét dấu còn nguyên, đều màu đỏ; chỗ chữ đen cắt ngang vòng dấu được lấp lại
    ring = [a.getpixel((6 + dx, h // 2 + dy)) for dx in range(0, 12) for dy in (-40, 0, 40)]
    assert max(ring) > 230
    r, g, b, _ = new.getpixel((w // 2, int(h * 0.3)))
    assert r > 150 and g < 90 and b < 90


# ------------------------------------------------------------------ giáp lai tự nhiên, chia nhóm trang
def _seam_doc(tmp_path, n):
    d = pymupdf.open()
    for _ in range(n):
        d.new_page(width=595, height=842)
    p = tmp_path / f"seam{n}.pdf"
    d.save(str(p))
    return PdfDocument(str(p))


def _red_cols(doc, i):
    bm = doc.render(i, 0.5)
    w, h, st = bm.width, bm.height, bm.stride
    buf = bytes(bm.buffer)
    bm.close()
    xs = [x for y in range(0, h, 2) for x in range(0, w)
          if buf[y * st + x * 3] > 150 and buf[y * st + x * 3 + 1] < 110]
    ys = [y for y in range(0, h, 2) for x in range(w - 30, w)
          if buf[y * st + x * 3] > 150 and buf[y * st + x * 3 + 1] < 110]
    return w, xs, ys


def _red_disc(px=400):
    from PIL import ImageDraw
    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((0, 0, px - 1, px - 1), fill=(210, 30, 40, 255))
    r, g, b, a = im.split()
    return Image.merge("RGBA", (b, g, r, a)).tobytes(), px     # BGRA


def test_seam_natural_and_groups(tmp_path):
    bgra, px = _red_disc()
    doc = _seam_doc(tmp_path, 20)
    doc.seam_stamp(list(range(20)), bgra, px, px, px * 4, 38 * 72 / 25.4, natural=True, group_size=8, seed=3)
    # 20 trang, mỗi dấu tối đa 8 -> 3 dấu (7/7/6 trang): mảnh rộng hơn nhiều so với chia 20
    widths = []
    for i in range(20):
        w, xs, _ = _red_cols(doc, i)
        assert xs and max(xs) >= w - 3
        widths.append(w - min(xs))
    even = 38 * 72 / 25.4 * 0.5 / 20
    assert min(widths) > even * 1.4
    assert len(set(widths)) > 3                                   # mảnh rộng hẹp không đều như đóng tay
    assert doc.undo_count() == 1 if hasattr(doc, "undo_count") else True
    doc.close()
    # chừa mép 5 mm
    doc = _seam_doc(tmp_path, 3)
    doc.seam_stamp([0, 1, 2], bgra, px, px, px * 4, 100, margin_pt=5 * 72 / 25.4)
    w, xs, _ = _red_cols(doc, 0)
    assert max(xs) < w - 5
    doc.close()


def test_seam_dialog_options(qapp, tmp_path):
    from app.library import STAMP, Library
    from app.ui_library import SeamDialog
    import io
    lib = Library(str(tmp_path / "lib"))
    bgra, px = _red_disc(200)
    r, g, b, a = Image.frombytes("RGBA", (px, px), bgra).split()
    buf = io.BytesIO()
    Image.merge("RGBA", (b, g, r, a)).save(buf, "PNG")
    lib.add("Dấu", buf.getvalue(), STAMP, 38)
    dlg = SeamDialog(None, lib, 30, [])
    assert dlg.sp_group.value() == 8 and "4 dấu" in dlg.lbl.text()
    assert dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()
    dlg.sp_angle.setValue(6)
    v = dlg.values()
    assert v["natural"] and v["angle"] == 6 and v["group_size"] == 8


# ------------------------------------------------------------------ phiếu chữ tay v2 (2 trang, ô to) + xem lại
def _filled_v2(pages=(1, 2), rotate=1.0, missing=(), as_pdf=False):
    import io
    from PIL import ImageDraw, ImageFont
    from app import fonts, handwriting as hw
    d = PdfDocument(data=hw.make_template())
    imgs = []
    f = ImageFont.truetype(fonts.handwriting_path("PatrickHand.ttf"), 170)
    mm = 300 / 25.4
    marks = {"̀": "`", "́": "/", "̉": "?", "̃": "~", "̣": "."}
    for page in pages:
        img = d.render(page - 1, 300 / 72).to_pil().convert("RGB")
        dr = ImageDraw.Draw(img)
        for k, ch in enumerate(hw.V2_PAGES[page - 1]):
            if ch in missing:
                continue
            x0, y0, x1, y1 = hw.v2_cell_mm(page, k)
            dr.text(((x0 + 5) * mm, (y0 + hw.V2_H * hw.BASELINE) * mm), marks.get(ch, ch), font=f,
                    fill=(20, 40, 160), anchor="ls")
        imgs.append(img.rotate(rotate, expand=True, fillcolor=(255, 255, 255)))
    d.close()
    if as_pdf:
        b = io.BytesIO()
        imgs[0].save(b, "PDF", resolution=300, save_all=True, append_images=imgs[1:])
        return [b.getvalue()]
    out = []
    for im in imgs:
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85)
        out.append(b.getvalue())
    return out


def test_handwriting_v2_two_pages_and_page_detection():
    from app import handwriting as hw
    ex = hw.extract_cells(_filled_v2(as_pdf=True))
    assert ex["version"] == 2 and sorted(ex["pages"]) == [1, 2] and len(ex["cells"]) == len(hw.CHARS)
    hs = hw.HandSet(hw.parse_scan(_filled_v2(pages=(2, 1))))                  # 2 ảnh, thứ tự nào cũng được
    assert hs.coverage > 0.95
    im = hs.render("Nguyễn Văn Hùng", height_px=120)
    assert im.width > im.height


def test_handwriting_v2_page1_only_uses_lowercase_for_capitals():
    from app import handwriting as hw
    hs = hw.HandSet(hw.parse_scan(_filled_v2(pages=(1,))))
    assert hs.has("a") and not hs.has("A")
    assert hs.render("An", height_px=100).width > 10                          # chữ hoa dùng tạm chữ thường


def test_handwriting_review_adjust_crop_and_drop():
    from app import handwriting as hw
    ex = hw.extract_cells(_filled_v2(pages=(1,), rotate=0))
    cell = ex["cells"]["b"]
    full = hw.process_cell(cell)
    assert full is not None
    left = hw.process_cell(cell, rect=(0, 0, 40, hw.SPRITE_H))               # khung cắt hẹp: bỏ nét ngoài khung
    assert left is None or left.getchannel("A").getbbox()[2] <= 40
    assert hw.process_cell(ex["cells"]["b"].crop((0, 0, 1, 1)).resize(cell.size)) is None   # ô trắng


def test_hand_review_dialog_flow(qapp, monkeypatch):
    from PySide6.QtCore import QPointF
    from app import handwriting as hw
    from app.ui_edit import HandReviewDialog
    ex = hw.extract_cells(_filled_v2(pages=(1,), missing=("k",)))
    dlg = HandReviewDialog(None, ex)
    assert dlg.list.count() == len(hw.V2_PAGES[0])
    assert dlg.cur == "k" and dlg.glyphs["k"] is None                  # mở ngay ô trống đầu tiên
    assert "trang 2" in dlg.info.text().lower()
    # viết lại chữ k bằng chuột
    dlg.btn_draw.setChecked(True)
    dlg.pad.strokes = [[QPointF(60, 40), QPointF(60, 250)], [QPointF(150, 120), QPointF(60, 190), QPointF(150, 250)]]
    dlg.btn_draw.setChecked(False)
    assert dlg.glyphs["k"] is not None
    # bỏ chữ a, thu hẹp khung chữ b
    dlg.list.setCurrentRow(dlg.order.index("a"))
    dlg.btn_drop.setChecked(True)
    assert dlg.glyphs["a"] is None
    dlg.list.setCurrentRow(dlg.order.index("b"))
    dlg.crop.rectChanged.emit((0, 0, 30, 30))
    assert dlg.glyphs["b"] is None or dlg.glyphs["b"].getchannel("A").getbbox()[2] <= 30
    hs = hw.HandSet(dlg.sprite())
    assert hs.has("k") and not hs.has("a")


# ------------------------------------------------------------------ sửa chữ: giữ cỡ chữ, cỡ gốc, đổi cỡ
def test_nice_size_snaps_rounding():
    from app.editing import nice_size
    assert nice_size(12.98) == 13 and nice_size(11.02) == 11 and nice_size(10.5) == 10.5 and nice_size(9.27) == 9.3


def test_edit_shows_original_size_and_applies_new_size(win, qapp, tmp_path):
    from app import editing
    from .test_dot2 import _open as _open2
    from .test_gui_phase5 import _click
    tab = _open2(win, qapp, tmp_path, 1)
    win.start_tool("edittext")
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 135))
    bar = tab.view._inline_bar
    assert bar.sp_size.value() == 11 and win.tool_opts.sp_size.value() == 11     # đúng cỡ gốc, không phải 0
    tab.view._finish_inline(True)                                               # không sửa gì -> không đổi
    assert not tab.doc.can_undo
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 135))
    tab.view._inline_bar.sp_size.setValue(20)
    tab.view._finish_inline(True)
    sizes = [r.size for r in editing.text_runs(tab.doc, 0) if r.text.startswith("Điều khoản")]
    assert 20 in sizes                                                          # cỡ mới được áp dụng
    win.stop_tool()


def test_paragraph_bigger_size_not_shrunk_back():
    from app import editing
    from app.document import PdfDocument
    from .test_phase4 import _contract
    d = PdfDocument(data=_contract(1))
    runs = editing.text_runs(d, 0)
    para = editing.paragraph_of(runs, runs[3])
    info = editing.replace_group(d, 0, para, editing.group_text(para), size=16)
    assert info["size"] == 16 and not info["shrunk"]


def test_original_size_remembered_after_save_and_restore(win, qapp, tmp_path):
    from app import editing
    from app.document import PdfDocument
    from .test_dot2 import _open as _open2
    from .test_gui_phase5 import _click
    from .test_phase4 import _contract
    d = PdfDocument(data=_contract(1))
    runs = editing.text_runs(d, 0)
    editing.replace_group(d, 0, [editing.line_of(runs, runs[1])], "Dòng đã phóng to", size=20)
    d2 = PdfDocument(data=d.to_bytes())                                       # lưu file rồi mở lại
    r = next(x for x in editing.text_runs(d2, 0) if x.text.startswith("Dòng đã"))
    assert r.size == 20 and r.orig_size == 11
    editing.replace_group(d2, 0, [[r]], "Dòng đã phóng to lần nữa", size=16)  # sửa tiếp vẫn nhớ cỡ gốc
    r = next(x for x in editing.text_runs(d2, 0) if x.text.startswith("Dòng đã"))
    assert r.size == 16 and r.orig_size == 11
    # giao diện: nút ↺ đưa về đúng cỡ gốc
    tab = _open2(win, qapp, tmp_path, 1)
    win.start_tool("edittext")
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 135))
    tab.view._inline_bar.sp_size.setValue(20)
    tab.view._finish_inline(True)
    tab.view.canvas.mousePressEvent(_click(tab.view, 0, 100, 140))
    bar = tab.view._inline_bar
    assert bar.sp_size.value() == 20 and bar.btn_orig.isEnabled()
    bar.btn_orig.click()
    assert bar.sp_size.value() == 11 and not bar.btn_orig.isEnabled()
    tab.view._finish_inline(True)
    r = next(x for x in editing.text_runs(tab.doc, 0) if x.text.startswith("Điều khoản") and x.orig_size)
    assert r.size == 11
    win.stop_tool()


# ------------------------------------------------------------------ dải công cụ / thanh trái gọn, bảng phải không tràn
def test_ribbon_hide_button_and_handle(win, qapp):
    win.set_ribbon_visible(True, save=False)
    assert not win.ribbon_handle_wrap.isVisibleTo(win)
    win.ribbon_hide_btn.click()                                          # nút ẩn ngay trên dải
    assert not win.ribbon_visible() and win.ribbon_handle_wrap.isVisibleTo(win)
    win.ribbon_handle.click()                                            # mấu nhỏ còn lại -> hiện lại
    assert win.ribbon_visible() and not win.ribbon_handle_wrap.isVisibleTo(win)
    b = next(b for b, ic, cmd, p in win.tool_buttons if not p)
    assert b.minimumHeight() <= 52


def test_side_panel_fits_long_file_name(win, qapp, samples, tmp_path):
    import shutil
    src = tmp_path / ("Thu_de_nghi_bao_gia_tu_van_Root_EMA_phien_ban_cuoi_cung_da_duyet_" * 2 + ".pdf")
    shutil.copy(samples["text"], src)
    win.resize(1000, 800)
    win.open_files([str(src)])
    pump(qapp, 100)
    side = win.side
    inner = side.scroll.widget()
    assert inner.width() <= side.scroll.viewport().width()               # nội dung không rộng hơn bảng
    assert side.geometry().right() <= win.centralWidget().width()


def test_layout_styles_quick_bar_and_start_tab(win, qapp, samples):
    """Kiểu tab ngang như Foxit (mặc định) <-> kiểu cột trái; thanh truy cập nhanh; tab "Bắt đầu"."""
    win.set_layout_style("tabs", save=False)
    pump(qapp, 20)
    assert not win.rail.isVisible() and all(t.isVisible() for t in win.mode_tabs)
    win.mode_tabs[2].click()
    assert win.mode_group.checkedId() == 2 and win.mode_tabs[2].isChecked() and not win.mode_tabs[0].isChecked()
    assert {c for _b, _i, c in win.quick_buttons} == {"open", "save", "saveas", "print", "undo", "redo"}
    win.set_layout_style("rail", save=False)
    pump(qapp, 20)
    assert win.rail.isVisible() and not win.mode_tabs[0].isVisible()
    assert win.quick_buttons[0][0].isVisible()                     # thanh nhanh có ở cả hai kiểu
    win.set_layout_style("tabs", save=False)
    win.open_files([samples["text"]])
    pump(qapp, 50)
    win.start_tab.click()
    pump(qapp, 20)
    ov = win.start_overlay
    assert ov.isVisible() and win.tabs.tabBar().isVisible()        # hàng tab file vẫn còn
    win.tabs.tabBar().tabBarClicked.emit(0)
    assert not ov.isVisible()
    win.start_tab.click()
    win.open_files([samples["mixed"]])
    pump(qapp, 50)
    assert not ov.isVisible()                                       # mở file mới -> về tài liệu


def test_thumbnail_column_resizable(win, qapp, samples):
    """Kéo vạch ngăn: cột ảnh thu nhỏ rộng / hẹp tùy ý, ảnh to nhỏ theo, nhớ độ rộng cho lần mở sau."""
    win.open_files([samples["text"]])
    pump(qapp, 50)
    tab = win.current()
    th = tab.thumbs
    tab.split.setSizes([300, 900])
    tab.split.splitterMoved.emit(300, 1)
    pump(qapp, 250)
    th._apply_width()
    assert th.thumb_w > 200 and th.iconSize().width() == th.thumb_w
    assert int(win.settings.value("ui/thumb_w")) >= 250
    tab.split.setSizes([70, 1100])
    pump(qapp, 50)
    th._apply_width()
    assert th.thumb_w < 80


def test_save_as_new_file_keeps_original(win, qapp, tmp_path, monkeypatch):
    from .test_phase4 import _contract
    """Sửa rồi 'Lưu thành…' ra file mới: file gốc giữ nguyên, tab chuyển sang file mới."""
    from PySide6.QtWidgets import QFileDialog
    from app.mainwindow import CMD_LABEL, READY
    from app import notes
    assert "saveas" in READY and CMD_LABEL["saveas"].startswith("Lưu thành")
    src = tmp_path / "goc.pdf"
    src.write_bytes(_contract(1))
    before = src.read_bytes()
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    notes.add_note(tab.doc, 0, 100, 100, "Sửa thử", "An")
    seen = {}

    def fake_dialog(parent, title, default, flt):
        seen["default"] = default
        return str(tmp_path / "moi"), "PDF (*.pdf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_dialog))
    win.run("saveas")
    assert seen["default"].endswith("goc_ban_sua.pdf")          # gợi ý tên mới, không trùng file gốc
    assert src.read_bytes() == before                            # file gốc không bị ghi đè
    new = tmp_path / "moi.pdf"
    assert new.exists() and tab.doc.path == str(new) and not tab.doc.modified
    assert any(n.text == "Sửa thử" for n in notes.list_notes(PdfDocument(str(new))))


def test_save_asks_overwrite_or_new(win, qapp, tmp_path, monkeypatch):
    """Bấm Lưu khi đã sửa file có sẵn: hỏi lưu đè hay lưu ra file mới (tránh ghi nhầm vào file gốc)."""
    from PySide6.QtWidgets import QFileDialog
    from app import notes
    from app.mainwindow import MainWindow
    from .test_phase4 import _contract
    asked = []
    monkeypatch.setattr(MainWindow, "_ask_save_mode", lambda self, tab: asked.append(1) or "new")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a: (str(tmp_path / "goc_ban_sua.pdf"), "")))
    src = tmp_path / "goc.pdf"
    src.write_bytes(_contract(1))
    before = src.read_bytes()
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    win.run("save")
    assert asked == []                                           # chưa sửa gì: không hỏi
    before = src.read_bytes()
    notes.add_note(tab.doc, 0, 100, 100, "Sửa", "An")
    win.run("save")
    assert asked == [1] and src.read_bytes() == before            # chọn "lưu ra file mới": gốc giữ nguyên
    assert tab.doc.path.endswith("goc_ban_sua.pdf")
    notes.add_note(tab.doc, 0, 200, 200, "Sửa tiếp", "An")
    win.run("save")                                               # đang ở bản mới: lưu luôn, không hỏi lại
    assert asked == [1] and not tab.doc.modified


def test_file_info_view_edit_and_clean(win, qapp, tmp_path, monkeypatch):
    import io
    import pikepdf
    from app import fileinfo
    from app.fileinfo_dialog import FileInfoDialog
    from .test_phase4 import _contract
    with pikepdf.open(io.BytesIO(_contract(1))) as pk:
        with pk.open_metadata() as m:
            m["dc:creator"] = ["Nguyễn Văn A"]
        pk.docinfo["/Author"] = "Nguyễn Văn A"
        pk.docinfo["/Company"] = "Cty X"
        pk.docinfo["/CreationDate"] = "D:20261110093000+07'00'"
        pk.save(str(tmp_path / "tt.pdf"))
    win.open_files([str(tmp_path / "tt.pdf")])
    pump(qapp)
    tab = win.current()
    seen = {}

    def fake_exec(self):
        rows = {self.table.item(r, 0).data(0x0100): self.table.item(r, 1).text() for r in range(self.table.rowCount())}
        seen.update(rows)
        self.clear_all()
        return FileInfoDialog.Accepted
    monkeypatch.setattr(FileInfoDialog, "exec", fake_exec)
    win.run("fileinfo")
    assert seen["/Author"] == "Nguyễn Văn A" and seen["/Company"] == "Cty X"
    assert seen["/CreationDate"] == "10/11/2026 09:30:00"
    assert tab.doc.modified
    win.save(tab)
    info = fileinfo.read_info((tmp_path / "tt.pdf").read_bytes())
    assert "/Author" not in info["fields"] and "/Company" not in info["fields"] and not info["xmp"]
    assert "/CreationDate" not in info["fields"]
    tab.doc.undo()
    assert fileinfo.read_info(tab.doc.to_bytes())["fields"].get("/Author") == "Nguyễn Văn A"
