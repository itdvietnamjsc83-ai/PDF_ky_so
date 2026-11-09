"""1.0.19 – bảng bên phải (rộng cố định) không được rộng hơn khung nhìn: trước đây chữ dài / ô chọn rộng làm
bảng Tẩy vùng, Bút... bị cắt mất phần bên phải trên Windows."""
import pytest

from app import items

from .test_gui import pump
from .test_gui_phase5 import _open, lib_path, qapp, win  # noqa: F401

TOOLS = ["erase", "inkerase", "pen:ball", "shape:rect", "shape:arrow", "textbox", "edittext", "note", "highlight"]


def _fits(win):
    inner = win.side.scroll.widget()
    return inner.minimumSizeHint().width(), win.side.scroll.viewport().width()


@pytest.mark.parametrize("tool", TOOLS)
def test_tool_panel_fits(win, qapp, tmp_path, tool):
    _open(win, qapp, tmp_path, 1)
    win.start_tool(tool)
    pump(qapp)
    need, have = _fits(win)
    assert need <= have, f"{tool}: cần {need}px, bảng chỉ có {have}px"
    win.stop_tool()


@pytest.mark.parametrize("spec", [
    items.text_spec(100, 100, 200, "Xin chào", None, 12, "#000000"),
    items.shape_spec("rect", (100, 100, 200, 180), {"stroke": "#d32f2f", "width": 1.5}),
    items.line_spec("arrow", (100, 100), (200, 150), {"stroke": "#d32f2f", "width": 1.5}),
])
def test_item_panel_fits(win, qapp, tmp_path, spec):
    tab = _open(win, qapp, tmp_path, 1)
    items.add_item(tab.doc, 0, spec)
    tab.refresh()
    pump(qapp)
    win._select_item(tab, 0, items.find_items(tab.doc, 0)[0])
    pump(qapp)
    need, have = _fits(win)
    assert need <= have
    tab.view.cancel_placement()


def test_notes_and_image_panels_fit(win, qapp, tmp_path):
    _open(win, qapp, tmp_path, 1)
    win.toggle_notes_panel(True)
    win.img_opts.setVisible(True)
    pump(qapp)
    need, have = _fits(win)
    assert need <= have


def test_wrapcheck_behaves_like_checkbox(qapp):  # noqa: F811
    from app.ui_edit import WrapCheck
    got = []
    c = WrapCheck("Một dòng chữ rất dài cần tự xuống dòng trong bảng hẹp", checked=True)
    c.toggled.connect(got.append)
    assert c.isChecked() and c.text().startswith("Một")
    c.setChecked(False)
    c.click()
    assert got == [False, True] and c.isChecked()
