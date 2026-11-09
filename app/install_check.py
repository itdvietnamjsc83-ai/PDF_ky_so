"""Bắt buộc cài đặt bằng bộ cài: bản đóng gói (.exe) chỉ chạy khi đã được cài đúng cách.

Chép nguyên thư mục phần mềm sang máy khác (hoặc chỗ khác) rồi bấm PdfKySo.exe -> không chạy, báo cần cài.
Cách kiểm tra: bộ cài (Inno Setup) ghi khóa gỡ cài đặt của phần mềm vào Registry kèm thư mục cài;
phần mềm đối chiếu khóa đó với chính thư mục đang chạy và file gỡ cài đặt (unins000.exe) đi kèm.
Khi chạy từ mã nguồn (python main.py – dành cho nhà phát triển) thì không kiểm tra.
"""
from __future__ import annotations

import os
import sys

APP_ID = "{6E2B1F0C-7A41-4C7E-9E1B-5D2A9C0F4B11}"          # trùng AppId trong installer/setup.iss
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID + "_is1"


def is_packaged(main_globals: dict | None = None) -> bool:
    """True khi đang chạy bản đã biên dịch (Nuitka) – không phải python main.py."""
    if main_globals is not None and "__compiled__" in main_globals:
        return True
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _read_install_locations() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                k = winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view)
                out.append(winreg.QueryValueEx(k, "InstallLocation")[0])
            except OSError:
                continue
    return out


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p.strip().strip('"'))))


def mac_bundle_path(exe: str | None = None) -> str:
    """Đường dẫn gói .app đang chạy (macOS)."""
    p = os.path.abspath(exe or sys.executable)
    k = p.find(".app/")
    return p[:k + 4] if k >= 0 else os.path.dirname(p)


def check_mac(bundle: str | None = None) -> tuple[bool, str]:
    """macOS: gói .app tự chứa đủ mọi thứ; chỉ nhắc khi đang chạy thẳng từ file .dmg / chưa chép vào Applications
    (macOS chạy từ vị trí tạm "App Translocation" -> không nhớ quyền, không cập nhật được)."""
    b = bundle or mac_bundle_path()
    if b.startswith("/Volumes/") or "/AppTranslocation/" in b:
        return False, ("Hãy cài PDF Ký Số trước khi dùng:\n\nKéo biểu tượng PDF Ký Số vào thư mục Applications "
                       "(Ứng dụng) trong cửa sổ cài đặt, sau đó mở phần mềm từ Launchpad hoặc thư mục Ứng dụng.")
    return True, ""


def check(app_dir: str | None = None, locations: list[str] | None = None) -> tuple[bool, str]:
    """(đã cài đúng?, thông báo cho người dùng)."""
    if sys.platform == "darwin" and locations is None:
        return check_mac()
    app_dir = _norm(app_dir or os.path.dirname(os.path.abspath(sys.argv[0])))
    locs = [_norm(p) for p in (locations if locations is not None else _read_install_locations()) if p]
    if not locs:
        return False, ("Phần mềm chưa được cài đặt trên máy này.\n\n"
                       "Hãy chạy file cài đặt PdfKySo-Setup.exe để cài, sau đó mở phần mềm từ biểu tượng "
                       "trên màn hình hoặc menu Start.")
    if app_dir not in locs:
        return False, ("Bản phần mềm này không phải bản đã cài trên máy (có thể được sao chép từ nơi khác).\n\n"
                       "Hãy mở phần mềm từ biểu tượng trên màn hình / menu Start, hoặc chạy lại file cài đặt "
                       "PdfKySo-Setup.exe.")
    if not any(os.path.exists(os.path.join(app_dir, f"unins{k:03d}.exe")) for k in range(10)):
        return False, "Bản cài đặt bị thiếu file. Hãy chạy lại file cài đặt PdfKySo-Setup.exe để sửa."
    return True, ""
