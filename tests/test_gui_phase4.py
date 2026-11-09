"""Giao diện ký số: hộp thoại chọn chứng thư, hình hiển thị, đặt khung và ký trọn luồng bằng token
giả lập, PIN sai, ký ẩn, lưu trước khi ký, kiểm tra chữ ký."""
import json
import os

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app import signing, ui_sign
from app.library import SIGNATURE, STAMP, Library
from app.mainwindow import MainWindow
from app.ui_sign import (LAYOUT_FULL, LAYOUT_HIDDEN, LAYOUT_IMAGE, LAYOUT_TEXT, LAYOUTS, SignDialog,
                         appearance_lines, render_appearance)

from .pki import CA, CN, PIN, SoftHSM, softhsm_lib
from .test_gui import _Settings, pump
from .test_phase3 import remove_background, stamp_jpeg
from .test_phase4 import _contract, _soft_signer


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ca():
    return CA()


@pytest.fixture
def lib_path(tmp_path):
    p = str(tmp_path / "lib.pdf")
    lib = Library(p)
    lib.add("Dấu công ty", remove_background(stamp_jpeg()), STAMP, 38)
    lib.add("Chữ ký giám đốc", remove_background(stamp_jpeg()), SIGNATURE, 40)
    return p


@pytest.fixture
def win(qapp, monkeypatch, lib_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=lib_path)
    w.resize(1440, 900)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def _cert(ca, days=365):
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return signing.parse_cert(ca.issue(k.public_key(), days=days, start_days=-1 if days > 0 else -30),
                              backend=signing.WINDOWS, provider="VNPT-CA CSP")


def _alpha_count(img: QImage) -> int:
    small = img.scaled(120, 60)
    return sum(1 for y in range(small.height()) for x in range(small.width()) if small.pixelColor(x, y).alpha() > 40)


# ------------------------------------------------------------------ hình hiển thị
def test_render_appearance_layouts(qapp):
    stamp = QImage(200, 200, QImage.Format_ARGB32)
    stamp.fill(0xFFCC0000)
    sig = QImage(300, 100, QImage.Format_ARGB32)
    sig.fill(0xFF000080)
    lines = ["Ký bởi: CÔNG TY TNHH THỬ NGHIỆM", "Ngày ký: 25/09/2026 10:00"]
    full = render_appearance(LAYOUT_FULL, stamp, sig, lines)
    assert (full.width(), full.height()) == (int(210 * 300 / 72), int(78 * 300 / 72))
    only_img = render_appearance(LAYOUT_IMAGE, stamp, None, lines)
    text = render_appearance(LAYOUT_TEXT, None, None, lines)
    for im in (full, only_img, text):
        assert _alpha_count(im) > 50                              # có vẽ nội dung
    # không có ảnh dấu/chữ ký -> tự chuyển sang chỉ thông tin (không để khung trống)
    fallback = render_appearance(LAYOUT_FULL, None, None, lines)
    assert fallback.size() == text.size()


def test_appearance_lines(ca):
    c = _cert(ca)
    lines = appearance_lines(c, "Phê duyệt", "Hà Nội", when=0)
    assert lines[0] == f"Ký bởi: {CN}" and "Lý do: Phê duyệt" in lines and "Nơi ký: Hà Nội" in lines
    assert any(l.startswith("Ngày ký: ") for l in lines)


