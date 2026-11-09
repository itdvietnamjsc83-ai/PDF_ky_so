"""Ký qua kho chứng thư Windows (đường dùng driver của hãng token). Chỉ chạy trên Windows khi CI đã tạo
sẵn chứng thư thử nghiệm (xem .github/workflows/windows.yml): KSP (CNG) RSA, KSP ECDSA và CSP đời cũ."""
import os
import sys

import pytest

from app import signing

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not os.environ.get("PDFKYSO_WIN_CERT_TEST"),
                                reason="chỉ chạy trên Windows CI có chứng thư thử nghiệm")

NAMES = ["PdfKySo CI KSP", "PdfKySo CI ECDSA", "PdfKySo CI CSP"]


@pytest.fixture(scope="module")
def win_certs():
    from app import wincert
    certs = {c.subject: c for c in wincert.list_certificates()}
    missing = [n for n in NAMES if n not in certs]
    assert not missing, f"thiếu chứng thư thử nghiệm: {missing}"
    return certs


def test_listed_with_provider(win_certs):
    for n in NAMES:
        c = win_certs[n]
        assert c.backend == signing.WINDOWS and c.provider
        assert not c.hardware                          # khóa phần mềm của Microsoft, không phải token


def test_trust_roots_not_empty():
    from app import wincert
    assert len(wincert.trust_roots()) > 5


@pytest.mark.parametrize("name", NAMES)
def test_sign_via_windows_store(win_certs, name):
    from asn1crypto import x509
    from .test_phase4 import _contract, _red_png
    c = win_certs[name]
    signer, close = signing.open_signer(c, hwnd=0)
    try:
        out = signing.sign_pdf(_contract(1), signer, signing.SignOptions(rect_pt=(300, 600, 500, 700),
                                                                        appearance_png=_red_png()))
    finally:
        close()
    r = signing.verify_pdf(out, [x509.Certificate.load(c.der)])[0]
    assert r.intact and r.valid and r.signer == name


def test_listing_merges_with_pkcs11(win_certs):
    certs, _ = signing.list_certificates(known_libs=[])
    assert {n for n in NAMES} <= {c.subject for c in certs}
