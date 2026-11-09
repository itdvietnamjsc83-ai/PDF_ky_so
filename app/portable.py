"""Bản portable (không cần cài): giải nén là chạy, mang theo USB được.

Nhận biết bằng file "PdfKySo.portable" đặt cạnh PdfKySo.exe (build_windows.bat tạo sẵn trong gói portable).
Bản portable lưu thư viện dấu, cài đặt, bản quyền trong thư mục "Data" cạnh file .exe.
Không có máy in ảo và mục "Mở bằng" (hai thứ này cần quyền cài đặt vào Windows).
Mã kích hoạt vẫn gắn với từng máy: mang sang máy khác thì dùng thử / kích hoạt lại theo mã máy mới.
"""
from __future__ import annotations

import os
import sys

MARKER = "PdfKySo.portable"


def app_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def is_portable(base: str | None = None) -> bool:
    return os.path.isfile(os.path.join(base or app_dir(), MARKER))


def data_dir(base: str | None = None) -> str:
    d = os.path.join(base or app_dir(), "Data")
    os.makedirs(d, exist_ok=True)
    return d


def settings_args() -> tuple:
    """Tham số tạo QSettings: bản cài -> Registry; bản portable -> file .ini trong thư mục Data."""
    if is_portable():
        from PySide6.QtCore import QSettings
        return (os.path.join(data_dir(), "caidat.ini"), QSettings.Format.IniFormat)
    return ("PdfKySo", "PdfKySo")
