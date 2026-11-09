"""Giai đoạn 4 – ký số: dò USB token (PKCS#11), ký qua driver kiểu Windows (ký theo giá trị băm),
hình hiển thị, PIN sai, ký chứng nhận, nhiều chữ ký, trang xoay, dấu thời gian, kiểm tra chữ ký."""
import io
import os
import time

import pytest

from app import signing, wincert
from app.document import PdfDocument
from app.signing import PKCS11, SignOptions

from .conftest import pymupdf
from .pki import CA, CN, PIN, SoftHSM, SoftKey, softhsm_lib

needs_hsm = pytest.mark.skipif(softhsm_lib() is None, reason="chưa cài SoftHSM2 (token giả lập)")


# ------------------------------------------------------------------ dữ liệu
@pytest.fixture(scope="session")
def ca():
    return CA()


@pytest.fixture(scope="session")
def hsm(ca, tmp_path_factory):
    if softhsm_lib() is None:
        pytest.skip("chưa cài SoftHSM2")
    return SoftHSM(str(tmp_path_factory.mktemp("hsm")), ca, tokens=(("Token RSA", "rsa"), ("Token EC", "ec")))


@pytest.fixture(scope="session")
def token_certs(hsm):
    certs, libs = signing.list_certificates(extra_libs=[hsm.lib], include_windows=False, known_libs=[])
    return {c.token_label: c for c in certs}


def _contract(pages=2, rotate=0) -> bytes:
    from .conftest import _FONT
    d = pymupdf.open()
    for k in range(pages):
        p = d.new_page(width=595, height=842)
        tw = pymupdf.TextWriter(p.rect)
        f = _FONT[0] if _FONT else None
        tw.append((72, 100), f"HỢP ĐỒNG KINH TẾ – trang {k + 1}", font=f, fontsize=14)
        for i in range(10):
            tw.append((72, 140 + i * 20), "Điều khoản thỏa thuận giữa hai bên.", font=f, fontsize=11)
        if k == pages - 1:
            tw.append((80, 600), "ĐẠI DIỆN BÊN A", font=f, fontsize=12)
            tw.append((360, 600), "GIÁM ĐỐC", font=f, fontsize=12)
            tw.append((350, 616), "(Ký, ghi rõ họ tên)", font=f, fontsize=10)
        tw.write_text(p)
        if rotate:
            p.set_rotation(rotate)
    return d.tobytes()


def _red_png(w=400, h=200) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((10, 10, w - 10, h - 10), outline=(220, 0, 0, 255), width=18)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _red_bbox(pdf: bytes, page: int):
    """Khung bao các điểm ảnh đỏ trên trang (toạ độ hiển thị, pt) – kiểm tra hình ký nằm đúng chỗ."""
    d = PdfDocument(data=pdf)
    try:
        bm = d.render(page, 1.0)
        img = bm.to_pil().convert("RGB")
    finally:
        d.close()
    px = img.load()
    xs, ys = [], []
    for y in range(0, img.height, 2):
        for x in range(0, img.width, 2):
            r, g, b = px[x, y]
            if r > 150 and g < 90 and b < 90:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _soft_signer(ca, kind="rsa"):
    k = SoftKey(kind)
    return k, wincert.make_digest_signer(ca.issue(k.key.public_key()), k.sign_digest, [ca.der])


# ------------------------------------------------------------------ dò token
def test_lib_name_patterns():
    for name in ("vnpt-ca_csp11.dll", "viettel-ca_v6.dll", "eTPKCS11.dll", "ShuttleCsp11_3003.dll", "BkavCA.dll",
                 "fptca_pkcs11.dll", "opensc-pkcs11.dll", "eps2003csp11.dll", "SafeNetP11.dll", "ngp11v211.dll",
                 "gclib.dll", "cryptoki.dll", "IDPrimePKCS11.dll"):
        assert signing.LIB_NAME_RE.search(name), name
    for name in ("kernel32.dll", "user32.dll", "msvcp140.dll", "python312.dll"):
        assert not signing.LIB_NAME_RE.search(name), name


@needs_hsm
def test_list_certificates_finds_token_skips_ca(hsm, token_certs):
    assert set(token_certs) == {"Token RSA", "Token EC"}
    c = token_certs["Token RSA"]
    assert c.backend == PKCS11 and c.subject == CN and c.issuer == "CA Thử Nghiệm"
    assert c.key_id == b"\x01" and not c.expired and c.days_left > 300
    assert "Token RSA" in c.label


