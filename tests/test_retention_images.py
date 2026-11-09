"""1.0.8: thời hạn tự xóa + xóa toàn bộ lịch sử/dữ liệu; tùy chọn ảnh (lớp, độ đậm, xoay, xóa nền, nhiều trang)."""
import io
import json
import os
import time

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox

from app import library, retention as R, tools
from app.document import PdfDocument
from app.mainwindow import MainWindow

from .test_gui import _Settings, pump


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    return _Settings()


@pytest.fixture
def spool(tmp_path, monkeypatch):
    d = tmp_path / "spool"
    monkeypatch.setenv("PDFKYSO_SPOOL", str(d))
    (d / "inbox").mkdir(parents=True)
    return d


@pytest.fixture
def win(qapp, monkeypatch, store, tmp_path, spool):
    monkeypatch.setattr("app.mainwindow.QSettings", lambda *a: store)
    w = MainWindow(library_path=str(tmp_path / "lib.pdf"))
    w.resize(1400, 880)
    w.show()
    pump(qapp, 50)
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.modified = False
    w.close()


OLD = time.time() - 40 * 86400


def _age(p, t=OLD):
    os.utime(p, (t, t))


def _fill(store, tmp_path, spool, samples):
    """Tạo dữ liệu ở mọi mục; trả về (file gốc của người dùng, các file cũ, các file mới)."""
    from app.library import STAMP, LibItem, Library
    from app.office import cache_dir
    from app.stability import local_dir
    user = str(tmp_path / "hop-dong.pdf")
    with open(samples["text"], "rb") as a, open(user, "wb") as b:
        b.write(a.read())
    tools.keep_version(user)
    old_ver = tools.versions(user)[0]["file"]
    _age(old_ver)
    time.sleep(1.05)
    tools.keep_version(user)
    # nhật ký dùng dấu: một dòng cũ, một dòng mới
    it = LibItem(id="x", name="Dấu", kind=STAMP, width_mm=36)
    library.log_usage(it, user, [0])
    rows = list(open(R.usage_path(), encoding="utf-8-sig").read().splitlines())
    old_row = rows[1].replace(rows[1][:19], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(OLD)))
    with open(R.usage_path(), "w", encoding="utf-8-sig") as f:
        f.write("\n".join([rows[0], old_row, rows[1]]) + "\n")
    old_off = os.path.join(cache_dir(), "cu.pdf")
    new_off = os.path.join(cache_dir(), "moi.pdf")
    for p in (old_off, new_off):
        open(p, "wb").write(b"%PDF")
    _age(old_off)
    old_sp, new_sp = str(spool / "inbox" / "In_cu.pdf"), str(spool / "inbox" / "In_moi.pdf")
    for p in (old_sp, new_sp):
        open(p, "wb").write(b"%PDF")
    _age(old_sp)
    rec = local_dir("recovery")
    old_rec, new_rec = os.path.join(rec, "aaa.pdf"), os.path.join(rec, "bbb.pdf")
    for p in (old_rec, new_rec):
        open(p, "wb").write(b"%PDF")
    _age(old_rec)
    logs = local_dir("logs")
    old_log = os.path.join(logs, "app.log.3")
    open(old_log, "w", encoding="utf-8").write("Mở hop-dong.pdf\n")
    _age(old_log)
    store["recent"] = [user, str(tmp_path / "cu.pdf")]
    store["recent_t"] = json.dumps({os.path.normcase(os.path.abspath(user)): time.time(),
                                    os.path.normcase(os.path.abspath(str(tmp_path / "cu.pdf"))): OLD})
    store["tray"] = json.dumps({"items": [{"path": user}]})
    store["tray_t"] = OLD
    store["last_dir"] = str(tmp_path)
    store["sign/last_cert"] = json.dumps({"organization": "CÔNG TY A"})
    tpl = str(tmp_path / "ho-so.khay.json")
    open(tpl, "w").write("{}")
    store["tray/template_files"] = json.dumps([tpl])
    store["protect/presets"] = json.dumps([{"name": "Mẫu riêng"}])
    store["auto/config"] = json.dumps({"enabled": True, "folder": str(tmp_path)})
    store["sign/reason"] = "Phê duyệt"
    lib = Library(str(tmp_path / "lib.pdf"))
    from .test_phase3 import remove_background, stamp_jpeg
    lib.add("Dấu", remove_background(stamp_jpeg()), STAMP, 36)
    return user, (old_ver, old_off, old_sp, old_rec, old_log), (new_off, new_sp, new_rec), tpl


