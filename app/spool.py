"""Nhận file từ máy in ảo "PDF Khay ghép" / "PDF Ký số".

Máy in ảo (dùng driver Microsoft Print to PDF có sẵn trong Windows) ghi file vào thư mục spool.
Phần mềm theo dõi thư mục, đợi file ghi xong, đổi tên duy nhất rồi chuyển sang khay ghép
hoặc mở để ký. Dùng QFileSystemWatcher (báo khi có thay đổi) -> không tốn CPU khi rảnh.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


def spool_root() -> str:
    """Thư mục máy in ảo ghi file. Bản cài đặt: C:\\ProgramData\\PdfKySo\\spool (bộ cài tạo sẵn, cấp quyền cho
    mọi người dùng – máy in chạy bằng tài khoản hệ thống nên không dùng được thư mục riêng của từng người)."""
    env = os.environ.get("PDFKYSO_SPOOL")
    if env:
        return env
    pd = os.environ.get("ProgramData")
    if pd and os.path.isdir(os.path.join(pd, "PdfKySo", "spool", "sign")):
        return os.path.join(pd, "PdfKySo", "spool")
    from .osutil import local_base
    return os.path.join(local_base(), "PdfKySo", "spool")


class SpoolWatcher(QObject):
    fileArrived = Signal(str, str)        # (loại: "tray" | "sign", đường dẫn file đã nhận)

    def __init__(self, root: str | None = None, parent=None):
        super().__init__(parent)
        self.root = root or spool_root()
        self.inbox = os.path.join(self.root, "inbox")
        self.dirs = {k: os.path.join(self.root, k) for k in ("tray", "sign")}
        for d in list(self.dirs.values()) + [self.inbox]:
            os.makedirs(d, exist_ok=True)
        self._watch = QFileSystemWatcher(list(self.dirs.values()), self)
        self._watch.directoryChanged.connect(lambda *_: self._timer.start())
        self._timer = QTimer(self, singleShot=True, interval=400, timeout=self.scan)
        self._sizes: dict[str, int] = {}
        self.scan()

    def scan(self):
        pending = False
        for kind, d in self.dirs.items():
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                if not name.lower().endswith(".pdf"):
                    continue
                src = os.path.join(d, name)
                try:
                    size = os.path.getsize(src)
                except OSError:
                    continue
                # chờ file ghi xong: kích thước không đổi giữa 2 lần quét và mở đọc được
                if size == 0 or self._sizes.get(src) != size:
                    self._sizes[src] = size
                    pending = True
                    continue
                dst = os.path.join(self.inbox, time.strftime("In_%Y%m%d_%H%M%S_") + f"{time.time_ns() % 10**6:06d}.pdf")
                try:
                    os.replace(src, dst)
                except OSError:          # máy in còn giữ file
                    pending = True
                    continue
                self._sizes.pop(src, None)
                self.fileArrived.emit(kind, dst)
        if pending:
            self._timer.start()

    def cleanup(self, days: int = 7):
        """Xóa file tạm cũ hơn N ngày."""
        limit = time.time() - days * 86400
        for name in os.listdir(self.inbox):
            p = os.path.join(self.inbox, name)
            try:
                if os.path.getmtime(p) < limit:
                    os.remove(p)
            except OSError:
                pass
