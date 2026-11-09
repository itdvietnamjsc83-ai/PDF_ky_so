"""Ký số qua kho chứng thư Windows – dùng chính driver/phần mềm của USB token.

Khi cắm USB token, phần mềm của hãng (VNPT-CA, Viettel-CA, BKAV-CA, FPT-CA, EasyCA, Safe-CA,
Newtel-CA, MISA…) đăng ký chứng thư vào kho "Personal" của Windows và gắn nó với nhà cung cấp khóa
(KSP của CNG hoặc CSP của CryptoAPI) do hãng viết. Mô-đun này:

- đọc kho Personal, lấy chứng thư có khóa riêng (không chạm vào token -> không hỏi PIN);
- khi ký: nhờ Windows mở khóa riêng qua driver của hãng. Driver tự hiện hộp thoại nhập PIN của nó
  (đúng hộp thoại người dùng vẫn thấy khi kê khai thuế), phần mềm không bao giờ thấy mã PIN;
- ký giá trị băm bằng NCryptSignHash (CNG) hoặc CryptSignHash (CSP đời cũ), hỗ trợ RSA và ECDSA.

Phần ctypes chỉ nạp trên Windows. Lớp DigestSigner độc lập hệ điều hành để kiểm thử được mọi nơi.
"""
from __future__ import annotations

import hashlib
import logging
import sys

log = logging.getLogger(__name__)

# Nhà cung cấp khóa phần mềm của Microsoft (khóa nằm trên máy, không phải token)
SOFTWARE_PROVIDERS = {
    "microsoft software key storage provider",
    "microsoft base cryptographic provider v1.0",
    "microsoft enhanced cryptographic provider v1.0",
    "microsoft enhanced rsa and aes cryptographic provider",
    "microsoft rsa schannel cryptographic provider",
    "microsoft strong cryptographic provider",
    "microsoft base dss and diffie-hellman cryptographic provider",
    "microsoft enhanced dss and diffie-hellman cryptographic provider",
    "microsoft dh schannel cryptographic provider",
}

HASH_OIDS = {"sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha384": hashlib.sha384,
             "sha512": hashlib.sha512}


def is_hardware_provider(name: str) -> bool:
    return (name or "").strip().lower() not in SOFTWARE_PROVIDERS


def ecdsa_raw_to_der(raw: bytes) -> bytes:
    """CNG trả chữ ký ECDSA dạng r||s; CMS cần DER SEQUENCE{r, s}."""
    from asn1crypto.algos import DSASignature
    n = len(raw) // 2
    return DSASignature({"r": int.from_bytes(raw[:n], "big"),
                         "s": int.from_bytes(raw[n:], "big")}).dump()


def _is_der_ecdsa(sig: bytes, key_bytes: int) -> bool:
    """Chữ ký ECDSA đã ở dạng DER SEQUENCE{r, s}? (Trước đây chỉ xét byte đầu = 0x30 -> chữ ký thô r||s có r bắt
    đầu bằng 0x30 – khoảng 1/256 lần ký – bị coi nhầm là DER, chữ ký báo KHÔNG HỢP LỆ.)"""
    if len(sig) == 2 * key_bytes:                    # đúng độ dài r||s của khóa -> dạng thô
        return False
    if not sig.startswith(b"\x30"):
        return False
    try:
        from asn1crypto.algos import DSASignature
        v = DSASignature.load(sig)
        v["r"].native, v["s"].native                 # noqa: B018 – ép giải mã đủ
        return v.dump() == sig
    except Exception:
        return False


# ------------------------------------------------------------------ bộ ký theo giá trị băm
def _make_signer_base():
    from pyhanko.sign.signers.pdf_cms import Signer
    return Signer


_CLS = None


