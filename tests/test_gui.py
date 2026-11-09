"""Kiểm thử giao diện (chạy không cần màn hình - QT_QPA_PLATFORM=offscreen)."""
import os
import shutil
import sys
import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from app.mainwindow import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: _Settings())
    w = MainWindow()
    w.resize(1440, 900)
    w.show()
    qapp.processEvents()
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


class _Settings(dict):
    def value(self, k, d=None):
        return self.get(k, d)

    def setValue(self, k, v):
        self[k] = v


def pump(app, ms=150):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()


def test_empty_state(win):
    assert win.stack.currentIndex() == 0
    assert "Chưa mở" in win.side.page_desc.text()


def test_open_view_and_status(win, qapp, samples):
    win.open_files([samples["mixed"]])
    pump(qapp)
    tab = win.current()
    assert tab and tab.doc.page_count == 4 and win.stack.currentIndex() == 1
    assert win.lbl_page.text() == "Trang 1 / 4"
    assert win.lbl_kind.text() == "Văn bản"
    # mở lại cùng file -> không tạo tab mới
    win.open_files([samples["mixed"]])
    assert win.tabs.count() == 1


def test_zoom_controls(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    v = win.current().view
    v.set_zoom(100)
    assert win.lbl_zoom.text() == "100%"
    v.zoom_step(1)
    assert v.zoom == 110
    v.zoom_step(-1)
    assert v.zoom == 100
    v.set_zoom(99999)
    assert v.zoom == 6400
    v.set_zoom(1)
    assert v.zoom == 10
    v.fit_width()
    fw = v.zoom
    v.fit_page()
    assert v.zoom < fw
    win.slider.setValue(200)
    assert v.zoom == 200


def test_ctrl_wheel_zoom_keeps_point_under_cursor(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    v = win.current().view
    v.set_zoom(100)
    pump(qapp)
    pos = QPoint(300, 250)
    before = v._anchor(pos)
    ev = QWheelEvent(QPointF(pos), QPointF(v.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
    v.wheelEvent(ev)
    assert v.zoom == 110
    after = v._anchor(pos)
    assert before[0] == after[0]
    assert abs(before[2] - after[2]) < 2     # điểm dưới con trỏ giữ nguyên theo chiều dọc
    # trang rộng hơn cửa sổ -> giữ cả chiều ngang
    v.set_zoom(300)
    pump(qapp)
    before = v._anchor(pos)
    v.wheelEvent(QWheelEvent(QPointF(pos), QPointF(v.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, 120),
                             Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False))
    after = v._anchor(pos)
    assert v.zoom > 300
    assert abs(before[1] - after[1]) < 2 and abs(before[2] - after[2]) < 2
    # không giữ Ctrl -> cuộn trang, không zoom
    ev = QWheelEvent(QPointF(pos), QPointF(v.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, -120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    v.wheelEvent(ev)
    assert v.zoom > 300


def test_page_ops_and_undo(win, qapp, samples, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from app import ui_pages
    for cls in (ui_pages.BlankPagesDialog, ui_pages.DeletePagesDialog):   # nhận lựa chọn mặc định
        monkeypatch.setattr(cls, "exec", lambda self: QDialog.Accepted)
    src = tmp_path / "ops.pdf"
    shutil.copy(samples["mixed"], src)
    win.open_files([str(src)])
    pump(qapp)
    tab = win.current()
    tab.thumbs.setCurrentRow(0)
    win.run("rotate")
    assert tab.doc.page_info(0).landscape
    assert "●" in win.tabs.tabText(0)
    win.run("blank")
    assert tab.doc.page_count == 5
    tab.thumbs.setCurrentRow(1)
    win.run("delete")
    assert tab.doc.page_count == 4
    win.run("undo")
    assert tab.doc.page_count == 5
    win.run("undo")
    win.run("undo")
    assert tab.doc.page_count == 4 and not tab.doc.page_info(0).landscape
    win.run("redo")
    assert tab.doc.page_info(0).landscape
    assert tab.thumbs.count() == tab.doc.page_count
    win.run("save")
    assert not tab.doc.modified


def test_cannot_delete_all_pages(win, qapp, samples):
    win.open_files([samples["ocr"]])
    pump(qapp)
    win.run("delete")
    assert win.current().doc.page_count == 1
    assert "Không thể xóa" in win.lbl_msg.text()


def test_not_supported_command_message(win, qapp, samples, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    win.open_files([samples["text"]])
    win.run("ocr")
    assert shown and "cập nhật sau" in shown[0]


def test_close_modified_asks(win, qapp, samples, monkeypatch):
    win.open_files([samples["text"]])
    pump(qapp)
    win.current().doc.rotate_pages([0])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    win.close_tab(0)
    assert win.tabs.count() == 1                 # Hủy -> giữ tab
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    win.close_tab(0)
    assert win.tabs.count() == 0 and win.stack.currentIndex() == 0


def test_thumbnails_render_lazily(win, qapp, samples):
    win.open_files([samples["big"]])
    pump(qapp, 100)
    th = win.current().thumbs
    assert th.count() == 300
    assert len(th._done) < 300                   # chưa render hết ngay -> không đơ
    pump(qapp, 3000)
    assert len(th._done) > 20


def test_theme_toggle_and_screenshots(win, qapp, samples):
    win.open_files([samples["mixed"]])
    pump(qapp, 400)
    out = os.environ.get("SHOT_DIR")
    if out:
        win.grab().save(os.path.join(out, "light.png"))
    win.toggle_theme()
    pump(qapp, 400)
    if out:
        win.grab().save(os.path.join(out, "dark.png"))
    win.toggle_theme()


def test_perf_open_to_first_paint(win, qapp, samples):
    t = time.perf_counter()
    win.open_files([samples["big"]])
    win.current().view.canvas.repaint()
    dt = time.perf_counter() - t
    assert dt < 1.0, f"mở file 300 trang tới lúc hiện trang đầu mất {dt:.2f}s"


def test_perf_zoom_is_smooth(win, qapp, samples):
    win.open_files([samples["big"]])
    pump(qapp)
    v = win.current().view
    v.set_zoom(100)
    v.canvas.repaint()
    t = time.perf_counter()
    for z in range(110, 300, 10):          # 19 nấc zoom liên tiếp (vẽ tạm, chưa render nét)
        v.set_zoom(z)
        v.canvas.repaint()
    dt = (time.perf_counter() - t) / 19
    assert dt < 0.03, f"mỗi nấc zoom mất {dt * 1000:.0f} ms"


def test_open_bad_files_no_crash(win, qapp, tmp_path, monkeypatch):
    msgs = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: msgs.append(a[2]))
    bad = tmp_path / "hong.pdf"
    bad.write_bytes(b"%PDF-1.7\nrac rac rac")
    txt = tmp_path / "khong-phai.pdf"
    txt.write_text("xin chao")
    win.open_files([str(bad), str(txt), str(tmp_path / "khong-ton-tai.pdf")])
    assert win.tabs.count() == 0 and len(msgs) == 3


def test_password_prompt(win, qapp, samples, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1234", True))
    win.open_files([samples["locked"]])
    assert win.tabs.count() == 1


def test_print_to_pdf(win, qapp, samples, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    from app.printing import print_pages
    from app.document import PdfDocument
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    out = tmp_path / "in.pdf"
    printer.setOutputFileName(str(out))
    d = PdfDocument(samples["mixed"])
    assert print_pages(d, printer, 0, 3, max_dpi=100) == 4
    d.close()
    assert PdfDocument(str(out)).page_count == 4


def test_high_zoom_renders_only_visible_part(win, qapp, samples):
    win.open_files([samples["scan"]])
    pump(qapp)
    v = win.current().view
    v.set_zoom(1600)
    v.canvas.repaint()
    pump(qapp, 200)
    v.canvas.repaint()
    crops = [k for k in v._cache if k[3] is not None]
    assert crops, "ở zoom lớn phải render theo vùng"
    biggest = max(img.width() * img.height() for img in v._cache.values())
    assert biggest < 12_000_000


def test_rotated_page_high_zoom(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    win.run("rotate")
    v = win.current().view
    v.set_zoom(800)
    v.canvas.repaint()
    pump(qapp, 200)
    v.canvas.repaint()
    assert v.doc.page_info(0).landscape


def test_drop_pdf(win, qapp, samples, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QDialog
    from app import ui_import
    shown = []
    monkeypatch.setattr(ui_import.ImportOptionsDialog, "exec", lambda self: (shown.append(len(self.paths)),
                                                                           QDialog.Accepted)[1])
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(samples["text"]), QUrl.fromLocalFile(samples["scan"])])

    class Ev:
        def mimeData(self):
            return md
    win.dropEvent(Ev())
    assert win.tabs.count() == 2 and shown == [2]         # kéo nhiều file -> bảng tích chọn


def test_memory_stays_bounded(win, qapp, samples):
    resource = pytest.importorskip("resource")                # đo bộ nhớ kiểu Linux/Mac
    win.open_files([samples["big"]])
    pump(qapp)
    v = win.current().view
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for z in (100, 150, 200, 300):
        v.set_zoom(z)
        for step in range(0, v.verticalScrollBar().maximum(), max(1, v.verticalScrollBar().maximum() // 30)):
            v.verticalScrollBar().setValue(step)
            v.canvas.repaint()
    pump(qapp, 200)
    unit = 1024 * 1024 if sys.platform == "darwin" else 1024     # macOS: byte; Linux: KB
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0) / unit
    assert v._cache_px <= 120_000_000
    assert grown_mb < 600, f"bộ nhớ tăng {grown_mb:.0f} MB"
