"""Ký số PDF bằng mọi USB token.

Hai đường kết nối, tự dò cả hai, người dùng không phải cấu hình:

1. PKCS#11 – chuẩn chung mọi hãng token (VNPT-CA, Viettel-CA, BKAV-CA, FPT-CA, MISA, EasyCA,
   Nacencomm, SafeCert…, và thẻ SafeNet/ePass/Feitian/OpenSC). Phần mềm quét các thư mục driver quen
   thuộc để tìm DLL PKCS#11, thử nạp từng DLL và giữ những DLL có token cắm vào. Người dùng có thể
   chỉ thêm DLL bằng tay nếu hãng đặt ở chỗ lạ.
2. Kho chứng thư Windows (CNG/CryptoAPI) – mọi token có driver đăng ký chứng thư vào Windows
   (gần như tất cả token tại Việt Nam, vì phục vụ kê khai thuế/hải quan). Mã PIN do chính driver
   của hãng hỏi -> tương thích tối đa. Xem wincert.py.

Chữ ký tạo theo chuẩn PAdES (ETSI EN 319 142) bằng pyHanko: SHA-256, có thể kèm dấu thời gian
(TSA), thông tin xác thực dài hạn (LTV) và ký chứng nhận (không cho sửa sau khi ký).
"""
from __future__ import annotations

import glob
import hashlib
import io
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

PKCS11 = "pkcs11"
WINDOWS = "windows"

# Tên file DLL PKCS#11 thường gặp chứa các cụm này (không phân biệt hoa thường)
LIB_NAME_RE = re.compile(r"(pkcs\s*#?\s*11|p11|cryptoki|csp11|opensc-pkcs11|etpkcs11|eps2003|"
                         r"shuttle|ngp11|ftp11|gclib|ep2k|vnpt|viettel|bkav|fpt|safenet|epass|smartcard|"
                         r"cardos|siecap|aetpkss|idprime)", re.I)
EXT = ".dll" if sys.platform == "win32" else (".dylib" if sys.platform == "darwin" else ".so")


def _safe_tz():
    """pyHanko lấy múi giờ máy qua tzlocal; một số máy đặt múi giờ kiểu cũ (vd. Asia/Saigon)
    hoặc thiếu dữ liệu múi giờ -> lỗi. Khi đó dùng độ lệch giờ hiện tại của máy (UTC+7)."""
    try:
        import tzlocal
    except ImportError:
        return
    if getattr(tzlocal, "_pdfkyso_safe", False):
        return
    orig = tzlocal.get_localzone

    def get_localzone():
        try:
            return orig()
        except Exception:
            from datetime import timedelta, timezone
            return timezone(timedelta(seconds=time.localtime().tm_gmtoff))
    tzlocal.get_localzone = get_localzone
    tzlocal._pdfkyso_safe = True


class SigningError(Exception):
    pass


class PinIncorrect(SigningError):
    def __init__(self, msg: str, final_try: bool = False, count_low: bool = False):
        super().__init__(msg)
        self.final_try = final_try
        self.count_low = count_low


class PinLocked(SigningError):
    pass


class TokenRemoved(SigningError):
    pass


class OwnerPasswordRequired(SigningError):
    pass


