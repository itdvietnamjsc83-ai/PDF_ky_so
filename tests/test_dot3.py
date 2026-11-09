"""Đợt 3: xuất Màu / Chữ đen / Xám / Đen trắng (khi mở, kéo thả, thêm vào khay, theo file, theo trang),
bảng tùy chọn mở file, chuyển màu file đang mở, tự nhận hướng trang scan."""
import io
import random
import zlib

import pikepdf
import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QDialog

from app import colormode as CM
from app import orient, ui_import
from app.document import PdfDocument
from app.merge import MergeOptions, TrayItem, merge

from .test_gui import pump
from .test_gui_phase5 import _open, lib_path, qapp, win  # noqa: F401

from app import fonts as _fonts                                        # noqa: E402
FONT = _fonts.system_font("serif")          # Times New Roman trên Windows, DejaVu Serif trên Linux


def color_pdf(pages=1) -> bytes:
    """Trang có: chữ đỏ, chữ trắng trên nền xanh, khối tô xanh, ảnh màu, dải màu chuyển (shading)."""
    pdf = pikepdf.new()
    img = Image.new("RGB", (60, 40), (220, 30, 30))
    ImageDraw.Draw(img).ellipse((30, 0, 60, 40), fill=(30, 120, 220))
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))
        pg = pdf.pages[-1]
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                    BaseFont=pikepdf.Name.Helvetica))
        im = pikepdf.Stream(pdf, zlib.compress(img.tobytes()))
        im.Type, im.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        im.Width, im.Height, im.BitsPerComponent = 60, 40, 8
        im.ColorSpace, im.Filter = pikepdf.Name.DeviceRGB, pikepdf.Name.FlateDecode
        sh = pdf.make_indirect(pikepdf.Dictionary(
            ShadingType=2, ColorSpace=pikepdf.Name.DeviceRGB, Coords=[72, 0, 272, 0], Extend=[True, True],
            Function=pikepdf.Dictionary(FunctionType=2, Domain=[0, 1], C0=[1, 0, 0], C1=[0, 0, 1], N=1)))
        pg.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font), XObject=pikepdf.Dictionary(Im1=im),
                                          Shading=pikepdf.Dictionary(Sh1=sh))
        pg.Contents = pikepdf.Stream(pdf, b"""
0.9 0.1 0.1 rg BT /F1 28 Tf 72 760 Td (RED TEXT) Tj ET
0.1 0.3 0.8 rg 72 650 300 50 re f
1 1 1 rg BT /F1 20 Tf 80 665 Td (WHITE ON BLUE) Tj ET
q 120 0 0 80 72 520 cm /Im1 Do Q
q 72 400 200 60 re W n /Sh1 sh Q
""")
    b = io.BytesIO()
    pdf.save(b)
    return b.getvalue()


def _render(data, page=0, scale=1.0):
    d = PdfDocument(data=data)
    im = d.render(page, scale).to_pil().convert("RGB")
    d.close()
    return im


def _sat(im, box):
    """Độ bão hòa màu lớn nhất trong vùng (0 = hoàn toàn xám)."""
    reg = im.crop(box)
    return max(max(p) - min(p) for p in reg.get_flattened_data())


def _dark(im, box):
    return min(sum(p) / 3 for p in im.crop(box).get_flattened_data())


# vùng (pt -> px ở scale 1, gốc trên-trái): chữ đỏ, khối xanh, ảnh, dải màu
RED_TXT = (72, 842 - 790, 260, 842 - 755)
BLUE_BOX = (380 - 10, 842 - 700, 372, 842 - 650)
BLUE_BOX = (300, 842 - 698, 370, 842 - 652)
IMAGE = (72, 842 - 600, 192, 842 - 520)
SHADE = (72, 842 - 460, 272, 842 - 400)