# ------------------------------------------------------------------ hộp thoại ký
def test_sign_dialog_lists_and_remembers(qapp, ca, lib_path):
    lib = Library(lib_path)
    st = _Settings()
    good, expired = _cert(ca), _cert(ca, days=-1)
    calls = []

    def lister(**kw):
        calls.append(kw)
        return [good, expired], ["/fake/pkcs11.dll"]
    dlg = SignDialog(None, lib, st, lister=lister)
    dlg.load(sync=True)
    assert dlg.cb_cert.count() == 2 and dlg.cert() is good
    assert dlg.cb_stamp.currentText() == "Dấu công ty"               # tự lấy dấu có sẵn để hiển thị
    assert dlg.cb_sig.currentText() == "Chữ ký giám đốc"
    assert "VNPT-CA CSP" in dlg.lbl_info.text() and dlg.btn_ok.isEnabled()
    assert dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()
    dlg.cb_cert.setCurrentIndex(1)
    assert not dlg.btn_ok.isEnabled() and "hết hạn" in dlg.lbl_info.text()
    dlg.cb_cert.setCurrentIndex(0)
    dlg.cb_reason.setCurrentText("Đồng ý ký kết")
    dlg.ed_location.setText("Đà Nẵng")
    dlg.cb_layout.setCurrentIndex([k for k, _ in LAYOUTS].index(LAYOUT_IMAGE))
    dlg._accept()
    assert dlg.result() == QDialog.Accepted
    v = dlg.values()
    assert v["cert"] is good and v["layout"] == LAYOUT_IMAGE and v["reason"] == "Đồng ý ký kết"
    assert json.loads(st["sign/known_libs"]) == ["/fake/pkcs11.dll"]
    # mở lại: nhớ chứng thư, lý do, nơi ký, kiểu hiển thị; lần sau dùng danh sách driver đã biết (nhanh)
    dlg2 = SignDialog(None, lib, st, lister=lister)
    dlg2.load(sync=True)
    assert calls[-1]["known_libs"] == ["/fake/pkcs11.dll"]
    assert dlg2.cb_reason.currentText() == "Đồng ý ký kết" and dlg2.ed_location.text() == "Đà Nẵng"
    assert dlg2.layout_key() == LAYOUT_IMAGE and dlg2.cert().thumbprint == good.thumbprint


def test_sign_dialog_no_token(qapp):
    dlg = SignDialog(None, None, _Settings(), lister=lambda **kw: ([], []))
    dlg.load(sync=True)
    assert not dlg.btn_ok.isEnabled() and "cắm USB token" in dlg.lbl_info.text()


def test_sign_dialog_hidden_layout(qapp, ca):
    dlg = SignDialog(None, None, _Settings(), lister=lambda **kw: ([_cert(ca)], []))
    dlg.load(sync=True)
    dlg.cb_layout.setCurrentIndex([k for k, _ in LAYOUTS].index(LAYOUT_HIDDEN))
    assert dlg.appearance() is None and "Ký ngay" in dlg.btn_ok.text()
    assert not dlg.cb_stamp.isEnabled()


def test_report_html():
    assert "chưa có chữ ký" in ui_sign.report_html([])


# ------------------------------------------------------------------ trọn luồng trên cửa sổ chính
def _patch_dialog(monkeypatch, certs, layout=LAYOUT_FULL):
    def load(self, refresh=False, sync=False):
        self.set_certs(certs)
        self.cb_layout.setCurrentIndex([k for k, _ in LAYOUTS].index(layout))

    monkeypatch.setattr(SignDialog, "load", load)
    monkeypatch.setattr(SignDialog, "exec", lambda self: (self._save(), QDialog.Accepted)[1])


def _open_contract(win, qapp, tmp_path, name="hop dong.pdf"):
    p = tmp_path / name
    p.write_bytes(_contract(2))
    win.open_files([str(p)])
    pump(qapp)
    return p


def test_full_flow_with_windows_style_signer(win, qapp, tmp_path, monkeypatch, ca):
    """Chọn chứng thư -> khung gợi ý dưới "GIÁM ĐỐC" -> Enter -> file _da_ky.pdf mở ra, chữ ký hợp lệ."""
    key, soft = _soft_signer(ca)
    cert = signing.parse_cert(soft.signing_cert.dump(), backend=signing.WINDOWS, provider="Viettel-CA KSP")
    monkeypatch.setattr(signing, "open_signer", lambda c, pin=None, hwnd=0: (soft, lambda: None))
    _patch_dialog(monkeypatch, [cert])
    src = _open_contract(win, qapp, tmp_path)
    original = src.read_bytes()
    win.run("digisign")
    tab = win.current()
    pl = tab.view.placement
    assert pl is not None and pl.page == 1                          # gợi ý ở trang cuối
    assert 560 < pl.rect.center().y() < 760                        # ngay dưới khối chữ ký
    pl.rect.translate(-20, 10)                                     # người dùng kéo khung đi chỗ khác
    want = (pl.rect.left(), pl.rect.top(), pl.rect.right(), pl.rect.bottom())
    tab.view.commit_placement()
    pump(qapp)
    out = tmp_path / "hop dong_da_ky.pdf"
    assert out.exists() and key.calls == 1
    assert win.current().doc.path == str(out) and win.current().doc.signature_count() == 1
    assert src.read_bytes() == original                            # file gốc không bị đụng tới
    rep = signing.verify_pdf(out.read_bytes(), [ca.asn1()])[0]
    assert rep.valid and rep.trusted and rep.signer == CN
    from .test_phase4 import _red_bbox                              # dấu đỏ nằm đúng chỗ đã kéo
    x0, y0, x1, y1 = _red_bbox(out.read_bytes(), 1)
    assert want[0] - 3 <= x0 and x1 <= want[2] + 3 and want[1] - 3 <= y0 and y1 <= want[3] + 3
    assert "ký số thành công" in win.lbl_msg.text()
    csv = os.path.join(os.environ["APPDATA"], "PdfKySo", "nhat_ky_dung_dau.csv")
    assert os.path.exists(csv) and "ký số" in open(csv, encoding="utf-8-sig").read()


