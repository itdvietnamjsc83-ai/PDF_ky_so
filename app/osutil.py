"""Tiện ích theo hệ điều hành (Windows / macOS / Linux): thư mục dữ liệu, mở file, hiện file trong thư mục,
chữ phím tắt (Ctrl ↔ ⌘ trên Mac), mã máy macOS."""
from __future__ import annotations

import os
import subprocess
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
APP_DIR_NAME = "PdfKySo"


def roaming_base() -> str:
    """Thư mục gốc cho dữ liệu người dùng (thư viện dấu, cài đặt, bản quyền)."""
    env = os.environ.get("APPDATA")
    if env:
        return env
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def local_base() -> str:
    """Thư mục gốc cho dữ liệu máy (nhật ký, bản nháp, bộ nhớ đệm, máy in ảo)."""
    env = os.environ.get("LOCALAPPDATA")
    if env:
        return env
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def logs_base() -> str:
    if IS_MAC and not os.environ.get("LOCALAPPDATA"):
        return os.path.expanduser("~/Library/Logs")
    return local_base()


def reveal(path: str):
    """Mở thư mục chứa file và chọn sẵn file đó (Explorer / Finder)."""
    path = os.path.abspath(path)
    try:
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return
        if IS_MAC:
            subprocess.Popen(["open", "-R", path])
            return
    except OSError:
        pass
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) if os.path.isfile(path) else path))


def open_path(path: str):
    """Mở file bằng phần mềm mặc định của máy."""
    try:
        if IS_WIN:
            os.startfile(path)                     # noqa: S606
            return
        if IS_MAC:
            subprocess.Popen(["open", path])
            return
    except OSError:
        pass
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def kbd(text: str) -> str:
    """Chữ hướng dẫn phím tắt đúng thói quen từng máy: trên Mac "Ctrl+Z" -> "⌘Z", "Alt" -> "⌥"."""
    if not IS_MAC or not text:
        return text
    return (text.replace("Ctrl + ", "⌘").replace("Ctrl+", "⌘").replace("Ctrl ", "⌘ ")
            .replace("Alt+", "⌥").replace("Alt ", "⌥ ").replace("(Alt", "(⌥"))


def mac_machine_ids() -> list[str]:
    """macOS: UUID phần cứng + số sê-ri máy (không đổi khi cài lại hệ điều hành)."""
    out = []
    try:
        r = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                           text=True, timeout=5)
        for line in r.stdout.splitlines():
            for key in ("IOPlatformUUID", "IOPlatformSerialNumber"):
                if f'"{key}"' in line and "=" in line:
                    out.append(line.split("=", 1)[1].strip().strip('"'))
    except Exception:
        pass
    return out


def mac_state_file() -> str:
    """macOS: bản sao trạng thái dùng thử (thay cho khóa Registry trên Windows)."""
    return os.path.expanduser("~/Library/Preferences/.vn.pdfkyso.state")


__all__ = ["IS_WIN", "IS_MAC", "roaming_base", "local_base", "logs_base", "reveal", "open_path", "kbd",
           "mac_machine_ids", "mac_state_file"]
