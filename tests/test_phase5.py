"""Giai đoạn 5 – lõi chỉnh sửa: chữ, hình, vẽ tay, ghi chú, sửa chữ, tìm & thay, tẩy vùng,
sửa/xóa ảnh đã chèn, ảnh scan đúng kích thước thật, bộ chữ tay từ phiếu mẫu."""
import io
import math
import time

import pytest

from app import editing, fonts, handwriting as hw, imaging
from app.document import PdfDocument

from .conftest import pymupdf
from .test_phase4 import _contract


def _doc(rot=0, pages=1):
    return PdfDocument(data=_contract(pages, rotate=rot))


def _ink_bbox(doc, page, pred, scale=1.0):
    img = doc.render(page, scale).to_pil().convert("RGB")
    px = img.load()
    xs, ys = [], []
    for y in range(0, img.height, 2):
        for x in range(0, img.width, 2):
            if pred(*px[x, y]):
                xs.append(x)
                ys.append(y)
    return (min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale) if xs else None


def red(r, g, b):
    return r > 150 and g < 90 and b < 90


def blue(r, g, b):
    return b > 120 and r < 90 and g < 110


# ------------------------------------------------------------------ phông
def test_fonts_available_and_vietnamese():
    for fam in ("serif", "sans"):
        p = fonts.system_font(fam)
        assert not fonts.missing_chars(p, "Tiếng Việt: ạệữỳđĐƯỜ")
    for name in fonts.HANDWRITING:
        assert not fonts.missing_chars(fonts.handwriting_path(name), "Nguyễn Văn Đức – ưởỡ")


def test_family_mapping():
    assert fonts.family_of("ABCDEF+TimesNewRomanPS-BoldMT") == "serif"
    assert fonts.family_of("Arial-ItalicMT") == "sans"
    assert fonts.family_of("Calibri") == "calibri"
    assert fonts.family_of("") == "serif"


def test_subset_is_small():
    p = fonts.system_font("serif")
    assert len(fonts.subset(p, "Xin chào")) < 30_000


def test_wrap():
    p = fonts.system_font("sans")
    lines = fonts.wrap(p, "một hai ba bốn năm sáu bảy tám chín mười", 12, 80)
    assert len(lines) > 2 and all(fonts.measure(p, l, 12) <= 80 or " " not in l for l in lines)


# ------------------------------------------------------------------ chữ
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_add_text_upright_and_searchable(rot):
    d = PdfDocument()
    d.insert_blank(-1)
    if rot:
        d.rotate_pages([0], rot)
    before = len(d.to_bytes())
    x0, y0, x1, y1 = editing.add_text(d, 0, 100, 150, "Chữ thử ĐỎ", size=30, color="#e00000")
    box = _ink_bbox(d, 0, red)
    assert box and x0 - 3 <= box[0] and box[2] <= x1 + 3 and y0 - 3 <= box[1] and box[3] <= y1 + 3
    assert (box[2] - box[0]) > (box[3] - box[1]) * 2           # đứng thẳng: ngang dài hơn cao
    assert "Chữ thử ĐỎ" in d.text(0)
    assert len(d.to_bytes()) - before < 40_000                  # phông rút gọn -> nhẹ


def test_add_text_wraps_in_box():
    d = _doc()
    x0, y0, x1, y1 = editing.add_text(d, 0, 300, 400, "một hai ba bốn năm sáu bảy tám chín mười mười một",
                                      size=12, width=120)
    assert x1 == 420 and y1 - y0 > 40


def test_missing_glyph_rejected():
    d = _doc()
    with pytest.raises(ValueError):
        editing.add_text(d, 0, 10, 10, "漢字", fonts.handwriting_path("PatrickHand.ttf"))


# ------------------------------------------------------------------ hình, ký hiệu, vẽ tay, ghi chú
@pytest.mark.parametrize("kind", ["rect", "ellipse", "line", "arrow", "check", "cross", "dot", "circle", "box",
                                  "boxcheck"])
def test_shapes_inside_rect(kind):
    d = PdfDocument()
    d.insert_blank(-1)
    rect = (200, 300, 260, 360)
    editing.add_shape(d, 0, kind, rect, stroke="#e00000", width=2)
    box = _ink_bbox(d, 0, red)
    assert box and rect[0] - 6 <= box[0] and box[2] <= rect[2] + 6 and rect[1] - 6 <= box[1] and box[3] <= rect[3] + 6
    assert d.can_undo and d.modified


def test_highlight_keeps_text_readable():
    d = _doc()
    editing.add_shape(d, 0, "highlight", (70, 85, 300, 105))
    img = d.render(0, 1).to_pil().convert("RGB")
    dark = sum(1 for x in range(75, 290) for y in range(88, 102) if sum(img.getpixel((x, y))) < 200)
    assert dark > 50                                             # chữ dưới lớp dạ quang vẫn thấy


