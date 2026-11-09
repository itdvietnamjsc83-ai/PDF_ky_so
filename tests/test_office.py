"""Word/Excel/PowerPoint -> PDF bằng chính phần mềm Office trên máy: giữ nguyên khổ giấy (cả khổ tự đặt)."""
import os
import shutil
import subprocess

import pytest

from app import office
from app.document import PdfDocument

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "data", "kho_tu_dat.docx")      # 3 phần: 210×330 mm, A4, 100×150 mm


def _sizes_mm(pdf):
    d = PdfDocument(pdf)
    try:
        return [tuple(round(v * 25.4 / 72) for v in d.page_size_pt(i)) for i in range(d.page_count)]
    finally:
        d.close()


def test_is_office_file():
    assert office.is_office_file("Hợp đồng.DOCX") and office.is_office_file("bang.xlsx")
    assert not office.is_office_file("a.pdf") and not office.is_office_file("~$tam.docx")


def test_libreoffice_keeps_custom_page_sizes(tmp_path):
    if not office.find_libreoffice():
        pytest.skip("máy kiểm thử không có LibreOffice")
    src = tmp_path / "Văn bản khổ lạ.docx"
    shutil.copy(SAMPLE, src)
    try:
        pdf, used = office.to_pdf(str(src))
    except office.OfficeError as e:
        pytest.skip(f"LibreOffice không chạy được trong môi trường này: {e}")
    assert used == "LibreOffice"
    assert _sizes_mm(pdf) == [(210, 330), (210, 297), (100, 150)]
    assert "210 x 330" in PdfDocument(pdf).text(0)


def test_com_tries_word_then_wps(tmp_path, monkeypatch):
    """Máy không có Microsoft Word nhưng có WPS: tự chuyển sang WPS."""
    calls = []
    dst = str(tmp_path / "out.pdf")

    def fake_run(cmd, timeout=0, env=None):
        prog = cmd[cmd.index("-Prog") + 1]
        calls.append(prog)
        if prog == "Word.Application":
            return subprocess.CompletedProcess(cmd, 1, "", "Retrieving the COM class factory failed 80040154")
        open(dst, "wb").write(b"%PDF-1.4 ok")
        return subprocess.CompletedProcess(cmd, 0, "OK\n", "")
    monkeypatch.setattr(office, "_run", fake_run)
    assert office._via_com(str(SAMPLE), dst, "word") == "KWPS.Application"
    assert calls == ["Word.Application", "KWPS.Application"]


def test_com_real_error_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(office, "_run", lambda cmd, timeout=0, env=None:
                        subprocess.CompletedProcess(cmd, 1, "", "The file is corrupt and cannot be opened"))
    with pytest.raises(office.OfficeError, match="corrupt"):
        office._via_com(SAMPLE, str(tmp_path / "o.pdf"), "word")


def test_no_office_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(office, "_via_com", lambda *a: None)
    monkeypatch.setattr(office, "find_libreoffice", lambda: None)
    monkeypatch.setattr(office.sys, "platform", "win32")
    with pytest.raises(office.OfficeError, match="chưa có phần mềm Office"):
        office.to_pdf(SAMPLE, str(tmp_path / "x.pdf"))


def test_cached_pdf_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    n = []

    def fake(src, dst=None):
        n.append(1)
        open(dst, "wb").write(b"%PDF-1.4")
        return dst, "Microsoft Word"
    monkeypatch.setattr(office, "to_pdf", fake)
    a, _ = office.cached_pdf(SAMPLE)
    b, how = office.cached_pdf(SAMPLE)
    assert a == b and len(n) == 1 and how == "đã chuyển trước đó"


# ------------------------------------------------------------------ giao diện
@pytest.fixture
def win(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.mainwindow import MainWindow
    from .test_gui import _Settings
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


def _fake_convert(tmp_path, monkeypatch):
    from .test_phase4 import _contract

    def fake(src, dst=None):
        dst = dst or str(tmp_path / (os.path.splitext(os.path.basename(src))[0] + ".pdf"))
        open(dst, "wb").write(_contract(2))
        return dst, "Microsoft Word"
    monkeypatch.setattr(office, "to_pdf", fake)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


def test_open_word_file_in_app(win, tmp_path, monkeypatch):
    _fake_convert(tmp_path, monkeypatch)
    src = tmp_path / "Hợp đồng.docx"
    src.write_bytes(b"x")
    win.open_files([str(src)])
    tab = win.current()
    assert tab.title == "Hợp đồng.pdf" and tab.doc.page_count == 2 and tab.doc.path is None
    assert tab.save_dir == str(tmp_path) and "Microsoft Word" in win.lbl_msg.text()


def test_receive_files_tray_and_open(win, tmp_path, monkeypatch):
    _fake_convert(tmp_path, monkeypatch)
    x = tmp_path / "bang.xlsx"
    x.write_bytes(b"x")
    from .test_phase4 import _contract
    p = tmp_path / "a.pdf"
    p.write_bytes(_contract(1))
    from PySide6.QtWidgets import QDialog
    from app import ui_import

    def fake_exec(self):                          # 8a: thêm Excel vào khay -> hỏi màu; chọn Chữ đen
        self.combos[0].setCurrentIndex(self.combos[0].findData("blacktext"))
        return QDialog.Accepted
    monkeypatch.setattr(ui_import.ImportOptionsDialog, "exec", fake_exec)
    win.receive_files(["tray:" + str(x), "tray:" + str(p)])
    items = win._tray.items
    assert len(items) == 2 and items[0].path.endswith(".pdf") and items[0].page_count == 2
    assert items[0].color == "blacktext" and items[1].color == ""
    win._tray.close()