def test_all_parts_listed_with_retention_choices():
    keys = [k for k, *_ in R.PARTS]
    assert keys == ["recent", "versions", "usage", "office", "spool", "recovery", "logs", "tray", "traces",
                    "templates", "library"]
    assert [lab for _, lab in R.RETENTION_CHOICES] == ["Không lưu", "7 ngày", "30 ngày", "6 tháng", "1 năm",
                                                       "Vĩnh viễn"]
    assert set(R.TIMED) == {"recent", "versions", "usage", "office", "spool", "recovery", "logs", "tray"}


def test_clear_everything(store, tmp_path, spool, samples):
    user, olds, news, tpl = _fill(store, tmp_path, spool, samples)
    lib = str(tmp_path / "lib.pdf")
    before = R.summary(store, lib)
    assert all(before[k][0] > 0 for k, *_ in R.PARTS), before
    done = R.clear([k for k, *_ in R.PARTS], store, lib)
    assert len(done) == len(R.PARTS)
    after = R.summary(store, lib)
    assert all(after[k][0] == 0 for k, *_ in R.PARTS), after
    assert not os.path.exists(tpl) and not os.path.exists(lib)
    assert os.path.exists(user)                          # file gốc không bị đụng tới
    assert store["recent"] == [] and store["tray"] == "" and store["protect/presets"] == ""


def test_apply_retention_removes_only_expired(store, tmp_path, spool, samples):
    user, olds, news, _ = _fill(store, tmp_path, spool, samples)
    for k in R.TIMED:
        R.set_retention(store, k, 30)
    out = R.apply_retention(store)
    for p in olds:
        assert not os.path.exists(p), p
    for p in news:
        assert os.path.exists(p), p
    assert len(tools.versions(user)) == 1                 # bản mới còn, bản 40 ngày đã xóa
    assert store["recent"] == [user]                      # file mở 40 ngày trước bị bỏ khỏi danh sách
    rows = open(R.usage_path(), encoding="utf-8-sig").read().splitlines()
    assert len(rows) == 2                                 # tiêu đề + dòng mới
    assert store["tray"] == ""                            # khay nhớ từ 40 ngày trước
    assert store["last_dir"]                              # "dấu vết" chỉ xóa khi người dùng chọn
    assert {"versions", "usage", "office", "spool", "recovery", "recent", "tray"} <= set(out)


def test_forever_keeps_everything(store, tmp_path, spool, samples):
    user, olds, news, _ = _fill(store, tmp_path, spool, samples)
    for k in R.TIMED:
        R.set_retention(store, k, None)
    assert R.apply_retention(store) == {}
    assert all(os.path.exists(p) for p in olds + news)


def test_recovery_of_open_document_is_kept(store, tmp_path, spool, samples):
    from app.stability import local_dir
    p = os.path.join(local_dir("recovery"), "dangmo.pdf")
    open(p, "wb").write(b"%PDF")
    _age(p)
    R.set_retention(store, "recovery", 0)
    R.apply_retention(store, active_recovery={"dangmo"})
    assert os.path.exists(p)


def test_no_keep_setting_stops_recording(win, store, samples, tmp_path):
    R.set_retention(store, "recent", 0)
    R.set_retention(store, "usage", 0)
    R.set_retention(store, "versions", 0)
    win.apply_retention_flags()
    win.add_recent(str(tmp_path / "a.pdf"))
    assert win.recent_files() == []
    assert library.USAGE_LOG_ENABLED is False
    user = str(tmp_path / "hd.pdf")
    with open(samples["text"], "rb") as a, open(user, "wb") as b:
        b.write(a.read())
    win.open_files([user])
    pump(QApplication.instance())
    win.current().doc.modified = True
    win.save(win.current())
    assert tools.versions(user) == []                     # "Không lưu" -> không cất bản cũ
    R.set_retention(store, "usage", None)
    win.apply_retention_flags()
    assert library.USAGE_LOG_ENABLED is True