# ------------------------------------------------------------------ chứng thư
@dataclass
class CertInfo:
    backend: str
    der: bytes
    subject: str
    organization: str
    issuer: str
    serial: str
    not_before: float
    not_after: float
    thumbprint: str                         # SHA-1, giống cách Windows hiển thị
    lib_path: str = ""                      # PKCS#11
    token_label: str = ""
    token_serial: str = ""
    key_id: bytes = b""
    hardware: bool = True
    provider: str = ""                      # Windows: tên KSP/CSP
    extra: dict = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return time.time() > self.not_after

    @property
    def not_yet_valid(self) -> bool:
        return time.time() < self.not_before

    @property
    def days_left(self) -> int:
        return int((self.not_after - time.time()) // 86400)

    @property
    def label(self) -> str:
        who = self.subject + (f" – {self.organization}" if self.organization and self.organization not in self.subject else "")
        exp = time.strftime("%d/%m/%Y", time.localtime(self.not_after))
        src = f"token {self.token_label}" if self.backend == PKCS11 else ("USB token" if self.hardware else "máy tính")
        state = " (ĐÃ HẾT HẠN)" if self.expired else ""
        return f"{who} · {self.issuer} · hết hạn {exp} · {src}{state}"


def parse_cert(der: bytes, **kw) -> CertInfo:
    from asn1crypto import x509
    c = x509.Certificate.load(der)
    subj = c.subject.native
    iss = c.issuer.native
    return CertInfo(
        der=der,
        subject=subj.get("common_name") or subj.get("organization_name") or "(không tên)",
        organization=subj.get("organization_name") or "",
        issuer=iss.get("common_name") or iss.get("organization_name") or "",
        serial=format(c.serial_number, "X"),
        not_before=c["tbs_certificate"]["validity"]["not_before"].native.timestamp(),
        not_after=c["tbs_certificate"]["validity"]["not_after"].native.timestamp(),
        thumbprint=hashlib.sha1(der).hexdigest().upper(),
        **kw)


def is_signing_cert(der: bytes) -> bool:
    """Loại chứng thư CA / chứng thư chỉ để mã hóa khỏi danh sách ký."""
    from asn1crypto import x509
    c = x509.Certificate.load(der)
    try:
        if c.ca:
            return False
        ku = c.key_usage_value
        if ku is not None and not ({"digital_signature", "non_repudiation"} & set(ku.native)):
            return False
    except Exception:
        pass
    return True


# ------------------------------------------------------------------ dò thư viện PKCS#11
def search_dirs() -> list[tuple[str, int]]:
    """(thư mục, độ sâu quét)."""
    if sys.platform == "win32":
        win = os.environ.get("SystemRoot", r"C:\Windows")
        pf = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        return [(os.path.join(win, "System32"), 0)] + [(p, 3) for p in dict.fromkeys(filter(None, pf))]
    if sys.platform == "darwin":
        # driver token của các hãng trên Mac: /usr/local/lib, /Library/(Frameworks|Application Support)/…,
        # hoặc nằm trong gói ứng dụng quản lý token ở /Applications/<Hãng>.app/Contents/…
        return [("/usr/local/lib", 2), ("/Library", 4), ("/opt/homebrew/lib", 2), ("/Applications", 5),
                (os.path.expanduser("~/Library"), 3)]
    return [("/usr/lib", 3), ("/usr/local/lib", 3), ("/opt", 3)]


def candidate_libs(extra: list[str] | tuple = ()) -> list[str]:
    """Các file có tên giống DLL PKCS#11 (chưa nạp thử)."""
    out = [p for p in extra if p and os.path.isfile(p)]
    env = os.environ.get("PDFKYSO_PKCS11", "")
    out += [p for p in env.split(os.pathsep) if p and os.path.isfile(p)]
    for base, depth in search_dirs():
        if not os.path.isdir(base):
            continue
        for d in range(depth + 1):
            pattern = os.path.join(base, *(["*"] * d), "*" + EXT)
            for p in glob.glob(pattern):
                name = os.path.basename(p)
                if LIB_NAME_RE.search(name) and "x86" not in os.path.dirname(p).lower().split(os.sep)[-1:]:
                    out.append(p)
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def quiet_windows_loader_errors():
    """Windows: nạp thử một DLL hỏng / 32-bit / không phải DLL làm Windows bật hộp thoại "Bad Image" chặn cả phần
    mềm. Tắt các hộp thoại lỗi hệ thống đó (lỗi vẫn được báo về cho phần mềm xử lý bình thường)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        k32.SetErrorMode(k32.SetErrorMode(0) | 0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass


def _looks_like_library(path: str) -> bool:
    """Kiểm tra nhanh phần đầu file trước khi nạp: DLL Windows bắt đầu bằng "MZ", .so là ELF, .dylib là Mach-O."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if sys.platform == "win32":
        return head[:2] == b"MZ"
    return head in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or head[:2] == b"MZ"


def _load(path: str, refresh: bool = False):
    import pkcs11
    if not _looks_like_library(path):
        raise OSError(f"Không phải thư viện: {path}")
    quiet_windows_loader_errors()
    if refresh:
        try:
            pkcs11.unload(path)
        except Exception:
            pass
    return pkcs11.lib(path)


def probe_lib(path: str, refresh: bool = False) -> bool:
    """Nạp thử DLL: True nếu đúng là thư viện PKCS#11."""
    try:
        _load(path, refresh).get_slots(token_present=False)
        return True
    except Exception as e:
        log.debug("Bỏ qua %s: %s", path, e)
        return False


def pkcs11_certificates(lib_path: str, refresh: bool = False) -> list[CertInfo]:
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    out = []
    lib = _load(lib_path, refresh)
    for slot in lib.get_slots(token_present=True):
        try:
            tok = slot.get_token()
            if not tok.flags & pkcs11.TokenFlag.TOKEN_INITIALIZED:
                continue                          # khe trống / token chưa khởi tạo
            with tok.open() as s:            # không cần PIN để đọc chứng thư công khai
                for obj in s.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                    try:
                        der = bytes(obj[Attribute.VALUE])
                        if not is_signing_cert(der):
                            continue
                        try:
                            kid = bytes(obj[Attribute.ID])
                        except Exception:
                            kid = b""
                        out.append(parse_cert(der, backend=PKCS11, lib_path=lib_path,
                                              token_label=tok.label.strip(),
                                              token_serial=(tok.serial or b"").decode(errors="ignore").strip()
                                              if isinstance(tok.serial, bytes) else str(tok.serial or ""),
                                              key_id=kid,
                                              extra={"protected": bool(tok.flags & pkcs11.TokenFlag.PROTECTED_AUTHENTICATION_PATH)}))
                    except Exception as e:
                        log.warning("Không đọc được chứng thư trên %s: %s", tok.label, e)
        except pkcs11.exceptions.PKCS11Error as e:
            log.warning("Không mở được token ở %s: %s", lib_path, e)
    return out


def list_certificates(extra_libs=(), include_windows: bool = True, refresh: bool = False,
                      known_libs: list[str] | None = None) -> tuple[list[CertInfo], list[str]]:
    """Dò mọi chứng thư ký số dùng được. Trả về (chứng thư, các DLL PKCS#11 hợp lệ đã thấy).
    known_libs: danh sách DLL hợp lệ đã dò lần trước (bỏ qua bước quét ổ đĩa -> nhanh)."""
    env = [p for p in os.environ.get("PDFKYSO_PKCS11", "").split(os.pathsep) if p and os.path.isfile(p)]
    scanned = known_libs if known_libs is not None else candidate_libs(extra_libs)
    libs = list(dict.fromkeys(list(extra_libs) + env + list(scanned)))
    valid = [p for p in libs if probe_lib(p, refresh)]
    certs: list[CertInfo] = []
    for p in valid:
        try:
            certs += pkcs11_certificates(p, refresh)
        except Exception as e:
            log.warning("Lỗi đọc token qua %s: %s", p, e)
    if include_windows and sys.platform == "win32":
        try:
            from . import wincert
            certs += wincert.list_certificates()
        except Exception as e:
            log.warning("Không đọc được kho chứng thư Windows: %s", e)
    # cùng một chứng thư thấy qua cả 2 đường: ưu tiên PKCS#11 (chủ động hỏi PIN, ổn định hơn)
    best: dict[str, CertInfo] = {}
    for c in certs:
        cur = best.get(c.thumbprint)
        if cur is None or (cur.backend == WINDOWS and c.backend == PKCS11):
            best[c.thumbprint] = c
    ordered = sorted(best.values(), key=lambda c: (c.expired, not c.hardware, -c.not_after))
    return ordered, valid


# ------------------------------------------------------------------ tạo bộ ký
class _Pkcs11Handle:
    def __init__(self, cert: CertInfo, pin: str):
        import pkcs11
        from pkcs11 import exceptions as ex
        from pyhanko.sign.pkcs11 import PKCS11Signer
        lib = _load(cert.lib_path)
        tok = slot = None
        for sl in lib.get_slots(token_present=True):
            t = sl.get_token()
            if t.label.strip() == cert.token_label:
                tok, slot = t, sl
                break
        if tok is None:
            raise TokenRemoved("Không thấy token. Hãy cắm USB token rồi thử lại.")
        flags = tok.flags
        if flags & pkcs11.TokenFlag.USER_PIN_LOCKED:
            raise PinLocked("Mã PIN của token đã bị khóa do nhập sai nhiều lần. Liên hệ nhà cung cấp chữ ký số để mở khóa.")
        if cert.extra.get("protected") or flags & pkcs11.TokenFlag.PROTECTED_AUTHENTICATION_PATH:
            pin = pkcs11.PROTECTED_AUTH          # token có bàn phím / driver tự hỏi PIN
        try:
            self.session = tok.open(user_pin=pin)
        except ex.PinIncorrect:
            f2 = tok.flags
            raise PinIncorrect("Sai mã PIN.", bool(f2 & pkcs11.TokenFlag.USER_PIN_FINAL_TRY),
                               bool(f2 & pkcs11.TokenFlag.USER_PIN_COUNT_LOW))
        except ex.PinLocked:
            raise PinLocked("Mã PIN của token đã bị khóa. Liên hệ nhà cung cấp chữ ký số để mở khóa.")
        except ex.PinLenRange:
            raise PinIncorrect("Độ dài mã PIN không hợp lệ.")
        from asn1crypto import x509
        c = x509.Certificate.load(cert.der)
        self.signer = PKCS11Signer(self.session, signing_cert=c,
                                   key_id=cert.key_id or None, cert_id=cert.key_id or None, bulk_fetch=True,
                                   use_raw_mechanism=_needs_raw(slot, c.public_key.algorithm))

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


def _needs_raw(slot, algo: str) -> bool:
    """Nhiều token (và driver đời cũ) không có cơ chế 'băm + ký' SHA-256 mà chỉ có ký thô
    (CKM_RSA_PKCS / CKM_ECDSA). Khi đó băm bằng phần mềm rồi nhờ token ký thô -> vẫn ký được."""
    from pkcs11 import Mechanism
    try:
        mechs = set(slot.get_mechanisms())
    except Exception:
        return algo == "ec"
    full = Mechanism.SHA256_RSA_PKCS if algo == "rsa" else Mechanism.ECDSA_SHA256
    raw = Mechanism.RSA_PKCS if algo == "rsa" else Mechanism.ECDSA
    return full not in mechs and raw in mechs


def open_signer(cert: CertInfo, pin: str | None = None, hwnd: int = 0):
    """Trả về (signer của pyHanko, hàm đóng). PKCS#11 cần pin; Windows để driver tự hỏi PIN."""
    if cert.backend == PKCS11:
        h = _Pkcs11Handle(cert, pin or "")
        return h.signer, h.close
    from . import wincert
    s = wincert.WinSigner(cert, hwnd=hwnd)
    return s, s.close


# ------------------------------------------------------------------ ký
@dataclass
class SignOptions:
    page: int = 0
    rect_pt: tuple | None = None            # (x0, y0, x1, y1) toạ độ hiển thị, gốc trên-trái; None = ký ẩn
    appearance_png: bytes | None = None     # ảnh khung ký đã dựng sẵn (dấu + chữ ký + thông tin)
    reason: str = ""
    location: str = ""
    contact: str = ""
    tsa_url: str = ""
    ltv: bool = False
    certify: bool = False                   # ký chứng nhận: không cho phép thay đổi sau khi ký
    field_name: str = ""
    owner_password: str = ""                # file đã "Lưu có bảo vệ": cần mật khẩu chủ sở hữu để ký
    timestamper: object = None              # dùng cho kiểm thử


def _user_rect(pdf_bytes: bytes, page: int, rect) -> tuple[tuple[float, float, float, float], int]:
    """Đổi khung hiển thị -> toạ độ PDF của trang (có tính /Rotate). Trả về (rect, rotate)."""
    from .document import PdfDocument
    d = PdfDocument(data=pdf_bytes)
    try:
        x0, y0, x1, y1 = rect
        pts = [d.display_to_user(page, x, y) for x, y in ((x0, y0), (x1, y1))]
        rot = d.page(page).get_rotation()
    finally:
        d.close()
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys)), rot


