"""Các cơ chế giúp phần mềm chạy ổn định sau khi đóng gói.

1. Ghi nhật ký (log) xoay vòng: %LOCALAPPDATA%\\PdfKySo\\logs\\app.log (tối đa 3 x 1 MB).
2. Bắt mọi lỗi chưa xử lý: ghi log + báo nhẹ nhàng, phần mềm KHÔNG tắt đột ngột.
3. faulthandler: nếu thư viện C gặp sự cố nghiêm trọng, ghi vết vào crash.log để sửa.
4. Chạy một phiên duy nhất: mở file lúc phần mềm đang chạy -> chuyển file sang cửa sổ đang mở
   (tránh 2 tiến trình cùng ghi thư viện dấu / thư mục máy in ảo).
5. Tự lưu bản khôi phục mỗi 2 phút cho tài liệu chưa lưu; mất điện/treo máy -> mở lại được.
"""
from __future__ import annotations

import faulthandler
import json
import logging
import logging.handlers
import io
import os
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("pdfkyso")


def local_dir(*parts) -> str:
    from .osutil import local_base, logs_base
    base = logs_base() if parts[:1] == ("logs",) else local_base()
    d = os.path.join(base, "PdfKySo", *parts)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- nhật ký + bắt lỗi
_crash_file = None


