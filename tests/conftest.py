"""Tạo file PDF mẫu cho kiểm thử (chỉ dùng khi phát triển, không đóng gói vào phần mềm)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# dữ liệu của phần mềm (thư viện dấu, nhật ký, bản khôi phục) ghi vào thư mục tạm khi kiểm thử
import tempfile as _tf
_DATA = _tf.mkdtemp(prefix="pdfkyso-test-")
os.environ["APPDATA"] = os.path.join(_DATA, "roaming")
os.environ["LOCALAPPDATA"] = os.path.join(_DATA, "local")
# trạng thái dùng thử / bản quyền: KHÔNG ghi vào Registry và C:\ProgramData thật của máy (nếu không, kiểm thử
# "hết hạn dùng thử" lần trước làm lần sau mọi lệnh đều bật màn hình kích hoạt -> treo / lỗi hàng loạt)
os.environ["ProgramData"] = os.path.join(_DATA, "programdata")
os.environ["PDFKYSO_REG_FILE"] = os.path.join(_DATA, "registry.json")
os.environ["PDFKYSO_NO_AUTOSIGN"] = "1"      # không tự bật hộp thoại ký khi nhận bản in (tránh treo kiểm thử)

pymupdf = pytest.importorskip("pymupdf")  # công cụ tạo file mẫu

VN = "Hợp đồng số 123/QĐ – ngày 24 tháng 9 năm 2026. Tiếng Việt có dấu: ạ ệ ữ ỳ đ Đ."


def _clean_font(path: str) -> bytes:
    """Phông cho file mẫu: bỏ mã U+00A0 dùng chung glyph với dấu cách (Times New Roman), nếu không PyMuPDF ghi
    dấu cách thành khoảng trắng cứng -> file mẫu trên Windows khác Linux."""
    import io
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=0) if path.lower().endswith(".ttc") else TTFont(path)
    for t in f["cmap"].tables:
        if hasattr(t, "cmap") and isinstance(t.cmap, dict) and t.cmap.get(0xA0) == t.cmap.get(0x20):
            t.cmap.pop(0xA0, None)
    b = io.BytesIO()
    f.save(b)
    return b.getvalue()


_FONT = []
try:                                   # cùng phông phần mềm dùng: Times New Roman (Windows), DejaVu Serif (Linux)
    from app import fonts as _fonts
    _FONT.append(pymupdf.Font(fontbuffer=_clean_font(_fonts.system_font("serif"))))
except Exception:
    for _f in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "C:/Windows/Fonts/times.ttf"):
        if os.path.exists(_f):
            _FONT.append(pymupdf.Font(fontfile=_f))
            break


def _font_page(doc, w=595, h=842, text=VN, lines=20):
    p = doc.new_page(width=w, height=h)
    font = _FONT[0] if _FONT else None
    tw = pymupdf.TextWriter(p.rect)
    for k in range(lines):
        tw.append((56, 80 + k * 24), f"{k + 1}. {text}", font=font, fontsize=11)
    tw.write_text(p)
    p.draw_rect(pymupdf.Rect(56, 60, w - 56, h - 60), color=(0.2, 0.2, 0.2))
    return p


def _image_bytes(w=1240, h=1754):
    pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pm.set_rect(pm.irect, (245, 243, 238))
    for y in range(200, 1600, 60):
        pm.set_rect(pymupdf.IRect(150, y, 1100, y + 14), (40, 40, 40))
    return pm.tobytes("jpeg", jpg_quality=70)


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdf")
    out = {}

    doc = pymupdf.open()
    for _ in range(5):
        _font_page(doc)
    out["text"] = str(d / "text.pdf")
    doc.save(out["text"])

    doc = pymupdf.open()
    img = _image_bytes()
    for _ in range(3):
        p = doc.new_page(width=595, height=842)
        p.insert_image(p.rect, stream=img)
    out["scan"] = str(d / "scan.pdf")
    doc.save(out["scan"])

    doc = pymupdf.open()   # scan có lớp chữ OCR ẩn
    p = doc.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=img)
    p.insert_text((72, 100), "OCR hidden text layer here " * 3, render_mode=3)
    out["ocr"] = str(d / "ocr.pdf")
    doc.save(out["ocr"])

    doc = pymupdf.open()
    _font_page(doc)
    doc.new_page(width=595, height=842)            # trang trắng
    _font_page(doc, 842, 595)                       # A4 ngang
    p = doc.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=img)             # scan
    out["mixed"] = str(d / "mixed.pdf")
    doc.save(out["mixed"])

    doc = pymupdf.open()
    for _ in range(300):
        _font_page(doc, lines=30)
    out["big"] = str(d / "big300.pdf")
    doc.save(out["big"], garbage=3, deflate=True)

    doc = pymupdf.open()
    _font_page(doc)
    out["locked"] = str(d / "locked.pdf")
    doc.save(out["locked"], encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="owner")

    out["dir"] = str(d)
    return out


@pytest.fixture(autouse=True)
def _hang_guard(request):
    """Test treo (hộp thoại modal chưa được giả lập...) -> ghi vị trí treo rồi dừng sau 120 giây thay vì treo mãi.
    Ghi vào ketqua_treo.log ở thư mục mã nguồn (pytest thu lại stderr nên không in ra màn hình được)."""
    import faulthandler
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ketqua_treo.log")
    log = open(path, "w", encoding="utf-8")
    log.write(f"Kiểm thử đang chạy: {request.node.nodeid}\n"
              "Nếu file này có phần 'Timeout' bên dưới: kiểm thử trên bị treo quá 120 giây và đã bị dừng.\n\n")
    log.flush()
    faulthandler.dump_traceback_later(120, exit=True, file=log)
    yield
    faulthandler.cancel_dump_traceback_later()
    log.close()


DEMO_PUBLIC_KEY = "16d9a5bb3b1fc67e19d4ab62f4fc003760e60ae5e393ef7fc3fff3817e52dc8f"


@pytest.fixture(autouse=True)
def _demo_license_key(monkeypatch):
    """Kiểm thử bản quyền dùng khóa mẫu, kể cả khi máy đã chạy `keygen.py init` (khóa thật của nhà phát triển)."""
    import app.license_key as lk
    monkeypatch.setattr(lk, "PUBLIC_KEY", DEMO_PUBLIC_KEY)


@pytest.fixture(autouse=True)
def _no_tray_save_dialog(monkeypatch):
    """1.0.22: bấm Ghép hiện hộp thoại Lưu – kiểm thử thì nhận luôn đường dẫn gợi ý (không mở hộp thoại thật -> treo)."""
    try:
        import app.tray as _tray
    except Exception:
        return
    monkeypatch.setattr(_tray.TrayDialog, "_ask_target", lambda self: self.target_path())


@pytest.fixture(autouse=True)
def _no_save_mode_prompt(monkeypatch):
    """1.0.22: bấm Lưu hỏi "lưu đè / lưu file mới" – kiểm thử mặc định chọn lưu đè (không mở hộp thoại thật)."""
    try:
        import app.mainwindow as _mw
    except Exception:
        return
    monkeypatch.setattr(_mw.MainWindow, "_ask_save_mode", lambda self, tab: "overwrite")
    # sửa chữ làm đổi hình thức -> cảnh báo; kiểm thử cũ mặc định chọn "thu nhỏ cho vừa" như trước
    monkeypatch.setattr(_mw.MainWindow, "_ask_edit_warning", lambda self, warns, strict, fit: "fit" if fit else "keep")


@pytest.fixture(autouse=True)
def _free_closed_windows():
    """Xóa hẳn các cửa sổ đã đóng sau mỗi kiểm thử. Nếu không, hàng trăm cửa sổ cũ còn nằm trong bộ nhớ làm các
    thao tác toàn ứng dụng (đổi giao diện sáng/tối = áp lại stylesheet cho MỌI widget) chậm dần tới mức quá giờ."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            if not w.isVisible():
                w.deleteLater()
        except RuntimeError:
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