def test_dialog_select_all_delete_all_and_save(win, store, tmp_path, spool, samples, monkeypatch):
    from app.ui_tools import ClearHistoryDialog
    _fill(store, tmp_path, spool, samples)
    d = ClearHistoryDialog(win, store, library_path=str(tmp_path / "lib.pdf"))
    assert set(d.combos) == set(R.TIMED)
    assert not d.checks["library"].isChecked() and not d.checks["templates"].isChecked()   # mục quan trọng: không tích sẵn
    d.chk_all.setChecked(True)
    assert all(cb.isChecked() for cb in d.checks.values() if cb.isEnabled())
    d.chk_all.setChecked(False)
    assert not d.btn_ok.isEnabled()
    d.combos["versions"].setCurrentIndex(1)               # 7 ngày
    d._save_only()
    assert R.retention_days(store, "versions") == 7 and d.parts() == []
    d2 = ClearHistoryDialog(win, store, library_path=str(tmp_path / "lib.pdf"))
    d2._delete_all(confirm=False)
    assert d2.parts() == [k for k, *_ in R.PARTS]


def test_window_delete_all_resets_library_and_views(win, store, tmp_path, spool, samples, monkeypatch):
    from app import ui_tools
    _fill(store, tmp_path, spool, samples)
    win.library = None
    win._init_library()
    assert len(win.library.items) == 1

    def fake_exec(self):
        self._delete_all(confirm=False)
        return ui_tools.ClearHistoryDialog.Accepted
    monkeypatch.setattr(ui_tools.ClearHistoryDialog, "exec", fake_exec)
    win.run("clearhistory")
    assert win.library is not None and win.library.items == []          # thư viện mới, trống
    assert win.lib_panel is not None and win.lib_panel.parent() is not None
    assert win.recent_files() == [] and "Chưa chọn" in win.side.cert_card.name.text()
    assert "Đã xóa" in win.lbl_msg.text()


