"""Giai đoạn 2: dải trang, tự xoay, trích/tách, đổi khổ, chèn ảnh, khay ghép, máy in ảo."""
import os
import time

import pikepdf
import pymupdf
import pytest

from app.document import BLANK, SCAN, TEXT, PdfDocument, format_ranges, parse_ranges
from app.merge import MergeOptions, TrayItem, count_pages, load_template, merge, plan, save_template, sheets
from app.pagetools import split_groups, write_split

from .conftest import _font_page, _image_bytes


# ---------------- tiện ích ----------------
def dark_box(bm, thr=100):
    """Khung bao các điểm tối trên ảnh render, tỉ lệ 0..1 (x0, y0, x1, y1)."""
    w, h, st = bm.width, bm.height, bm.stride
    buf = bytes(bm.buffer)
    xs, ys = [], []
    for y in range(0, h, 2):
        row = buf[y * st: y * st + w * 3]
        for x in range(0, w, 2):
            if row[x * 3] < thr and row[x * 3 + 1] < thr:
                xs.append(x)
                ys.append(y)
    bm.close()
    if not xs:
        return None
    return min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h


def make(pages):
    """pages: danh sách hàm vẽ trang lên doc pymupdf -> PdfDocument."""
    d = pymupdf.open()
    for fn in pages:
        fn(d)
    return PdfDocument(data=d.tobytes())


def text_page(rot_text=0, page_rot=0, w=595, h=842):
    def f(d):
        p = d.new_page(width=w, height=h)
        for k in range(12):
            p.insert_text((100 if rot_text == 0 else 200 + k * 20, 100 + k * 20 if rot_text == 0 else 700),
                          "Noi dung van ban mau so %d" % k, fontsize=11, rotate=rot_text)
        p.set_rotation(page_rot)
    return f


def black_rect_page(page_rot=0):
    def f(d):
        p = d.new_page(width=595, height=842)
        p.draw_rect(pymupdf.Rect(50, 50, 250, 120), color=(0, 0, 0), fill=(0, 0, 0))
        p.set_rotation(page_rot)
    return f


# ---------------- dải trang ----------------
@pytest.mark.parametrize("text,expect", [
    ("1-3, 5, 8-", [0, 1, 2, 4, 7, 8, 9]), ("", list(range(10))), ("tất cả", list(range(10))),
    ("lẻ", [0, 2, 4, 6, 8]), ("chẵn", [1, 3, 5, 7, 9]), ("-2", [0, 1]), ("3–1", [2, 1, 0]),
    ("10", [9]), (" 2 ; 4 ", [1, 3]),
])
def test_parse_ranges(text, expect):
    assert parse_ranges(text, 10) == expect


@pytest.mark.parametrize("bad", ["0", "11", "1-11", "abc", "2-x"])
def test_parse_ranges_errors(bad):
    with pytest.raises(ValueError):
        parse_ranges(bad, 10)


def test_format_ranges():
    assert format_ranges([0, 1, 2, 4, 7, 8, 9]) == "1-3, 5, 8-10"
    assert format_ranges([]) == ""


# ---------------- tự xoay ----------------
def test_auto_rotate_text_pages():
    d = make([text_page(), text_page(rot_text=90), text_page(page_rot=90), text_page(page_rot=180),
              lambda d: d.new_page()])
    done = d.auto_rotate()
    assert done == [1, 2, 3]
    for i in range(4):
        assert d.text_rotation_fix(i) == d.page(i).get_rotation()
    assert d.page(0).get_rotation() == 0            # trang đúng sẵn không bị động tới
    d.undo()
    assert d.page(2).get_rotation() == 90


def test_auto_rotate_skips_scan(samples):
    d = PdfDocument(samples["scan"])
    assert d.auto_rotate() == [] and not d.modified


# ---------------- trích / tách ----------------
def test_extract_and_split(samples, tmp_path):
    d = PdfDocument(samples["mixed"])
    data = d.extract([3, 0])
    e = PdfDocument(data=data)
    assert e.page_count == 2 and e.page_kind(0) == SCAN and e.page_kind(1) == TEXT
    assert split_groups(10, "every", 3, []) == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    assert split_groups(4, "single", 0, []) == [[0], [1], [2], [3]]
    assert split_groups(10, "ranges", "1-3, 4-6; 7-", []) == [[0, 1, 2], [3, 4, 5], [6, 7, 8, 9]]
    assert split_groups(10, "selected", 0, [5, 2]) == [[2, 5]]
    with pytest.raises(ValueError):
        split_groups(10, "selected", 0, [])
    files = write_split(d, split_groups(4, "every", 2, []), str(tmp_path / "out"), "hs")
    assert [os.path.basename(f) for f in files] == ["hs_1_trang_1-2.pdf", "hs_2_trang_3-4.pdf"]
    assert [count_pages(f) for f in files] == [2, 2]


