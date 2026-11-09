"""macOS – tích hợp với hệ điều hành:

- Word / Excel / PowerPoint cho Mac -> PDF bằng AppleScript (giữ nguyên khổ giấy như khi in).
  Office trên Mac chạy trong "hộp cát" (sandbox): file được chép vào thư mục nhóm của Office
  (~/Library/Group Containers/UBF8T346G9.Office) để Office đọc / ghi được mà không hỏi quyền từng file.
- Gửi email: tạo thư mới trong ứng dụng Mail (hoặc Outlook) đã đính kèm file.
- "Máy in ảo" kiểu Mac: mục PDF Services trong hộp thoại In của mọi ứng dụng (nút PDF ▾):
    "Mở bằng PDF Ký Số"  và  "Thêm vào Khay ghép PDF Ký Số".
- Đổi chữ "Ctrl+" thành "⌘" trên giao diện.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid

BUNDLE_ID = "vn.pdfkyso.app"
OFFICE_GROUP = os.path.expanduser("~/Library/Group Containers/UBF8T346G9.Office")
APPS = {"word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint"}

_SCRIPTS = {
    "word": '''on run argv
  set src to item 1 of argv
  set dst to item 2 of argv
  tell application "Microsoft Word"
    open (POSIX file src)
    set theDoc to active document
    save as theDoc file name dst file format format PDF
    close theDoc saving no
  end tell
  return "OK"
end run''',
    "excel": '''on run argv
  set src to item 1 of argv
  set dst to item 2 of argv
  set wanted to {}
  if (count of argv) > 2 and item 3 of argv is not "" then
    set AppleScript's text item delimiters to "|"
    set wanted to text items of (item 3 of argv)
    set AppleScript's text item delimiters to ""
  end if
  set fitMode to ""
  if (count of argv) > 3 then set fitMode to item 4 of argv
  set orientMode to ""
  if (count of argv) > 4 then set orientMode to item 5 of argv
  tell application "Microsoft Excel"
    open (POSIX file src)
    set wb to active workbook
    repeat with ws in worksheets of wb
      if (count of wanted) > 0 and (name of ws) is not in wanted then
        try
          set visible of ws to sheet hidden
        end try
      else
        try
          set ps to page setup object of ws
          if fitMode is "page" then
            set zoom of ps to false
            set fit to pages wide of ps to 1
            set fit to pages tall of ps to 1
          else if fitMode is "width" then
            set zoom of ps to false
            set fit to pages wide of ps to 1
            set fit to pages tall of ps to false
          end if
          if orientMode is "portrait" then set orientation of ps to portrait
          if orientMode is "landscape" then set orientation of ps to landscape
        end try
      end if
    end repeat
    save workbook as wb filename dst file format PDF file format
    close wb saving no
  end tell
  return "OK"
end run''',
    "powerpoint": '''on run argv
  set src to item 1 of argv
  set dst to item 2 of argv
  tell application "Microsoft PowerPoint"
    open (POSIX file src)
    set thePres to active presentation
    save thePres in (POSIX file dst) as save as PDF
    close thePres saving no
  end tell
  return "OK"
end run''',
}


def office_app_installed(kind: str) -> bool:
    name = APPS.get(kind, "")
    return any(os.path.isdir(os.path.join(base, name + ".app"))
               for base in ("/Applications", os.path.expanduser("~/Applications")))


def office_to_pdf(src: str, dst: str, kind: str, excel: dict | None = None, timeout: int = 180) -> str | None:
    """Chuyển bằng Microsoft Office cho Mac. Trả về tên ứng dụng đã dùng, None nếu máy không có Office."""
    from .office import OfficeError
    if not office_app_installed(kind):
        return None
    work = os.path.join(OFFICE_GROUP, "PdfKySo", uuid.uuid4().hex[:10])
    try:
        os.makedirs(work, exist_ok=True)
    except OSError:
        work = tempfile.mkdtemp(prefix="pdfkyso-office-")
    try:
        tmp_src = os.path.join(work, os.path.basename(src))
        shutil.copy2(src, tmp_src)
        tmp_dst = os.path.join(work, os.path.splitext(os.path.basename(src))[0] + ".pdf")
        args = ["/usr/bin/osascript", "-e", _SCRIPTS[kind], tmp_src, tmp_dst]
        if kind == "excel" and excel:
            args += ["|".join(excel.get("sheets") or []), excel.get("fit") or "", excel.get("orientation") or ""]
        try:
            r = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise OfficeError(f"{APPS[kind]} không phản hồi (quá thời gian). Hãy đóng các hộp thoại đang mở trong "
                              f"{APPS[kind]} rồi thử lại.")
        # PowerPoint / Excel đôi khi thêm đuôi .pdf vào tên đã có
        made = next((p for p in (tmp_dst, tmp_dst + ".pdf") if os.path.exists(p) and os.path.getsize(p) > 0), None)
        if made:
            shutil.move(made, dst)
            return APPS[kind]
        err = (r.stderr or r.stdout).strip()
        if "-1743" in err or "Not authorized" in err:
            raise OfficeError(f"Máy chưa cho phép PDF Ký Số điều khiển {APPS[kind]}.\nVào Cài đặt hệ thống → Quyền "
                              "riêng tư & Bảo mật → Tự động hóa → bật PDF Ký Số → " + APPS[kind] + ", rồi thử lại.")
        raise OfficeError(f"{APPS[kind]} báo lỗi khi chuyển sang PDF:\n{err[-600:]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def find_libreoffice() -> str | None:
    for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
              os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice")):
        if os.path.isfile(p):
            return p
    return None


# ------------------------------------------------------------------ email
def send_email(path: str, subject: str = "", body: str = "") -> str:
    """Thư mới trong Mail (hoặc Outlook nếu là ứng dụng email chính) đã đính kèm file."""
    def esc(t):
        return (t or "").replace("\\", "\\\\").replace('"', '\\"')
    outlook = os.path.isdir("/Applications/Microsoft Outlook.app") and _default_mail_app() == "com.microsoft.outlook"
    if outlook:
        script = f'''tell application "Microsoft Outlook"
  set m to make new outgoing message with properties {{subject:"{esc(subject)}", plain text content:"{esc(body)}"}}
  make new attachment at m with properties {{file:(POSIX file "{esc(path)}")}}
  open m
  activate
end tell'''
    else:
        script = f'''tell application "Mail"
  set m to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}" & return & return, visible:true}}
  tell content of m to make new attachment with properties {{file name:(POSIX file "{esc(path)}")}} at after last paragraph
  activate
end tell'''
    try:
        r = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, errors="replace", timeout=30)
        if r.returncode == 0:
            return "mail"
    except Exception:
        pass
    subprocess.Popen(["open", "-R", path])
    return "folder"


def _default_mail_app() -> str:
    try:
        r = subprocess.run(["/usr/bin/defaults", "read", "com.apple.LaunchServices/com.apple.launchservices.secure",
                            "LSHandlers"], capture_output=True, text=True, timeout=5)
        txt = r.stdout
        k = txt.find("mailto")
        if k >= 0:
            seg = txt[max(0, k - 200):k + 200].lower()
            if "com.microsoft.outlook" in seg:
                return "com.microsoft.outlook"
    except Exception:
        pass
    return "com.apple.mail"


# ------------------------------------------------------------------ PDF Services (máy in ảo kiểu Mac)
SERVICES = {"sign": "Mở bằng PDF Ký Số", "tray": "Thêm vào Khay ghép PDF Ký Số"}

_SERVICE_SH = '''#!/bin/sh
# macOS PDF Services: $1 = tên tài liệu, $2 = tùy chọn, $3 = đường dẫn file PDF vừa in
DEST="{dest}"
mkdir -p "$DEST"
NAME=$(printf '%s' "$1" | tr '/:' '__' | cut -c1-80)
[ -z "$NAME" ] && NAME="Ban_in"
cp "$3" "$DEST/$(date +%Y%m%d-%H%M%S)-$NAME.pdf"
open -b {bundle} 2>/dev/null || open -a "PDF Ký Số"
'''


def services_dir() -> str:
    return os.path.expanduser("~/Library/PDF Services")


def install_pdf_services(spool_root: str | None = None) -> list[str]:
    """Tạo 2 mục trong nút PDF ▾ của hộp thoại In (mọi ứng dụng). Gọi lại nhiều lần không sao."""
    from .spool import spool_root as _root
    root = spool_root or _root()
    out = []
    d = services_dir()
    os.makedirs(d, exist_ok=True)
    for kind, title in SERVICES.items():
        p = os.path.join(d, title)
        content = _SERVICE_SH.format(dest=os.path.join(root, kind), bundle=BUNDLE_ID)
        try:
            old = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
            if old != content:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
            os.chmod(p, 0o755)
            out.append(p)
        except OSError:
            pass
    return out


def remove_pdf_services():
    for title in SERVICES.values():
        try:
            os.remove(os.path.join(services_dir(), title))
        except OSError:
            pass


def selftest() -> str:
    parts = []
    parts.append("Office: " + (", ".join(n for k, n in APPS.items() if office_app_installed(k)) or "không có"))
    parts.append("LibreOffice: " + ("có" if find_libreoffice() else "không có"))
    parts.append("PDF Services: " + ("có" if all(os.path.isfile(os.path.join(services_dir(), t))
                                                 for t in SERVICES.values()) else "chưa cài"))
    return "; ".join(parts)


# ------------------------------------------------------------------ chữ phím tắt trên giao diện
def fix_shortcut_texts(root):
    """Đổi "Ctrl+…" -> "⌘…" trong chữ, gợi ý của mọi nút / nhãn / ô nhập bên trong `root`."""
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget
    from .osutil import kbd
    for w in [root] + root.findChildren(QWidget):
        try:
            tt = w.toolTip()
            if "Ctrl" in tt or "Alt" in tt:
                w.setToolTip(kbd(tt))
            if isinstance(w, (QLabel, QAbstractButton)):
                t = w.text()
                if "Ctrl" in t:
                    w.setText(kbd(t))
            elif isinstance(w, QLineEdit):
                ph = w.placeholderText()
                if "Ctrl" in ph:
                    w.setPlaceholderText(kbd(ph))
        except RuntimeError:
            continue


__all__ = ["office_to_pdf", "send_email", "install_pdf_services", "remove_pdf_services", "fix_shortcut_texts",
           "find_libreoffice", "selftest"]
