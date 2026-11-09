"""Thay thế tối thiểu cho tools/keygen.py khi kho mã không có bộ tạo key (kho GitHub không chứa keygen).
Chỉ dùng để kiểm thử với KHÓA MẪU (cụm mật khẩu mẫu công khai trong README)."""
import hashlib

KDF_SALT = b"PdfKySo-license-keypair-v1"


def derive_private(passphrase: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = hashlib.scrypt(passphrase.strip().encode("utf-8"), salt=KDF_SALT, n=2 ** 15, r=8, p=1,
                          maxmem=128 * 1024 * 1024, dklen=32)
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_hex(priv) -> str:
    from cryptography.hazmat.primitives import serialization
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def current_public():
    try:
        from app.license_key import PUBLIC_KEY
        return PUBLIC_KEY
    except Exception:
        return None
