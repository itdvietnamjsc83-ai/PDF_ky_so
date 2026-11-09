"""1.0.9: file đối tác gửi đã có chữ ký số / đã khóa / chữ ký hỏng / file được bảo vệ -> cảnh báo rõ ràng
trước mọi thao tác sửa, trước khi ký, khi lưu, ghép, tách, nén, thư mục tự xử lý."""
import os

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app import protect, signing
from app.document import PdfDocument
from app.mainwindow import MainWindow

from .pki import CA
from .test_gui import _Settings, pump
from .test_phase4 import _contract, _soft_signer


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ca():
    return CA()


@pytest.fixture(scope="module")
def files(ca, tmp_path_factory):
    d = tmp_path_factory.mktemp("ky")
    base = _contract(2)
    O = lambda **k: signing.SignOptions(page=1, **k)
    out = {}
    out["plain"] = base
    out["signed"] = signing.sign_pdf(base, _soft_signer(ca)[1], O(rect_pt=(60, 620, 220, 700)))
    out["locked"] = signing.sign_pdf(base, _soft_signer(ca)[1], O(rect_pt=(60, 620, 220, 700), certify=True))
    # đối tác ký rồi có người đóng dấu ảnh lên trang và lưu -> chữ ký báo không hợp lệ
    p = d / "hong.pdf"
    p.write_bytes(out["signed"])
    doc = PdfDocument(str(p))
    doc.insert_image(0, (100, 100, 160, 160), bytes([200, 30, 40, 255]) * 400, 20, 20)
    doc.save(str(p))
    doc.close()
    out["broken"] = p.read_bytes()
    out["protected"], _ = protect.protect_pdf(base, protect.ProtectOptions(printing="none", owner_password="chu"))
    return out


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    monkeypatch.setenv("PDFKYSO_SPOOL", str(tmp_path / "spool"))
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def _open(win, qapp, data, tmp_path, name):
    p = tmp_path / name
    p.write_bytes(data)
    win.open_files([str(p)])
    pump(qapp)
    return win.current()


# ------------------------------------------------------------------ phân tích chữ ký
def test_analyze_states(files, ca):
    assert signing.analyze_signatures(files["plain"]) is None
    st = signing.analyze_signatures(files["signed"], [ca.asn1()])
    assert len(st.reports) == 1 and not st.locked and not st.invalid and not st.untrusted
    assert "1 chữ ký số" in st.short()
    lk = signing.analyze_signatures(files["locked"], [ca.asn1()])
    assert lk.locked and lk.locked_by
    br = signing.analyze_signatures(files["broken"], [ca.asn1()])
    assert br.invalid
    nt = signing.analyze_signatures(files["signed"])            # không có chứng thư gốc -> chưa xác minh
    assert nt.untrusted and not nt.invalid


def test_locked_file_sign_error_is_vietnamese(files, ca):
    with pytest.raises(signing.SigningError) as e:
        signing.sign_pdf(files["locked"], _soft_signer(ca)[1], signing.SignOptions(page=1, rect_pt=(300, 620, 460, 700)))
    assert "KHÓA" in str(e.value) and "forbids" not in str(e.value)


# ------------------------------------------------------------------ dải cảnh báo
def test_banner_for_each_state(win, qapp, files, tmp_path):
    t = _open(win, qapp, files["plain"], tmp_path, "thuong.pdf")
    assert not t.banner.isVisible()
    t = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    assert t.banner.isVisible() and t.banner.level == "warn"
    assert "chữ ký số" in t.banner.text.text() and "Ký số" in t.banner.text.text()
    assert t.banner.buttons["verify"].isVisible() and t.banner.buttons["sign"].isVisible()
    t = _open(win, qapp, files["locked"], tmp_path, "khoa.pdf")
    assert t.banner.level == "danger" and "KHÓA" in t.banner.text.text()
    assert not t.banner.buttons["sign"].isVisible()
    t = _open(win, qapp, files["broken"], tmp_path, "hong.pdf")
    assert t.banner.level == "danger" and "KHÔNG HỢP LỆ" in t.banner.text.text()
    t = _open(win, qapp, files["protected"], tmp_path, "baove.pdf")
    assert t.banner.isVisible() and "bảo vệ" in t.banner.text.text()
    assert t.banner.buttons["unprotect"].isVisible()