# ---------------- đổi kích thước ----------------
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_resize_keeps_orientation_and_content(rot):
    d = make([black_rect_page(rot)])
    before = dark_box(d.render(0, 0.3))
    d.resize_pages([0], "A4", "keep", "fit")          # cùng khổ -> nội dung giữ nguyên chỗ
    after = dark_box(d.render(0, 0.3))
    assert after == pytest.approx(before, abs=0.02)
    d.resize_pages([0], "A5", "keep", "fit")
    info = d.page_info(0)
    assert info.paper == "A5" and info.landscape == (rot in (90, 270))
    assert dark_box(d.render(0, 0.3)) == pytest.approx(before, abs=0.03)   # co đều -> tỉ lệ như cũ


def test_resize_modes_and_vector_text(samples):
    d = PdfDocument(samples["mixed"])                 # trang 3 là A4 ngang
    d.resize_pages([0, 2], "A5", "portrait", "fit", margin_mm=10)
    assert d.page_info(0).paper == "A5" and not d.page_info(2).landscape
    assert "Hợp đồng" in d.text(0)                    # chữ vẫn là chữ thật (vector)
    assert d.page_info(1).paper == "A4"               # trang không chọn giữ nguyên
    d.resize_pages([3], "A3", "keep", "none")
    assert d.page_info(3).paper == "A3"
    d.resize_pages([3], "A4", "keep", "fill")
    assert d.page_info(3).paper == "A4"
    d.resize_pages([1], "A4", "keep", "fit", custom_mm=(100, 150))
    assert d.page_info(1).paper == "100×150 mm"
    for _ in range(4):
        d.undo()
    assert d.page_info(0).paper == "A4" and d.page_info(2).landscape


# ---------------- chèn ảnh ----------------
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_insert_image_position_on_rotated_pages(rot):
    d = make([lambda doc: doc.new_page(width=595, height=842).set_rotation(rot)])
    w, h = d.page_size_pt(0)
    rect = (w - 150, h - 100, w - 50, h - 50)
    d.insert_image(0, rect, bytes([0, 0, 0, 255]) * 100, 10, 10)
    box = dark_box(d.render(0, 0.3))
    assert box == pytest.approx((rect[0] / w, rect[1] / h, rect[2] / w, rect[3] / h), abs=0.02)


@pytest.mark.parametrize("rot", [0, 90, 270])
def test_inserted_image_is_upright(rot):
    """Ảnh nửa trên đen, nửa dưới trắng: sau khi chèn, phần đen phải nằm ở nửa trên khung."""
    d = make([lambda doc: doc.new_page(width=595, height=842).set_rotation(rot)])
    px = bytes([0, 0, 0, 255]) * (20 * 10) + bytes([255, 255, 255, 255]) * (20 * 10)
    d.insert_image(0, (100, 100, 300, 300), px, 20, 20)
    w, h = d.page_size_pt(0)
    box = dark_box(d.render(0, 0.5))
    assert box[1] == pytest.approx(100 / h, abs=0.02) and box[3] == pytest.approx(200 / h, abs=0.02)


def test_transparent_png_keeps_text_visible():
    d = make([black_rect_page()])
    clear = bytes([255, 0, 0, 0]) * (10 * 10)          # hoàn toàn trong suốt
    d.insert_image(0, (40, 40, 260, 130), clear, 10, 10)
    assert dark_box(d.render(0, 0.3)) is not None       # hình chữ nhật đen bên dưới vẫn thấy


def test_insert_jpeg_keeps_file_small(tmp_path):
    d = make([lambda doc: doc.new_page()])
    jpg = _image_bytes(600, 800)
    d.insert_image(0, (50, 50, 350, 450), b"", 0, 0, jpeg=jpg)
    out = d.save(str(tmp_path / "jpg.pdf"))
    assert os.path.getsize(out) < len(jpg) + 20_000
    assert PdfDocument(out).page_kind(0) in (SCAN, TEXT)
    d.undo()
    assert dark_box(d.render(0, 0.2)) is None