@needs_hsm
def test_env_variable_driver(hsm, monkeypatch):
    monkeypatch.setenv("PDFKYSO_PKCS11", hsm.lib)
    certs, libs = signing.list_certificates(include_windows=False, known_libs=[])
    assert hsm.lib in libs and len(certs) == 2


def test_probe_rejects_non_pkcs11(tmp_path):
    bad = tmp_path / "fake_pkcs11.so"
    bad.write_bytes(b"not a library")
    assert not signing.probe_lib(str(bad))
    certs, libs = signing.list_certificates(extra_libs=[str(bad)], include_windows=False, known_libs=[])
    assert libs == [] and certs == []


def test_is_signing_cert_filters_encryption_only(ca):
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert signing.is_signing_cert(ca.issue(k.public_key()))
    assert not signing.is_signing_cert(ca.issue(k.public_key(), signing=False))
    assert not signing.is_signing_cert(ca.der)


def test_expired_certificate_info(ca):
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    c = signing.parse_cert(ca.issue(k.public_key(), days=-1, start_days=-30), backend=PKCS11)
    assert c.expired and "HẾT HẠN" in c.label


# ------------------------------------------------------------------ ký bằng token PKCS#11
@needs_hsm
@pytest.mark.parametrize("label", ["Token RSA", "Token EC"])
def test_pkcs11_sign_visible_and_verify(ca, token_certs, label):
    pdf = _contract()
    signer, close = signing.open_signer(token_certs[label], PIN)
    try:
        t = time.perf_counter()
        out = signing.sign_pdf(pdf, signer, SignOptions(page=1, rect_pt=(350, 650, 550, 750),
                                                        appearance_png=_red_png(), reason="Phê duyệt"))
        assert time.perf_counter() - t < 3
    finally:
        close()
    rep = signing.verify_pdf(out, [ca.asn1()])
    assert len(rep) == 1
    r = rep[0]
    assert r.intact and r.valid and r.trusted and r.covers_whole and r.signer == CN
    assert r.summary == "Hợp lệ" and r.field == "ChuKy1"
    x0, y0, x1, y1 = _red_bbox(out, 1)
    assert 345 <= x0 and x1 <= 555 and 645 <= y0 and y1 <= 755     # hình ký nằm trong khung đã đặt
    assert out[:len(pdf)] == pdf                                     # lưu nối tiếp: bytes gốc giữ nguyên


@needs_hsm
def test_untrusted_without_root(token_certs):
    signer, close = signing.open_signer(token_certs["Token RSA"], PIN)
    try:
        out = signing.sign_pdf(_contract(1), signer, SignOptions())
    finally:
        close()
    r = signing.verify_pdf(out)[0]
    assert r.intact and r.valid and not r.trusted and "chưa xác minh" in r.summary


@needs_hsm
def test_wrong_pin(token_certs):
    with pytest.raises(signing.PinIncorrect):
        signing.open_signer(token_certs["Token RSA"], "000000")
    signer, close = signing.open_signer(token_certs["Token RSA"], PIN)    # PIN đúng vẫn ký được
    close()


@needs_hsm
def test_token_removed(token_certs):
    import dataclasses
    gone = dataclasses.replace(token_certs["Token RSA"], token_label="Token đã rút")
    with pytest.raises(signing.TokenRemoved):
        signing.open_signer(gone, PIN)


@needs_hsm
def test_two_signatures_on_same_file(ca, token_certs):
    pdf = _contract()
    for label, rect in (("Token RSA", (60, 640, 260, 740)), ("Token EC", (340, 640, 540, 740))):
        s, close = signing.open_signer(token_certs[label], PIN)
        try:
            pdf = signing.sign_pdf(pdf, s, SignOptions(page=1, rect_pt=rect, appearance_png=_red_png()))
        finally:
            close()
    reps = signing.verify_pdf(pdf, [ca.asn1()])
    assert [r.field for r in reps] == ["ChuKy1", "ChuKy2"]
    assert all(r.intact and r.valid and r.trusted for r in reps)
    assert reps[0].modified_after and not reps[1].modified_after
    assert PdfDocument(data=pdf).signature_count() == 2