def test_ink_smooth_and_small():
    d = PdfDocument()
    d.insert_blank(-1)
    pts = [(100 + k * 0.5, 300 + 20 * math.sin(k / 20)) for k in range(600)]
    before = len(d.to_bytes())
    editing.add_ink(d, 0, [pts], color="#1030c0", width=2)
    assert _ink_bbox(d, 0, blue)
    assert len(d.to_bytes()) - before < 6000                     # 600 điểm -> rút gọn còn ít đoạn cong
    assert len(editing.simplify(pts)) < 120


def test_note_annotation():
    d = _doc()
    editing.add_note(d, 0, 400, 200, "Cần bổ sung phụ lục", "Kế toán")
    d2 = PdfDocument(data=d.to_bytes())
    assert editing.notes(d2, 0) == ["Cần bổ sung phụ lục"]


# ------------------------------------------------------------------ sửa chữ, tìm & thay, tẩy
def test_text_runs_and_replace():
    d = _doc()
    run = editing.run_at(d, 0, 100, 95)
    assert run and run.text.startswith("HỢP ĐỒNG") and run.size == 14
    editing.replace_run(d, 0, run, "HỢP ĐỒNG MUA BÁN")
    t = d.text(0)
    assert "HỢP ĐỒNG MUA BÁN" in t and "KINH TẾ" not in t
    new = editing.run_at(d, 0, 100, 95)
    assert new.size == pytest.approx(14, abs=0.1) and abs(new.rect[0] - run.rect[0]) < 2
    d.undo()
    assert "KINH TẾ" in d.text(0)


def test_replace_empty_deletes_line():
    d = _doc()
    run = editing.run_at(d, 0, 100, 95)
    editing.replace_run(d, 0, run, "")
    assert "HỢP ĐỒNG" not in d.text(0)


def test_find_replace_all_pages_single_undo():
    d = _doc(pages=3)
    done, left = editing.find_replace(d, "điều khoản", "Điều mục")
    assert done == 30 and left == 0
    assert "Điều mục" in d.text(2) and "khoản" not in d.text(1)
    d.undo()
    assert "Điều khoản" in d.text(0) and "Điều khoản" in d.text(2)


def test_find_replace_skips_scan_pages(samples):
    d = PdfDocument(samples["scan"])
    assert editing.find_replace(d, "abc", "x") == (0, 0)


def test_erase_area_removes_text():
    d = _doc()
    n = editing.erase_area(d, 0, (60, 125, 560, 165))
    assert n == 2
    assert d.text(0).count("Điều khoản") == 8


# ------------------------------------------------------------------ ảnh đã chèn: sửa / xóa
def _with_image():
    d = PdfDocument()
    d.insert_blank(-1)
    w, h = 80, 40
    d.insert_image(0, (100, 100, 260, 180), bytes([230, 0, 0, 255]) * (w * h), w, h)
    return d


def test_image_move_resize_delete_undo():
    d = _with_image()
    info = editing.image_at(d, 0, 150, 150)
    assert info and info.rect == pytest.approx((100, 100, 260, 180))
    assert editing.image_preview(d, 0, info.index).size == (80, 40)
    e = editing.ObjectEdit(d, 0, info)
    assert editing.image_at(d, 0, 150, 150) is None             # đang kéo: tạm gỡ khỏi trang
    e.commit((300, 500, 380, 540))
    assert _ink_bbox(d, 0, red) == pytest.approx((300, 500, 380, 540), abs=3)
    d.undo()
    assert editing.image_at(d, 0, 150, 150)
    e = editing.ObjectEdit(d, 0, editing.image_at(d, 0, 150, 150))
    e.delete()
    assert _ink_bbox(d, 0, red) is None
    d.undo()
    e = editing.ObjectEdit(d, 0, editing.image_at(d, 0, 150, 150))
    n = len(d._undo)
    e.cancel()
    assert len(d._undo) == n - 1 and editing.image_at(d, 0, 150, 150)


def test_scan_background_not_selectable(samples):
    d = PdfDocument(samples["scan"])
    assert editing.image_at(d, 0, 300, 400) is None


def test_moved_image_keeps_original_data():
    d = PdfDocument()
    d.insert_blank(-1)
    jpg = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (400, 300), (200, 30, 30)).save(jpg, "JPEG", quality=80)
    d.insert_image(0, (50, 50, 250, 200), b"", 0, 0, jpeg=jpg.getvalue())
    size0 = len(d.to_bytes())
    e = editing.ObjectEdit(d, 0, editing.image_at(d, 0, 100, 100))
    e.commit((100, 300, 300, 450))
    assert abs(len(d.to_bytes()) - size0) < 500                 # không nén lại ảnh


# ------------------------------------------------------------------ ảnh scan đúng kích thước thật
def _a4_scan_with_stamp(dpi=600, mm=40, meta=True):
    from PIL import Image, ImageDraw
    W, H = int(8.27 * dpi), int(11.69 * dpi)
    img = Image.new("RGB", (W, H), (250, 248, 244))
    px = mm / 25.4 * dpi
    ImageDraw.Draw(img).ellipse((W / 2 - px / 2, H / 2 - px / 2, W / 2 + px / 2, H / 2 + px / 2),
                                outline=(200, 20, 30), width=int(dpi / 20))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=80, **({"dpi": (dpi, dpi)} if meta else {}))
    return b.getvalue()