def test_window_asks_before_deleting_library(win, store, tmp_path, spool, samples, monkeypatch):
    from app import ui_tools
    _fill(store, tmp_path, spool, samples)

    def fake_exec(self):
        self.checks["library"].setChecked(True)
        self.checks["recent"].setChecked(True)
        return ui_tools.ClearHistoryDialog.Accepted
    monkeypatch.setattr(ui_tools.ClearHistoryDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    win.run("clearhistory")
    assert os.path.exists(str(tmp_path / "lib.pdf"))        # không đồng ý -> giữ thư viện
    assert win.recent_files() == []                          # mục khác vẫn xóa


# ================================================================== ảnh: lớp, độ đậm, xoay
RED = (220, 30, 40)


def _dark_in(doc, i, rect, scale=2):
    im = doc.render(i, scale).to_pil().convert("RGB")
    x0, y0, x1, y1 = (int(v * scale) for v in rect)
    return sum(1 for x in range(x0, x1, 2) for y in range(y0, y1, 2) if sum(im.getpixel((x, y))) < 200)


def _red_block(w=20, h=20, a=255):
    return bytes([*RED, a]) * (w * h), w, h


BOX = (50, 70, 300, 200)                                  # phủ lên các dòng chữ 1–5 của trang mẫu


@pytest.mark.parametrize("layer,text_visible", [("top", False), ("multiply", True), ("behind", True)])
def test_layers_on_text_page(samples, layer, text_visible):
    d = PdfDocument(samples["text"])
    base = _dark_in(d, 0, BOX)
    rgba, w, h = _red_block()
    d.insert_image(0, BOX, rgba, w, h, layer=layer)
    dark = _dark_in(d, 0, BOX)
    assert (dark > base * 0.8) == text_visible, (layer, base, dark)
    from app import editing
    idx = [k for k in range(editing.C.FPDFPage_CountObjects(d.page(0).raw))
           if editing.C.FPDFPageObj_GetType(editing.C.FPDFPage_GetObject(d.page(0).raw, k)) == editing.C.FPDF_PAGEOBJ_IMAGE]
    assert editing.image_layer(d, 0, idx[0]) == layer
    # lưu, mở lại: vẫn đúng lớp, vẫn thấy/không thấy chữ
    d2 = PdfDocument(data=d.to_bytes())
    assert (_dark_in(d2, 0, BOX) > base * 0.8) == text_visible
    assert d.undo() and _dark_in(d, 0, BOX) == base      # 1 bước hoàn tác


def test_behind_falls_back_on_scan_and_signed(samples):
    d = PdfDocument(samples["scan"])
    assert d.layer_for(0, "behind") == "multiply"
    t = PdfDocument(samples["text"])
    assert t.layer_for(0, "behind") == "behind" and t.layer_for(0, "xyz") == "top"


def test_rotation_fits_bounding_box(samples):
    d = PdfDocument(samples["text"])
    rgba, w, h = _red_block(40, 10)                      # ảnh ngang 4:1
    d.insert_image(1, (200, 300, 250, 500), rgba, w, h, angle=90)   # xoay 90° -> khung đứng 50×200
    im = d.render(1, 1).to_pil().convert("RGB")
    xs = [x for x in range(595) for y in range(250, 550, 5) if im.getpixel((x, y)) == RED]
    ys = [y for y in range(842) for x in range(150, 300, 5) if im.getpixel((x, y)) == RED]
    assert 198 <= min(xs) and max(xs) <= 252 and 298 <= min(ys) and max(ys) <= 502
    assert max(ys) - min(ys) > 180                        # dài theo chiều dọc


def test_rotated_corners_math():
    bl, br, tl = PdfDocument.rotated_corners((0, 0, 100, 50), 100, 50, 0)
    assert (bl, br, tl) == ((0, 50), (100, 50), (0, 0))
    bl, br, tl = PdfDocument.rotated_corners((0, 0, 50, 100), 100, 50, 90)
    assert round(bl[0]) == 0 and round(bl[1]) == 0 and round(br[0]) == 0 and round(br[1]) == 100


def test_gui_insert_image_with_options(win, qapp, samples, tmp_path):
    from PySide6.QtGui import QImage
    p = str(tmp_path / "dau.png")
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (200, 100), (*RED, 255)))
    img.save(p)
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    win.insert_image(tab, p)
    assert win.img_opts.isVisible() and win.img_opts.cb_scope.isVisible() and win.img_opts.chk_bg.isVisible()
    pl = tab.view.placement
    w0, h0 = pl.rect.width(), pl.rect.height()
    win.img_opts.cb_layer.setCurrentIndex(win.img_opts.cb_layer.findData("multiply"))
    win.img_opts.sl_opacity.setValue(50)
    win.img_opts.rotate_by(90)
    # khung đặt tự xoay (núm tròn như Word): giữ nguyên cỡ ảnh, chỉ đổi góc
    assert pl.rotatable and abs(pl.angle - 90) < 0.01
    assert abs(pl.rect.width() - w0) < 2 and abs(pl.rect.height() - h0) < 2
    win.img_opts.cb_scope.setCurrentIndex(win.img_opts.cb_scope.findData("all"))
    tab.view.commit_placement()
    pump(qapp)
    assert not win.img_opts.isVisible()
    from app import editing
    for i in range(tab.doc.page_count):                  # đóng lên tất cả các trang
        objs = [editing.C.FPDFPage_GetObject(tab.doc.page(i).raw, k)
                for k in range(editing.C.FPDFPage_CountObjects(tab.doc.page(i).raw))]
        imgs = [k for k, o in enumerate(objs) if editing.C.FPDFPageObj_GetType(o) == editing.C.FPDF_PAGEOBJ_IMAGE]
        assert imgs and editing.image_layer(tab.doc, i, imgs[-1]) == "multiply"
    r = pl.rect
    im = tab.doc.render(0, 1).to_pil().convert("RGB")
    px = im.getpixel((int(r.center().x()), int(r.top() + 5)))
    assert 200 < px[0] and 120 < px[1] < 160               # đỏ 50% trên nền trắng
    # các lần sau nhớ lớp + độ đậm, góc xoay về 0
    win.insert_image(tab, p)
    assert win.img_opts.layer == "multiply" and win.img_opts.opacity == 50 and win.img_opts.angle == 0
    tab.view.cancel_placement()