def _reader(pdf_bytes: bytes):
    from pyhanko.pdf_utils.reader import PdfFileReader
    r = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
    if r.encrypted:
        try:
            r.decrypt("")                       # file bảo vệ không có mật khẩu mở
        except Exception:
            pass
    return r


def is_encrypted(pdf_bytes: bytes) -> bool:
    from pyhanko.pdf_utils.reader import PdfFileReader
    try:
        return bool(PdfFileReader(io.BytesIO(pdf_bytes), strict=False).encrypted)
    except Exception:
        return False


def next_field_name(pdf_bytes: bytes) -> str:
    r = _reader(pdf_bytes)
    try:
        names = {s.field_name for s in r.embedded_signatures}
    except Exception:
        names = set()
    k = 1
    while f"ChuKy{k}" in names:
        k += 1
    return f"ChuKy{k}"


def sign_pdf(pdf_bytes: bytes, signer, opts: SignOptions) -> bytes:
    """Ký và trả về bytes file đã ký (lưu nối tiếp: chữ ký cũ, nếu có, vẫn còn hiệu lực)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers, timestamps
    from pyhanko.sign.fields import MDPPerm, SigFieldSpec

    _safe_tz()
    w = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    if w.prev.encrypted:
        if not opts.owner_password:
            raise OwnerPasswordRequired("File đang được bảo vệ. Nhập mật khẩu chủ sở hữu (đặt khi bảo vệ file) để ký.")
        try:
            from pyhanko.pdf_utils.crypt import AuthStatus
            res = w.encrypt(opts.owner_password)
            if getattr(res, "status", None) not in (AuthStatus.OWNER,):
                raise OwnerPasswordRequired("Sai mật khẩu chủ sở hữu.")
        except OwnerPasswordRequired:
            raise
        except Exception as e:
            raise OwnerPasswordRequired("Sai mật khẩu chủ sở hữu.") from e
    name = opts.field_name or next_field_name(pdf_bytes)
    stamp_style = None
    existing = {f.name: f for f in empty_fields(pdf_bytes)}
    if name in existing:                     # ký vào ô đã chuẩn bị sẵn (luồng ký nhiều người)
        if opts.appearance_png:
            stamp_style = _image_stamp_style(opts.appearance_png, existing[name].rotate)
    elif opts.rect_pt:
        box, rot = _user_rect(pdf_bytes, opts.page, opts.rect_pt)
        fields.append_signature_field(w, SigFieldSpec(sig_field_name=name, on_page=opts.page, box=box))
        if opts.appearance_png:
            stamp_style = _image_stamp_style(opts.appearance_png, rot)
    else:
        fields.append_signature_field(w, SigFieldSpec(sig_field_name=name, on_page=opts.page, box=None))

    vc = None
    if opts.ltv:
        from pyhanko_certvalidator import ValidationContext
        vc = ValidationContext(allow_fetching=True, trust_roots=_trust_roots(signer))
    meta = signers.PdfSignatureMetadata(
        field_name=name, md_algorithm="sha256", reason=opts.reason or None,
        location=opts.location or None, contact_info=opts.contact or None,
        certify=opts.certify, docmdp_permissions=MDPPerm.NO_CHANGES if opts.certify else MDPPerm.FILL_FORMS,
        subfilter=fields.SigSeedSubFilter.PADES, embed_validation_info=opts.ltv,
        validation_context=vc, use_pades_lta=False)
    tsa = opts.timestamper
    if tsa is None and opts.tsa_url:
        tsa = timestamps.HTTPTimeStamper(opts.tsa_url, timeout=15)
    pdf_signer = signers.PdfSigner(meta, signer=signer, timestamper=tsa, stamp_style=stamp_style)
    out = io.BytesIO()
    try:
        pdf_signer.sign_pdf(w, output=out)
    except Exception as e:
        raise _friendly(e) from e
    return out.getvalue()


def _trust_roots(signer):
    roots = []
    try:
        for c in signer.cert_registry:
            if c.self_signed == "maybe" or c.self_signed == "yes":
                roots.append(c)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            from . import wincert
            roots += wincert.trust_roots()
        except Exception:
            pass
    return roots


def _friendly(e: Exception) -> Exception:
    msg = str(e)
    low = msg.lower()
    if "forbids all changes" in low or "docmdp" in low and "no_changes" in low:
        return SigningError("Không ký được: tài liệu đã được KHÓA bởi chữ ký trước (người ký đã chọn “không cho phép "
                            "thay đổi sau khi ký”). Mọi chữ ký thêm sẽ làm chữ ký đó mất hiệu lực.\n"
                            "Đề nghị bên gửi cung cấp bản chưa khóa để các bên cùng ký.")
    if isinstance(e, SigningError):
        return e
    if "timestamp" in low or "tsa" in low or "timed out" in low or "connection" in low:
        return SigningError("Không lấy được dấu thời gian (TSA). Kiểm tra Internet hoặc bỏ chọn dấu thời gian.\n" + msg)
    if "revocation" in low or "ocsp" in low or "crl" in low or "validation" in low:
        return SigningError("Không lấy được thông tin xác thực dài hạn (LTV). Kiểm tra Internet hoặc bỏ chọn LTV.\n" + msg)
    if "device" in low or "removed" in low or "token" in low:
        return TokenRemoved("Mất kết nối với USB token trong lúc ký. Cắm lại token và ký lại.\n" + msg)
    return SigningError(msg)


def _image_stamp_style(png: bytes, rotate: int):
    """Khung ký = đúng ảnh đã dựng (dấu + chữ ký + dòng thông tin), không thêm chữ của pyHanko."""
    from PIL import Image
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.pdf_utils.layout import AxisAlignment, Margins, SimpleBoxLayoutRule
    from pyhanko.stamp import StaticStampStyle
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    if rotate:
        img = img.rotate(rotate, expand=True)   # trang có /Rotate: xoay ảnh để hiển thị đứng thẳng
    return StaticStampStyle(background=PdfImage(img), background_opacity=1.0, border_width=0,
                            background_layout=SimpleBoxLayoutRule(
                                x_align=AxisAlignment.ALIGN_MID, y_align=AxisAlignment.ALIGN_MID,
                                margins=Margins(0, 0, 0, 0)))


# ------------------------------------------------------------------ luồng ký: ô chữ ký trống
@dataclass
class EmptyField:
    name: str
    page: int
    rect: tuple                  # khung hiển thị (x0, y0, x1, y1)
    rotate: int = 0


def empty_fields(pdf_bytes: bytes) -> list[EmptyField]:
    """Các ô chữ ký đã chuẩn bị nhưng chưa ai ký."""
    import pikepdf
    try:
        pk = pikepdf.open(io.BytesIO(pdf_bytes))
    except Exception:
        return []
    out = []
    from .document import PdfDocument
    d = None
    try:
        for i, page in enumerate(pk.pages):
            for a in page.obj.get("/Annots", []) or []:
                try:
                    ft = a.get("/FT") or (a.get("/Parent") or {}).get("/FT")
                    if ft != "/Sig" or a.get("/V") is not None or (a.get("/Parent") or {}).get("/V") is not None:
                        continue
                    name = str(a.get("/T") or (a.get("/Parent") or {}).get("/T") or "")
                    x0, y0, x1, y1 = [float(v) for v in a.Rect]
                    if abs(x1 - x0) < 1 or abs(y1 - y0) < 1:
                        continue
                    if d is None:
                        d = PdfDocument(data=pdf_bytes)
                    pts = [d.user_to_display(i, x, y) for x, y in ((x0, y0), (x1, y1))]
                    out.append(EmptyField(name, i, (min(p[0] for p in pts), min(p[1] for p in pts),
                                                    max(p[0] for p in pts), max(p[1] for p in pts)),
                                          int(page.obj.get("/Rotate", 0)) % 360))
                except Exception:
                    continue
    finally:
        pk.close()
        if d is not None:
            d.close()
    return out


def add_signature_fields(pdf_bytes: bytes, specs: list[tuple[str, int, tuple]]) -> bytes:
    """Chuẩn bị ô ký cho từng người: specs = [(tên ô, trang, khung hiển thị)]. Lưu nối tiếp."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields
    from pyhanko.sign.fields import SigFieldSpec
    _safe_tz()
    w = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    for name, page, rect in specs:
        box, _ = _user_rect(pdf_bytes, page, rect)
        fields.append_signature_field(w, SigFieldSpec(sig_field_name=name, on_page=page, box=box))
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# ------------------------------------------------------------------ ký hàng loạt
def sign_many(items, signer, progress=None, stop=None) -> list[tuple[str, str | None]]:
    """items: [(file nguồn, file đích, SignOptions)]. Mở token 1 lần, ký lần lượt.
    Trả về [(file nguồn, lỗi hoặc None)]; file lỗi không làm dừng các file khác."""
    results = []
    for k, (src, dst, opts) in enumerate(items, 1):
        if stop and stop():
            break
        try:
            with open(src, "rb") as f:
                data = f.read()
            write_atomic(dst, sign_pdf(data, signer, opts))
            results.append((src, None))
        except (PinLocked, TokenRemoved):
            raise
        except Exception as e:
            results.append((src, str(e) or type(e).__name__))
        if progress:
            progress(k, len(items))
    return results