@pytest.mark.parametrize("meta", [True, False])
def test_scan_600dpi_real_size(meta):
    data = _a4_scan_with_stamp(meta=meta)
    assert imaging.scan_dpi(data) == pytest.approx(600, abs=2)
    assert imaging.ink_width_mm(data) == pytest.approx(40, abs=1.2)
    png = imaging.remove_background(data)
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    assert im.width / im.info["dpi"][0] * 25.4 == pytest.approx(41, abs=1.5)   # PNG ghi lại DPI thật
    assert im.width > 800                                        # cắt sát trước khi thu nhỏ -> vẫn nét


def test_photo_without_dpi_unknown():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1200, 900), (255, 255, 255)).save(b, "JPEG")
    assert imaging.scan_dpi(b.getvalue()) is None and imaging.ink_width_mm(b.getvalue()) is None


# ------------------------------------------------------------------ bộ chữ tay
def _filled_scan(rotate=1.5, missing=()):
    from PIL import Image, ImageDraw, ImageFont
    d = PdfDocument(data=hw.make_template())
    img = d.render(0, 300 / 72).to_pil().convert("RGB")
    d.close()
    dr = ImageDraw.Draw(img)
    f = ImageFont.truetype(fonts.handwriting_path("PatrickHand.ttf"), 150)
    mm = 300 / 25.4
    marks = {"̀": "`", "́": "/", "̉": "?", "̃": "~", "̣": "."}
    for k, ch in enumerate(hw.CHARS):
        if ch in missing:
            continue
        x0, y0, x1, y1 = hw.cell_rect_mm(k)
        dr.text(((x0 + 5) * mm, (y0 + hw.CELL_H * hw.BASELINE) * mm), marks.get(ch, ch), font=f,
                fill=(20, 40, 160), anchor="ls")
    img = img.rotate(rotate, expand=True, fillcolor=(255, 255, 255))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=85)
    return b.getvalue()


def test_template_small_and_fast():
    t = time.perf_counter()
    data = hw.make_template()
    assert time.perf_counter() - t < 2 and len(data) < 60_000
    d = PdfDocument(data=data)
    assert "PHIẾU MẪU CHỮ VIẾT TAY" in d.text(0) and len(hw.CHARS) <= hw.COLS * hw.ROWS


def test_homography_exact():
    src = [(0, 0), (10, 0), (0, 10), (10, 10)]
    dst = [(5, 5), (25, 6), (4, 26), (26, 27)]
    h = hw.homography(src, dst)
    for a, b in zip(src, dst):
        assert hw._apply(h, *a) == pytest.approx(b, abs=1e-6)


def test_parse_scan_and_compose():
    sprite = hw.parse_scan(_filled_scan(missing=("q", "Q")))
    hs = hw.HandSet(sprite)
    assert hs.coverage > 0.95 and not hs.has("q")
    im = hs.render("Nguyễn Văn Hùng\nĐã duyệt", height_px=120)
    assert im.mode == "RGBA" and im.width > im.height
    one = hs.render("Hùng", height_px=120)
    base = hs.render("Hung", height_px=120)
    assert one.height > base.height                              # dấu huyền nằm trên chữ u
    q = hs.render("q", height_px=120)                            # ô bỏ trống -> dùng chữ hoa/thường khác hoặc bỏ qua
    assert q.size[0] >= 1


def test_parse_scan_pdf_input():
    from PIL import Image
    img = Image.open(io.BytesIO(_filled_scan(rotate=0)))
    b = io.BytesIO()
    img.save(b, "PDF", resolution=300)
    assert hw.HandSet(hw.parse_scan(b.getvalue())).coverage > 0.9


def test_parse_scan_rejects_wrong_image():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1000, 1400), (255, 255, 255)).save(b, "PNG")
    with pytest.raises(ValueError):
        hw.parse_scan(b.getvalue())


def test_text_edit_performance():
    d = PdfDocument(data=_contract(1))
    for k in range(30):
        editing.add_text(d, 0, 50, 300 + k * 10, f"Dòng {k}", size=8)
    t = time.perf_counter()
    for k in range(20):
        editing.add_shape(d, 0, "rect", (50, 50, 100, 100))
    assert time.perf_counter() - t < 3
    assert pymupdf  # dùng fixture tạo file mẫu


def test_edits_survive_save_and_reopen(tmp_path):
    """Chữ sửa/thêm phải còn đúng sau khi lưu và mở lại (lỗi trùng tên phông của PDFium)."""
    d = _doc(pages=2)
    run = editing.run_at(d, 0, 100, 95)
    editing.replace_run(d, 0, run, "HỢP ĐỒNG MUA BÁN")
    editing.find_replace(d, "Điều khoản", "Điều mục")
    editing.add_text(d, 1, 72, 700, "Chữ thêm – ạệữ", size=12)
    p = str(tmp_path / "luu.pdf")
    d.save(p)
    d2 = PdfDocument(p)
    assert "HỢP ĐỒNG MUA BÁN" in d2.text(0) and d2.text(1).count("Điều mục") == 10
    assert "Chữ thêm – ạệữ" in d2.text(1)
