"""Kiểm tra thư viện cần thiết (khi chạy từ mã nguồn) và giải thích lỗi thiếu thư viện bằng tiếng Việt."""
from __future__ import annotations

import importlib.util
import re

# (tên module khi import, tên gói cài bằng pip, dùng cho việc gì)
REQUIRED = [
    ("PySide6", "PySide6-Essentials", "giao diện"),
    ("pypdfium2", "pypdfium2", "đọc, hiển thị, sửa PDF"),
    ("pikepdf", "pikepdf", "lưu, ghép, bảo vệ PDF"),
    ("PIL", "Pillow", "xử lý ảnh, con dấu"),
    ("fontTools", "fonttools", "chữ: hộp chữ, trang bìa, mục lục, đánh số trang"),
    ("pyhanko", "pyHanko", "ký số, kiểm tra chữ ký"),
    ("pkcs11", "python-pkcs11", "USB token"),
    ("cryptography", "cryptography", "mật mã"),
]
PIP_CMD = "py -3.12 -m pip install -r requirements.txt"


def missing() -> list[tuple[str, str, str]]:
    out = []
    for mod, pkg, use in REQUIRED:
        try:
            if importlib.util.find_spec(mod) is None:
                out.append((mod, pkg, use))
        except (ImportError, ValueError):
            out.append((mod, pkg, use))
    return out


def missing_message(items) -> str:
    lines = "\n".join(f"• {pkg} ({use})" for _, pkg, use in items)
    return ("Máy chưa cài đủ thư viện cho phần mềm (thường gặp khi chạy từ mã nguồn sau khi cập nhật bản mới):\n"
            f"{lines}\n\nMở cửa sổ lệnh tại thư mục phần mềm và chạy:\n    {PIP_CMD}\n"
            "rồi mở lại phần mềm. (Bản đã đóng gói bằng build_windows.bat hoặc bộ cài đã kèm đủ thư viện.)")


def explain(err) -> str:
    """Lỗi thiếu module -> câu hướng dẫn tiếng Việt; lỗi khác -> chuỗi rỗng."""
    text = str(err)
    m = re.search(r"No module named '([\w.]+)'", text)
    if not m:
        return ""
    top = m.group(1).split(".")[0]
    pkg = next((p for mod, p, _ in REQUIRED if mod == top), top)
    return (f"Thiếu thư viện “{pkg}”. Mở cửa sổ lệnh tại thư mục phần mềm và chạy:\n    {PIP_CMD}\n"
            "rồi mở lại phần mềm.")