def test_remove_white_background_option(win, qapp, samples, tmp_path):
    p = str(tmp_path / "chu_ky.jpg")
    img = Image.new("RGB", (300, 150), (250, 250, 248))
    img.paste((20, 40, 140), (40, 60, 260, 90))
    img.save(p, "JPEG", quality=95)
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    win.img_opts.cb_layer.setCurrentIndex(0)
    win.img_opts.sl_opacity.setValue(100)
    win.insert_image(tab, p)
    win.img_opts.chk_bg.setChecked(True)
    pl = tab.view.placement
    pl.rect.moveTo(40, 60)
    tab.view.commit_placement()
    pump(qapp)
    r = pl.rect
    # góc ảnh (nền giấy) giờ trong suốt: thấy chữ/nền trang bên dưới, không còn nền xám nhạt của ảnh
    base = PdfDocument(samples["text"])
    assert _dark_in(tab.doc, 0, (r.left(), r.top(), r.left() + 30, r.top() + 15)) == \
        _dark_in(base, 0, (r.left(), r.top(), r.left() + 30, r.top() + 15))


def test_edit_existing_image_change_layer(win, qapp, samples):
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    rgba, w, h = _red_block()
    tab.doc.insert_image(0, BOX, rgba, w, h, layer="top")
    tab.refresh()
    base_hidden = _dark_in(tab.doc, 0, BOX)
    cx, cy = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
    win.page_pressed(0, cx, cy)
    assert tab.view.placement is not None and win.img_opts.isVisible()
    assert win.img_opts.cb_layer.currentData() == "keep" and "nổi trên chữ" in win.img_opts.cb_layer.currentText()
    assert win.img_opts.sp_angle.isVisible() and tab.view.placement.rotatable   # 1.0.22: xoay được ảnh đã chèn
    win.img_opts.cb_layer.setCurrentIndex(win.img_opts.cb_layer.findData("multiply"))
    tab.view.commit_placement()
    pump(qapp)
    assert _dark_in(tab.doc, 0, BOX) > base_hidden + 200    # chữ hiện lại qua lớp mực
    assert tab.doc.undo() and _dark_in(tab.doc, 0, BOX) == base_hidden
    # mở lại lần nữa: không đổi gì -> chỉ di chuyển, lớp giữ nguyên
    win.page_pressed(0, cx, cy)
    assert win.img_opts.cb_layer.currentData() == "keep"
    tab.view.cancel_placement()
    assert win.img_opts.layer != "keep"


def test_rotate_existing_image(win, qapp, samples):
    """Ảnh / dấu / chữ ký đã chèn: bấm chọn rồi xoay (ô Xoay hoặc núm tròn), Ctrl+Z trả về góc cũ."""
    from app import editing
    win.open_files([samples["text"]])
    pump(qapp)
    tab = win.current()
    rgba, w, h = _red_block()
    tab.doc.insert_image(0, BOX, rgba, w, h, layer="top")
    tab.refresh()
    cx, cy = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2

    def frame():
        page = tab.doc.page(0).raw
        objs = [editing.C.FPDFPage_GetObject(page, k) for k in range(editing.C.FPDFPage_CountObjects(page))]
        k = [k for k, o in enumerate(objs) if editing.C.FPDFPageObj_GetType(o) == editing.C.FPDF_PAGEOBJ_IMAGE][-1]
        return editing.image_frame(tab.doc, 0, k)
    r0, a0 = frame()
    assert a0 == 0
    win.page_pressed(0, cx, cy)
    win.img_opts.rotate_by(90)
    assert abs(tab.view.placement.angle - 90) < 0.01
    tab.view.commit_placement()
    pump(qapp)
    r1, a1 = frame()
    assert abs(a1 - 90) < 0.5
    assert abs((r1[2] - r1[0]) - (r0[2] - r0[0])) < 0.5 and abs((r1[3] - r1[1]) - (r0[3] - r0[1])) < 0.5
    # bấm lại: khung hiện đúng góc đang có, xoay tiếp
    win.page_pressed(0, cx, cy)
    assert abs(win.img_opts.angle - 90) < 0.5 and abs(tab.view.placement.angle - 90) < 0.5
    tab.view.placement.angle = 135
    tab.view.commit_placement()
    pump(qapp)
    assert abs(frame()[1] - 135) < 0.5
    assert tab.doc.undo() and abs(frame()[1] - 90) < 0.5
