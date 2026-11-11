"""1.0.22 – con dấu chữ tùy biến: hình dạng, chữ vòng, đặt nổi, kéo sang trang khác, sửa lại sau khi đóng."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QDialog

from app import items, ui_tools
from app.document import PdfDocument
from app.library import Library
from app.mainwindow import MainWindow
from app.stamp_dialog import StampDialog
from .test_gui import _Settings, pump
from .test_phase4 import _contract


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


class _Ev:
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def position(self):
        return self._p

    def button(self):
        return Qt.LeftButton


def _open(win, qapp, tmp_path, pages=3):
    p = tmp_path / "hd.pdf"
    p.write_bytes(_contract(pages))
    win.open_files([str(p)])
    pump(qapp)
    return win.current()


@pytest.mark.parametrize("shape", [k for k, _ in items.STAMP_SHAPES])
def test_stamp_shapes_build_and_reselect(shape):
    d = PdfDocument(data=_contract(1))
    sp = items.stamp_spec("ĐÃ DUYỆT", shape, (100, 100, 260, 160 if shape != "circle" else 260),
                          sub="Ngày 11/11/2026", arc="CÔNG TY ABC" if shape == "circle" else "", angle=15)
    items.add_item(d, 0, sp)
    t = d.text(0)
    assert "ĐÃ DUYỆT" in t and "11/11/2026" in t
    its = [i for i in items.find_items(d, 0) if i.kind == "stamp"]
    assert len(its) == 1 and its[0].spec["shape"] == shape and its[0].label == "Con dấu"
    assert items.item_at(d, 0, 180, 130 if shape != "circle" else 180) is not None
    img, m = items.render_preview(its[0].spec)
    assert img.width > 100


def test_stamp_layout_fits_box():
    sp = items.stamp_spec("SAO Y\nBẢN CHÍNH", "rect", (0, 0, 150, 60), sub="Phòng Hành chính")
    lay = items.stamp_layout(sp)
    assert len(lay["lines"]) == 3
    from app import fonts
    fp = items.stamp_font(sp)
    for ln, s, x, yb in lay["lines"]:
        assert x >= 0 and x + fonts.measure(fp, ln, s) <= 150 + 0.5 and 0 < yb < 60


def test_dialog_preview_and_spec(qapp):
    st = _Settings()
    dlg = StampDialog(None, st)
    dlg.cb_text.setCurrentText("SAO Y|BẢN CHÍNH")
    dlg.cb_shape.setCurrentIndex(dlg.cb_shape.findData("circle"))
    dlg.ed_arc.setText("ỦY BAN NHÂN DÂN")
    dlg.sl_w.setValue(40)
    dlg.sl_angle.setValue(-20)
    dlg._render()
    sp = dlg.spec()
    assert sp["text"] == "SAO Y\nBẢN CHÍNH" and sp["shape"] == "circle" and sp["arc"] == "ỦY BAN NHÂN DÂN"
    x0, y0, x1, y1 = items.spec_rect(sp)
    assert x1 - x0 == pytest.approx(40 * 72 / 25.4) == pytest.approx(y1 - y0)       # tròn: cao = rộng
    assert sp["angle"] == 340
    assert dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()
    dlg.remember()
    dlg2 = StampDialog(None, st)
    assert dlg2.cb_recent.count() == 2                 # "Mẫu của tôi" nhớ kiểu vừa dùng
    dlg2.cb_recent.setCurrentIndex(1)
    assert dlg2.cb_shape.currentData() == "circle" and dlg2.ed_arc.text() == "ỦY BAN NHÂN DÂN"


def test_place_drag_to_other_page_then_edit(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path)
    v = tab.view

    def fake(self):
        self.cb_text.setCurrentText("ĐÃ DUYỆT")
        self.cb_shape.setCurrentIndex(self.cb_shape.findData("ellipse"))
        return QDialog.Accepted
    monkeypatch.setattr(StampDialog, "exec", fake)
    win.run("stamptext")
    pl = v.placement
    assert pl is not None and pl.rotatable and pl.page == 0
    # kéo khung xuống trang 2
    sr = v._placement_screen_rect()
    c = sr.center()
    r1 = v._rects[1]
    target = QPointF(r1.center().x(), r1.top() + 120)
    v._place_press(_Ev(c.x(), c.y()))
    v._place_move(_Ev(target.x(), target.y()))
    v._place_release(None)
    assert v.placement.page == 1
    v.commit_placement()
    assert "ĐÃ DUYỆT" in tab.doc.text(1) and "ĐÃ DUYỆT" not in tab.doc.text(0)
    it = [i for i in items.find_items(tab.doc, 1) if i.kind == "stamp"][0]
    assert it.spec["shape"] == "ellipse"

    # bấm vào dấu đã đóng -> chọn; nháy đúp -> sửa chữ, hình dạng
    cx, cy = (it.rect[0] + it.rect[2]) / 2, (it.rect[1] + it.rect[3]) / 2
    win.page_pressed(1, cx, cy)
    assert v.placement is not None and v.placement.on_dblclick is not None

    def edit(self):
        assert self.editing and self.cb_shape.currentData() == "ellipse"
        self.cb_text.setCurrentText("SAO Y BẢN CHÍNH")
        self.cb_shape.setCurrentIndex(self.cb_shape.findData("rect"))
        self.sl_angle.setValue(-15)
        return QDialog.Accepted
    monkeypatch.setattr(StampDialog, "exec", edit)
    v.placement.on_dblclick(v.placement)
    v.commit_placement()
    t = tab.doc.text(1)
    assert "SAO Y BẢN CHÍNH" in t and "ĐÃ DUYỆT" not in t
    its = [i for i in items.find_items(tab.doc, 1) if i.kind == "stamp"]
    assert len(its) == 1 and its[0].spec["shape"] == "rect" and its[0].spec["angle"] == 345

    # dấu đã đóng: kéo sang trang 3
    it = its[0]
    win.page_pressed(1, (it.rect[0] + it.rect[2]) / 2, (it.rect[1] + it.rect[3]) / 2)
    sr = v._placement_screen_rect()
    c = sr.center()
    r2 = v._rects[2]
    v._place_press(_Ev(c.x(), c.y()))
    v._place_move(_Ev(r2.center().x(), r2.top() + 200))
    v._place_release(None)
    assert v.placement.page == 2
    v.commit_placement()
    assert "SAO Y BẢN CHÍNH" in tab.doc.text(2) and "SAO Y BẢN CHÍNH" not in tab.doc.text(1)
    tab.doc.undo()
    assert "SAO Y BẢN CHÍNH" in tab.doc.text(1) and "SAO Y BẢN CHÍNH" not in tab.doc.text(2)


def test_stamp_all_pages_and_watermark(win, qapp, tmp_path, monkeypatch):
    tab = _open(win, qapp, tmp_path)

    def wm(self):
        self.cb_text.setCurrentText("NHÁP")
        self.cb_style.setCurrentIndex(self.cb_style.findData("watermark"))
        assert self.sl_op.isEnabled() and self.sl_op.value() == 25          # một thanh Độ đậm, chỉnh được
        self.sl_op.setValue(40)
        self.cb_scope.setCurrentIndex(self.cb_scope.findData("all"))
        return QDialog.Accepted
    monkeypatch.setattr(ui_tools.StampTextDialog, "exec", wm)
    win.run("stamptext")
    assert tab.view.placement is not None                   # chữ chìm cũng nổi trên trang, kéo được
    tab.view.commit_placement()
    assert all("NHÁP" in tab.doc.text(i) for i in range(3))
    its = [i for i in items.find_items(tab.doc, 1) if i.kind == "stamp"]
    assert its and its[0].spec["shape"] == "none" and its[0].spec["opacity"] == 40 and its[0].spec["angle"] == 315
    # chọn lại -> bảng phải có nút sửa con dấu, độ đậm chỉnh được
    it = its[0]
    win.page_pressed(1, (it.rect[0] + it.rect[2]) / 2, (it.rect[1] + it.rect[3]) / 2)
    o = win.tool_opts
    assert o.btn_stamp_edit.isVisibleTo(o) and o.sl_opacity.value() == 40
    o.sl_opacity.setValue(70)
    tab.view.commit_placement()
    it = [i for i in items.find_items(tab.doc, 1) if i.kind == "stamp"][0]
    assert it.spec["opacity"] == 70


def test_no_border_and_page_peek(win, qapp, tmp_path):
    sp = items.stamp_spec("ĐÃ DUYỆT", "rect", (0, 0, 150, 50), border="none")
    lay = items.stamp_layout(sp)
    assert lay["paths"] == [] and lay["lines"]                      # không viền, chỉ chữ
    circ = items.stamp_spec("ĐÃ DUYỆT", "circle", (0, 0, 120, 120), border="none", arc="CÔNG TY ABC")
    assert items.stamp_layout(circ)["paths"] == [] and items.stamp_layout(circ)["arc"]
    tab = _open(win, qapp, tmp_path)
    peek = win._page_peek(tab, 0)
    assert peek is not None and not peek[0].isNull()
    dlg = StampDialog(None, _Settings(), page=peek)
    dlg.cb_border.setCurrentIndex(dlg.cb_border.findData("none"))
    dlg._render()
    assert dlg.spec()["border"] == "none"
    assert dlg.page_preview.pixmap() is not None and not dlg.page_preview.pixmap().isNull()
