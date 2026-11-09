"""File mà pip / cmd.exe / PowerShell đọc trên Windows phải đọc được bằng bảng mã mặc định của máy."""
import glob
import os

ROOT = os.path.dirname(os.path.dirname(__file__))


def test_pip_and_bat_files_are_ascii():
    for p in glob.glob(os.path.join(ROOT, "requirements*.txt")) + glob.glob(os.path.join(ROOT, "*.bat")):
        with open(p, "rb") as f:
            f.read().decode("ascii")                  # pip trên Windows đọc bằng cp1252


def test_powershell_scripts_have_bom():
    for p in glob.glob(os.path.join(ROOT, "installer", "*.ps1")):
        with open(p, "rb") as f:
            assert f.read(3) == b"\xef\xbb\xbf", p      # PowerShell 5.1 cần BOM để đọc đúng tiếng Việt