def _signer_class():
    global _CLS
    if _CLS is not None:
        return _CLS
    Signer = _make_signer_base()

    class _DigestSigner(Signer):
        """Signer của pyHanko; phép ký thật giao cho hàm sign_digest(digest, hash_name) -> bytes.
        RSA: trả chữ ký PKCS#1 v1.5; ECDSA: trả r||s (tự đổi sang DER)."""

        def __init__(self, cert_der: bytes, sign_digest, chain_der=(), close=None):
            from asn1crypto import x509
            from pyhanko_certvalidator.registry import SimpleCertificateStore
            cert = x509.Certificate.load(cert_der)
            others = [x509.Certificate.load(d) for d in chain_der if d != cert_der]
            super().__init__(signing_cert=cert,
                             cert_registry=SimpleCertificateStore.from_certs([cert] + others),
                             embed_roots=True)
            self._sign_digest = sign_digest
            self._close = close
            self._algo = cert.public_key.algorithm            # 'rsa' | 'ec'
            self._key_bytes = (cert.public_key.bit_size + 7) // 8

        async def async_sign_raw(self, data: bytes, digest_algorithm: str, dry_run=False) -> bytes:
            if dry_run:                                       # chỉ ước lượng kích thước, không chạm token
                if self._algo == "ec":
                    return bytes(8 + 2 * (self._key_bytes + 1))
                return bytes(self._key_bytes)
            name = digest_algorithm.lower().replace("-", "")
            if name not in HASH_OIDS:
                raise ValueError(f"Thuật toán băm không hỗ trợ: {digest_algorithm}")
            digest = HASH_OIDS[name](data).digest()
            sig = self._sign_digest(digest, name)
            if self._algo == "ec" and not _is_der_ecdsa(sig, self._key_bytes):
                sig = ecdsa_raw_to_der(sig)
            return sig

        def close(self):
            if self._close:
                try:
                    self._close()
                finally:
                    self._close = None

    _CLS = _DigestSigner
    return _DigestSigner


def make_digest_signer(cert_der: bytes, sign_digest, chain_der=(), close=None):
    return _signer_class()(cert_der, sign_digest, chain_der, close)


# ------------------------------------------------------------------ Windows API (ctypes)
_api = None