# ------------------------------------------------------------------ hỏi trước mọi thao tác sửa
def test_every_edit_on_signed_file_asks(win, qapp, files, tmp_path, monkeypatch):
    tab = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    asked = []
    answer = {"v": ("cancel", False)}

    def ask(t, action):
        asked.append(action)
        return answer["v"]
    monkeypatch.setattr(win, "_ask_signed_edit", ask)
    rot = tab.doc.page_info(0).rotation if hasattr(tab.doc.page_info(0), "rotation") else None
    for cmd in ("rotate", "delete", "blank", "textbox", "stamptext", "image", "seam", "erase", "resize"):
        win.run(cmd)
    assert len(asked) == 9 and "Xoay phải" in asked[0]
    assert not tab.doc.modified                                     # hủy -> không đổi gì
    win.move_pages([0], 1)
    assert asked[-1] == "Sắp xếp lại trang" and not tab.doc.modified
    # không cảnh báo: hoàn tác, thêm ô ký trống (luồng ký giữ được chữ ký cũ)
    n = len(asked)
    win.run("undo")
    assert len(asked) == n
    # "Vẫn sửa": sửa được, dải cảnh báo chuyển đỏ; lần sau vẫn hỏi
    answer["v"] = ("go", False)
    win.run("rotate")
    assert tab.doc.modified and tab.banner.level == "danger" and "Bạn đã sửa" in tab.banner.text.text()
    win.run("rotate")
    assert len(asked) == n + 2
    # tích "không hỏi lại" -> không hỏi nữa với file này
    answer["v"] = ("go", True)
    win.run("rotate")
    win.run("rotate")
    assert len(asked) == n + 3 and tab.sig_ack


def test_choose_sign_instead(win, qapp, files, tmp_path, monkeypatch):
    tab = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    monkeypatch.setattr(win, "_ask_signed_edit", lambda t, a: ("sign", False))
    called = []
    monkeypatch.setattr(win, "digital_sign", lambda t=None: called.append(t))
    win.run("image")
    assert called == [tab] and not tab.doc.modified


def test_warning_dialog_text(win, qapp, files, tmp_path):
    tab = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    head, body = win._signed_edit_text(tab, "Con dấu")
    assert "Con dấu" in head and "KHÔNG HỢP LỆ" in body and "Ký số" in body
    tab = _open(win, qapp, files["locked"], tmp_path, "khoa.pdf")
    head, body = win._signed_edit_text(tab, "Chèn ảnh")
    assert "KHÓA" in body and "mất hiệu lực" in body


def test_click_inserted_image_on_signed_file_asks(win, qapp, files, tmp_path, monkeypatch):
    tab = _open(win, qapp, files["broken"], tmp_path, "hong.pdf")   # có ảnh đỏ ở (100,100)-(160,160)
    asked = []
    monkeypatch.setattr(win, "_ask_signed_edit", lambda t, a: (asked.append(a), ("cancel", False))[1])
    win.page_pressed(0, 130, 130)
    assert asked == ["Sửa ảnh đã chèn"] and tab.view.placement is None


# ------------------------------------------------------------------ ký số tiếp
def test_sign_locked_file_is_blocked(win, qapp, files, tmp_path, monkeypatch):
    _open(win, qapp, files["locked"], tmp_path, "khoa.pdf")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[1:3]) or QMessageBox.Ok)
    opened = []
    from app import ui_sign
    monkeypatch.setattr(ui_sign.SignDialog, "exec", lambda self: opened.append(1) or 0)
    win.run("digisign")
    assert shown and "khóa" in shown[0][0].lower() and "KHÓA" in shown[0][1] and not opened


def test_sign_file_with_broken_signature_asks(win, qapp, files, tmp_path, monkeypatch):
    _open(win, qapp, files["broken"], tmp_path, "hong.pdf")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]) or QMessageBox.No)
    opened = []
    from app import ui_sign
    monkeypatch.setattr(ui_sign.SignDialog, "exec", lambda self: opened.append(1) or 0)
    win.run("digisign")
    assert shown and "KHÔNG HỢP LỆ" in shown[0] and not opened


