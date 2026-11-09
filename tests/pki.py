"""Hạ tầng chứng thư giả lập cho kiểm thử ký số: CA thử nghiệm, chứng thư người ký (RSA/ECDSA) và
USB token giả lập bằng SoftHSM2 (chuẩn PKCS#11 như token thật)."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PIN = "123456"
SO_PIN = "12345678"
ORG = "Công ty Thử nghiệm"
CN = "CÔNG TY TNHH THỬ NGHIỆM"

SOFTHSM_LIBS = ["/usr/lib/softhsm/libsofthsm2.so", "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
                "/usr/local/lib/softhsm/libsofthsm2.so", "/opt/homebrew/lib/softhsm/libsofthsm2.so"]


def softhsm_lib() -> str | None:
    if not shutil.which("softhsm2-util"):
        return None
    return next((p for p in SOFTHSM_LIBS if os.path.exists(p)), None)


def _name(cn, org=ORG):
    return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


class CA:
    def __init__(self, name="CA Thử Nghiệm"):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(_name(name)).issuer_name(_name(name))
                     .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                     .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                     .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                     .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), True)
                     .sign(self.key, hashes.SHA256()))

    @property
    def der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    def asn1(self):
        from asn1crypto import x509 as ax
        return ax.Certificate.load(self.der)

    def issue(self, public_key, cn=CN, days=365, start_days=-1, signing=True) -> bytes:
        now = dt.datetime.now(dt.timezone.utc)
        ku = (x509.KeyUsage(True, True, False, False, False, False, False, False, False) if signing
              else x509.KeyUsage(False, False, True, True, False, False, False, False, False))
        b = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(self.cert.subject)
             .public_key(public_key).serial_number(x509.random_serial_number())
             .not_valid_before(now + dt.timedelta(days=start_days)).not_valid_after(now + dt.timedelta(days=days))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(ku, critical=True))
        if signing:
            b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
        return b.sign(self.key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


class SoftKey:
    """Khóa phần mềm đóng vai 'driver token' cho bộ ký theo giá trị băm (giống đường Windows)."""

    def __init__(self, kind="rsa"):
        self.kind = kind
        self.key = (rsa.generate_private_key(public_exponent=65537, key_size=2048) if kind == "rsa"
                    else ec.generate_private_key(ec.SECP256R1()))
        self.calls = 0

    def sign_digest(self, digest: bytes, hash_name: str) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
        self.calls += 1
        h = {"sha256": hashes.SHA256(), "sha384": hashes.SHA384(), "sha512": hashes.SHA512(),
             "sha1": hashes.SHA1()}[hash_name]
        if self.kind == "rsa":
            return self.key.sign(digest, padding.PKCS1v15(), Prehashed(h))
        der = self.key.sign(digest, ec.ECDSA(Prehashed(h)))
        r, s = decode_dss_signature(der)                   # trả r||s như CNG
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


class SoftHSM:
    """Khởi tạo các token SoftHSM trong thư mục tạm, sinh khóa ngay trên token (không lấy ra được,
    giống USB token thật), nạp chứng thư do CA cấp và cả chứng thư CA (phải bị loại khỏi danh sách ký)."""

    def __init__(self, folder: str, ca: CA, tokens=(("Token RSA", "rsa"),), cn=CN):
        import pkcs11
        self.lib = softhsm_lib()
        os.makedirs(os.path.join(folder, "tokens"), exist_ok=True)
        self.conf = os.path.join(folder, "softhsm2.conf")
        with open(self.conf, "w") as f:
            f.write(f"directories.tokendir = {folder}/tokens\nobjectstore.backend = file\nlog.level = ERROR\n")
        os.environ["SOFTHSM2_CONF"] = self.conf
        for label, _ in tokens:
            subprocess.run(["softhsm2-util", "--init-token", "--free", "--label", label, "--pin", PIN,
                            "--so-pin", SO_PIN], check=True, capture_output=True)
        try:
            pkcs11.unload(self.lib)
        except Exception:
            pass
        self.certs = {}
        lib = pkcs11.lib(self.lib)
        for label, kind in tokens:
            self.certs[label] = self._populate(lib.get_token(token_label=label), ca, kind, cn)
        try:
            pkcs11.unload(self.lib)           # phần mềm nạp lại như lần đầu cắm token
        except Exception:
            pass

    @staticmethod
    def _populate(tok, ca, kind, cn) -> bytes:
        from pkcs11 import Attribute, CertificateType, KeyType, ObjectClass
        with tok.open(rw=True, user_pin=PIN) as s:
            if kind == "rsa":
                from pkcs11.util.rsa import encode_rsa_public_key
                pub, _ = s.generate_keypair(KeyType.RSA, 2048, id=b"\x01", label="sign", store=True)
                pk = serialization.load_der_public_key(_spki_rsa(encode_rsa_public_key(pub)))
            else:
                from pkcs11.util.ec import encode_ec_public_key, encode_named_curve_parameters
                params = s.create_domain_parameters(KeyType.EC, {
                    Attribute.EC_PARAMS: encode_named_curve_parameters("secp256r1")}, local=True)
                pub, _ = params.generate_keypair(id=b"\x01", label="sign", store=True)
                pk = serialization.load_der_public_key(encode_ec_public_key(pub))
            der = ca.issue(pk, cn=cn)
            for value, oid, lbl, subj in ((der, b"\x01", "sign", x509.load_der_x509_certificate(der).subject),
                                          (ca.der, b"\x09", "ca", ca.cert.subject)):
                s.create_object({Attribute.CLASS: ObjectClass.CERTIFICATE,
                                 Attribute.CERTIFICATE_TYPE: CertificateType.X_509, Attribute.VALUE: value,
                                 Attribute.ID: oid, Attribute.LABEL: lbl, Attribute.TOKEN: True,
                                 Attribute.SUBJECT: subj.public_bytes()})
        return der


def _spki_rsa(pkcs1: bytes) -> bytes:
    from asn1crypto import keys
    return keys.PublicKeyInfo({"algorithm": {"algorithm": "rsa"},
                               "public_key": keys.RSAPublicKey.load(pkcs1)}).dump()


__all__ = ["CA", "SoftKey", "SoftHSM", "softhsm_lib", "PIN", "CN", "ORG", "encode_dss_signature"]