def _win():
    """Nạp các hàm Windows cần dùng (một lần)."""
    global _api
    if _api is not None:
        return _api
    if sys.platform != "win32":
        raise OSError("Chỉ có trên Windows")
    import ctypes
    from ctypes import wintypes as wt

    class CRYPT_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [("dwCertEncodingType", wt.DWORD), ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                    ("cbCertEncoded", wt.DWORD), ("pCertInfo", ctypes.c_void_p), ("hCertStore", ctypes.c_void_p)]

    class CRYPT_KEY_PROV_INFO(ctypes.Structure):
        _fields_ = [("pwszContainerName", wt.LPWSTR), ("pwszProvName", wt.LPWSTR), ("dwProvType", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("cProvParam", wt.DWORD), ("rgProvParam", ctypes.c_void_p),
                    ("dwKeySpec", wt.DWORD)]

    class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
        _fields_ = [("pszAlgId", wt.LPCWSTR)]

    class CERT_ENHKEY_USAGE(ctypes.Structure):
        _fields_ = [("cUsageIdentifier", wt.DWORD), ("rgpszUsageIdentifier", ctypes.c_void_p)]

    class CERT_USAGE_MATCH(ctypes.Structure):
        _fields_ = [("dwType", wt.DWORD), ("Usage", CERT_ENHKEY_USAGE)]

    class CERT_CHAIN_PARA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("RequestedUsage", CERT_USAGE_MATCH)]

    class CERT_CHAIN_ELEMENT(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("pCertContext", ctypes.POINTER(CERT_CONTEXT))]

    class CERT_SIMPLE_CHAIN(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("TrustStatus", wt.DWORD * 2), ("cElement", wt.DWORD),
                    ("rgpElement", ctypes.POINTER(ctypes.POINTER(CERT_CHAIN_ELEMENT)))]

    class CERT_CHAIN_CONTEXT(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("TrustStatus", wt.DWORD * 2), ("cChain", wt.DWORD),
                    ("rgpChain", ctypes.POINTER(ctypes.POINTER(CERT_SIMPLE_CHAIN)))]

    PCCERT = ctypes.POINTER(CERT_CONTEXT)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)

    def fn(dll, name, res, *args):
        f = getattr(dll, name)
        f.restype, f.argtypes = res, list(args)
        return f

    ns = type("Api", (), {})()
    ns.ct, ns.wt = ctypes, wt
    ns.CERT_CONTEXT, ns.PCCERT, ns.CRYPT_KEY_PROV_INFO = CERT_CONTEXT, PCCERT, CRYPT_KEY_PROV_INFO
    ns.BCRYPT_PKCS1_PADDING_INFO, ns.CERT_CHAIN_PARA = BCRYPT_PKCS1_PADDING_INFO, CERT_CHAIN_PARA
    ns.CERT_CHAIN_CONTEXT = CERT_CHAIN_CONTEXT
    ns.CertOpenStore = fn(crypt32, "CertOpenStore", ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                          ctypes.c_void_p, wt.DWORD, ctypes.c_void_p)
    ns.CertCloseStore = fn(crypt32, "CertCloseStore", wt.BOOL, ctypes.c_void_p, wt.DWORD)
    ns.CertEnumCertificatesInStore = fn(crypt32, "CertEnumCertificatesInStore", PCCERT, ctypes.c_void_p, PCCERT)
    ns.CertDuplicateCertificateContext = fn(crypt32, "CertDuplicateCertificateContext", PCCERT, PCCERT)
    ns.CertFreeCertificateContext = fn(crypt32, "CertFreeCertificateContext", wt.BOOL, PCCERT)
    ns.CertFindCertificateInStore = fn(crypt32, "CertFindCertificateInStore", PCCERT, ctypes.c_void_p, wt.DWORD,
                                       wt.DWORD, wt.DWORD, ctypes.c_void_p, PCCERT)
    ns.CertGetCertificateContextProperty = fn(crypt32, "CertGetCertificateContextProperty", wt.BOOL, PCCERT,
                                              wt.DWORD, ctypes.c_void_p, ctypes.POINTER(wt.DWORD))
    ns.CryptAcquireCertificatePrivateKey = fn(crypt32, "CryptAcquireCertificatePrivateKey", wt.BOOL, PCCERT,
                                              wt.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                              ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.BOOL))
    ns.CertGetCertificateChain = fn(crypt32, "CertGetCertificateChain", wt.BOOL, ctypes.c_void_p, PCCERT,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(CERT_CHAIN_PARA), wt.DWORD,
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(CERT_CHAIN_CONTEXT)))
    ns.CertFreeCertificateChain = fn(crypt32, "CertFreeCertificateChain", None,
                                     ctypes.POINTER(CERT_CHAIN_CONTEXT))
    ns.NCryptSignHash = fn(ncrypt, "NCryptSignHash", ctypes.c_long, ctypes.c_size_t, ctypes.c_void_p,
                           ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD)
    ns.NCryptSetProperty = fn(ncrypt, "NCryptSetProperty", ctypes.c_long, ctypes.c_size_t, wt.LPCWSTR,
                              ctypes.c_void_p, wt.DWORD, wt.DWORD)
    ns.NCryptGetProperty = fn(ncrypt, "NCryptGetProperty", ctypes.c_long, ctypes.c_size_t, wt.LPCWSTR,
                              ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD)
    ns.NCryptFreeObject = fn(ncrypt, "NCryptFreeObject", ctypes.c_long, ctypes.c_size_t)
    ns.CryptCreateHash = fn(advapi32, "CryptCreateHash", wt.BOOL, ctypes.c_size_t, wt.DWORD, ctypes.c_size_t,
                            wt.DWORD, ctypes.POINTER(ctypes.c_size_t))
    ns.CryptSetHashParam = fn(advapi32, "CryptSetHashParam", wt.BOOL, ctypes.c_size_t, wt.DWORD,
                              ctypes.c_void_p, wt.DWORD)
    ns.CryptSignHashW = fn(advapi32, "CryptSignHashW", wt.BOOL, ctypes.c_size_t, wt.DWORD, wt.LPCWSTR,
                           wt.DWORD, ctypes.c_void_p, ctypes.POINTER(wt.DWORD))
    ns.CryptDestroyHash = fn(advapi32, "CryptDestroyHash", wt.BOOL, ctypes.c_size_t)
    ns.CryptReleaseContext = fn(advapi32, "CryptReleaseContext", wt.BOOL, ctypes.c_size_t, wt.DWORD)
    ns.CryptSetProvParam = fn(advapi32, "CryptSetProvParam", wt.BOOL, ctypes.c_size_t, wt.DWORD,
                              ctypes.c_void_p, wt.DWORD)
    _api = ns
    return ns


