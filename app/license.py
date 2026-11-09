"""Bản quyền offline theo mã máy.

- Mã máy: băm SHA-256 từ MachineGuid của Windows + số sê-ri ổ hệ thống -> 16 ký tự (XXXX-XXXX-XXXX-XXXX).
  Cài lại phần mềm không đổi mã máy; cài lại Windows / đổi ổ cứng thì đổi -> cấp lại key.
- Mã kích hoạt: chữ ký số Ed25519 (thư viện cryptography, có sẵn trong phần mềm) trên nội dung
  {mã máy, hạn dùng, gói, số thứ tự}. Phần mềm chỉ chứa KHÓA CÔNG KHAI -> không ai tạo được key giả,
  kể cả khi dịch ngược phần mềm.
- Một cặp khóa cố định: khóa bí mật sinh ra từ "cụm mật khẩu nhà phát triển" (tools/keygen.py). Không có
  file khóa nào để làm mất – nhớ cụm mật khẩu là cấp được key ở bất kỳ máy nào, không phải đóng gói lại.
- Dùng thử 15 ngày: ngày bắt đầu lưu ở nhiều nơi (thư mục dữ liệu, Registry, ProgramData) kèm mã chống sửa;
  phát hiện chỉnh lùi đồng hồ máy.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import struct
import sys
import time
from dataclasses import dataclass

TRIAL_DAYS = 15
EPOCH = dt.date(2024, 1, 1)
FOREVER = 0xFFFF
EDITIONS = {1: "Tiêu chuẩn", 2: "Chuyên nghiệp", 3: "Doanh nghiệp"}
_SALT = b"PdfKySo-trial-v1"


class LicenseError(Exception):
    pass


# ------------------------------------------------------------------ mã máy
def _machine_sources() -> list[str]:
    out = []
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                               winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
            out.append(winreg.QueryValueEx(k, "MachineGuid")[0])
        except OSError:
            pass
        try:
            import ctypes
            serial = ctypes.c_ulong(0)
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            if ctypes.windll.kernel32.GetVolumeInformationW(drive, None, 0, ctypes.byref(serial), None, None, None, 0):
                out.append(f"{serial.value:08X}")
        except Exception:
            pass
    elif sys.platform == "darwin":
        from .osutil import mac_machine_ids
        out += mac_machine_ids()
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(p) as f:
                    out.append(f.read().strip())
                break
            except OSError:
                pass
    if not out:
        import uuid
        out.append(f"{uuid.getnode():012X}")
    return out


def machine_code() -> str:
    h = hashlib.sha256("|".join(_machine_sources()).encode("utf-8") + b"PdfKySo-machine").digest()
    s = base64.b32encode(h[:10]).decode()          # 16 ký tự A–Z2–7, không nhầm 0/O 1/I
    return "-".join(s[i:i + 4] for i in range(0, 16, 4))


def normalize_code(code: str) -> str:
    s = "".join(c for c in code.upper() if c.isalnum())
    if len(s) != 16:
        raise LicenseError("Mã máy không đúng (phải có 16 ký tự).")
    return "-".join(s[i:i + 4] for i in range(0, 16, 4))


def _code_hash(code: str) -> bytes:
    return hashlib.sha256(normalize_code(code).encode()).digest()[:8]


# ------------------------------------------------------------------ mã kích hoạt
@dataclass
class License:
    machine: str
    expiry: dt.date | None          # None = vĩnh viễn
    edition: int
    serial: int

    @property
    def edition_name(self) -> str:
        return EDITIONS.get(self.edition, f"Gói {self.edition}")

    def days_left(self, today: dt.date | None = None) -> int | None:
        if self.expiry is None:
            return None
        return (self.expiry - (today or dt.date.today())).days

    def describe(self) -> str:
        return f"{self.edition_name} · " + ("vĩnh viễn" if self.expiry is None else
                                            f"đến hết ngày {self.expiry:%d/%m/%Y}")


def _payload(code: str, expiry: dt.date | None, edition: int, serial: int) -> bytes:
    days = FOREVER if expiry is None else (expiry - EPOCH).days
    if expiry is not None and not 0 <= days < FOREVER:
        raise LicenseError("Hạn dùng không hợp lệ.")
    return _code_hash(code) + struct.pack(">HBH", days, edition & 0xFF, serial & 0xFFFF)


def format_key(raw: bytes) -> str:
    s = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(s[i:i + 6] for i in range(0, len(s), 6))


def parse_key(text: str) -> bytes:
    s = "".join(c for c in text.upper() if c.isalnum())
    if len(s) < 100:
        raise LicenseError("Mã kích hoạt không đầy đủ. Hãy dán nguyên văn cả mã.")
    try:
        return base64.b32decode(s + "=" * (-len(s) % 8))
    except Exception as e:
        raise LicenseError("Mã kích hoạt có ký tự không hợp lệ.") from e


def sign_key(private_key, code: str, expiry: dt.date | None, edition: int = 1, serial: int = 1) -> str:
    """Dùng trong bộ tạo key (tools/keygen.py) – cần khóa bí mật."""
    p = _payload(code, expiry, edition, serial)
    return format_key(p + private_key.sign(p))


def public_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from .license_key import PUBLIC_KEY
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY))


def verify_key(key: str, code: str | None = None, pub=None) -> License:
    from cryptography.exceptions import InvalidSignature
    raw = parse_key(key)
    if len(raw) != 13 + 64:
        raise LicenseError("Mã kích hoạt không đúng định dạng.")
    p, sig = raw[:13], raw[13:]
    try:
        (pub or public_key()).verify(sig, p)
    except InvalidSignature as e:
        raise LicenseError("Mã kích hoạt không hợp lệ.") from e
    code = normalize_code(code or machine_code())
    if p[:8] != _code_hash(code):
        raise LicenseError("Mã kích hoạt này cấp cho máy khác. Hãy gửi đúng mã máy của máy này để được cấp key.")
    days, edition, serial = struct.unpack(">HBH", p[8:])
    exp = None if days == FOREVER else EPOCH + dt.timedelta(days=days)
    return License(code, exp, edition, serial)


# ------------------------------------------------------------------ lưu trạng thái (nhiều nơi)
def _data_file() -> str:
    from .library import data_dir
    return os.path.join(data_dir(), "license.dat")


def _programdata_file() -> str | None:
    base = os.environ.get("ProgramData")
    return os.path.join(base, "PdfKySo", ".ps") if base else None


def _mac(obj: dict) -> str:
    body = json.dumps({k: obj[k] for k in sorted(obj) if k != "mac"}, sort_keys=True).encode()
    return hmac.new(hashlib.sha256(_SALT + machine_code().encode()).digest(), body, hashlib.sha256).hexdigest()[:24]


def _machine_tag() -> str:
    return hashlib.sha256(b"tag|" + machine_code().encode()).hexdigest()[:12]


def _check(d: dict) -> dict | None:
    """Dữ liệu của máy khác (vd. thư mục portable mang từ máy khác sang) -> bỏ qua, không coi là gian lận."""
    if d.get("m") and d["m"] != _machine_tag():
        return None
    return d if d.get("mac") == _mac(d) else {"tampered": True}


def _read_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return _check(d)
    except (OSError, ValueError, AttributeError):
        return None


def _write_json(path: str | None, d: dict):
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        d = dict(d)
        d["m"] = _machine_tag()
        d["mac"] = _mac(d)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _reg_get() -> dict | None:
    alt = os.environ.get("PDFKYSO_REG_FILE")          # kiểm thử: không đụng Registry thật của máy
    if alt:
        return _read_json(alt)
    if sys.platform == "darwin":                     # macOS: bản sao trạng thái trong ~/Library/Preferences
        from .osutil import mac_state_file
        return _read_json(mac_state_file())
    if sys.platform != "win32":
        return None
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\PdfKySo")
        d = json.loads(winreg.QueryValueEx(k, "s")[0])
        return _check(d)
    except (OSError, ValueError):
        return None


def _reg_set(d: dict):
    alt = os.environ.get("PDFKYSO_REG_FILE")
    if alt:
        _write_json(alt, d)
        return
    if sys.platform == "darwin":
        from .osutil import mac_state_file
        _write_json(mac_state_file(), d)
        return
    if sys.platform != "win32":
        return
    try:
        import winreg
        d = dict(d)
        d["m"] = _machine_tag()
        d["mac"] = _mac(d)
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\PdfKySo")
        winreg.SetValueEx(k, "s", 0, winreg.REG_SZ, json.dumps(d))
    except OSError:
        pass


def _load_state() -> dict:
    parts = [p for p in (_read_json(_data_file()), _reg_get(), _read_json(_programdata_file())) if p]
    st = {"tampered": any(p.get("tampered") for p in parts)}
    good = [p for p in parts if not p.get("tampered")]
    starts = [p["trial_start"] for p in good if p.get("trial_start")]
    seen = [p.get("last_seen", 0) for p in good]
    keys = [p["key"] for p in good if p.get("key")]
    st["trial_start"] = min(starts) if starts else None
    st["last_seen"] = max(seen) if seen else 0
    st["key"] = keys[0] if keys else None
    return st


def _save_state(st: dict):
    d = {k: st.get(k) for k in ("trial_start", "last_seen", "key")}
    _write_json(_data_file(), d)
    _reg_set(d)
    _write_json(_programdata_file(), d)


# ------------------------------------------------------------------ trạng thái bản quyền
ACTIVE, TRIAL, NEW, TRIAL_OVER, EXPIRED, CLOCK, INVALID = ("active", "trial", "new", "trial_over", "expired",
                                                            "clock", "invalid")


@dataclass
class Status:
    kind: str
    days_left: int | None = None
    license: License | None = None
    message: str = ""

    @property
    def usable(self) -> bool:
        return self.kind in (ACTIVE, TRIAL)

    @property
    def short(self) -> str:
        if self.kind == ACTIVE:
            return "Đã kích hoạt · " + self.license.describe()
        if self.kind == TRIAL:
            return f"Dùng thử · còn {self.days_left} ngày"
        return self.message


def status(now: float | None = None) -> Status:
    now = now or time.time()
    st = _load_state()
    if st["last_seen"] and now < st["last_seen"] - 2 * 86400:
        return Status(CLOCK, message="Đồng hồ máy tính đang bị chỉnh lùi. Hãy đặt lại đúng ngày giờ.")
    if st["key"]:
        try:
            lic = verify_key(st["key"])
            left = lic.days_left(dt.date.fromtimestamp(now))
            if left is not None and left < 0:
                return Status(EXPIRED, 0, lic, f"Bản quyền đã hết hạn ngày {lic.expiry:%d/%m/%Y}.")
            _touch(st, now)
            return Status(ACTIVE, left, lic)
        except LicenseError:
            pass                                  # key của máy khác / hỏng -> xét dùng thử
    if st["tampered"] and not st["trial_start"]:
        return Status(INVALID, message="Thông tin bản quyền trên máy bị sửa đổi. Hãy nhập mã kích hoạt.")
    if not st["trial_start"]:
        return Status(NEW, TRIAL_DAYS, message="Chưa kích hoạt.")
    used = int((now - st["trial_start"]) // 86400)
    left = TRIAL_DAYS - used
    if left <= 0:
        return Status(TRIAL_OVER, 0, message="Đã hết thời gian dùng thử 15 ngày.")
    _touch(st, now)
    return Status(TRIAL, left)


def _touch(st: dict, now: float):
    if now > st.get("last_seen", 0) + 3600:           # ghi tối đa 1 lần/giờ
        st["last_seen"] = now
        _save_state(st)


def start_trial(now: float | None = None) -> Status:
    st = _load_state()
    if not st["trial_start"]:
        st["trial_start"] = now or time.time()
        st["last_seen"] = now or time.time()
        _save_state(st)
    return status(now)


def activate(key: str) -> License:
    lic = verify_key(key)
    if lic.days_left() is not None and lic.days_left() < 0:
        raise LicenseError(f"Mã kích hoạt đã hết hạn ngày {lic.expiry:%d/%m/%Y}.")
    st = _load_state()
    st["key"] = format_key(parse_key(key))
    st["last_seen"] = max(st.get("last_seen") or 0, time.time())
    _save_state(st)
    return lic


def read_license_file(path: str) -> str:
    """File .lic do nhà phát triển gửi: chứa mã kích hoạt (và thông tin khách hàng)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for line in text.splitlines():
        if line.lower().startswith("ma kich hoat:") or line.lower().startswith("mã kích hoạt:"):
            return line.split(":", 1)[1].strip()
    return text.strip()
