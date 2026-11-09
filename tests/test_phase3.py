"""Giai đoạn 3: tách nền, thư viện dấu mã hóa, đóng dấu nhiều trang, giáp lai, ổn định."""
import io
import json
import os
import sys
import time

import pikepdf
import pytest
from PIL import Image, ImageDraw

from app.document import PdfDocument
from app.imaging import has_transparency, remove_background
from app.library import SIGNATURE, STAMP, Library, LibraryLocked, log_usage

from .test_phase2 import dark_box, make


# ---------------- ảnh mẫu ----------------
def stamp_jpeg(ink=(200, 30, 40), paper=(242, 238, 228), size=600, noise=True) -> bytes:
    img = Image.new("RGB", (size, size), paper)
    d = ImageDraw.Draw(img)
    d.ellipse((60, 60, size - 60, size - 60), outline=ink, width=22)
    d.ellipse((140, 140, size - 140, size - 140), outline=ink, width=8)
    d.regular_polygon((size / 2, size / 2, 60), 5, fill=ink)
    if noise:                                        # vết bẩn / bóng giấy nhạt
        for k in range(0, size, 37):
            d.point((k, (k * 7) % size), fill=(225, 222, 215))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=85)
    return b.getvalue()


def rgba(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGBA")


# ---------------- tách nền ----------------
@pytest.mark.parametrize("ink", [(200, 30, 40), (30, 50, 170), (30, 30, 30)])
def test_remove_background_keeps_ink_drops_paper(ink):
    out = rgba(remove_background(stamp_jpeg(ink)))
    w, h = out.size
    assert out.getpixel((w // 2, 6))[3] > 200                    # viền dấu (sau khi cắt viền) còn đậm
    # nền giấy giữa hai vòng tròn phải trong suốt
    assert out.getpixel((w // 2, int(h * 0.2)))[3] < 20
    r, g, b, a = out.getpixel((w // 2, 6))
    assert abs(r - ink[0]) < 70 and abs(b - ink[2]) < 70       # màu mực gần đúng màu gốc
    assert has_transparency(remove_background(stamp_jpeg(ink)))


def test_remove_background_trim_and_recolor():
    src = stamp_jpeg()
    out = rgba(remove_background(src, ink="blue"))
    assert out.size[0] < 600 and out.size[1] < 600                # đã cắt viền thừa
    r, g, b, a = out.getpixel((out.width // 2, 6))
    assert b > r and a > 200
    assert rgba(remove_background(src, trim=False)).size == (600, 600)


def test_remove_background_limits_size_and_speed():
    big = io.BytesIO()
    Image.new("RGB", (4000, 3000), (250, 250, 250)).save(big, "JPEG")
    t = time.perf_counter()
    out = rgba(remove_background(big.getvalue(), trim=False))
    dt = time.perf_counter() - t
    assert max(out.size) <= 1600
    assert dt < 1.5, f"tách nền ảnh 12 MP mất {dt:.2f}s"


# ---------------- thư viện ----------------
def test_library_crud_and_persist(tmp_path):
    p = str(tmp_path / "lib.pdf")
    lib = Library(p)
    png = remove_background(stamp_jpeg())
    a = lib.add("Dấu công ty", png, STAMP)
    b = lib.add("Chữ ký giám đốc", png, SIGNATURE, 50)
    assert [i.name for i in lib.of_kind(STAMP)] == ["Dấu công ty"]
    lib.update(b.id, name="Chữ ký GĐ")
    lib.move(b.id, -1)
    lib2 = Library(p)
    assert [i.name for i in lib2.items] == ["Chữ ký GĐ", "Dấu công ty"]
    assert lib2.get(b.id).width_mm == 50 and lib2.image(a.id) == png
    lib2.remove(a.id)
    assert [i.id for i in Library(p).items] == [b.id]
    assert os.path.exists(p + ".bak")                            # luôn có bản sao lưu


def test_library_encryption(tmp_path):
    p = str(tmp_path / "lib.pdf")
    lib = Library(p)
    png = remove_background(stamp_jpeg())
    lib.add("Dấu", png)
    lib.set_password("matkhau123")
    raw = open(p, "rb").read()
    assert b"\x89PNG" not in raw and "Dấu".encode() not in raw   # ảnh và tên đều đã mã hóa
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(p)
    locked = Library(p)
    assert locked.locked and locked.items == []
    with pytest.raises(LibraryLocked):
        locked.image("x")
    assert not locked.unlock("sai")
    assert locked.unlock("matkhau123") and locked.items[0].name == "Dấu"
    locked.lock()
    assert locked.locked and not locked._images
    locked.unlock("matkhau123")
    locked.set_password(None)
    assert not Library(p).locked


def test_library_corrupt_file_recovers_from_backup(tmp_path):
    p = str(tmp_path / "lib.pdf")
    lib = Library(p)
    lib.add("A", remove_background(stamp_jpeg()))
    lib.add("B", remove_background(stamp_jpeg()))        # .bak giờ chứa bản có "A"
    with open(p, "wb") as f:
        f.write(b"hong hoan toan")
    lib2, msg = Library.open_safe(p)
    assert msg and [i.name for i in lib2.items] == ["A"]
    assert any(n.startswith("lib.pdf.hong") for n in os.listdir(tmp_path))


def test_usage_log(tmp_path):
    lib = Library(str(tmp_path / "l.pdf"))
    it = lib.add("Dấu công ty", remove_background(stamp_jpeg()))
    log = str(tmp_path / "log.csv")
    log_usage(it, "D:/Hop dong.pdf", [0, 2], path=log)
    log_usage(it, "D:/Hop dong.pdf", [4], "giáp lai", path=log)
    text = open(log, encoding="utf-8-sig").read().splitlines()
    assert len(text) == 3 and "Dấu công ty" in text[1] and "1, 3" in text[1] and "giáp lai" in text[2]


# ---------------- đóng dấu ----------------
def _argb(w=60, h=60, color=(0, 0, 0, 255)):
    b, g, r, a = color[2], color[1], color[0], color[3]
    return bytes([b, g, r, a]) * (w * h), w, h, w * 4


def test_stamp_pages_same_position_one_undo():
    d = make([lambda doc: doc.new_page(width=595, height=842)] * 3 +
             [lambda doc: doc.new_page(width=842, height=595)])
    data, w, h, st = _argb()
    d.stamp_pages([0, 1, 2, 3], (400, 700, 500, 800), data, w, h, st)
    for i in range(3):
        box = dark_box(d.render(i, 0.3))
        assert box == pytest.approx((400 / 595, 700 / 842, 500 / 595, 800 / 842), abs=0.02)
    lw, lh = d.page_size_pt(3)                        # trang ngang: dời theo tỉ lệ, vẫn trong trang
    box = dark_box(d.render(3, 0.3))
    assert box[2] <= 1 and box[3] <= 1 and box[0] == pytest.approx(400 * lw / 595 / lw, abs=0.02)
    d.undo()                                          # 1 lần hoàn tác gỡ hết
    assert all(dark_box(d.render(i, 0.3)) is None for i in range(4))


@pytest.mark.parametrize("n", [2, 5])
def test_seam_stamp_slices(n):
    d = make([lambda doc: doc.new_page(width=595, height=842)] * n)
    w = h = 100
    # ảnh 100x100: mỗi cột đậm dần để biết mảnh nào đi trang nào
    buf = bytearray()
    for y in range(h):
        for x in range(w):
            v = int(x * 2)
            buf += bytes([v, v, v, 255])
    diameter = 40 * 72 / 25.4
    d.seam_stamp(list(range(n)), bytes(buf), w, h, w * 4, diameter, 0.5)
    slice_w = diameter / n / 595
    means = []
    for i in range(n):
        bm = d.render(i, 1.0)
        bw, bh, stc = bm.width, bm.height, bm.stride
        raw = bytes(bm.buffer)
        bm.close()
        y = bh // 2
        x = bw - 2                                    # sát mép phải
        means.append(raw[y * stc + x * 3])
        x_left = int(bw * (1 - slice_w)) - 3          # ngay ngoài mảnh -> giấy trắng
        assert raw[y * stc + x_left * 3] > 240
    assert means == sorted(means)                     # mảnh trái -> trang đầu, mảnh phải -> trang cuối
    d.undo()
    assert d.page_count == n and not d.can_undo


def test_seam_needs_two_pages():
    d = make([lambda doc: doc.new_page()])
    data, w, h, st = _argb()
    with pytest.raises(ValueError):
        d.seam_stamp([0], data, w, h, st, 100)


def test_stamp_keeps_file_small(tmp_path):
    d = make([lambda doc: doc.new_page()] * 20)
    png = remove_background(stamp_jpeg())
    img = rgba(png)
    img = img.resize((400, 400))
    bgra = img.tobytes("raw", "BGRA")
    d.stamp_pages(list(range(20)), (400, 700, 510, 810), bgra, 400, 400, 1600)
    out = d.save(str(tmp_path / "s.pdf"))
    # 20 trang cùng một dấu: nhỏ gọn nhờ nén khi lưu
    assert os.path.getsize(out) < 200_000          # ảnh trùng được gộp: ~80 KB thay vì ~1,6 MB


# ---------------- ổn định ----------------
def test_selftest_passes():
    from app.stability import selftest
    assert selftest() == 0


def test_logging_and_excepthook(tmp_path):
    import logging
    import sys
    from app import stability
    path = stability.setup_logging()
    seen = []
    hook = stability.install_excepthook(seen.append)
    try:
        raise RuntimeError("thử lỗi")
    except RuntimeError:
        hook(*sys.exc_info())
    for h in logging.getLogger().handlers:
        h.flush()
    assert seen and "thử lỗi" in seen[0]
    assert "thử lỗi" in open(path, encoding="utf-8").read()
    sys.excepthook = sys.__excepthook__


def test_recovery_roundtrip(tmp_path, samples):
    from app.stability import Recovery
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    d = PdfDocument(samples["text"])
    docs = [("k1", d, "text.pdf")]
    rec = Recovery(lambda: docs, str(tmp_path))
    rec.autosave()
    assert rec.pending() == []                          # chưa sửa -> không lưu gì
    d.rotate_pages([0])
    rec.autosave()
    mtime = os.path.getmtime(tmp_path / "k1.pdf")
    rec.autosave()                                      # không đổi -> không ghi lại
    assert os.path.getmtime(tmp_path / "k1.pdf") == mtime
    rec2 = Recovery(lambda: [], str(tmp_path))          # giả lập lần chạy sau sự cố
    pend = rec2.pending()
    assert len(pend) == 1 and pend[0]["path"] == samples["text"]
    r = PdfDocument(data=open(pend[0]["file"], "rb").read())
    assert r.page_info(0).landscape
    rec2.clear_all()
    assert rec2.pending() == []
    rec.timer.stop()
    rec2.timer.stop()
    del app


def test_single_instance_passes_files():
    from PySide6.QtWidgets import QApplication
    from app.stability import SingleInstance
    app = QApplication.instance() or QApplication([])
    key = f"pdfkyso-test-{os.getpid()}"
    first = SingleInstance(key)
    assert first.listen()
    got = []
    first.filesReceived.connect(got.extend)
    # phiên thứ hai là MỘT TIẾN TRÌNH KHÁC như khi dùng thật (bấm đúp file khi phần mềm đang mở)
    import subprocess
    code = ("import sys; from PySide6.QtCore import QCoreApplication; a = QCoreApplication([]); "
            "from app.stability import SingleInstance; "
            f"sys.exit(0 if SingleInstance({key!r}).send_to_running(['D:/Tài liệu/hợp đồng.pdf']) else 3)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=root)
    end = time.time() + 20
    while (not got or proc.poll() is None) and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert proc.wait(10) == 0
    assert got and got[0].endswith("hợp đồng.pdf")
    assert not SingleInstance(key + "-khong-co").send_to_running([])
    for _ in range(10):
        app.processEvents()
    first.close()


def test_unicode_paths(tmp_path, samples):
    """Tên thư mục/file tiếng Việt có dấu, có khoảng trắng."""
    folder = tmp_path / "Hồ sơ thầu 2026" / "Bản gốc"
    folder.mkdir(parents=True)
    src = folder / "Hợp đồng – bản ký.pdf"
    src.write_bytes(open(samples["text"], "rb").read())
    d = PdfDocument(str(src))
    d.rotate_pages([0])
    d.save()
    out = d.save(str(folder / "Bản sao đã xoay.pdf"))
    d.close()
    assert PdfDocument(out).page_info(0).landscape
    lib = Library(str(folder / "thư viện.pdf"))
    lib.add("Dấu", remove_background(stamp_jpeg()))
    assert Library(str(folder / "thư viện.pdf")).items[0].name == "Dấu"


def test_save_when_target_locked_does_not_lose_original(tmp_path, samples, monkeypatch):
    """Lưu thất bại giữa chừng (ví dụ file đang mở bằng phần mềm khác): file gốc phải còn nguyên."""
    src = tmp_path / "a.pdf"
    src.write_bytes(open(samples["text"], "rb").read())
    before = src.read_bytes()
    d = PdfDocument(str(src))
    d.rotate_pages([0])

    def boom(*a, **k):
        raise PermissionError("File đang được mở bởi chương trình khác")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(PermissionError):
        d.save()
    monkeypatch.undo()
    assert src.read_bytes() == before and d.modified


def test_manifest_versions_pinned():
    here = os.path.dirname(os.path.dirname(__file__))
    for line in open(os.path.join(here, "requirements.txt"), encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            assert "==" in line, f"phiên bản phải cố định: {line}"
    json.dumps({})


@pytest.mark.parametrize("name,is_sig", [("dau-chup", False), ("Dấu công ty", False), ("chu-ky-GD", True),
                                         ("Chữ ký giám đốc", True), ("signature_ceo", True), ("chuky", True),
                                         ("con dau ky thuat", False)])
def test_guess_kind_from_filename(name, is_sig):
    from app.ui_library import looks_like_signature
    assert looks_like_signature(name) == is_sig


def test_vietnamese_standard_buttons():
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from app import i18n
    app = QApplication.instance() or QApplication([])
    tr = i18n.install(app)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save)
    texts = {b.text().replace("&", "") for b in bb.buttons()}
    app.removeTranslator(tr)
    assert {"Hủy", "Lưu"} <= texts