CERT_STORE_PROV_SYSTEM_W = 10
CERT_SYSTEM_STORE_CURRENT_USER = 1 << 16
CERT_STORE_READONLY_FLAG = 0x8000
CERT_STORE_OPEN_EXISTING_FLAG = 0x4000
X509_ASN = 0x00010001
CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_FIND_SHA1_HASH = 0x10000
CRYPT_ACQUIRE_CACHE_FLAG = 0x1
CRYPT_ACQUIRE_COMPARE_KEY_FLAG = 0x4
CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG = 0x80
CRYPT_ACQUIRE_ALLOW_NCRYPT_KEY_FLAG = 0x10000
CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x20000
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
BCRYPT_PAD_PKCS1 = 0x2
PP_CLIENT_HWND = 1
HP_HASHVAL = 2
CALG = {"sha1": 0x8004, "sha256": 0x800C, "sha384": 0x800D, "sha512": 0x800E}

# Mã lỗi hay gặp -> thông báo dễ hiểu
ERRORS = {
    0x8010006E: "Bạn đã hủy nhập mã PIN.",                      # SCARD_W_CANCELLED_BY_USER
    0x800704C7: "Bạn đã hủy thao tác.",                          # ERROR_CANCELLED
    0x8010006B: "Sai mã PIN.",                                   # SCARD_W_WRONG_CHV
    0x8010006C: "Mã PIN đã bị khóa do nhập sai nhiều lần.",       # SCARD_W_CHV_BLOCKED
    0x80100069: "Không thấy USB token. Hãy cắm token rồi thử lại.",   # SCARD_W_REMOVED_CARD
    0x8010000C: "Không thấy USB token. Hãy cắm token rồi thử lại.",   # SCARD_E_NO_SMARTCARD
    0x80090016: "Không thấy khóa riêng trên token. Hãy cắm đúng token của chứng thư này.",  # NTE_BAD_KEYSET
    0x8009000D: "Không thấy khóa riêng trên token. Hãy cắm đúng token của chứng thư này.",  # NTE_NO_KEY
    0x80090029: "Driver của token không hỗ trợ thuật toán SHA-256. Hãy cập nhật phần mềm token của hãng.",
    0x80090008: "Driver của token không hỗ trợ thuật toán SHA-256. Hãy cập nhật phần mềm token của hãng.",
    0x80090030: "Token đang bận hoặc đã bị rút ra. Cắm lại token và thử lại.",   # NTE_DEVICE_NOT_READY
    0x8009001D: "Driver của token chưa được cài hoặc bị lỗi. Hãy cài phần mềm token của hãng.",  # NTE_PROV_DLL_NOT_FOUND
}


def _error(code: int, action: str):
    from .signing import PinIncorrect, PinLocked, SigningError, TokenRemoved
    code &= 0xFFFFFFFF
    if code in (0x8010006E, 0x800704C7):
        return SigningError(ERRORS[code])
    if code == 0x8010006B:
        return PinIncorrect(ERRORS[code])
    if code == 0x8010006C:
        return PinLocked(ERRORS[code])
    if code in (0x80100069, 0x8010000C, 0x80090030):
        return TokenRemoved(ERRORS[code])
    msg = ERRORS.get(code, f"Lỗi Windows khi {action} (mã 0x{code:08X}).")
    return SigningError(msg)


def _last_error() -> int:
    import ctypes
    e = ctypes.get_last_error()
    return (e | 0x80070000) if 0 < e < 0x10000 else e


def _open_store(name: str):
    a = _win()
    h = a.CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, None,
                        CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG | CERT_STORE_OPEN_EXISTING_FLAG,
                        a.ct.c_wchar_p(name))
    if not h:
        raise OSError(f"Không mở được kho chứng thư {name}")
    return h


def _der(pc) -> bytes:
    a = _win()
    c = pc.contents
    return a.ct.string_at(c.pbCertEncoded, c.cbCertEncoded)


