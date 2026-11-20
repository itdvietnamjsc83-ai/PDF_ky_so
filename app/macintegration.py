"""macOS – tích hợp với hệ điều hành:

- Word / Excel / PowerPoint cho Mac -> PDF bằng AppleScript (giữ nguyên khổ giấy như khi in).
  Office trên Mac chạy trong "hộp cát" (sandbox): file được chép vào thư mục nhóm của Office
  (~/Library/Group Containers/UBF8T346G9.Office) để Office đọc / ghi được mà không hỏi quyền từng file.
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
    # 1.0.25: Word mở file bất đồng bộ và có thể đang hiện hộp thoại (màn hình bắt đầu, đăng nhập, cấp quyền…):
    # - không chờ lệnh "open" trả lời (lỗi -1712 hết thời gian chờ), đưa Word lên trước để thấy hộp thoại;
    # - không dùng "active document" (lỗi -1708): chờ tài liệu theo tên file rồi mới lưu PDF.
    "word": '''on run argv
  set src to item 1 of argv
  set dst to item 2 of argv
  set srcName to ""
  if (count of argv) > 2 then set srcName to item 3 of argv
  tell application "Microsoft Word" to activate
  ignoring application responses
    tell application "Microsoft Word" to open (POSIX file src)
  end ignoring
  set lastErr to "NOT_OPENED"
  repeat 150 times
    delay 1
    set theDoc to missing value
    try
      with timeout of 10 seconds
        tell application "Microsoft Word"
          repeat with i from 1 to (count of documents)
            if (name of document i) is srcName then set theDoc to document i
          end repeat
          if theDoc is missing value and srcName is "" and (count of documents) > 0 then set theDoc to document 1
        end tell
      end timeout
    on error errMsg number errNum
      set lastErr to errMsg & " (" & errNum & ")"
    end try
    if theDoc is not missing value then
      with timeout of 300 seconds
        tell application "Microsoft Word"
          try
            save as theDoc file name dst file format format PDF
          on error
            save as theDoc file name ((POSIX file dst) as string) file format format PDF
          end try
          try
            close theDoc saving no
          end try
        end tell
      end timeout
      return "OK"
    end if
  end repeat
  error lastErr
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


def _unquarantine(path: str):
    """File tải từ mạng / Zalo mang cờ "quarantine": Word mở ở chế độ Xem được bảo vệ (Protected View), không lưu
    PDF được. Bản chép tạm của mình thì bỏ cờ này (file gốc giữ nguyên)."""
    try:
        subprocess.run(["/usr/bin/xattr", "-d", "com.apple.quarantine", path], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def office_to_pdf(src: str, dst: str, kind: str, excel: dict | None = None, timeout: int = 480) -> str | None:
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
        _unquarantine(tmp_src)
        args = ["/usr/bin/osascript", "-e", _SCRIPTS[kind], tmp_src, tmp_dst]
        if kind == "word":
            args.append(os.path.basename(tmp_src))
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
        if "NOT_OPENED" in err or "-1712" in err:
            raise OfficeError(f"{APPS[kind]} chưa mở được tài liệu (không phản hồi). Thường do {APPS[kind]} đang hiện "
                              "một hộp thoại: màn hình chọn mẫu, đăng nhập tài khoản Microsoft, kích hoạt, cấp quyền "
                              f"truy cập file… Hãy chuyển sang cửa sổ {APPS[kind]}, đóng hộp thoại đó rồi thử lại.")
        raise OfficeError(f"{APPS[kind]} báo lỗi khi chuyển sang PDF:\n{err[-600:]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def find_libreoffice() -> str | None:
    for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
              os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice")):
        if os.path.isfile(p):
            return p
    return None


# ------------------------------------------------------------------ PDF Services (máy in ảo kiểu Mac)
SERVICES = {"sign": "Mở bằng PDF Ký Số", "open": "Chỉ chuyển thành PDF trong PDF Ký Số",
            "tray": "Thêm vào Khay ghép PDF Ký Số"}

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


def helpers_dir() -> str:
    return os.path.expanduser("~/Library/Application Support/PdfKySo/pdfservices")


# 1.0.25: mục PDF Services là ứng dụng nhỏ (applet AppleScript) thay cho script sh.
# Lý do: script sh chạy BÊN TRONG tiến trình của ứng dụng đang in. Word / Excel / PowerPoint cho Mac chạy trong
# hộp cát (sandbox) nên script không ghi được vào thư mục của PDF Ký Số -> macOS báo lỗi khi in từ Word.
# Applet được macOS mở như một ứng dụng riêng (ngoài hộp cát), nhận file PDF vừa in qua sự kiện "open".
_APPLET = '''on open theFiles
  repeat with f in theFiles
    set p to POSIX path of f
    set n to name of (info for f)
    if n ends with ".pdf" then set n to text 1 thru -5 of n
    do shell script "/bin/sh " & quoted form of "@HELPER@" & " " & quoted form of n & " '' " & quoted form of p
  end repeat
end open

on run
  display dialog "Mục này dùng trong hộp thoại In của mọi ứng dụng: bấm nút PDF ▾ rồi chọn \"@TITLE@\"." buttons {"OK"} default button 1 with title "PDF Ký Số"
end run
'''


def _osacompile() -> str | None:
    p = "/usr/bin/osacompile"
    return p if os.path.isfile(p) else shutil.which("osacompile")


def _write_if_changed(path: str, content: str, mode: int = 0o755) -> bool:
    old = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
    if old != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    os.chmod(path, mode)
    return old != content


def _make_applet(app_path: str, source: str) -> bool:
    """Dịch applet bằng osacompile (có sẵn trên mọi máy Mac). Ghi nhớ mã nguồn để lần sau không dịch lại."""
    tool = _osacompile()
    if not tool:
        return False
    stamp = os.path.join(helpers_dir(), os.path.basename(app_path) + ".applescript")
    exe_ok = os.path.isdir(os.path.join(app_path, "Contents", "MacOS"))
    if exe_ok and os.path.isfile(stamp) and open(stamp, encoding="utf-8").read() == source:
        return True
    tmp = app_path + ".tmp-build.app"
    shutil.rmtree(tmp, ignore_errors=True)
    src = stamp + ".tmp"
    with open(src, "w", encoding="utf-8") as f:
        f.write(source)
    try:
        r = subprocess.run([tool, "-o", tmp, src], capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            os.remove(src)
        except OSError:
            pass
    if r.returncode != 0 or not os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    shutil.rmtree(app_path, ignore_errors=True)
    os.replace(tmp, app_path)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(source)
    return True


def install_pdf_services(spool_root: str | None = None) -> list[str]:
    """Tạo 3 mục trong nút PDF ▾ của hộp thoại In (mọi ứng dụng). Gọi lại nhiều lần không sao.
    Trả về đường dẫn các mục đã cài (".app" nếu dịch được applet, không thì script sh như bản cũ)."""
    from .spool import spool_root as _root
    root = spool_root or _root()
    out = []
    d = services_dir()
    os.makedirs(d, exist_ok=True)
    try:
        os.makedirs(helpers_dir(), exist_ok=True)
    except OSError:
        pass
    for kind, title in SERVICES.items():
        content = _SERVICE_SH.format(dest=os.path.join(root, kind), bundle=BUNDLE_ID)
        sh_in_services = os.path.join(d, title)
        app = os.path.join(d, title + ".app")
        try:
            helper = os.path.join(helpers_dir(), kind + ".sh")
            _write_if_changed(helper, content)
            source = _APPLET.replace("@HELPER@", helper).replace("@TITLE@", title)
            if _make_applet(app, source):
                if os.path.isfile(sh_in_services):       # bỏ mục script sh của bản cũ (trùng tên trong menu)
                    os.remove(sh_in_services)
                out.append(app)
                continue
        except OSError:
            pass
        try:                                             # không dịch được applet: dùng script sh như cũ
            _write_if_changed(sh_in_services, content)
            out.append(sh_in_services)
        except OSError:
            pass
    return out


def remove_pdf_services():
    for title in SERVICES.values():
        p = os.path.join(services_dir(), title)
        try:
            os.remove(p)
        except OSError:
            pass
        shutil.rmtree(p + ".app", ignore_errors=True)


def _installed(title: str) -> bool:
    p = os.path.join(services_dir(), title)
    return os.path.isfile(p) or os.path.isdir(p + ".app")


def selftest() -> str:
    parts = []
    parts.append("Office: " + (", ".join(n for k, n in APPS.items() if office_app_installed(k)) or "không có"))
    parts.append("LibreOffice: " + ("có" if find_libreoffice() else "không có"))
    parts.append("PDF Services: " + ("có" if all(_installed(t) for t in SERVICES.values()) else "chưa cài"))
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


__all__ = ["office_to_pdf", "install_pdf_services", "remove_pdf_services", "fix_shortcut_texts",
           "find_libreoffice", "selftest"]
