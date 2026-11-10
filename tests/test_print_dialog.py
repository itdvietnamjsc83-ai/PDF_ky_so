"""1.0.22 – hộp thoại In: bố cục in (tỉ lệ %, vừa khổ, nhiều trang/tờ, tự xoay) và xem trước = bản in."""
from PySide6.QtWidgets import QFileDialog

from app.document import PdfDocument
from app.printing import MM, PrintOptions, parse_range, plan_sheets, select_pages

from .test_gui import pump
from .test_gui_phase5 import qapp, win, lib_path  # noqa: F401
from .test_phase4 import _contract

A4 = (595.0, 842.0)


def test_parse_range_and_subset():
    assert parse_range("1-3, 5, 8-", 10) == [0, 1, 2, 4, 7, 8, 9]
    assert parse_range("3-1, x, 99", 5) == [2, 1, 0]
    assert select_pages(list(range(6)), PrintOptions(subset="odd")) == [0, 2, 4]
    assert select_pages(list(range(6)), PrintOptions(subset="even", reverse=True)) == [5, 3, 1]


def test_scale_modes():
    sizes = [A4, (842.0, 595.0), (1191.0, 1684.0)]          # A4 dọc, A4 ngang, A2 (quá khổ)
    m = (14, 14, 14, 14)
    fit = plan_sheets(sizes, [0], A4, m, PrintOptions(scale_mode="fit"))[0].slots[0]
    assert 0.9 < fit.scale < 1 and abs(fit.rect[0] + fit.rect[2] / 2 - A4[0] / 2) < 0.5       # căn giữa
    pct = plan_sheets(sizes, [0], A4, m, PrintOptions(scale_mode="custom", percent=50))[0].slots[0]
    assert pct.scale == 0.5 and abs(pct.rect[2] - 297.5) < 0.1
    big = plan_sheets(sizes, [0], A4, m, PrintOptions(scale_mode="custom", percent=150))[0].slots[0]
    assert big.scale == 1.5 and big.rect[2] > A4[0]                                            # lớn hơn tờ giấy
    shrink = plan_sheets(sizes, [0, 2], A4, (0, 0, 0, 0), PrintOptions(scale_mode="shrink"))
    assert shrink[0].slots[0].scale == 1.0 and shrink[1].slots[0].scale < 0.5                  # chỉ thu trang A2
    real = plan_sheets(sizes, [0], A4, m, PrintOptions(scale_mode="none"))[0].slots[0]
    assert real.scale == 1.0
    land = plan_sheets(sizes, [1], A4, m, PrintOptions())[0]                                   # tự động: giấy ngang
    assert land.landscape and not land.slots[0].rotate
    rot = plan_sheets(sizes, [1], A4, m, PrintOptions(orientation="portrait"))[0]              # giấy dọc: xoay trang
    assert not rot.landscape and rot.slots[0].rotate
    left = plan_sheets(sizes, [0], A4, m, PrintOptions(scale_mode="custom", percent=50, center=False,
                                                       margin_mm=10))[0].slots[0]
    assert abs(left.rect[0] - (14 + 10 * MM)) < 0.1


def test_n_up():
    sizes = [A4] * 7
    sh = plan_sheets(sizes, list(range(7)), A4, (0, 0, 0, 0), PrintOptions(nup=4))
    assert len(sh) == 2 and len(sh[0].slots) == 4 and len(sh[1].slots) == 3 and not sh[0].landscape
    two = plan_sheets(sizes, list(range(7)), A4, (0, 0, 0, 0), PrintOptions(nup=2))
    assert len(two) == 4 and two[0].landscape                                                  # 2 trang dọc / tờ ngang
    a, b = two[0].slots
    assert a.rect[0] + a.rect[2] <= b.rect[0]                                                  # cạnh nhau, không đè


def test_dialog_preview_and_print_to_pdf(qapp, tmp_path, monkeypatch):
    from app.print_dialog import PDF_TARGET, PrintDialog
    d = PdfDocument(data=_contract(5))
    dlg = PrintDialog(None, d, 2)
    dlg.cb_printer.setCurrentIndex(dlg.cb_printer.findData(PDF_TARGET))
    dlg.cb_paper.setCurrentIndex(1)                                                            # A4
    dlg._set_percent(70)
    dlg._refresh()
    assert dlg.lbl_zoom.text().startswith("70%") and dlg.preview.pixmap() is not None
    assert dlg.btn_print.text() == "In 5 tờ"
    dlg.rb_pages.setChecked(True)
    dlg.ed_pages.setText("1-4")
    dlg.cb_nup.setCurrentIndex(dlg.cb_nup.findData(2))
    dlg._refresh()
    assert dlg.btn_print.text() == "In 2 tờ" and dlg.lbl_sheet.text() == "Tờ 1 / 2"
    out = tmp_path / "ban_in.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    dlg._do_print()
    assert dlg.result() == PrintDialog.Accepted and dlg.printed == 2
    r = PdfDocument(str(out))
    assert r.page_count == 2
    w, h = r.page_size_pt(0)
    assert w > h and abs(w - 842) < 3 and abs(h - 595) < 3                                     # A4 ngang
    r.close()


def test_print_button_opens_dialog(win, qapp, samples, monkeypatch):
    from app import print_dialog
    seen = {}
    monkeypatch.setattr(print_dialog.PrintDialog, "exec", lambda self: seen.setdefault("pages", self.doc.page_count)
                        and 0)
    win.open_files([samples["text"]])
    pump(qapp)
    win.run("print")
    assert seen["pages"] >= 1


def test_spool_open_printer_only_opens(win, qapp, samples, tmp_path, monkeypatch):
    """Máy in ảo "PDF Ky so - Mo file": Word/Excel in ra -> chỉ mở thành PDF, không bật ký số."""
    import shutil
    called = []
    monkeypatch.setattr(type(win), "digital_sign", lambda self, *a: called.append(1))
    root = tmp_path / "spool"
    win.start_spool(str(root))
    assert (root / "open").is_dir()
    mode = win.mode_group.checkedId()
    shutil.copy(samples["text"], root / "open" / "ban_in.pdf")
    for _ in range(3):
        win.spool.scan()
        pump(qapp, 400)
    assert win.tabs.count() == 1 and win.current().from_spool
    assert win.mode_group.checkedId() == mode and not called


def test_printer_scripts_have_open_printer():
    import os
    here = os.path.join(os.path.dirname(__file__), "..", "installer")
    for name in ("cai_may_in_ao.ps1", "go_may_in_ao.ps1"):
        raw = open(os.path.join(here, name), "rb").read()
        assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
        assert "PDF Ky so - Mo file" in raw.decode("utf-8-sig")