def _prov_info(pc):
    """(tên nhà cung cấp khóa, loại, có khóa riêng?) – đọc thuộc tính, không chạm token."""
    a = _win()
    n = a.wt.DWORD(0)
    if not a.CertGetCertificateContextProperty(pc, CERT_KEY_PROV_INFO_PROP_ID, None, a.ct.byref(n)):
        return None
    buf = a.ct.create_string_buffer(n.value)
    if not a.CertGetCertificateContextProperty(pc, CERT_KEY_PROV_INFO_PROP_ID, buf, a.ct.byref(n)):
        return None
    info = a.ct.cast(buf, a.ct.POINTER(a.CRYPT_KEY_PROV_INFO)).contents
    return (info.pwszProvName or ""), info.dwProvType, (info.pwszContainerName or "")


def _iter_store(name: str):
    a = _win()
    h = _open_store(name)
    try:
        pc = a.CertEnumCertificatesInStore(h, None)
        while pc:
            yield pc
            pc = a.CertEnumCertificatesInStore(h, pc)       # tự giải phóng pc trước
    finally:
        a.CertCloseStore(h, 0)


def list_certificates():
    from .signing import WINDOWS, is_signing_cert, parse_cert
    out = []
    for pc in _iter_store("MY"):
        try:
            prov = _prov_info(pc)
            if prov is None:                                # không có khóa riêng -> không ký được
                continue
            der = _der(pc)
            if not is_signing_cert(der):
                continue
            name, ptype, container = prov
            out.append(parse_cert(der, backend=WINDOWS, hardware=is_hardware_provider(name), provider=name,
                                  extra={"prov_type": ptype, "container": container}))
        except Exception as e:
            log.warning("Bỏ qua một chứng thư trong kho Windows: %s", e)
    return out


def trust_roots():
    """Chứng thư gốc tin cậy của Windows (có sẵn gốc của Bộ TT&TT/NEAC nếu máy đã cài token)."""
    from asn1crypto import x509
    out = []
    for store in ("ROOT", "CA"):
        try:
            for pc in _iter_store(store):
                try:
                    c = x509.Certificate.load(_der(pc))
                    if store == "ROOT" or c.self_signed in ("yes", "maybe"):
                        out.append(c)
                except Exception:
                    pass
        except Exception as e:
            log.debug("Không đọc được kho %s: %s", store, e)
    return out


def _find(thumbprint: str):
    """Tìm lại chứng thư theo SHA-1 trong kho MY (trả về PCCERT đã nhân bản + handle kho)."""
    a = _win()
    h = _open_store("MY")
    raw = bytes.fromhex(thumbprint)
    buf = a.ct.create_string_buffer(raw, len(raw))

    class BLOB(a.ct.Structure):
        _fields_ = [("cbData", a.wt.DWORD), ("pbData", a.ct.c_void_p)]
    blob = BLOB(len(raw), a.ct.cast(buf, a.ct.c_void_p))
    pc = a.CertFindCertificateInStore(h, X509_ASN, 0, CERT_FIND_SHA1_HASH, a.ct.byref(blob), None)
    if not pc:
        a.CertCloseStore(h, 0)
        from .signing import TokenRemoved
        raise TokenRemoved("Không còn thấy chứng thư trong Windows. Hãy cắm USB token rồi bấm Làm mới.")
    return pc, h


def _chain(pc) -> list[bytes]:
    a = _win()
    para = a.CERT_CHAIN_PARA()
    para.cbSize = a.ct.sizeof(para)
    ctx = a.ct.POINTER(a.CERT_CHAIN_CONTEXT)()
    if not a.CertGetCertificateChain(None, pc, None, None, a.ct.byref(para), 0, None, a.ct.byref(ctx)):
        return []
    try:
        out = []
        c = ctx.contents
        if c.cChain:
            simple = c.rgpChain[0].contents
            for i in range(simple.cElement):
                out.append(_der(simple.rgpElement[i].contents.pCertContext))
        return out
    finally:
        a.CertFreeCertificateChain(ctx)


