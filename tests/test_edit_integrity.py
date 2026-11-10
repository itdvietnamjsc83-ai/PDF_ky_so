"""1.0.22 – sửa chữ có sẵn giữ toàn vẹn hình thức: không tự đổi phông / cỡ / độ rộng chữ; chỉ kéo dài dòng
hoặc thêm dòng vào chỗ trống. Phải thu nhỏ / đổi phông -> nút ⚠ trên thanh định dạng và hỏi lại khi xong."""
import time

from app import editing
from app.document import PdfDocument
from .test_gui import pump, qapp, win  # noqa: F401
from .test_gui_phase5 import _click
from .test_phase4 import _contract

LONG = "Điều khoản thỏa thuận giữa hai bên được sửa đổi bổ sung thêm rất nhiều nội dung mới " * 2


def _line(d, y):
    runs = editing.text_runs(d, 0)
    r = next(r for r in runs if r.rect[1] <= y <= r.rect[3])
    return runs, [editing.line_of(runs, r)]


def test_strict_never_changes_size_or_width():
    d = PdfDocument(data=_contract(2))
    runs, lines = _line(d, 136)                      # dòng 1: ngay dưới còn dòng khác -> không có chỗ
    info = editing.replace_group(d, 0, lines, LONG, dry=True, runs_all=runs, allow_shrink=False,
                                 allow_condense=False)
    assert info["overflow"] and info["size"] == 11 and info["hscale"] == 1.0 and not info["shrunk"]
    fit = editing.replace_group(d, 0, lines, LONG, dry=True, runs_all=runs)
    assert fit["shrunk"] or fit["condensed"]
    before = d.to_bytes()
    editing.replace_group(d, 0, lines, LONG, dry=True)                      # dry: không sửa file
    assert d.to_bytes() == before


def test_short_addition_extends_line_keeps_size():
    d = PdfDocument(data=_contract(2))
    runs, lines = _line(d, 136)
    info = editing.replace_group(d, 0, lines, "Điều khoản thỏa thuận giữa hai bên và bên thứ ba.", runs_all=runs,
                                 allow_shrink=False, allow_condense=False)
    assert info["extended"] and info["size"] == 11 and info["hscale"] == 1.0 and not info["overflow"]


def test_last_line_wraps_into_free_space_below():
    d = PdfDocument(data=_contract(2))
    runs, lines = _line(d, 316)                      # dòng cuối trang 1: bên dưới trống
    info = editing.replace_group(d, 0, lines, LONG, runs_all=runs, allow_shrink=False, allow_condense=False)
    assert info["added_lines"] >= 1 and info["size"] == 11 and info["hscale"] == 1.0 and not info["overflow"]
    t = d.text(0)
    assert "nội dung mới" in t
    sizes = {r.size for r in editing.text_runs(d, 0) if "nội dung" in r.text}
    assert sizes == {11}


def _wait(qapp, ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        pump(qapp, 2)


def test_gui_warning_button_and_confirm(win, qapp, tmp_path, monkeypatch):
    p = tmp_path / "hd.pdf"
    p.write_bytes(_contract(2))
    win.open_files([str(p)])
    pump(qapp)
    tab = win.current()
    v = tab.view
    win.start_tool("edittext")
    v.canvas.mousePressEvent(_click(v, 0, 100, 136))
    bar = v._inline_bar
    assert bar is not None and not bar.btn_warn.isVisible()          # chưa gõ gì: không cảnh báo
    v._inline[0].setPlainText("Điều khoản thỏa thuận giữa hai bên đã sửa.")
    _wait(qapp)
    assert not bar.btn_warn.isVisibleTo(bar)                          # vẫn vừa chỗ: không cảnh báo
    v._inline[0].setPlainText(LONG)
    _wait(qapp)
    assert bar.btn_warn.isVisibleTo(bar) and "thu nhỏ" in bar.warning()
    asked = []
    monkeypatch.setattr(type(win), "_ask_edit_warning",
                        lambda self, warns, strict, fit: (asked.append((warns, fit)), "back")[1])
    v._finish_inline(True)
    _wait(qapp, 100)
    assert asked and asked[0][1] is not None
    assert v._inline is not None and v._inline[0].toPlainText() == LONG   # quay lại sửa, giữ chữ đang gõ
    assert "nội dung mới" not in tab.doc.text(0)
    monkeypatch.setattr(type(win), "_ask_edit_warning", lambda self, warns, strict, fit: "keep")
    v._finish_inline(True)
    pump(qapp)
    rs = [r for r in editing.text_runs(tab.doc, 0) if "nội dung mới" in r.text]
    assert rs and all(r.size == 11 for r in rs)                       # giữ nguyên cỡ chữ
    win.stop_tool()


def test_gui_font_substitution_warns(win, qapp, tmp_path, monkeypatch):
    from app import fonts
    p = tmp_path / "hd.pdf"
    p.write_bytes(_contract(2))
    win.open_files([str(p)])
    pump(qapp)
    tab = win.current()
    v = tab.view
    monkeypatch.setattr(editing, "original_font", lambda run, text="", doc=None, i=None:
                        (fonts.system_font("sans"), "family"))
    win.start_tool("edittext")
    v.canvas.mousePressEvent(_click(v, 0, 100, 136))
    bar = v._inline_bar
    v._inline[0].setPlainText("Điều khoản đã sửa.")
    _wait(qapp)
    assert bar.btn_warn.isVisibleTo(bar) and "Đổi phông" in bar.btn_warn.text() and "phông thay thế" in bar.warning()
    asked = []
    monkeypatch.setattr(type(win), "_ask_edit_warning",
                        lambda self, warns, strict, fit: (asked.append(warns), "keep")[1])
    v._finish_inline(True)
    pump(qapp)
    assert asked and asked[0][0][0] == "Đổi phông" and "đã sửa" in tab.doc.text(0)
    win.stop_tool()
