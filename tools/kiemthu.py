"""Chạy toàn bộ kiểm thử, vừa hiện trên màn hình vừa ghi ketqua_kiemthu.txt, rồi gom mọi thứ cần để hỗ trợ
(kết quả, nhật ký treo, thông tin máy) vào ketqua_kiemthu.zip.

    python tools/kiemthu.py            (Windows: kiemthu_windows.bat)
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TXT = os.path.join(ROOT, "ketqua_kiemthu.txt")
XML = os.path.join(ROOT, "ketqua_kiemthu.xml")
HANG = os.path.join(ROOT, "ketqua_treo.log")
ZIP = os.path.join(ROOT, "ketqua_kiemthu.zip")


def main() -> int:
    for p in (TXT, XML, HANG, ZIP):
        try:
            os.remove(p)
        except OSError:
            pass
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    cmd = [sys.executable, "-X", "faulthandler", "-m", "pytest", "tests", "-v", "-rfEs", "--tb=short",
           "-p", "no:cacheprovider", f"--junitxml={XML}"] + sys.argv[1:]
    print("Đang chạy kiểm thử (3–10 phút)...", flush=True)
    with open(TXT, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace")
            out.write(line)
            out.flush()
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                pass
        rc = proc.wait()
        out.write(f"\n===== Mã thoát pytest: {rc} =====\n")
        if os.path.isfile(HANG):
            with open(HANG, encoding="utf-8", errors="replace") as f:
                hang = f.read()
            out.write("\n===== ketqua_treo.log (kiểm thử chạy cuối cùng / chỗ bị treo) =====\n" + hang)
            if "Timeout" in hang:
                print("\n" + hang, flush=True)
        try:
            import PySide6
            qt = PySide6.__version__
        except Exception as e:
            qt = f"lỗi: {e}"
        out.write(f"\nPython {sys.version}\nHệ điều hành {platform.platform()}\nPySide6 {qt}\nThư mục {ROOT}\n")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in (TXT, XML, HANG):
            if os.path.isfile(p):
                z.write(p, os.path.basename(p))
    print(f"\n===== Mã thoát {rc}. Đã tạo {ZIP} – gửi file này để được hỗ trợ =====", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