def setup_logging(level=logging.INFO) -> str:
    global _crash_file
    d = local_dir("logs")
    path = os.path.join(d, "app.log")
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(x, logging.handlers.RotatingFileHandler) for x in root.handlers):
        root.addHandler(h)
    try:
        _crash_file = open(os.path.join(d, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        pass
    return path


def install_excepthook(show_error=None):
    """show_error(message) được gọi trên luồng giao diện để báo lỗi cho người dùng."""
    last = {"t": 0.0}

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Lỗi chưa xử lý:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        now = time.time()
        if show_error and now - last["t"] > 3:     # không dội hàng loạt hộp thoại
            last["t"] = now
            try:
                show_error(f"{exc_type.__name__}: {exc}")
            except Exception:
                pass

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    return hook


# ---------------------------------------------------------------- một phiên duy nhất
class SingleInstance(QObject):
    filesReceived = Signal(list)

    def __init__(self, key: str | None = None):
        super().__init__()
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
        self.key = key or f"PdfKySo-{user}"
        self.server = None

    def send_to_running(self, files: list[str], timeout_ms: int = 800) -> bool:
        """True nếu đã có phiên đang chạy và đã chuyển file sang đó."""
        sock = QLocalSocket()
        sock.connectToServer(self.key)
        if not sock.waitForConnected(timeout_ms):
            return False
        def norm(f):                                  # giữ tiền tố "tray:" (thêm vào khay ghép)
            return "tray:" + os.path.abspath(f[5:]) if f.startswith("tray:") else os.path.abspath(f)
        # kết thúc bằng xuống dòng; ĐỢI phiên đang chạy đọc xong rồi tự ngắt (Windows: nếu bên gửi ngắt trước,
        # đường ống có thể bị đóng khi bên nhận chưa kịp đọc -> file không được mở)
        sock.write(json.dumps([norm(f) for f in files]).encode("utf-8") + b"\n")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        if sock.state() != QLocalSocket.UnconnectedState:
            sock.waitForDisconnected(max(timeout_ms, 3000))
        sock.abort()                                   # dọn hẳn trước khi đối tượng bị hủy
        return True

    def close(self):
        if self.server is not None:
            self.server.close()
            self.server = None

    def listen(self) -> bool:
        self.server = QLocalServer(self)
        if not self.server.listen(self.key):
            QLocalServer.removeServer(self.key)       # dọn socket cũ sau lần tắt đột ngột
            if not self.server.listen(self.key):
                log.warning("Không mở được kênh một phiên: %s", self.server.errorString())
                return False
        self.server.newConnection.connect(self._on_conn)
        return True

    def _on_conn(self):
        while self.server.hasPendingConnections():
            self._serve(self.server.nextPendingConnection())

    def _serve(self, sock):
        buf = bytearray()
        state = {"done": False}

        def done():
            if state["done"]:
                return
            state["done"] = True
            buf.extend(bytes(sock.readAll()))
            try:
                files = json.loads(bytes(buf).decode("utf-8").strip() or "[]")
            except ValueError:
                files = []
            self.filesReceived.emit([f for f in files if isinstance(f, str)])
            sock.disconnectFromServer()                # báo bên gửi: đã nhận xong
            sock.deleteLater()

        def ready():
            buf.extend(bytes(sock.readAll()))
            if buf.endswith(b"\n"):
                done()
        sock.readyRead.connect(ready)
        sock.disconnected.connect(done)
        ready()                                        # dữ liệu có thể đã tới trước khi nối tín hiệu
        if not state["done"] and sock.state() == QLocalSocket.UnconnectedState:
            done()


# ---------------------------------------------------------------- bản khôi phục
class Recovery(QObject):
    """Tự lưu tài liệu chưa lưu. Chỉ ghi khi nội dung đổi (theo doc.version) -> không tốn tài nguyên."""

    INTERVAL_MS = 120_000

    def __init__(self, get_docs, folder: str | None = None, parent=None):
        super().__init__(parent)
        self.folder = folder or local_dir("recovery")
        self.get_docs = get_docs                    # -> list[(key, PdfDocument, tiêu đề)]
        self._saved: dict[str, int] = {}
        self.timer = QTimer(self, interval=self.INTERVAL_MS, timeout=self.autosave)
        self.timer.start()

    def _paths(self, key: str):
        return os.path.join(self.folder, key + ".pdf"), os.path.join(self.folder, key + ".json")

    def autosave(self):
        alive = set()
        for key, doc, title in self.get_docs():
            alive.add(key)
            if not doc.modified:
                self.discard(key)
                continue
            if self._saved.get(key) == doc.version:
                continue
            pdf, meta = self._paths(key)
            try:
                tmp = pdf + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(doc.to_bytes())
                os.replace(tmp, pdf)
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump({"path": doc.path, "title": title, "time": time.time()}, f, ensure_ascii=False)
                self._saved[key] = doc.version
            except Exception:
                log.exception("Tự lưu bản khôi phục thất bại")
        for key in list(self._saved):
            if key not in alive:
                self.discard(key)

    def discard(self, key: str):
        self._saved.pop(key, None)
        for p in self._paths(key):
            try:
                os.remove(p)
            except OSError:
                pass

    def pending(self) -> list[dict]:
        """Bản khôi phục còn sót lại từ lần chạy trước (bị tắt đột ngột)."""
        out = []
        for name in os.listdir(self.folder):
            if name.endswith(".json"):
                key = name[:-5]
                pdf, meta = self._paths(key)
                if os.path.exists(pdf) and key not in self._saved:
                    try:
                        with open(meta, encoding="utf-8") as f:
                            d = json.load(f)
                        d.update(key=key, file=pdf)
                        out.append(d)
                    except (OSError, ValueError):
                        pass
        return sorted(out, key=lambda d: d.get("time", 0))

    def clear_all(self):
        for d in self.pending():
            self.discard(d["key"])


# ---------------------------------------------------------------- tự kiểm tra sau khi đóng gói
def _selftest_signing(pdf: bytes):
    """Ký thử bằng khóa tạm trong bộ nhớ (không cần token) rồi kiểm tra lại chữ ký."""
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID
    from . import signing, wincert
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tự kiểm tra")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
            .sign(key, hashes.SHA256())).public_bytes(Encoding.DER)
    hs = {"sha256": hashes.SHA256()}
    s = wincert.make_digest_signer(cert, lambda d, h: key.sign(d, padding.PKCS1v15(), Prehashed(hs[h])))
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGBA", (60, 30), (200, 0, 0, 255)).save(b, "PNG")
    out = signing.sign_pdf(pdf, s, signing.SignOptions(rect_pt=(50, 50, 170, 110), appearance_png=b.getvalue()))
    rep = signing.verify_pdf(out)
    if not (rep and rep[0].intact and rep[0].valid):
        raise RuntimeError("chữ ký tự kiểm tra không hợp lệ")


def selftest() -> int:
    """Chạy nhanh các chức năng lõi để chắc bản .exe có đủ thư viện. Trả về mã thoát 0 = ổn."""
    import io
    import tempfile
    steps = []
    try:
        from .document import PdfDocument
        d = PdfDocument()
        d.insert_blank(-1, 2)
        d.render(0, 1.0).close()
        steps.append("PDFium: tạo, render")
        tmp = os.path.join(tempfile.gettempdir(), "pdfkyso_selftest.pdf")
        d.save(tmp)
        steps.append("pikepdf: lưu tối ưu")
        from .imaging import remove_background
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (40, 40), (255, 255, 255)).save(b, "PNG")
        remove_background(b.getvalue())
        steps.append("Pillow: tách nền")
        from .library import Library
        lib = Library(os.path.join(tempfile.gettempdir(), "pdfkyso_selftest_lib.pdf"))
        lib.set_password("selftest123")
        steps.append("Thư viện dấu: mã hóa AES-256")
        from . import editing, fonts
        editing.add_text(d, 0, 50, 50, "Tiếng Việt ạệữ", fonts.handwriting_path("PatrickHand.ttf"), 12)
        steps.append("Phông chữ + hộp chữ")
        ui_font = os.path.join(fonts.assets_dir(), "fonts", "ui", "BeVietnamPro-Regular.ttf")
        if not os.path.isfile(ui_font):
            raise RuntimeError("Thiếu phông giao diện assets/fonts/ui (kiểm tra cờ --include-data-dir khi biên dịch)")
        steps.append("Phông giao diện Be Vietnam Pro")
        _selftest_signing(d.to_bytes())
        steps.append("Ký số PAdES + kiểm tra chữ ký")
        from . import license as L
        L.public_key()
        steps.append(f"Bản quyền (mã máy {L.machine_code()})")
        import pkcs11                                # driver PKCS#11 của USB token
        pkcs11.lib  # noqa: B018
        steps.append("PKCS#11")
        if sys.platform == "darwin":
            from . import macintegration
            steps.append(f"macOS: {macintegration.selftest()}")
        if sys.platform == "win32":
            from . import wincert
            n = len(wincert.list_certificates())
            wincert.trust_roots()
            steps.append(f"Kho chứng thư Windows ({n} chứng thư ký được)")
        os.remove(tmp)
        os.remove(lib.path)
        print("SELFTEST OK:", "; ".join(steps))
        return 0
    except Exception:
        print("SELFTEST FAIL sau:", "; ".join(steps))
        traceback.print_exc()
        return 1
