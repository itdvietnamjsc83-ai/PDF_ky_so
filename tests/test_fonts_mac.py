"""1.0.21 – macOS: Times New Roman / Arial nằm ở /System/Library/Fonts/Supplemental với tên có dấu cách
("Times New Roman.ttf") -> trước đây báo "Không tìm thấy phông chữ tiếng Việt trên máy"."""
import os
import shutil

from app import fonts


def _with_dirs(monkeypatch, dirs):
    monkeypatch.setattr(fonts, "font_dirs", lambda: dirs)
    fonts._find_file.cache_clear()


def _name(p):          # ổ đĩa Mac không phân biệt hoa/thường: "arial.ttf" mở được "Arial.ttf"
    return os.path.basename(p).lower()


def test_mac_font_names(monkeypatch, tmp_path):
    src = fonts.system_font("serif")
    sup = tmp_path / "Supplemental"
    sup.mkdir()
    for name in ("Times New Roman.ttf", "Times New Roman Bold.ttf", "Arial.ttf"):
        shutil.copy(src, sup / name)
    _with_dirs(monkeypatch, [str(sup)])
    try:
        assert _name(fonts.system_font("serif")) == "times new roman.ttf"
        assert _name(fonts.system_font("serif", bold=True)) == "times new roman bold.ttf"
        assert _name(fonts.system_font("sans")) == "arial.ttf"
    finally:
        fonts._find_file.cache_clear()


def test_fallback_to_bundled_font(monkeypatch, tmp_path):
    _with_dirs(monkeypatch, [str(tmp_path)])
    try:
        p = fonts.system_font("serif")
        assert p.endswith("BeVietnamPro-Regular.ttf") and os.path.isfile(p)
        assert not fonts.missing_chars(p, "Hợp đồng ạệữỳđĐ")
        assert fonts.system_font("sans", bold=True).endswith("BeVietnamPro-Bold.ttf")
    finally:
        fonts._find_file.cache_clear()