def test_sign_partner_file_goes_ahead(win, qapp, files, tmp_path, monkeypatch):
    _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    opened = []
    from app import ui_sign
    monkeypatch.setattr(ui_sign.SignDialog, "load", lambda self, *a, **k: self.set_certs([]))
    monkeypatch.setattr(ui_sign.SignDialog, "exec", lambda self: opened.append(1) or 0)
    win.run("digisign")
    assert opened and "chữ ký cũ vẫn giữ hiệu lực" in win.lbl_msg.text()


def test_flow_on_locked_file_blocked(win, qapp, files, tmp_path, monkeypatch):
    _open(win, qapp, files["locked"], tmp_path, "khoa.pdf")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]) or QMessageBox.Ok)
    win.run("flow")
    assert shown and "KHÓA" in shown[0]


# ------------------------------------------------------------------ lưu, tách, nén, ghép, thư mục tự xử lý
def test_save_modified_signed_file_warns(win, qapp, files, tmp_path, monkeypatch):
    tab = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    monkeypatch.setattr(win, "_ask_signed_edit", lambda t, a: ("go", True))
    win.run("rotate")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]) or QMessageBox.No)
    assert win.save(tab) is False and "KHÔNG HỢP LỆ" in shown[0] and tab.doc.modified
    assert win.save_as() is False and len(shown) == 2


def test_split_signed_file_warns(win, qapp, files, tmp_path, monkeypatch):
    _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    shown = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: shown.append(a[2]) or QMessageBox.No)
    win.run("split")
    assert shown and "KHÔNG còn chữ ký số" in shown[0]


def test_tray_warns_about_signed_files(win, qapp, files, tmp_path, monkeypatch):
    p1 = tmp_path / "a_da_ky.pdf"
    p1.write_bytes(files["signed"])
    p2 = tmp_path / "b.pdf"
    p2.write_bytes(files["plain"])
    info, ques = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: info.append(a[2]) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: ques.append(a[2]) or QMessageBox.No)
    t = win.show_tray()
    t.items.clear()
    t.add_paths([str(p1), str(p2)])
    assert info and "a_da_ky.pdf" in info[0] and "b.pdf" not in info[0]
    assert t.do_merge(False) is None and "a_da_ky.pdf" in ques[0]
    t.items.clear()
    t.close()


def test_autofolder_skips_signed(files, tmp_path):
    from app.autofolder import AutoConfig, process_file
    p = tmp_path / "da_ky.pdf"
    p.write_bytes(files["signed"])
    with pytest.raises(ValueError) as e:
        process_file(str(p), AutoConfig(enabled=True, folder=str(tmp_path), stamp_text="ĐÃ DUYỆT"))
    assert "chữ ký số" in str(e.value)
    assert p.read_bytes() == files["signed"]


def test_real_warning_dialog_buttons(win, qapp, files, tmp_path):
    from PySide6.QtCore import QTimer
    tab = _open(win, qapp, files["signed"], tmp_path, "da_ky.pdf")
    seen = {}

    def press(label_part, tick=False):
        def go():
            box = QApplication.activeModalWidget()
            seen["title"] = box.windowTitle() + " " + box.text()   # macOS ẩn tiêu đề hộp thoại
            seen["buttons"] = [b.text() for b in box.buttons()]
            if tick:
                box.checkBox().setChecked(True)
            next(b for b in box.buttons() if label_part in b.text()).click()
        QTimer.singleShot(50, go)
    press("Hủy")
    assert win._ask_signed_edit(tab, "Con dấu") == ("cancel", False)
    assert "chữ ký số" in seen["title"] and any("Ký số" in t for t in seen["buttons"])
    press("Vẫn sửa", tick=True)
    assert win._ask_signed_edit(tab, "Con dấu") == ("go", True)
    press("Ký số")
    assert win._ask_signed_edit(tab, "Con dấu") == ("sign", False)
    tab = _open(win, qapp, files["locked"], tmp_path, "khoa.pdf")
    press("Hủy")
    win._ask_signed_edit(tab, "Con dấu")
    assert not any("Ký số" in t for t in seen["buttons"])       # file đã khóa: không gợi ý ký tiếp