def test_gray_keeps_text_removes_color():
    src = color_pdf()
    out = CM.convert_bytes(src, {0: "gray"})
    im = _render(out)
    for box in (RED_TXT, BLUE_BOX, IMAGE, SHADE):
        assert _sat(im, box) <= 6, box
    assert _sat(_render(src), RED_TXT) > 100
    assert "RED TEXT" in PdfDocument(data=out).text(0)          # chữ vẫn là chữ thật


def test_bw_text_black_fills_light():
    out = CM.convert_bytes(color_pdf(), {0: "bw"})
    im = _render(out)
    assert _dark(im, RED_TXT) < 40                                  # chữ màu -> đen
    box = im.crop(BLUE_BOX)
    assert min(sum(p) / 3 for p in box.get_flattened_data()) > 150             # nền tô đậm -> xám nhạt
    px = [p[0] for p in im.crop(IMAGE).get_flattened_data()]
    assert _sat(im, IMAGE) == 0 and sum(1 for v in px if 40 < v < 215) < len(px) * 0.2   # ảnh 1-bit đen trắng
    assert "WHITE ON BLUE" in PdfDocument(data=out).text(0)


def test_blacktext_only_text_changes():
    out = CM.convert_bytes(color_pdf(), {0: "blacktext"})
    im = _render(out)
    assert _sat(im, RED_TXT) <= 30 and _dark(im, RED_TXT) < 40     # chữ đỏ -> đen
    assert _sat(im, BLUE_BOX) > 100                                 # khối tô xanh giữ nguyên màu
    assert _sat(im, IMAGE) > 100 and _sat(im, SHADE) > 100          # ảnh, dải màu giữ nguyên
    # chữ trắng trên nền xanh vẫn trắng (đọc được)
    reg = im.crop((80, 842 - 682, 250, 842 - 662))
    assert max(sum(p) / 3 for p in reg.get_flattened_data()) > 240


def test_scan_page_bw_is_small():
    img = Image.new("RGB", (1240, 1754), (250, 244, 228))
    dr = ImageDraw.Draw(img)
    F = ImageFont.truetype(FONT, 30)
    for k in range(30):
        dr.text((100, 100 + k * 50), f"Dòng {k + 1} nội dung scan màu", font=F, fill=(40, 40, 60))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=85)
    p = pytest.importorskip("tempfile").mktemp(suffix=".jpg")
    open(p, "wb").write(b.getvalue())
    d = PdfDocument.from_images([p])
    data = d.to_bytes()
    bw = CM.convert_bytes(data, {0: "bw"})
    gray = CM.convert_bytes(data, {0: "gray"})
    assert len(bw) < len(data) / 5 and len(gray) < len(data)


def test_only_listed_pages_change():
    src = color_pdf(3)
    out = CM.convert_bytes(src, {1: "gray"})
    assert _sat(_render(out, 0), RED_TXT) > 100 and _sat(_render(out, 1), RED_TXT) <= 6
    assert _sat(_render(out, 2), RED_TXT) > 100


def test_convert_document_undo():
    d = PdfDocument(data=color_pdf(2))
    CM.convert_document(d, [0, 1], "gray")
    assert d.modified and d.can_undo
    d.undo()
    assert _sat(d.render(0, 1).to_pil().convert("RGB"), RED_TXT) > 100