# ---------------- khay ghép ----------------
def _files(tmp_path, counts, landscape_idx=()):
    paths = []
    for k, n in enumerate(counts):
        doc = pymupdf.open()
        for _ in range(n):
            if k in landscape_idx:
                _font_page(doc, 842, 595, lines=5)
            else:
                _font_page(doc, lines=5)
        p = tmp_path / f"f{k}.pdf"
        doc.save(p)
        paths.append(str(p))
    return paths


def test_plan_duplex_example_from_spec(tmp_path):
    a, b, c, e = _files(tmp_path, [3, 5, 40, 8])
    items = [TrayItem(a, page_count=3), TrayItem(b, whole=False, ranges="1-3, 5", page_count=5),
             TrayItem(c, checked=False, page_count=40), TrayItem(e, page_count=8)]
    rows, total, blanks = plan(items, MergeOptions(duplex=True))
    assert [(r.start, len(r.pages), r.blanks_after) for r in rows] == [(1, 3, 1), (5, 4, 0), (9, 8, 0)]
    assert (total, blanks, sheets(total, True)) == (16, 1, 8)
    rows, total, blanks = plan(items, MergeOptions(duplex=False))
    assert (total, blanks) == (15, 0)
    rows, total, blanks = plan(items, MergeOptions(duplex=False, even_total=True))
    assert (total, blanks) == (16, 1)


def test_merge_output(tmp_path):
    a, b, c = _files(tmp_path, [3, 5, 2], landscape_idx=(1,))
    items = [TrayItem(a, page_count=3), TrayItem(b, whole=False, ranges="5, 1", page_count=5),
             TrayItem(c, page_count=2)]
    doc = merge(items, MergeOptions(duplex=True, bookmarks=True, auto_rotate=False))
    assert doc.page_count == 3 + 1 + 2 + 2
    assert doc.page_kind(3) == BLANK
    assert doc.page_size_pt(3) == pytest.approx(doc.page_size_pt(2), abs=0.5)   # trắng cùng khổ trang trước
    assert doc.page_info(4).landscape and doc.page_info(5).landscape           # giữ nguyên khổ gốc
    assert doc.page_info(6).paper == "A4" and not doc.page_info(6).landscape
    out = doc.save(str(tmp_path / "ghep.pdf"))
    with pikepdf.open(out) as pk, pk.open_outline() as ol:
        assert [x.title for x in ol.root] == ["f0", "f1", "f2"]


def test_merge_resize_and_errors(tmp_path):
    a, b = _files(tmp_path, [1, 1], landscape_idx=(1,))
    doc = merge([TrayItem(a, page_count=1), TrayItem(b, page_count=1)],
                MergeOptions(duplex=False, resize="A5", auto_rotate=False))
    assert [doc.page_info(i).paper for i in range(doc.page_count)] == ["A5", "A5"]
    with pytest.raises(ValueError):
        merge([TrayItem(a, checked=False, page_count=1)], MergeOptions())


def test_template_roundtrip(tmp_path):
    a, b = _files(tmp_path, [2, 3])
    items = [TrayItem(a, page_count=2, password="bi-mat"), TrayItem(b, whole=False, ranges="2-3", page_count=3)]
    p = str(tmp_path / "mau.khay.json")
    save_template(p, items, MergeOptions(duplex=False, bookmarks=True))
    assert "bi-mat" not in open(p, encoding="utf-8").read()
    items2, opts = load_template(p)
    assert [(i.path, i.whole, i.ranges) for i in items2] == [(a, True, ""), (b, False, "2-3")]
    assert opts.bookmarks and not opts.duplex


def test_perf_merge(tmp_path):
    paths = _files(tmp_path, [30] * 10)
    items = [TrayItem(p, page_count=30) for p in paths]
    t = time.perf_counter()
    doc = merge(items, MergeOptions(auto_rotate=True))
    dt = time.perf_counter() - t
    assert doc.page_count == 300
    assert dt < 2.0, f"ghép 10 file x 30 trang mất {dt:.2f}s"


def test_perf_resize(samples):
    d = PdfDocument(samples["big"])
    t = time.perf_counter()
    d.resize_pages(list(range(100)), "A5")
    dt = time.perf_counter() - t
    assert dt < 2.0, f"đổi khổ 100 trang mất {dt:.2f}s"
