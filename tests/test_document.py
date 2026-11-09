"""Kiểm thử lõi tài liệu: mở, nhận biết loại trang, thao tác trang, hoàn tác, lưu, hiệu năng."""
import os
import shutil
import time

import pytest

from app.document import BLANK, SCAN, TEXT, PasswordRequired, PdfDocument, paper_name


def test_open_and_info(samples):
    d = PdfDocument(samples["text"])
    assert d.page_count == 5
    info = d.page_info(0)
    assert info.paper == "A4" and not info.landscape and info.kind == TEXT
    assert "Hợp đồng" in d.text(0)
    assert d.signature_count() == 0
    d.close()


@pytest.mark.parametrize("key,kinds", [
    ("text", [TEXT] * 5),
    ("scan", [SCAN] * 3),
    ("ocr", [SCAN]),
    ("mixed", [TEXT, BLANK, TEXT, SCAN]),
])
def test_detect_kind(samples, key, kinds):
    d = PdfDocument(samples[key])
    assert [d.page_kind(i) for i in range(d.page_count)] == kinds
    d.close()


def test_landscape_and_paper_names(samples):
    d = PdfDocument(samples["mixed"])
    info = d.page_info(2)
    assert info.landscape and info.paper == "A4" and info.label == "A4 · Ngang"
    assert paper_name(148, 210) == "A5" and paper_name(100, 100) == "100×100 mm"
    d.close()


def test_rotate_undo_redo(samples):
    d = PdfDocument(samples["text"])
    w, h = d.page_size_pt(0)
    d.rotate_pages([0], 90)
    assert d.page_size_pt(0) == pytest.approx((h, w), abs=0.5)
    assert d.modified and d.can_undo
    assert d.undo()
    assert d.page_size_pt(0) == pytest.approx((w, h), abs=0.5)
    assert d.redo()
    assert d.page_size_pt(0) == pytest.approx((h, w), abs=0.5)
    d.close()


def test_delete_and_guard(samples):
    d = PdfDocument(samples["text"])
    d.delete_pages([1, 3])
    assert d.page_count == 3
    with pytest.raises(ValueError):
        d.delete_pages([0, 1, 2])
    d.undo()
    assert d.page_count == 5
    d.close()


def test_insert_blank_same_size_as_previous(samples):
    d = PdfDocument(samples["mixed"])
    d.insert_blank(2)                 # sau trang A4 ngang
    assert d.page_count == 5
    assert d.page_size_pt(3) == pytest.approx(d.page_size_pt(2), abs=0.5)
    assert d.page_kind(3) == BLANK
    d.insert_blank(-1)                # chèn lên đầu
    assert d.page_count == 6 and d.page_kind(0) == BLANK
    d.close()


def test_move_and_import(samples):
    d = PdfDocument(samples["mixed"])
    d.move_pages([3], 0)              # trang scan lên đầu
    assert d.page_kind(0) == SCAN
    other = PdfDocument(samples["scan"])
    d.import_pages(other, [0, 1], 1)
    assert d.page_count == 6 and d.page_kind(1) == SCAN and d.page_kind(2) == SCAN
    other.close()
    d.close()


def test_save_roundtrip_same_path_and_new_path(samples, tmp_path):
    src = tmp_path / "a.pdf"
    shutil.copy(samples["text"], src)
    d = PdfDocument(str(src))
    d.rotate_pages([0], 90)
    d.save()                          # lưu đè file đang mở
    assert not d.modified
    d.delete_pages([4])
    out = d.save(str(tmp_path / "b.pdf"))
    d.close()
    r = PdfDocument(out)
    assert r.page_count == 4 and r.page_info(0).landscape
    r.close()
    assert PdfDocument(str(src)).page_count == 5


def test_save_after_undo_from_bytes(samples, tmp_path):
    src = tmp_path / "c.pdf"
    shutil.copy(samples["text"], src)
    d = PdfDocument(str(src))
    d.delete_pages([0])
    d.undo()                          # tài liệu giờ nạp từ bytes
    d.save()
    d.close()
    assert PdfDocument(str(src)).page_count == 5


def test_optimized_save_not_bigger(samples, tmp_path):
    d = PdfDocument(samples["big"])
    out = d.save(str(tmp_path / "opt.pdf"))
    d.close()
    assert os.path.getsize(out) <= os.path.getsize(samples["big"]) * 1.02


def test_password(samples):
    with pytest.raises(PasswordRequired):
        PdfDocument(samples["locked"])
    d = PdfDocument(samples["locked"], password="1234")
    assert d.page_count == 1
    d.close()


def test_undo_memory_cap(samples):
    d = PdfDocument(samples["text"])
    d.MAX_UNDO = 5
    for _ in range(12):
        d.rotate_pages([0], 90)
    assert len(d._undo) == 5
    d.close()


def test_render_rgb_and_crop(samples):
    d = PdfDocument(samples["text"])
    bm = d.render(0, 2.0)
    assert bm.n_channels == 3 and bm.width == pytest.approx(1190, abs=2)
    bm.close()
    bm = d.render(0, 2.0, crop=(100, 200, 100, 200))
    assert bm.width == pytest.approx(790, abs=2) and bm.height == pytest.approx(884, abs=2)
    bm.close()
    d.close()


# ---------------- hiệu năng ----------------
def test_perf_open_big(samples):
    t = time.perf_counter()
    d = PdfDocument(samples["big"])
    sizes = [d.page_size_pt(i) for i in range(d.page_count)]
    dt = time.perf_counter() - t
    assert len(sizes) == 300
    assert dt < 0.5, f"mở + đọc khổ 300 trang mất {dt:.3f}s"
    d.close()


def test_perf_render_page(samples):
    d = PdfDocument(samples["big"])
    d.render(0, 1.0).close()          # làm nóng
    t = time.perf_counter()
    for i in range(10):
        d.render(i, 150 / 72).close()  # A4 ở 150 dpi (~ zoom 112% màn hình thường)
    dt = (time.perf_counter() - t) / 10
    assert dt < 0.12, f"render 1 trang mất {dt * 1000:.0f} ms"
    d.close()


def test_perf_detect_kind(samples):
    d = PdfDocument(samples["big"])
    t = time.perf_counter()
    for i in range(50):
        d.page_kind(i)
    dt = (time.perf_counter() - t) / 50
    assert dt < 0.03, f"nhận biết loại trang mất {dt * 1000:.1f} ms/trang"
    d.close()