# ------------------------------------------------------------------ kiểm tra chữ ký
@dataclass
class SigReport:
    field: str
    signer: str
    organization: str
    issuer: str
    signing_time: str
    timestamp: str
    intact: bool                 # nội dung đã ký còn nguyên
    valid: bool                  # chữ ký toán học đúng
    trusted: bool                # chuỗi chứng thư tới gốc tin cậy
    modified_after: bool         # có thay đổi sau khi ký (lưu nối tiếp)
    covers_whole: bool
    summary: str
    certify: bool = False
    expired_at_sign: bool = False
    mdp: int = 0                 # ký chứng nhận: 1 = khóa hoàn toàn, 2 = chỉ điền biểu mẫu/ký thêm, 3 = + ghi chú

    @property
    def who(self) -> str:
        return self.organization or self.signer or self.field


def verify_pdf(pdf_bytes: bytes, extra_roots=()) -> list[SigReport]:
    roots = list(extra_roots)
    if sys.platform == "win32":
        try:
            from . import wincert
            roots += wincert.trust_roots()
        except Exception:
            pass
    r = _reader(pdf_bytes)
    out = []
    with _quiet("pyhanko", "pyhanko_certvalidator"):
        out = _verify_all(r, roots)
    return out


class _quiet:
    """Tắt tạm log cảnh báo của thư viện (thiếu gốc tin cậy là chuyện bình thường, không phải lỗi)."""

    def __init__(self, *names):
        self.loggers = [logging.getLogger(n) for n in names]

    def __enter__(self):
        self.old = [lg.level for lg in self.loggers]
        for lg in self.loggers:
            lg.setLevel(logging.CRITICAL)

    def __exit__(self, *a):
        for lg, lv in zip(self.loggers, self.old):
            lg.setLevel(lv)