# ------------------------------------------------------------------ đường Windows (ký theo giá trị băm)
@pytest.mark.parametrize("kind", ["rsa", "ec"])
def test_digest_signer_like_windows_driver(ca, kind):
    key, s = _soft_signer(ca, kind)
    out = signing.sign_pdf(_contract(1), s, SignOptions(reason="Duyệt", location="Hà Nội"))
    assert key.calls == 1                           # chỉ chạm token đúng 1 lần (driver hỏi PIN 1 lần)
    r = signing.verify_pdf(out, [ca.asn1()])[0]
    assert r.valid and r.trusted


def test_digest_signer_dry_run_does_not_touch_key(ca):
    import asyncio
    key, s = _soft_signer(ca)
    placeholder = asyncio.run(s.async_sign_raw(b"abc", "sha256", dry_run=True))
    assert key.calls == 0 and len(placeholder) == 256


def test_ecdsa_raw_to_der_roundtrip():
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    raw = (123456789).to_bytes(32, "big") + (987654321).to_bytes(32, "big")
    assert decode_dss_signature(wincert.ecdsa_raw_to_der(raw)) == (123456789, 987654321)


def test_windows_error_mapping():
    assert isinstance(wincert._error(0x8010006B, "ký"), signing.PinIncorrect)
    assert isinstance(wincert._error(0x8010006C, "ký"), signing.PinLocked)
    assert isinstance(wincert._error(0x80100069, "ký"), signing.TokenRemoved)
    e = wincert._error(0x8010006E, "ký")
    assert type(e) is signing.SigningError and "hủy" in str(e)
    assert "0x12345678" in str(wincert._error(0x12345678, "ký"))


def test_hardware_provider_detection():
    assert not wincert.is_hardware_provider("Microsoft Software Key Storage Provider")
    assert not wincert.is_hardware_provider("Microsoft Enhanced RSA and AES Cryptographic Provider")
    for p in ("Microsoft Smart Card Key Storage Provider", "VNPT-CA CSP", "Viettel-CA KSP", "eToken Base Cryptographic Provider"):
        assert wincert.is_hardware_provider(p)


# ------------------------------------------------------------------ tùy chọn ký
def test_certify_then_modify_is_detected(ca):
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    _, s = _soft_signer(ca)
    out = signing.sign_pdf(_contract(1), s, SignOptions(certify=True))
    r = signing.verify_pdf(out, [ca.asn1()])[0]
    assert r.valid and r.certify
    w = IncrementalPdfFileWriter(io.BytesIO(out))      # kẻ gian thêm ghi chú sau khi ký
    pg = w.root["/Pages"]["/Kids"][0].get_object()
    ann = w.add_object(generic.DictionaryObject({
        generic.NameObject("/Type"): generic.NameObject("/Annot"),
        generic.NameObject("/Subtype"): generic.NameObject("/Text"),
        generic.NameObject("/Rect"): generic.ArrayObject([generic.FloatObject(v) for v in (10, 10, 50, 50)])}))
    pg[generic.NameObject("/Annots")] = generic.ArrayObject([ann])
    w.update_container(pg)
    b = io.BytesIO()
    w.write(b)
    r = signing.verify_pdf(b.getvalue(), [ca.asn1()])[0]
    assert not r.valid and "KHÔNG HỢP LỆ" in r.summary


def test_tampered_bytes_invalid(ca):
    _, s = _soft_signer(ca)
    out = bytearray(signing.sign_pdf(_contract(1), s, SignOptions()))
    k = out.find(b"stream") + 20                   # sửa 1 byte trong nội dung trang
    out[k] ^= 0xFF
    reps = signing.verify_pdf(bytes(out), [ca.asn1()])
    assert reps and not (reps[0].intact and reps[0].valid)