class _WinKey:
    """Khóa riêng mở qua driver của token. PIN do driver hỏi ở lần ký đầu tiên."""

    def __init__(self, thumbprint: str, hwnd: int = 0):
        self.a = _win()
        self.pc, self.store = _find(thumbprint)
        self.hwnd = hwnd
        self.handle = None
        self.spec = 0
        self.free = False

    def _acquire(self):
        if self.handle is not None:
            return
        a = self.a
        if self.hwnd:                                       # hộp thoại PIN của CSP nằm trên cửa sổ phần mềm
            hw = a.ct.c_void_p(self.hwnd)
            a.CryptSetProvParam(0, PP_CLIENT_HWND, a.ct.byref(hw), 0)
        h = a.ct.c_size_t(0)
        spec = a.wt.DWORD(0)
        free = a.wt.BOOL(0)
        flags = CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG | CRYPT_ACQUIRE_COMPARE_KEY_FLAG
        param = None
        if self.hwnd:
            hw = a.ct.c_void_p(self.hwnd)
            flags |= CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG
            param = a.ct.byref(hw)
        if not a.CryptAcquireCertificatePrivateKey(self.pc, flags, param, a.ct.byref(h), a.ct.byref(spec),
                                                   a.ct.byref(free)):
            raise _error(_last_error(), "mở khóa riêng trên token")
        self.handle, self.spec, self.free = h.value, spec.value, bool(free.value)
        if self.spec == CERT_NCRYPT_KEY_SPEC and self.hwnd:
            hw = a.ct.c_void_p(self.hwnd)
            a.NCryptSetProperty(self.handle, "HWND Handle", a.ct.byref(hw), a.ct.sizeof(hw), 0)

    def sign_digest(self, digest: bytes, hash_name: str, algo: str) -> bytes:
        self._acquire()
        a = self.a
        if self.spec == CERT_NCRYPT_KEY_SPEC:
            pad = None
            flags = 0
            if algo == "rsa":
                info = a.BCRYPT_PKCS1_PADDING_INFO(hash_name.upper())
                pad, flags = a.ct.byref(info), BCRYPT_PAD_PKCS1
            dbuf = a.ct.create_string_buffer(digest, len(digest))
            n = a.wt.DWORD(0)
            st = a.NCryptSignHash(self.handle, pad, dbuf, len(digest), None, 0, a.ct.byref(n), flags)
            if st:
                raise _error(st, "ký")
            out = a.ct.create_string_buffer(n.value)
            st = a.NCryptSignHash(self.handle, pad, dbuf, len(digest), out, n, a.ct.byref(n), flags)
            if st:
                raise _error(st, "ký")
            return out.raw[:n.value]
        # CSP đời cũ (CryptoAPI)
        hh = a.ct.c_size_t(0)
        if not a.CryptCreateHash(self.handle, CALG[hash_name], 0, 0, a.ct.byref(hh)):
            raise _error(_last_error(), "tạo giá trị băm")
        try:
            dbuf = a.ct.create_string_buffer(digest, len(digest))
            if not a.CryptSetHashParam(hh.value, HP_HASHVAL, dbuf, 0):
                raise _error(_last_error(), "đặt giá trị băm")
            n = a.wt.DWORD(0)
            if not a.CryptSignHashW(hh.value, self.spec, None, 0, None, a.ct.byref(n)):
                raise _error(_last_error(), "ký")
            out = a.ct.create_string_buffer(n.value)
            if not a.CryptSignHashW(hh.value, self.spec, None, 0, out, a.ct.byref(n)):
                raise _error(_last_error(), "ký")
            return out.raw[:n.value][::-1]                  # CryptoAPI trả little-endian
        finally:
            a.CryptDestroyHash(hh.value)

    def close(self):
        a = self.a
        if self.handle is not None and self.free:
            if self.spec == CERT_NCRYPT_KEY_SPEC:
                a.NCryptFreeObject(self.handle)
            else:
                a.CryptReleaseContext(self.handle, 0)
        self.handle = None
        if self.pc:
            a.CertFreeCertificateContext(self.pc)
            self.pc = None
        if self.store:
            a.CertCloseStore(self.store, 0)
            self.store = None


def WinSigner(cert, hwnd: int = 0):
    """Bộ ký pyHanko dùng khóa trên token qua driver Windows của hãng."""
    from asn1crypto import x509
    key = _WinKey(cert.thumbprint, hwnd)
    try:
        chain = _chain(key.pc)
    except Exception:
        chain = []
    algo = x509.Certificate.load(cert.der).public_key.algorithm
    return make_digest_signer(cert.der, lambda d, h: key.sign_digest(d, h, algo), chain, key.close)