def _verify_all(r, roots) -> list[SigReport]:
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    out = []
    for sig in r.embedded_signatures:
        vc = ValidationContext(trust_roots=roots, allow_fetching=False)
        try:
            st = validate_pdf_signature(sig, vc)
        except Exception as e:
            out.append(SigReport(sig.field_name, "?", "", "", "", "", False, False, False, True, False,
                                 f"Không kiểm tra được: {e}"))
            continue
        cert = st.signing_cert
        subj = cert.subject.native
        iss = cert.issuer.native
        cov = str(getattr(st, "coverage", ""))
        whole = "ENTIRE_FILE" in cov
        modified = not whole
        t = st.signer_reported_dt.astimezone().strftime("%d/%m/%Y %H:%M:%S") if st.signer_reported_dt else ""
        ts = ""
        if st.timestamp_validity is not None:
            ts = st.timestamp_validity.timestamp.astimezone().strftime("%d/%m/%Y %H:%M:%S")
        trusted = bool(st.trusted)
        mdp_ok = getattr(st, "docmdp_ok", True) is not False
        if not st.intact or not st.valid:
            summary = "KHÔNG HỢP LỆ – nội dung đã bị thay đổi hoặc chữ ký hỏng"
        elif not mdp_ok:
            summary = "KHÔNG HỢP LỆ – nội dung trang đã bị thay đổi sau khi ký"
        elif trusted:
            summary = "Hợp lệ" + (" – có thay đổi được phép sau khi ký" if modified else "")
        else:
            summary = "Nội dung toàn vẹn, nhưng chưa xác minh được nhà cung cấp chứng thư (thiếu chứng thư gốc tin cậy)"
        out.append(SigReport(sig.field_name, subj.get("common_name", ""), subj.get("organization_name", ""),
                             iss.get("common_name", ""), t, ts, bool(st.intact), bool(st.valid) and mdp_ok, trusted,
                             modified, whole, summary, certify=_is_certify(sig), mdp=_mdp_level(sig)))
    return out