def test_hidden_signature_flow(win, qapp, tmp_path, monkeypatch, ca):
    _, soft = _soft_signer(ca)
    cert = signing.parse_cert(soft.signing_cert.dump(), backend=signing.WINDOWS)
    monkeypatch.setattr(signing, "open_signer", lambda c, pin=None, hwnd=0: (soft, lambda: None))
    _patch_dialog(monkeypatch, [cert], LAYOUT_HIDDEN)
    _open_contract(win, qapp, tmp_path, "an.pdf")
    win.run("digisign")
    pump(qapp)
    out = tmp_path / "an_da_ky.pdf"
    assert out.exists() and signing.verify_pdf(out.read_bytes(), [ca.asn1()])[0].valid


def test_modified_doc_must_be_saved_first(win, qapp, tmp_path, monkeypatch, ca):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (asked.append(a[2]), QMessageBox.No)[1])
    monkeypatch.setattr(SignDialog, "exec", lambda self: pytest.fail("không được mở hộp thoại ký"))
    _open_contract(win, qapp, tmp_path, "sua.pdf")
    win.current().doc.rotate_pages([0])
    win.run("digisign")
    assert asked and "lưu" in asked[0].lower()


def test_verify_command(win, qapp, tmp_path, monkeypatch, ca):
    _, soft = _soft_signer(ca)
    p = tmp_path / "da ky.pdf"
    p.write_bytes(signing.sign_pdf(_contract(1), soft, signing.SignOptions()))
    shown = []
    monkeypatch.setattr(ui_sign.VerifyDialog, "exec", lambda self: shown.append(self.view.toPlainText()))
    win.open_files([str(p)])
    pump(qapp)
    win.run("verify")
    assert len(win.last_verify) == 1 and win.last_verify[0].intact
    assert shown and CN in shown[0]


@pytest.mark.skipif(softhsm_lib() is None, reason="chưa cài SoftHSM2")
def test_pkcs11_flow_wrong_pin_then_right(win, qapp, tmp_path, monkeypatch, ca, tmp_path_factory):
    """Token thật (giả lập PKCS#11): nhập sai PIN -> cảnh báo -> nhập lại đúng -> ký thành công."""
    hsm = SoftHSM(str(tmp_path_factory.mktemp("hsm-gui")), ca, tokens=(("Token GUI", "rsa"),))
    certs, _ = signing.list_certificates(extra_libs=[hsm.lib], include_windows=False, known_libs=[])
    pins, warnings = iter(["111111", PIN]), []

    def ask(parent, cert, warning=""):
        warnings.append(warning)
        return next(pins)
    monkeypatch.setattr(ui_sign, "ask_pin", ask)
    monkeypatch.setattr(ui_sign.sign_with_ui, "__defaults__", (0, ask))
    _patch_dialog(monkeypatch, certs)
    _open_contract(win, qapp, tmp_path, "token.pdf")
    win.run("digisign")
    win.current().view.commit_placement()
    pump(qapp)
    out = tmp_path / "token_da_ky.pdf"
    assert out.exists()
    assert warnings[0] == "" and "Sai mã PIN" in warnings[1]
    rep = signing.verify_pdf(out.read_bytes(), [ca.asn1()])[0]
    assert rep.valid and rep.trusted


def test_cancel_pin_does_nothing(win, qapp, tmp_path, monkeypatch, ca):
    import dataclasses
    cert = dataclasses.replace(_cert(ca), backend=signing.PKCS11, token_label="X")
    monkeypatch.setattr(ui_sign.sign_with_ui, "__defaults__", (0, lambda *a, **k: None))
    _patch_dialog(monkeypatch, [cert], LAYOUT_HIDDEN)
    _open_contract(win, qapp, tmp_path, "huy.pdf")
    n = win.tabs.count()
    win.run("digisign")
    pump(qapp)
    assert not (tmp_path / "huy_da_ky.pdf").exists() and win.tabs.count() == n