def test_timestamp_embedded(ca):
    from asn1crypto import keys
    from cryptography.hazmat.primitives import serialization
    from pyhanko.sign.timestamps import DummyTimeStamper
    tsa_key = keys.PrivateKeyInfo.load(ca.key.private_bytes(serialization.Encoding.DER,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    _, s = _soft_signer(ca)
    out = signing.sign_pdf(_contract(1), s, SignOptions(timestamper=DummyTimeStamper(ca.asn1(), tsa_key)))
    r = signing.verify_pdf(out, [ca.asn1()])[0]
    assert r.timestamp and r.valid


@pytest.mark.parametrize("rot", [90, 180, 270])
def test_visible_signature_on_rotated_page(ca, rot):
    _, s = _soft_signer(ca)
    pdf = _contract(1, rotate=rot)
    d = PdfDocument(data=pdf)
    pw, ph = d.page_size_pt(0)
    d.close()
    rect = (pw - 230, ph - 130, pw - 30, ph - 30)                  # góc dưới phải như người dùng nhìn thấy
    out = signing.sign_pdf(pdf, s, SignOptions(rect_pt=rect, appearance_png=_red_png()))
    x0, y0, x1, y1 = _red_bbox(out, 0)
    assert rect[0] - 6 <= x0 and x1 <= rect[2] + 6 and rect[1] - 6 <= y0 and y1 <= rect[3] + 6
    assert (x1 - x0) > (y1 - y0)                                    # hình ký đứng thẳng (ngang hơn cao)


def test_tsa_unreachable_gives_friendly_error(ca):
    _, s = _soft_signer(ca)
    with pytest.raises(signing.SigningError) as ei:
        signing.sign_pdf(_contract(1), s, SignOptions(tsa_url="http://127.0.0.1:9/tsa"))
    assert "dấu thời gian" in str(ei.value)


def test_field_names_increment(ca):
    _, s = _soft_signer(ca)
    pdf = _contract(1)
    assert signing.next_field_name(pdf) == "ChuKy1"
    pdf = signing.sign_pdf(pdf, s, SignOptions())
    assert signing.next_field_name(pdf) == "ChuKy2"


def test_sign_large_document_fast(ca):
    d = pymupdf.open()
    for k in range(300):
        d.new_page().insert_text((72, 72), f"Trang {k + 1}")
    pdf = d.tobytes()
    _, s = _soft_signer(ca)
    t = time.perf_counter()
    out = signing.sign_pdf(pdf, s, SignOptions(page=299, rect_pt=(300, 600, 500, 700), appearance_png=_red_png()))
    assert time.perf_counter() - t < 5
    assert len(out) - len(pdf) < 120_000                            # chỉ thêm phần chữ ký, không phình file


def test_verify_unsigned_file():
    assert signing.verify_pdf(_contract(1)) == []


# ------------------------------------------------------------------ gợi ý vị trí, tiện ích
def test_find_sign_spot_under_title():
    d = PdfDocument(data=_contract(3))
    page, x, y = d.find_sign_spot()
    d.close()
    assert page == 2 and 600 < y < 720                              # ngay dưới "GIÁM ĐỐC"/"(Ký, ghi rõ…)"


def test_find_sign_spot_fallback():
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Không có chỗ ký")
    doc = PdfDocument(data=d.tobytes())
    page, x, y = doc.find_sign_spot()
    pw, ph = doc.page_size_pt(0)
    assert page == 0 and x > pw / 2 and y > ph / 2


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_user_display_roundtrip(rot):
    d = PdfDocument(data=_contract(1, rotate=rot))
    for x, y in ((10, 20), (300, 500), (100, 700)):
        ux, uy = d.display_to_user(0, x, y)
        assert d.user_to_display(0, ux, uy) == pytest.approx((x, y))


def test_default_output(tmp_path):
    src = tmp_path / "hop dong số 1.pdf"
    src.write_bytes(b"x")
    a = signing.default_output(str(src))
    assert a.endswith("hop dong số 1_da_ky.pdf")
    open(a, "wb").close()
    b = signing.default_output(str(src))
    assert b.endswith("_da_ky(2).pdf")
    assert signing.default_output(a) == b                            # ký lại file đã ký: không thành _da_ky_da_ky


def test_write_atomic(tmp_path):
    p = tmp_path / "a.pdf"
    signing.write_atomic(str(p), b"123")
    assert p.read_bytes() == b"123" and not os.path.exists(str(p) + ".tmp")


def test_safe_tz_fallback(monkeypatch):
    import tzlocal
    monkeypatch.setattr(tzlocal, "_pdfkyso_safe", False, raising=False)

    def broken():
        raise LookupError("Asia/Saigon")
    monkeypatch.setattr(tzlocal, "get_localzone", broken)
    signing._safe_tz()
    assert tzlocal.get_localzone().utcoffset(None) is not None


def test_ecdsa_raw_starting_with_0x30_is_converted():
    """Chữ ký thô r||s mà r bắt đầu bằng byte 0x30 không được coi nhầm là DER (lỗi ~1/256 lần ký bằng token EC)."""
    from app.wincert import _is_der_ecdsa, ecdsa_raw_to_der
    raw = bytes([0x30]) + bytes(range(1, 32)) + bytes(range(40, 72))
    assert len(raw) == 64 and not _is_der_ecdsa(raw, 32)
    der = ecdsa_raw_to_der(raw)
    assert _is_der_ecdsa(der, 32)