def test_merge_color_modes(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(color_pdf(2))
    b.write_bytes(color_pdf(2))
    it_a = TrayItem(str(a), page_count=2, color="gray", page_colors={"1": "color"})
    it_b = TrayItem(str(b), page_count=2, page_colors={"0": "blacktext"})
    opts = MergeOptions(duplex=False, auto_rotate=False, color="bw")
    doc = merge([it_a, it_b], opts)
    data = doc.to_bytes()
    assert _sat(_render(data, 0), RED_TXT) <= 6                     # file a: xám
    assert _sat(_render(data, 1), RED_TXT) > 100                    # trang riêng: màu
    im2 = _render(data, 2)
    assert _sat(im2, BLUE_BOX) > 100 and _dark(im2, RED_TXT) < 40   # trang riêng: chữ đen
    assert min(sum(p) / 3 for p in _render(data, 3).crop(BLUE_BOX).get_flattened_data()) > 150   # theo chung: đen trắng
    assert it_b.mode_of(1, "bw") == "bw" and it_a.mode_of(0) == "gray"


# ------------------------------------------------------------------ khay: cột Màu, xem trước từng trang
def test_tray_color_column_and_preview(win, qapp, tmp_path):
    a = tmp_path / "mau.pdf"
    a.write_bytes(color_pdf(3))
    t = win.show_tray()
    t.quiet = True
    t.items.clear()
    t.add_paths([str(a)])
    it = t.items[-1]
    col = t.table.cellWidget(0, 9)
    col.setCurrentIndex(col.findData("gray"))
    assert it.color == "gray"
    t.cmb_color.setCurrentIndex(t.cmb_color.findData("bw"))
    assert t.opts.color == "bw"
    t.table.selectRow(0)
    pump(qapp, 300)
    pv = t.preview
    pv.picker.clearSelection()
    pv.picker.item(1).setSelected(True)
    pv.color_buttons["blacktext"].click()
    assert it.page_colors == {"1": "blacktext"} and "Chữ đen" in pv.picker.item(1).text()
    assert "Xám" in pv.picker.item(0).text()
    pump(qapp, 800)
    assert pv._conv                                              # xem trước vẽ từ bản đã chuyển màu
    col = t.table.cellWidget(0, 9)
    assert "*" in col.currentText()                               # có trang đặt riêng
    t.items.clear()
    t.refresh()
    t.close()


# ------------------------------------------------------------------ mở file: bảng tùy chọn
def test_import_dialog_modes_and_merge(win, qapp, tmp_path, monkeypatch):
    a = tmp_path / "a.pdf"
    a.write_bytes(color_pdf(1))
    img = tmp_path / "anh.png"
    Image.new("RGB", (800, 600), (200, 30, 30)).save(img)

    def fake_exec(self):
        assert [ui_import.file_kind(p) for p in self.paths] == ["PDF", "Ảnh"]
        self.combos[0].setCurrentIndex(self.combos[0].findData("blacktext"))
        self.combos[1].setCurrentIndex(self.combos[1].findData("gray"))
        return QDialog.Accepted
    monkeypatch.setattr(ui_import.ImportOptionsDialog, "exec", fake_exec)
    n0 = win.tabs.count()
    tabs = win.import_files([str(a), str(img)])
    assert len(tabs) == 2 and win.tabs.count() == n0 + 2
    assert _dark(tabs[0].doc.render(0, 1).to_pil().convert("RGB"), RED_TXT) < 40
    assert tabs[0].doc.can_undo                                   # về màu gốc bằng Ctrl+Z
    im = tabs[1].doc.render(0, 0.3).to_pil().convert("RGB")
    assert max(max(p) - min(p) for p in im.get_flattened_data()) <= 4

    def fake_merge(self):
        self.rb_merge.setChecked(True)
        return QDialog.Accepted
    monkeypatch.setattr(ui_import.ImportOptionsDialog, "exec", fake_merge)
    tabs = win.import_files([str(a), str(img)])
    assert len(tabs) == 1 and tabs[0].doc.page_count == 2 and tabs[0].title.startswith("Gop_2")


def test_import_single_pdf_no_dialog_and_dont_ask(win, qapp, tmp_path, monkeypatch):
    a = tmp_path / "a.pdf"
    a.write_bytes(color_pdf(1))
    called = []
    monkeypatch.setattr(ui_import.ImportOptionsDialog, "exec", lambda self: called.append(1) or QDialog.Rejected)
    win.import_files([str(a)])                                    # 1 file PDF: mở luôn
    assert not called
    img = tmp_path / "x.png"
    Image.new("RGB", (100, 100), "red").save(img)
    win.settings.setValue("import/ask", False)
    win.settings.setValue("import/color", "gray")
    tabs = win.import_files([str(img)])                           # không hỏi lại: dùng lựa chọn đã nhớ
    assert not called and len(tabs) == 1
    im = tabs[0].doc.render(0, 0.3).to_pil().convert("RGB")
    assert max(max(p) - min(p) for p in im.get_flattened_data()) <= 4
    dlg = ui_import.ImportSettingsDialog(win, win.settings)
    assert not dlg.chk_ask.isChecked()
    dlg.chk_ask.setChecked(True)
    dlg.accept()
    assert str(win.settings.value("import/ask")).lower() == "true"


def test_color_mode_command(win, qapp, tmp_path, monkeypatch):
    a = tmp_path / "a.pdf"
    a.write_bytes(color_pdf(3))
    win.open_files([str(a)])
    pump(qapp)
    tab = win.current()

    def fake_exec(self):
        self.modes["gray"].setChecked(True)
        self.scope["range"].setChecked(True)
        self.ed_range.setText("2-3")
        return QDialog.Accepted
    monkeypatch.setattr(ui_import.ColorModeDialog, "exec", fake_exec)
    win.run("colormode")
    d = tab.doc
    assert _sat(d.render(0, 1).to_pil().convert("RGB"), RED_TXT) > 100
    assert _sat(d.render(1, 1).to_pil().convert("RGB"), RED_TXT) <= 6
    assert "2 trang" in win.lbl_msg.text()


def test_multipage_tiff(tmp_path):
    p = tmp_path / "scan.tif"
    frames = [Image.new("RGB", (400, 560), c) for c in ("white", "yellow", "gray")]
    frames[0].save(p, save_all=True, append_images=frames[1:], dpi=(100, 100))
    d = PdfDocument.from_images([str(p)])
    assert d.page_count == 3 and abs(d.page_size_pt(0)[0] - 288) < 1


# ------------------------------------------------------------------ 20a: hướng trang scan
WORDS = ("hợp đồng mua bán hàng hóa giữa công ty trách nhiệm hữu hạn và bên mua điều khoản thanh toán giao hàng "
         "bảo hành chất lượng sản phẩm Việt Nam số lượng đơn giá tổng cộng").split()


def scan_image(lines=30, seed=3):
    random.seed(seed)
    im = Image.new("L", (1240, 1754), 245)
    dr = ImageDraw.Draw(im)
    F = ImageFont.truetype(FONT, 26)
    for k in range(lines):
        dr.text((100, 120 + k * 44), " ".join(random.choice(WORDS) for _ in range(8)).capitalize(), font=F, fill=30)
    return im


@pytest.mark.parametrize("ccw,need", [(0, 0), (90, 90), (180, 180), (270, 270)])
def test_orient_detect(ccw, need):
    im = scan_image().rotate(ccw, expand=True)                  # xoay ngược chiều kim đồng hồ
    got, conf = orient.detect(im)
    assert got == need and conf > 0.3


def test_orient_blank_unsure():
    assert orient.detect(Image.new("L", (800, 1100), 250))[0] is None


def test_auto_rotate_scan_pages(tmp_path):
    ims = [scan_image(seed=1), scan_image(seed=2).rotate(180), scan_image(seed=3).rotate(90, expand=True)]
    paths = []
    for k, im in enumerate(ims):
        p = tmp_path / f"s{k}.png"
        im.convert("RGB").save(p, dpi=(150, 150))
        paths.append(str(p))
    d = PdfDocument.from_images(paths)
    fix, unknown = d.rotation_candidates()
    assert fix == {1: 180, 2: 90} and unknown == []
    d.auto_rotate()
    assert [d.page(i).get_rotation() for i in range(3)] == [0, 180, 90]