def _mdp_level(sig) -> int:
    try:
        lv = sig.docmdp_level
        return int(lv.value) if lv is not None else 0
    except Exception:
        return 0


@dataclass
class SigState:
    """Tóm tắt tình trạng chữ ký số có sẵn trong file (file đối tác gửi sang) để cảnh báo trước khi sửa / ký."""
    reports: list
    locked_by: str = ""          # người ký chứng nhận "không cho phép thay đổi" (không sửa, không ký thêm được)
    forms_only_by: str = ""      # ký chứng nhận cho phép ký thêm/điền biểu mẫu, không cho sửa nội dung
    invalid: list = field(default_factory=list)      # chữ ký đã hỏng / file bị sửa trái phép sau khi ký
    untrusted: list = field(default_factory=list)    # chưa xác minh được nhà cung cấp (thiếu chứng thư gốc)

    @property
    def names(self) -> list:
        return [r.who for r in self.reports]

    @property
    def locked(self) -> bool:
        return bool(self.locked_by)

    def short(self) -> str:
        ds = ", ".join(f"{r.who}{' (' + r.signing_time[:10] + ')' if r.signing_time else ''}" for r in self.reports)
        return f"{len(self.reports)} chữ ký số: {ds}"


def analyze_signatures(pdf_bytes: bytes, extra_roots=()) -> "SigState | None":
    """None nếu file chưa có chữ ký số."""
    if b"/ByteRange" not in pdf_bytes:
        return None
    try:
        reps = verify_pdf(pdf_bytes, extra_roots)
    except Exception as e:
        log.warning("Không kiểm tra được chữ ký: %s", e)
        return SigState([], invalid=["(không đọc được chữ ký trong file)"])
    if not reps:
        return None
    st = SigState(reps)
    for r in reps:
        if r.certify and r.mdp == 1:
            st.locked_by = r.who
        elif r.certify and r.mdp in (2, 3) and not st.forms_only_by:
            st.forms_only_by = r.who
        if not r.valid or not r.intact:
            st.invalid.append(r.who)
        elif not r.trusted:
            st.untrusted.append(r.who)
    return st



def _is_certify(sig) -> bool:
    try:
        return sig.docmdp_level is not None
    except Exception:
        return False


# ------------------------------------------------------------------ tiện ích file
def default_output(path: str) -> str:
    """hop-dong.pdf -> hop-dong_da_ky.pdf (đã có thì _da_ky(2).pdf …)."""
    base, _ = os.path.splitext(path)
    if base.endswith("_da_ky"):
        base = base[:-6]
    cand = base + "_da_ky.pdf"
    k = 2
    while os.path.exists(cand):
        cand = f"{base}_da_ky({k}).pdf"
        k += 1
    return cand


def write_atomic(path: str, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
