"""Cửa sổ chính (giao diện "Ấn triện"): thanh điều hướng trái, dải công cụ ẩn/hiện được, tab file, thumbnail,
vùng xem, bảng bên phải (chứng thư số, thư viện dấu, tài liệu), màn hình bắt đầu."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QStatusBar, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, theme
from .document import KIND_LABEL, PasswordRequired, PdfDocument, format_ranges
from .icons import TILE_OF, icon, seal, tile_icon
from .theme import tiles
from .thumbnails import ThumbnailList
from .viewer import PageView

# (mã, nhãn, [nhóm công cụ: [(mã lệnh, nhãn, icon, nổi bật?)]])
MODES = [
    ("home", "Trang chủ", [
        [("open", "Mở", "open", 0), ("save", "Lưu", "save", 0), ("print", "In", "print", 0)],
        [("undo", "Hoàn tác", "undo", 0), ("redo", "Làm lại", "redo", 0)],
        [("tray", "Khay ghép", "merge", 0), ("image", "Chèn ảnh", "image", 0), ("protect", "Lưu có bảo vệ", "lock", 0)]]),
    ("edit", "Chỉnh sửa", [
        [("select", "Chọn", "select", 0), ("edittext", "Sửa chữ", "text", 0), ("textbox", "Hộp chữ", "textbox", 0),
         ("hand", "Chữ viết tay", "hand", 0), ("image", "Ảnh", "image", 0)],
        [("note", "Ghi chú", "note", 0), ("notes", "DS ghi chú", "notelist", 0), ("symbol", "Ký hiệu", "check", 0),
         ("shape", "Hình vẽ", "shape", 0), ("pen", "Vẽ tay", "pen", 0)],
        [("erase", "Tẩy vùng", "erase", 0), ("find", "Tìm & thay", "search", 0)]]),
    ("page", "Trang", [
        [("insertpdf", "Chèn trang", "pageadd", 0), ("blank", "Trang trắng", "page", 0),
         ("delete", "Xóa trang", "delete", 0)],
        [("rotateleft", "Xoay trái", "rotateleft", 0), ("rotate", "Xoay phải", "rotate", 0),
         ("autorotate", "Tự xoay", "autorotate", 0)],
        [("split", "Tách file", "split", 0), ("resize", "Đổi kích thước", "resize", 0),
         ("colormode", "Màu / đen trắng", "colormode", 0)]]),
    ("sign", "Ký & Đóng dấu", [
        [("stamp", "Con dấu", "stamp", 0), ("sigimg", "Chữ ký ảnh", "sign", 0),
         ("seam", "Giáp lai", "seam", 0)],
        [("digisign", "Ký số", "token", 1), ("batchsign", "Ký hàng loạt", "batch", 0),
         ("verify", "Kiểm tra chữ ký", "shield", 0)],
        [("flow", "Luồng ký", "flow", 0), ("remote", "Ký từ xa", "phone", 0)]]),
    ("protect", "Bảo vệ", [
        [("protect", "Lưu có bảo vệ", "lock", 1), ("password", "Mật khẩu", "key", 0),
         ("printperm", "Quyền in", "print", 0)],
        [("presets", "Mẫu bảo vệ", "shield", 0)]]),
    ("tray", "Khay ghép", [
        [("tray", "Mở khay", "merge", 0), ("trayadd", "Thêm file", "open", 0),
         ("traytabs", "Thêm tab đang mở", "tabs", 0)],
        [("toc", "Bìa & mục lục", "toc", 0), ("merge", "Ghép", "merge", 0),
         ("mergesign", "Ghép + ký", "token", 1)]]),
    ("tools", "Công cụ", [
        [("compare", "So sánh 2 bản", "compare", 0), ("stamptext", "Dấu chữ", "stamptext", 0),
         ("compress", "Nén theo dung lượng", "compress", 0)],
        [("batchxl", "Tạo hàng loạt từ Excel", "batchxl", 0), ("ocr", "Nhận dạng chữ", "ocr", 0)],
        [("autofolder", "Thư mục tự xử lý", "autofolder", 0), ("history", "Lịch sử phiên bản", "history", 0),
         ("backup", "Sao lưu & chuyển máy", "backup", 0)],
        [("importopts", "Tùy chọn mở file", "gear", 0), ("clearhistory", "Xóa lịch sử", "delete", 0),
         ("license", "Bản quyền", "key", 0),
         ("about", "Giới thiệu", "info", 0)]]),
]

# lệnh đã có ở phiên bản này; còn lại báo giai đoạn phát triển
READY = {"open", "save", "print", "undo", "redo", "blank", "delete", "rotate", "rotateleft", "insertpdf",
         "tray", "trayadd", "traytabs", "merge", "mergesign", "split", "resize", "autorotate", "image",
         "stamp", "sigimg", "seam", "digisign", "verify",
         "edittext", "textbox", "hand", "note", "symbol", "shape", "pen", "erase", "find",
         "protect", "password", "printperm", "presets", "batchsign", "flow", "compare", "stamptext", "compress",
         "batchxl", "autofolder", "history", "backup", "toc", "license", "about", "clearhistory",
         "select", "notes", "colormode", "importopts"}
# dùng được cả khi hết hạn dùng thử / chưa kích hoạt (chỉ xem, in, kiểm tra chữ ký)
FREE_CMDS = {"open", "print", "verify", "license", "about", "history", "undo", "redo", "clearhistory", "select",
             "notes", "importopts"}
# lệnh làm thay đổi nội dung -> bị chặn với file được bảo vệ (mở không có mật khẩu chủ sở hữu)
MODIFY_CMDS = {"blank", "delete", "rotate", "rotateleft", "insertpdf", "autorotate", "resize", "image", "stamp",
               "colormode",
               "sigimg", "seam", "edittext", "textbox", "hand", "note", "symbol", "shape", "pen", "erase", "find",
               "stamptext", "flow", "undo", "redo"}
NOT_SUPPORTED = {
    "remote": "Ký từ xa qua điện thoại cần máy chủ trung gian trên Internet (dịch vụ trả phí của nhà cung cấp chữ ký "
              "số từ xa). Bản phần mềm offline này chưa hỗ trợ.",
    "ocr": "Nhận dạng chữ (OCR) cho file scan sẽ có ở bản cập nhật sau.",
}
RAIL_LABEL = {"sign": "Ký & Dấu"}
RAIL_ICON = {"home": "home", "edit": "text", "page": "page", "sign": "stamp", "protect": "shield", "tray": "merge",
             "tools": "gear"}
CMD_LABEL = {cmd: label for _, _, groups in MODES for g in groups for cmd, label, *_ in g}
# sửa được mà không làm hỏng chữ ký có sẵn -> không cảnh báo (hoàn tác, thêm ô ký trống)
SIG_SAFE_CMDS = {"undo", "redo", "flow"}
NO_DOC_OK = {"open", "tray", "trayadd", "traytabs", "merge", "mergesign"}
PHASE_OF: dict = {}


class PageJump(QWidget):
    """Ô số trang ở thanh trạng thái: bấm vào, gõ số trang, Enter để tới ngay (Esc: thôi).
    Giữ giao diện giống nhãn cũ: text() -> "Trang 3 / 10"."""
    jump = Signal(int)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.pre = QLabel("Trang")
        self.edit = QLineEdit(objectName="pagebox")
        self.edit.setFixedWidth(46)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setToolTip("Gõ số trang rồi nhấn Enter để tới trang (Ctrl+G)")
        self.total = QLabel("")
        for w in (self.pre, self.edit, self.total):
            lay.addWidget(w)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.cur, self.count = 0, 0
        self.edit.returnPressed.connect(self._go)
        self.edit.editingFinished.connect(self._restore)
        self.edit.installEventFilter(self)
        self.setVisible(False)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self._restore()
            self.edit.clearFocus()
            return True
        if ev.type() == QEvent.FocusIn:
            QTimer.singleShot(0, self.edit.selectAll)
        if ev.type() == QEvent.Wheel and self.count:          # lăn chuột trên ô: sang trang trước/sau
            d = -1 if ev.angleDelta().y() > 0 else 1
            n = min(max(self.cur - 1 + d, 0), self.count - 1)
            self.jump.emit(n)
            return True
        return super().eventFilter(obj, ev)

    def setText(self, s: str):
        import re as _re
        m = _re.match(r"Trang (\d+) / (\d+)", s or "")
        if not m:
            self.cur = self.count = 0
            self.setVisible(False)
            return
        self.cur, self.count = int(m.group(1)), int(m.group(2))
        self.setVisible(True)
        self.total.setText(f"/ {self.count}")
        if not self.edit.hasFocus():
            self.edit.setText(str(self.cur))

    def text(self) -> str:
        return f"Trang {self.cur} / {self.count}" if self.count else ""

    def _go(self):
        t = self.edit.text().strip()
        if t.isdigit() and self.count:
            n = min(max(int(t), 1), self.count)
            self.edit.clearFocus()
            self.jump.emit(n - 1)
        self._restore()

    def _restore(self):
        if self.count:
            self.edit.setText(str(self.cur))

    def focus_edit(self):
        self.edit.setFocus()
        self.edit.selectAll()


class DocBanner(QFrame):
    """Dải cảnh báo trên đầu tài liệu: file đã ký số / đã khóa / chữ ký không hợp lệ / file được bảo vệ."""
    ICON = {"danger": "⛔", "warn": "⚠", "info": "ℹ"}

    def __init__(self):
        super().__init__(objectName="banner")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 10, 8)
        h.setSpacing(10)
        self.icon = QLabel("", objectName="bannericon")
        self.icon.setAlignment(Qt.AlignTop)
        h.addWidget(self.icon)
        self.text = QLabel("", objectName="bannertext", wordWrap=True)
        self.text.setTextFormat(Qt.RichText)
        h.addWidget(self.text, 1)
        self.buttons: dict[str, QPushButton] = {}
        for key, label in (("verify", "Kiểm tra chữ ký"), ("sign", "Ký số tiếp…"), ("unprotect", "Gỡ bảo vệ…")):
            b = QPushButton(label, objectName="bannerbtn")
            b.setVisible(False)
            h.addWidget(b, 0, Qt.AlignTop)
            self.buttons[key] = b
        self.btn_close = QToolButton(text="✕", objectName="bannerclose", toolTip="Ẩn thông báo")
        self.btn_close.clicked.connect(lambda: self.setVisible(False))
        h.addWidget(self.btn_close, 0, Qt.AlignTop)
        self.level = ""
        self.setVisible(False)

    def show_message(self, level: str, html: str, buttons=()):
        changed = (level, html) != (self.level, self.text.text())
        self.level = level
        self.setProperty("level", level)
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon.setText(self.ICON.get(level, ""))
        self.text.setText(html)
        for k, b in self.buttons.items():
            b.setVisible(k in buttons)
        if changed:
            self.setVisible(True)

    def clear(self):
        self.level = ""
        self.text.setText("")
        self.setVisible(False)


class DocTab(QWidget):
    """Một tab = một file: thumbnail + vùng xem."""

    def __init__(self, doc: PdfDocument, colors: dict, owner=None):
        super().__init__()
        self.doc = doc
        self.thumbs = ThumbnailList(doc)
        self.view = PageView(doc, colors["canvas"])
        self.sig_state = None                     # tình trạng chữ ký số có sẵn trong file (signing.SigState)
        self.sig_ack = False                      # người dùng đã chọn "không hỏi lại" khi sửa file đã ký
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.banner = DocBanner()
        outer.addWidget(self.banner)
        # 1.0.22: vạch ngăn kéo được giữa cột ảnh thu nhỏ và trang xem – nhớ độ rộng cho lần sau
        from PySide6.QtWidgets import QSplitter
        self.split = QSplitter(Qt.Horizontal, objectName="docsplit")
        self.split.setHandleWidth(5)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.thumbs)
        self.split.addWidget(self.view)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        tw = 0
        if owner is not None and hasattr(owner, "settings"):
            try:
                tw = int(owner.settings.value("ui/thumb_w", 0) or 0)
            except (TypeError, ValueError):
                tw = 0
        tw = tw or self.thumbs.sizeHint().width()
        self.split.setSizes([tw, 1000])
        if owner is not None and hasattr(owner, "settings"):
            self.split.splitterMoved.connect(lambda *_: owner.settings.setValue("ui/thumb_w", self.thumbs.width()))
        outer.addWidget(self.split, 1)
        self.thumbs.pageClicked.connect(self.view.go_to)
        self.view.currentPageChanged.connect(self.thumbs.select_page)
        if owner:
            self.view.libraryDropped.connect(owner.place_library_item)
            self.view.pagePressed.connect(owner.page_pressed)
            self.view.pageDoubleClicked.connect(owner.page_double_clicked)
            self.view.hover_provider = lambda i, x, y: owner._hover_kind(self, i, x, y)
            self.view.guide_provider = lambda i: owner._guides(self, i)
            # bấm vào bảng tùy chọn bên phải (cỡ chữ, đậm, màu...) khi đang gõ sửa chữ: không đóng ô sửa
            self.view.inline_keep = lambda w: w is getattr(owner, "tool_opts", None)
            self.view.bandSelected.connect(lambda pg, x0, y0, x1, y1, t=self: owner.band_selected(t, pg, (x0, y0, x1, y1)))
            self.view.clipboardAction.connect(lambda act, t=self: owner.clipboard_action(t, act))
            self.view.textSelected.connect(lambda t=self: owner.text_selected(t))
            self.view.textMenu.connect(lambda pg, x, y, gp, t=self: owner.page_context_menu(t, pg, x, y, gp))
            self.view.toolChanged.connect(owner._tool_changed)
            self.thumbs.pagesMoved.connect(owner.move_pages)
            self.thumbs.menuRequested.connect(owner.page_menu)
            self.view.placementEnded.connect(owner._placement_ended)
            self.thumbs.rotateRequested.connect(owner.rotate_page_quick)
            self.thumbs.deleteRequested.connect(owner.delete_selected_pages)
            self.thumbs.filesDropped.connect(lambda paths, at, t=self: owner.insert_files_at(t, paths, at))

    def refresh(self):
        self.view.document_changed()
        self.thumbs.rebuild()


QUICK = [("open", "Mở file", "open"), ("digisign", "Ký số", "token"), ("stamp", "Đóng dấu", "stamp"),
         ("tray", "Ghép file", "merge"), ("protect", "Lưu có bảo vệ", "lock"), ("compress", "Nén file", "compress")]
RECENT_MAX = 12


class StartPage(QScrollArea):
    """Màn hình bắt đầu: khung kéo thả, bắt đầu nhanh, file mở gần đây, bản quyền."""
    command = Signal(str)
    openPath = Signal(str)
    removeRecent = Signal(str)

    def __init__(self):
        super().__init__(objectName="start")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget(objectName="root")
        self.setWidget(inner)
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(28)

        left = QVBoxLayout()
        left.setSpacing(14)
        self.hero = QLabel("Xin chào! Hôm nay bạn cần ký gì?", objectName="hero")
        left.addWidget(self.hero)
        left.addWidget(QLabel("Mở PDF, Word, Excel để ký số, đóng dấu, chỉnh sửa, ghép và bảo vệ file – "
                              "tất cả trên máy của bạn, không cần Internet.", objectName="lbl", wordWrap=True))
        drop = QFrame(objectName="drop")
        drop.setMinimumHeight(190)
        dl = QVBoxLayout(drop)
        dl.setContentsMargins(28, 24, 28, 24)
        dl.setSpacing(8)
        seal_lbl = QLabel()
        seal_lbl.setPixmap(seal(128).pixmap(56, 56))
        dl.addWidget(seal_lbl)
        t = QLabel("Kéo thả file vào đây")
        t.setStyleSheet("font-size: 20px; font-weight: 800;")
        dl.addWidget(t)
        dl.addWidget(QLabel("PDF · Word · Excel · PowerPoint – file Office được chuyển sang PDF, giữ nguyên khổ giấy.",
                            objectName="dropsub", wordWrap=True))
        row = QHBoxLayout()
        self.btn_open = QPushButton("Mở file…  (Ctrl+O)")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(lambda: self.command.emit("open"))
        row.addWidget(self.btn_open)
        row.addStretch()
        dl.addStretch()
        dl.addLayout(row)
        left.addWidget(drop)

        left.addSpacing(6)
        left.addWidget(QLabel("BẮT ĐẦU NHANH", objectName="cap"))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.quick_buttons: list[tuple] = []
        for i, (cmd, label, ic) in enumerate(QUICK):
            b = QToolButton(text=label, objectName="quick")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(40, 40))
            b.setMinimumSize(120, 96)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cmd: self.command.emit(c))
            self.quick_buttons.append((b, ic, cmd))
            grid.addWidget(b, i // 3, i % 3)
        left.addLayout(grid)
        left.addStretch()
        outer.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(10)
        cap = QHBoxLayout()
        cap.addWidget(QLabel("MỞ GẦN ĐÂY", objectName="cap"))
        cap.addStretch()
        self.btn_clear = QPushButton("Xóa lịch sử…", objectName="link")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip("Xóa danh sách mở gần đây, bản cũ, nhật ký dùng dấu…")
        self.btn_clear.clicked.connect(lambda: self.command.emit("clearhistory"))
        cap.addWidget(self.btn_clear)
        right.addLayout(cap)
        self.recent = QListWidget(objectName="recent")
        self.recent.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent.customContextMenuRequested.connect(self._recent_menu)
        self.recent.installEventFilter(self)
        self.recent.setIconSize(QSize(28, 28))
        self.recent.itemActivated.connect(self._activate)
        self.recent.itemClicked.connect(self._activate)
        self.recent.setMinimumHeight(260)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent.setTextElideMode(Qt.ElideMiddle)
        right.addWidget(self.recent, 1)
        self.no_recent = QLabel("Chưa có file nào. File bạn mở sẽ hiện ở đây.", objectName="lbl", wordWrap=True)
        self.no_recent.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        right.addWidget(self.no_recent, 1)
        lic = QFrame(objectName="card")
        ll = QVBoxLayout(lic)
        ll.setContentsMargins(14, 12, 14, 12)
        ll.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bản quyền", objectName="h"))
        row.addStretch()
        self.lic_chip = QLabel("", objectName="chip")
        row.addWidget(self.lic_chip)
        ll.addLayout(row)
        self.lic_desc = QLabel("", objectName="lbl", wordWrap=True)
        ll.addWidget(self.lic_desc)
        row = QHBoxLayout()
        b = QPushButton("Kích hoạt / gia hạn…")
        b.clicked.connect(lambda: self.command.emit("license"))
        row.addWidget(b)
        b = QPushButton("Giới thiệu")
        b.clicked.connect(lambda: self.command.emit("about"))
        row.addWidget(b)
        row.addStretch()
        ll.addLayout(row)
        lic.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        right.addWidget(lic)
        wrap = QWidget()
        wrap.setLayout(right)
        wrap.setFixedWidth(380)
        outer.addWidget(wrap)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "recent", None) and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Delete:
            it = self.recent.currentItem()
            if it:
                self.removeRecent.emit(it.data(Qt.UserRole + 1))
            return True
        return super().eventFilter(obj, ev)

    def _recent_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        it = self.recent.itemAt(pos)
        m = QMenu(self)
        if it:
            p = it.data(Qt.UserRole + 1)
            a = m.addAction("Mở")
            a.setEnabled(bool(it.data(Qt.UserRole)))
            a.triggered.connect(lambda: self._activate(it))
            m.addAction("Mở thư mục chứa file", lambda: self._show_folder(p)).setEnabled(os.path.exists(p))
            m.addAction("Xóa khỏi danh sách (Delete)", lambda: self.removeRecent.emit(p))
            m.addSeparator()
        m.addAction("Xóa file không còn trên máy", lambda: self.command.emit("recentprune"))
        m.addAction("Xóa toàn bộ danh sách", lambda: self.command.emit("recentclear"))
        m.addAction("Xóa lịch sử khác…", lambda: self.command.emit("clearhistory"))
        m.exec(self.recent.viewport().mapToGlobal(pos))

    @staticmethod
    def _show_folder(p):
        from .osutil import reveal
        reveal(p)

    def _activate(self, item):
        p = item.data(Qt.UserRole)
        if p:
            self.openPath.emit(p)

    def set_recent(self, paths: list[str], colors: dict):
        self.recent.clear()
        for p in paths:
            name = os.path.basename(p)
            exists = os.path.exists(p)
            ext = os.path.splitext(p)[1].lower()
            kind = "PDF" if ext == ".pdf" else ("Word" if ext.startswith(".doc") or ext in (".rtf", ".odt") else
                                                "Excel" if ext.startswith(".xl") or ext in (".ods", ".csv") else "Office")
            bg, fg = tiles(colors)["red" if kind == "PDF" else "blue" if kind == "Word" else "green"]
            it = QListWidgetItem(tile_icon("page", bg, fg), f"{name}\n{os.path.dirname(p)}" +
                                 ("" if exists else "  (không còn file)"))
            it.setData(Qt.UserRole, p if exists else "")
            it.setData(Qt.UserRole + 1, p)
            it.setToolTip(p)
            self.recent.addItem(it)
        self.recent.setVisible(bool(paths))
        self.no_recent.setVisible(not paths)

    def set_license(self, short: str, state: str):
        self.lic_chip.setText({"ok": "Đã kích hoạt", "warn": "Dùng thử"}.get(state, "Chưa kích hoạt"))
        self.lic_chip.setProperty("state", state)
        self.lic_chip.style().unpolish(self.lic_chip)
        self.lic_chip.style().polish(self.lic_chip)
        self.lic_desc.setText(short)

    def apply_colors(self, c: dict):
        for b, ic, cmd in self.quick_buttons:
            bg, fg = (c["accent"], "#FFFFFF") if cmd == "digisign" else tiles(c)[TILE_OF.get(cmd, "gray")]
            b.setIcon(tile_icon(ic, bg, fg))


class CertCard(QFrame):
    """Thẻ chứng thư số màu tối: chứng thư dùng gần nhất / kết quả dò USB token."""
    scanRequested = Signal()
    signRequested = Signal()

    def __init__(self):
        super().__init__(objectName="cert")
        l = QVBoxLayout(self)
        l.setContentsMargins(14, 12, 14, 12)
        l.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("CHỨNG THƯ SỐ", objectName="certcap"))
        row.addStretch()
        self.state = QLabel("", objectName="certsub")
        row.addWidget(self.state)
        l.addLayout(row)
        self.name = QLabel("", objectName="certname", wordWrap=True)
        self.sub = QLabel("", objectName="certsub", wordWrap=True)
        l.addWidget(self.name)
        l.addWidget(self.sub)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_scan = QPushButton("Dò USB token")
        self.btn_scan.clicked.connect(self.scanRequested)
        self.btn_sign = QPushButton("Ký số…")
        self.btn_sign.clicked.connect(self.signRequested)
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_sign)
        row.addStretch()
        l.addSpacing(4)
        l.addLayout(row)
        self.show_cert(None)

    def show_cert(self, info: dict | None, found: int | None = None):
        import time as _t
        if not info:
            self.name.setText("Chưa chọn chứng thư")
            self.sub.setText("Cắm USB token rồi bấm “Dò USB token”." if found is None else
                             "Không thấy chứng thư ký số nào. Kiểm tra USB token và driver của nhà cung cấp.")
            self.state.setText("")
            return
        self.name.setText(info.get("organization") or info.get("subject") or "Chứng thư số")
        left = int((float(info.get("not_after", 0)) - _t.time()) // 86400)
        until = _t.strftime("%d/%m/%Y", _t.localtime(float(info.get("not_after", 0))))
        issuer = info.get("issuer", "")
        extra = f"\n{info['subject']}" if info.get("organization") and info.get("subject") else ""
        self.sub.setText(f"{issuer}{extra}\nHiệu lực đến {until} · " +
                         (f"còn {left} ngày" if left >= 0 else "ĐÃ HẾT HẠN"))
        if found is not None:
            self.state.setText(f"● Đã thấy {found} chứng thư" if found else "")
        else:
            self.state.setText("Dùng gần nhất")


def _breakable(name: str) -> str:
    """Tên file dài không có dấu cách (a_b_c.pdf) -> cho phép xuống dòng sau _ . - để không tràn bảng."""
    for ch in "_.-\\/":
        name = name.replace(ch, ch + "\u200b")
    return name


class SidePanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("side")
        self.setFixedWidth(300)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(objectName="sidescroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = self._inner = QWidget(objectName="sideinner")
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll)
        # 1.0.22: nội dung luôn vừa đúng bề ngang bảng – tên file dài / chữ rộng không đẩy cả cột lệch ra ngoài
        self.scroll.viewport().installEventFilter(self)
        lay = self._lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.cert_card = CertCard()
        lay.addWidget(self.cert_card)

        self.page_card, pl = self._card()
        row = QHBoxLayout()
        h = QLabel("Trang hiện tại", objectName="h")
        self.kind = QLabel("", objectName="badge")
        row.addWidget(h)
        row.addStretch()
        row.addWidget(self.kind)
        pl.addLayout(row)
        self.page_desc = QLabel("", objectName="lbl", wordWrap=True)
        pl.addWidget(self.page_desc)
        lay.addWidget(self.page_card)

        self.doc_card, dl = self._card()
        dl.addWidget(QLabel("Tài liệu", objectName="h"))
        self.doc_desc = QLabel("", objectName="lbl", wordWrap=True)
        self.doc_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for lb in (self.page_desc, self.doc_desc):
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lb.setMinimumWidth(0)
        dl.addWidget(self.doc_desc)
        lay.addWidget(self.doc_card)
        lay.addStretch()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.scroll.viewport() and ev.type() == QEvent.Resize:
            self._inner.setFixedWidth(max(120, obj.width()))
        return super().eventFilter(obj, ev)

    def layout(self):
        """Các thẻ nằm trong vùng cuộn (màn hình thấp vẫn xem đủ) – layout() trả về layout của các thẻ."""
        return self._lay

    def _card(self):
        f = QFrame(objectName="card")
        l = QVBoxLayout(f)
        l.setContentsMargins(12, 12, 12, 12)
        l.setSpacing(8)
        return f, l

    def show_page(self, doc: PdfDocument | None, i: int):
        self.kind.setVisible(bool(doc and doc.page_count))
        if not doc or doc.page_count == 0:
            self.kind.setText("")
            self.page_desc.setText("Chưa mở tài liệu")
            self.doc_desc.setText("Kéo thả file PDF vào cửa sổ hoặc bấm Mở (Ctrl+O).")
            return
        info = doc.page_info(i)
        self.kind.setText(KIND_LABEL[info.kind])
        hint = {"text": "PDF xuất từ Word/Excel – sửa được chữ.",
                "scan": "PDF ảnh/scan – chỉ cắt bỏ, chèn ảnh, ghi chú, ký hiệu, hình vẽ.",
                "blank": "Trang trắng."}[info.kind]
        self.page_desc.setText(f"{hint}\nKhổ {info.label} · {info.width_mm:.0f} × {info.height_mm:.0f} mm")
        size = ""
        if doc.path and os.path.exists(doc.path):
            size = f" · {os.path.getsize(doc.path) / 1048576:.2f} MB"
        sig = doc.signature_count()
        self.doc_desc.setText(f"{_breakable(doc.name)}\n{doc.page_count} trang{size}\n"
                              f"Chữ ký số trong file: {sig if sig else 'chưa có'}")


class CurrentStack(QStackedWidget):
    """QStackedWidget lấy cỡ theo trang ĐANG HIỆN (mặc định lấy trang rộng nhất -> cửa sổ không thu hẹp được)."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(lambda *_: self.updateGeometry())

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w else super().minimumSizeHint()


class RibbonScroll(QScrollArea):
    """Dải công cụ cuộn ngang được khi cửa sổ hẹp (chia đôi màn hình, màn hình nhỏ / phóng to 125–150%):
    trước đây dải công cụ bắt cửa sổ rộng tối thiểu ~1140 px -> bảng bên phải bị đẩy ra ngoài màn hình."""

    def __init__(self, widget: QWidget):
        super().__init__(objectName="ribbonscroll")
        self.setWidget(widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.horizontalScrollBar().rangeChanged.connect(lambda *_: self._fit_height())

    def _fit_height(self):
        w = self.widget()
        h = w.minimumSizeHint().height() if w else 0
        if self.horizontalScrollBar().maximum() > 0:
            h += self.horizontalScrollBar().sizeHint().height()
        if self.height() != h:
            self.setFixedHeight(h)

    def minimumSizeHint(self):
        return QSize(120, super().minimumSizeHint().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_height()

    def wheelEvent(self, ev):                   # lăn chuột dọc -> cuộn ngang dải công cụ
        d = ev.angleDelta()
        if abs(d.y()) > abs(d.x()) and self.horizontalScrollBar().maximum() > 0:
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - d.y())
            ev.accept()
            return
        super().wheelEvent(ev)


class MainWindow(QMainWindow):
    def __init__(self, library_path: str | None = None):
        super().__init__()
        self.library_path = library_path
        self.library = None
        self.auto_sign = not os.environ.get("PDFKYSO_NO_AUTOSIGN")   # file in vào máy in "PDF Ky so" / "Ghép + ký" -> mở ngay hộp thoại ký
        from . import portable
        self.settings = QSettings(*portable.settings_args())
        self.theme_pref = self.settings.value("theme", "system")
        self.colors = theme.resolve(self.theme_pref)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon("app"))
        self.setAcceptDrops(True)
        self.resize(1440, 900)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- tab file ---
        self.tabs = QTabWidget(documentMode=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().setElideMode(Qt.ElideMiddle)           # tên dài: giữ đầu + đuôi (…_v2.pdf)
        self.tabs.tabBar().setExpanding(False)
        # 1.0.22: tab "Bắt đầu" kiểu Foxit ở đầu hàng tab -> về trang bắt đầu (mở file, gần đây) khi đang mở file
        self.start_tab = QToolButton(objectName="starttab", text="Bắt đầu", checkable=True,
                                     toolTip="Trang bắt đầu: mở file, file gần đây, bắt đầu nhanh")
        self.start_tab.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.start_tab.setIconSize(QSize(14, 14))
        self.start_tab.setCursor(Qt.PointingHandCursor)
        self.start_tab.clicked.connect(lambda: self.show_start_page(True))
        self.tabs.setCornerWidget(self.start_tab, Qt.TopLeftCorner)
        self.tabs.tabBar().tabBarClicked.connect(lambda _i: self.show_start_page(False))
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.empty = StartPage()
        self.empty.command.connect(self.run)
        self.empty.openPath.connect(lambda p: self.open_files([p]))
        self.empty.removeRecent.connect(self.remove_recent)

        # --- thanh điều hướng trái (nhóm công cụ) ---
        self.rail = QFrame(objectName="rail")
        self.rail.setFixedWidth(self.RAIL_W)          # 1.0.22: thu gọn (trước 88 px) để dành chỗ xem văn bản
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(0, 10, 0, 8)
        rl.setSpacing(2)
        logo = self.rail_logo = QLabel(objectName="raillogo", alignment=Qt.AlignCenter)
        logo.setPixmap(seal(128).pixmap(34, 34))
        logo.setToolTip(APP_NAME)
        rl.addWidget(logo)
        rl.addSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.toolbars = CurrentStack()
        self.tool_buttons: list[tuple] = []
        self.mode_buttons: list[tuple] = []
        for k, (mode, label, groups) in enumerate(MODES):
            b = QToolButton(text=RAIL_LABEL.get(mode, label).replace("&", "&&"), objectName="pivot", checkable=True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(20, 20))
            b.setFixedHeight(50)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setToolTip(label)
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, k)
            self.mode_buttons.append((b, RAIL_ICON.get(mode, "page")))
            rl.addWidget(b)
            self.toolbars.addWidget(self._toolbar(groups))
        self.mode_group.idClicked.connect(self._mode_clicked)
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idToggled.connect(self._rail_icons)
        rl.addStretch()
        # nút thu gọn / mở rộng ngay trên thanh: chỉ còn biểu tượng (hẹp hơn nữa) <-> biểu tượng + chữ
        self.rail_btn = QToolButton(objectName="railbtn")
        self.rail_btn.setIconSize(QSize(18, 18))
        self.rail_btn.clicked.connect(lambda: self.set_rail_compact(not self.rail_compact()))
        rl.addWidget(self.rail_btn, 0, Qt.AlignHCenter)
        self.theme_btn = QToolButton(objectName="railbtn", toolTip="Đổi giao diện sáng/tối")
        self.theme_btn.setIconSize(QSize(20, 20))
        self.theme_btn.clicked.connect(self.toggle_theme)
        rl.addWidget(self.theme_btn, 0, Qt.AlignHCenter)
        self.dev_btn = QToolButton(objectName="railbtn", toolTip="Thông tin nhà phát triển")
        self.dev_btn.setIconSize(QSize(20, 20))
        self.dev_btn.clicked.connect(self.show_developer)
        rl.addWidget(self.dev_btn, 0, Qt.AlignHCenter)
        outer.addWidget(self.rail)

        col = QWidget(objectName="root")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        outer.addWidget(col, 1)

        # --- hàng tiêu đề: tên nhóm, bản quyền, tìm kiếm, ẩn/hiện dải công cụ ---
        top = QFrame(objectName="topbar")
        th = QHBoxLayout(top)
        th.setContentsMargins(8, 4, 10, 2)          # 1.0.22: một hàng duy nhất sát mép trên (dải công cụ + tìm kiếm)
        th.setSpacing(6)
        self.lbl_title = QLabel(MODES[0][1], objectName="title")     # tên nhóm: đã có trên thanh trái -> ẩn
        self.lbl_title.setVisible(False)
        self.lic_chip = QLabel("", objectName="chip")
        self.lic_chip.setCursor(Qt.PointingHandCursor)
        self.lic_chip.setVisible(False)
        self.lic_chip.mousePressEvent = lambda e: self.run("license")
        th.addWidget(self.lic_chip)
        self.search = QLineEdit(placeholderText="Tìm trong tài liệu (Ctrl+F)", objectName="search")
        self.search.setMinimumWidth(140)
        self.search.setMaximumWidth(280)
        self.search.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.search.setToolTip("Gõ chữ cần tìm rồi nhấn Enter; nhấn Enter tiếp để tới trang có chữ đó tiếp theo")
        self.search.returnPressed.connect(lambda: self.search_doc(self.search.text()))
        self.search.textChanged.connect(lambda t: None if t.strip() else self.clear_search())
        self.search.installEventFilter(self)
        th.addWidget(self.search)
        self.layout_btn = QToolButton(objectName="flat", toolTip="Bố cục: ẩn/hiện thanh trang, nhóm công cụ, bảng bên "
                                      "phải (Ctrl+F2: chỉ xem văn bản)")
        self.layout_btn.setIconSize(QSize(18, 18))
        self.layout_btn.setPopupMode(QToolButton.InstantPopup)
        th.addWidget(self.layout_btn)
        self.ribbon_btn = QToolButton(objectName="flat", checkable=True)
        self.ribbon_btn.setIconSize(QSize(18, 18))
        self.ribbon_btn.clicked.connect(lambda on: self.set_ribbon_visible(not on))
        th.addWidget(self.ribbon_btn)
        # --- 1.0.22: hàng trên cùng kiểu Foxit: thanh truy cập nhanh + các nhóm thành tab ngang ---
        self.menubar_row = QFrame(objectName="quickrow")
        qh = QHBoxLayout(self.menubar_row)
        qh.setContentsMargins(8, 2, 10, 0)
        qh.setSpacing(2)
        self.quick_buttons = []
        for cmd, ic, tip in (("open", "open", "Mở (Ctrl+O)"), ("save", "save", "Lưu (Ctrl+S)"),
                             ("print", "print", "In (Ctrl+P)"), (None, None, None),
                             ("undo", "undo", "Hoàn tác (Ctrl+Z)"), ("redo", "redo", "Làm lại (Ctrl+Y)")):
            if cmd is None:
                sep = QFrame(objectName="vsep")
                sep.setFixedHeight(16)
                qh.addWidget(sep)
                continue
            b = QToolButton(objectName="qa", toolTip=tip)
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(26, 26)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cmd: self.run(c))
            self.quick_buttons.append((b, ic, cmd))
            qh.addWidget(b)
        qh.addSpacing(10)
        self.mode_tabs = []
        for k, (mode, label, _g) in enumerate(MODES):
            t = QToolButton(objectName="modetab", text=RAIL_LABEL.get(mode, label).replace("&", "&&"), checkable=True)
            t.setCursor(Qt.PointingHandCursor)
            t.setToolTip(label)
            t.clicked.connect(lambda _=False, k=k: self.mode_group.button(k).click())
            self.mode_tabs.append(t)
            qh.addWidget(t)
        self.mode_tabs[0].setChecked(True)
        self.mode_group.idToggled.connect(lambda k, on: on and [t.setChecked(i == k)
                                                                 for i, t in enumerate(self.mode_tabs)])
        qh.addStretch()
        v.addWidget(self.menubar_row)
        v.addWidget(top)

        # --- dải công cụ (ẩn/hiện được) ---
        self.ribbon = QFrame(objectName="ribbon")
        rb = QHBoxLayout(self.ribbon)
        rb.setContentsMargins(6, 2, 4, 2)
        rb.setSpacing(2)
        self.ribbon_scroll = RibbonScroll(self.toolbars)
        rb.addWidget(self.ribbon_scroll)
        # 1.0.22: nút ẩn ngay trên dải công cụ (góc phải)
        self.ribbon_hide_btn = QToolButton(objectName="stripbtn", toolTip="Ẩn dải công cụ (Ctrl+F1)")
        self.ribbon_hide_btn.setIconSize(QSize(14, 14))
        self.ribbon_hide_btn.clicked.connect(lambda: self.set_ribbon_visible(False))
        rb.addWidget(self.ribbon_hide_btn, 0, Qt.AlignTop)
        self.ribbon_wrap = QWidget()
        rw = QHBoxLayout(self.ribbon_wrap)
        rw.setContentsMargins(0, 0, 0, 0)
        rw.addWidget(self.ribbon)
        th.insertWidget(0, self.ribbon_wrap, 1)
        # dải đã ẩn: còn một mấu nhỏ ngay chỗ đó để hiện lại
        self.ribbon_handle_wrap = QWidget()
        hw = QHBoxLayout(self.ribbon_handle_wrap)
        hw.setContentsMargins(0, 0, 0, 0)
        self.ribbon_handle = QToolButton(objectName="striphandle", text="Hiện dải công cụ",
                                         toolTip="Hiện dải công cụ (Ctrl+F1)")
        self.ribbon_handle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.ribbon_handle.setIconSize(QSize(12, 12))
        self.ribbon_handle.setCursor(Qt.PointingHandCursor)
        self.ribbon_handle.clicked.connect(lambda: self.set_ribbon_visible(True))
        hw.addWidget(self.ribbon_handle)
        hw.addStretch()
        self.ribbon_handle_wrap.setVisible(False)
        th.insertWidget(1, self.ribbon_handle_wrap, 1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        body.addWidget(self.stack, 1)
        self.side = SidePanel()
        self.side.cert_card.scanRequested.connect(self.scan_certs)
        self.side.cert_card.signRequested.connect(lambda: self.run("digisign"))
        body.addWidget(self.side)
        from .ui_edit import ToolOptions
        self.tool_opts = ToolOptions(self.settings)
        self.tool_opts.closeRequested.connect(self._opts_close)
        self.tool_opts.changed.connect(self._tool_opts_changed)
        self.tool_opts.zRequested.connect(self._sel_z)
        self.tool_opts.deleteRequested.connect(self._sel_delete)
        from .ui_edit import NotesPanel
        self.notes_panel = NotesPanel()
        self.notes_panel.gotoRequested.connect(self._note_goto)
        self.notes_panel.replyRequested.connect(self._note_reply)
        self.notes_panel.toggleDoneRequested.connect(self._note_toggle_done)
        self.notes_panel.editRequested.connect(lambda pg, nm: self.current() and
                                               self._edit_note_dialog(self.current(), pg, nm))
        self.notes_panel.deleteRequested.connect(self._note_delete)
        self.notes_panel.closeRequested.connect(lambda: self.toggle_notes_panel(False))
        self.notes_panel.exportRequested.connect(self.export_notes)
        self.notes_panel.showToggled.connect(self.show_notes_on_page)
        self.notes_panel.printToggled.connect(lambda on: self.settings.setValue("print/notes", on))
        self.notes_panel.chk_print.setChecked(str(self.settings.value("print/notes", "false")).lower() == "true")
        self.side.layout().insertWidget(0, self.notes_panel)   # trên cùng: bảng công cụ, danh sách ghi chú, rồi mới tới thẻ chứng thư
        self.side.layout().insertWidget(0, self.tool_opts)
        from .ui_edit import ImageOptions
        self.img_opts = ImageOptions(self.settings)
        self.img_opts.changed.connect(self._img_opts_changed)
        self.side.layout().insertWidget(0, self.img_opts)
        self._img_ctx = None
        from .ui_edit import fit_side_panel
        fit_side_panel(self.side)                  # bảng bên phải không bị cắt khi chữ rộng (Windows, phóng to)
        v.addLayout(body, 1)
        self._side_auto = False                     # bảng phải đang tạm hiện vì có bảng tùy chọn (người dùng đã ẩn)
        for w in (self.tool_opts, self.img_opts, self.notes_panel):
            w.installEventFilter(self)

        self._build_status()
        self._build_shortcuts()
        self.set_ribbon_visible(self._bool_setting("ui/ribbon", True), save=False)
        self._build_layout_menu()
        self._load_last_cert()
        self.apply_theme()
        self.refresh_recent()
        self._update_state()
        QTimer.singleShot(0, self._init_library)   # nạp sau khi cửa sổ hiện -> khởi động nhanh

    # ---------- dựng giao diện ----------
    def _toolbar(self, groups) -> QFrame:
        f = QFrame(objectName="toolbar")
        h = QHBoxLayout(f)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(2)
        for gi, group in enumerate(groups):
            if gi:
                h.addWidget(QFrame(objectName="vsep"))
            for cmd, label, ic, primary in group:
                b = QToolButton(text=label.replace("&", "&&"), objectName="tool")
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setIconSize(QSize(20, 20) if primary else QSize(24, 24))   # 1.0.22: dải thấp hơn (trước 66 px)
                b.setMinimumHeight(52)
                b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)   # hẹp thì cuộn ngang, không cắt chữ "Chè…ang"
                b.setCursor(Qt.PointingHandCursor)
                if primary:
                    b.setProperty("primary", True)
                    if cmd == "digisign":
                        b.setToolTip("Ký số bằng USB token / chứng thư trên máy (Ctrl+K)")
                b.clicked.connect(lambda _=False, c=cmd: self.run(c))
                self.tool_buttons.append((b, ic, cmd, bool(primary)))
                h.addWidget(b)
        h.addStretch()
        return f

    def _bool_setting(self, key: str, default: bool) -> bool:
        v = self.settings.value(key, default)
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")

    def show_start_page(self, on: bool):
        """Tab "Bắt đầu" (kiểu Foxit): xem trang bắt đầu ngay trong vùng tài liệu, hàng tab file vẫn còn;
        bấm một tab file để quay lại tài liệu."""
        ov = getattr(self, "start_overlay", None)
        if on and self.tabs.count():
            if ov is None:
                ov = self.start_overlay = StartPage()
                ov.setParent(self.tabs)
                ov.command.connect(self.run)
                ov.openPath.connect(lambda p: self.open_files([p]))
                ov.removeRecent.connect(self.remove_recent)
                self.tabs.installEventFilter(self)
            ov.apply_colors(self.colors)
            ov.set_recent(self.recent_files(), self.colors)
            st = getattr(self, "_lic_short", None)
            if st:
                ov.set_license(*st)
            self._place_start_overlay()
            ov.show()
            ov.raise_()
        elif ov is not None:
            ov.hide()
        self.start_tab.setChecked(bool(ov is not None and ov.isVisible()) or not self.tabs.count())

    def _place_start_overlay(self):
        ov = getattr(self, "start_overlay", None)
        w = self.tabs.currentWidget()
        if ov is not None and w is not None:
            from PySide6.QtCore import QPoint, QRect
            ov.setGeometry(QRect(w.mapTo(self.tabs, QPoint(0, 0)), w.size()))

    def layout_style(self) -> str:
        return "tabs" if getattr(self, "_layout_style", "rail") == "tabs" else "rail"

    def set_layout_style(self, style: str, save: bool = True):
        """1.0.22: "rail" = cột nhóm công cụ bên trái; "tabs" = các nhóm thành tab ngang trên cùng (như Foxit).
        Thanh truy cập nhanh (Mở, Lưu, In, Hoàn tác, Làm lại) có ở cả hai kiểu."""
        style = "tabs" if style == "tabs" else "rail"
        self._layout_style = style
        for t in self.mode_tabs:
            t.setVisible(style == "tabs")
        if style == "tabs":
            self.rail.setVisible(False)
        else:
            self.rail.setVisible(self._bool_setting("ui/rail", True))
        for key, a in getattr(self, "style_actions", {}).items():
            a.blockSignals(True)
            a.setChecked(key == style)
            a.blockSignals(False)
        a = getattr(self, "panel_actions", {}).get("rail")
        if a is not None:
            a.setEnabled(style == "rail")
        if save:
            self.settings.setValue("ui/layout_style", style)

    def _mode_clicked(self, k: int):
        self.toolbars.setCurrentIndex(k)
        self.lbl_title.setText(MODES[k][1])
        if self.ribbon_wrap.isHidden():          # đang ẩn dải công cụ: bấm nhóm -> hiện lại
            self.set_ribbon_visible(True)

    RAIL_W, RAIL_W_COMPACT = 64, 46

    def rail_compact(self) -> bool:
        return self.rail.width() <= self.RAIL_W_COMPACT

    def set_rail_compact(self, on: bool, save: bool = True):
        """1.0.22: thanh nhóm công cụ bên trái chỉ còn biểu tượng (hẹp) hoặc biểu tượng + chữ – nhớ cho lần sau."""
        self.rail.setFixedWidth(self.RAIL_W_COMPACT if on else self.RAIL_W)
        for b, _ic in self.mode_buttons:
            b.setToolButtonStyle(Qt.ToolButtonIconOnly if on else Qt.ToolButtonTextUnderIcon)
            b.setFixedHeight(40 if on else 50)
        self.rail_logo.setPixmap(seal(128).pixmap(28 if on else 34, 28 if on else 34))
        self.rail_btn.setToolTip("Mở rộng thanh bên trái (hiện tên nhóm)" if on else
                                 "Thu gọn thanh bên trái (chỉ còn biểu tượng)")
        if hasattr(self, "colors"):
            self.rail_btn.setIcon(icon("chevright" if on else "chevleft", self.colors["railtext"]))
        if save:
            self.settings.setValue("ui/rail_compact", on)

    def ribbon_visible(self) -> bool:
        return not self.ribbon_wrap.isHidden()

    def set_ribbon_visible(self, on: bool, save: bool = True):
        """Ẩn/hiện dải công cụ chính (Ctrl+F1) – nhớ lựa chọn cho lần mở sau."""
        self.ribbon_wrap.setVisible(on)
        self.ribbon_handle_wrap.setVisible(not on)
        self.ribbon_btn.setChecked(not on)
        self.ribbon_btn.setToolTip("Ẩn thanh công cụ (Ctrl+F1)" if on else "Hiện thanh công cụ (Ctrl+F1)")
        if save:
            self.settings.setValue("ui/ribbon", on)
        a = getattr(self, "panel_actions", {}).get("ribbon")
        if a is not None and a.isChecked() != on:
            a.blockSignals(True)
            a.setChecked(on)
            a.blockSignals(False)
        if hasattr(self, "colors"):
            self.ribbon_btn.setIcon(icon("chevup" if on else "chevdown", self.colors["text"]))
        if save:
            self._flash("Đã ẩn thanh công cụ – bấm một nhóm bên trái hoặc Ctrl+F1 để hiện lại." if not on else "")

    def toggle_ribbon(self):
        self.set_ribbon_visible(not self.ribbon_visible())

    # ---------- bố cục: ẩn/hiện các thanh để dành chỗ xem văn bản (chia đôi màn hình) ----------
    PANELS = (("thumbs", "Thanh xem nhanh trang (bên trái)"), ("rail", "Thanh nhóm công cụ (bên trái)"),
              ("ribbon", "Dải công cụ (Ctrl+F1)"), ("side", "Bảng bên phải (chứng thư, thư viện dấu…)"))

    def _build_layout_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        self.panel_actions = {}
        for key, label in self.PANELS:
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.panel_visible(key))
            a.toggled.connect(lambda on, k=key: self.set_panel_visible(k, on))
            self.panel_actions[key] = a
        m.addSeparator()
        self.style_actions = {}
        for key, label in (("rail", "Kiểu nhóm công cụ ở cột trái"), ("tabs", "Kiểu tab ngang trên cùng (như Foxit)")):
            a = m.addAction(label)
            a.setCheckable(True)
            a.toggled.connect(lambda on, k=key: on and self.set_layout_style(k))
            self.style_actions[key] = a
        m.addSeparator()
        m.addAction("Chỉ xem văn bản – ẩn tất cả (Ctrl+F2)", lambda: self.set_focus_view(True))
        m.addAction("Hiện lại tất cả", lambda: self.set_focus_view(False))
        m.addSeparator()
        m.addAction(icon("window", self.colors["text"]), "Mở tab đang xem ở cửa sổ riêng", self.detach_current_tab)
        m.addAction("Mở file ở cửa sổ mới…", lambda: self.open_in_new_window())
        self.layout_btn.setMenu(m)
        for key in ("thumbs", "rail", "side"):
            self.set_panel_visible(key, self._bool_setting(f"ui/{key}", True), save=False)
        self.set_rail_compact(self._bool_setting("ui/rail_compact", False), save=False)
        self.set_layout_style(str(self.settings.value("ui/layout_style", "tabs")), save=False)   # mặc định kiểu Foxit

    def panel_visible(self, key: str) -> bool:
        if key == "ribbon":
            return self.ribbon_visible()
        if key == "thumbs":
            return self._bool_setting("ui/thumbs", True)
        if key == "side":
            return not getattr(self, "_side_hidden", False)
        return not self.rail.isHidden()

    def set_panel_visible(self, key: str, on: bool, save: bool = True):
        if key == "ribbon":
            if self.ribbon_visible() != on:
                self.set_ribbon_visible(on, save=save)
        elif key == "thumbs":
            if save:
                self.settings.setValue("ui/thumbs", on)
            for i in range(self.tabs.count()):
                t = self.tabs.widget(i)
                if isinstance(t, DocTab):
                    t.thumbs.setVisible(on)
        elif key == "rail":
            self.rail.setVisible(on and self.layout_style() == "rail")
            if save:
                self.settings.setValue("ui/rail", on)
        elif key == "side":
            self._side_hidden = not on
            self._side_auto = False
            self.side.setVisible(on or self._side_needed())
            self._side_auto = not on and self.side.isVisible()
            if save:
                self.settings.setValue("ui/side", on)
        a = getattr(self, "panel_actions", {}).get(key)
        if a is not None and a.isChecked() != on:
            a.blockSignals(True)
            a.setChecked(on)
            a.blockSignals(False)

    def set_focus_view(self, on: bool):
        """Chỉ xem văn bản: ẩn thanh trang, nhóm công cụ, dải công cụ, bảng phải (bật lại: hiện tất cả)."""
        for key, _ in self.PANELS:
            self.set_panel_visible(key, not on)
        if on:
            self._flash("Đang chỉ xem văn bản – Ctrl+F2 hoặc nút Bố cục để hiện lại các thanh.")

    def toggle_focus_view(self):
        self.set_focus_view(any(self.panel_visible(k) for k, _ in self.PANELS))

    def _side_needed(self) -> bool:
        """Có bảng tùy chọn đang dùng (đặt ảnh, công cụ vẽ, ghi chú) -> bảng phải phải hiện dù người dùng đã ẩn."""
        return any(not w.isHidden() for w in (self.tool_opts, self.img_opts, self.notes_panel))

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.tabs and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_start_overlay)
        if obj is getattr(self, "search", None) and ev.type() == QEvent.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ShiftModifier:
                self.search_doc(self.search.text(), backward=True)
                return True
            if ev.key() == Qt.Key_Escape:
                self.clear_search()
                tab = self.current()
                if tab:
                    tab.view.setFocus()
                return True
        if ev.type() in (QEvent.ShowToParent, QEvent.HideToParent) and getattr(self, "_side_hidden", False) and \
                obj in (getattr(self, "tool_opts", None), getattr(self, "img_opts", None),
                        getattr(self, "notes_panel", None)):
            need = self._side_needed()
            if need and self.side.isHidden():
                self.side.setVisible(True)
                self._side_auto = True
            elif not need and self._side_auto:
                self.side.setVisible(False)
                self._side_auto = False
        return super().eventFilter(obj, ev)

    # ---------- file gần đây ----------
    def recent_files(self) -> list[str]:
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v] if v else []
        return [p for p in (v or []) if isinstance(p, str) and p]

    def add_recent(self, path: str):
        from .retention import keeps, touch_recent
        if not path or not keeps(self.settings, "recent"):
            return
        path = os.path.abspath(path)
        lst = [p for p in self.recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        lst.insert(0, path)
        self.settings.setValue("recent", lst[:RECENT_MAX])
        touch_recent(self.settings, path)
        self.refresh_recent()

    def remove_recent(self, path: str):
        n = os.path.normcase(os.path.abspath(path))
        self.settings.setValue("recent", [p for p in self.recent_files() if os.path.normcase(os.path.abspath(p)) != n])
        self.refresh_recent()

    def clear_recent(self, missing_only: bool = False):
        keep = [p for p in self.recent_files() if os.path.exists(p)] if missing_only else []
        self.settings.setValue("recent", keep)
        self.refresh_recent()

    def clear_history_dialog(self):
        from . import retention as R
        from .ui_tools import ClearHistoryDialog
        lib_path = self.library.path if self.library is not None else self.library_path
        dlg = ClearHistoryDialog(self, self.settings, library_path=lib_path)
        if dlg.exec() != ClearHistoryDialog.Accepted:
            return
        self.apply_retention_flags()
        parts = dlg.parts()
        if not parts:
            n = self.run_retention()
            self._flash("Đã lưu thời hạn tự xóa." + (f" Đã xóa phần quá hạn ({sum(n.values())} mục)." if n else ""))
            return
        risky = [p for p in parts if p in R.DANGEROUS and dlg.action != "all"]
        if risky and QMessageBox.question(
                self, APP_NAME, "Xóa hẳn:\n" + "\n".join("• " + R.LABELS[p] for p in risky) +
                "\n\nKhông khôi phục lại được. Tiếp tục?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            parts = [p for p in parts if p not in risky]
        done = self.clear_data(parts)
        self.run_retention()
        self._flash(("Đã xóa: " + "; ".join(done).lower()) if done else "Không có gì để xóa.")

    def clear_data(self, parts) -> list[str]:
        """Xóa các mục lịch sử/dữ liệu; cập nhật giao diện liên quan (thư viện, khay, thẻ chứng thư...)."""
        from . import retention as R
        lib_path = self.library.path if self.library is not None else self.library_path
        if "library" in parts:
            self._drop_library()
        done = R.clear(parts, self.settings, lib_path, self._active_recovery())
        if "library" in parts:
            self._init_library()                     # thư viện trống mới
        if "tray" in parts and getattr(self, "_tray", None) is not None:
            self._tray.items.clear()
            self._tray.refresh()
            self.settings.setValue("tray", "")
        if "templates" in parts:
            self.start_autofolder()                  # cấu hình đã xóa -> tắt thư mục tự xử lý
        if "traces" in parts:
            self._load_last_cert()
        self.refresh_recent()
        return done

    def _drop_library(self):
        panel = getattr(self, "lib_panel", None)
        if panel is not None:
            panel.setParent(None)
            panel.deleteLater()
        self.lib_panel = None
        self.library = None

    def _active_recovery(self) -> set:
        return {getattr(self.tabs.widget(i), "recovery_key", None) for i in range(self.tabs.count())} - {None}

    def apply_retention_flags(self):
        from . import library, retention
        library.USAGE_LOG_ENABLED = retention.keeps(self.settings, "usage")

    def run_retention(self) -> dict:
        from . import retention
        try:
            out = retention.apply_retention(self.settings, active_recovery=self._active_recovery())
        except Exception:
            return {}
        if "recent" in out:
            self.refresh_recent()
        return out

    def start_retention(self):
        """Tự xóa lịch sử quá hạn: ngay khi mở và mỗi 6 giờ khi phần mềm đang chạy."""
        self.apply_retention_flags()
        self.run_retention()
        self._ret_timer = QTimer(self, interval=6 * 3600 * 1000, timeout=self.run_retention)
        self._ret_timer.start()

    def refresh_recent(self):
        self.empty.set_recent(self.recent_files(), self.colors)

    # ---------- chứng thư số (thẻ bên phải) ----------
    def _load_last_cert(self):
        import json
        try:
            info = json.loads(self.settings.value("sign/last_cert", "") or "null")
        except (TypeError, ValueError):
            info = None
        self.side.cert_card.show_cert(info if isinstance(info, dict) else None)

    @staticmethod
    def _cert_dict(cert) -> dict:
        return {k: getattr(cert, k, "") for k in ("subject", "organization", "issuer", "not_after", "thumbprint")}

    def remember_cert(self, cert):
        import json
        try:
            d = self._cert_dict(cert)
        except Exception:
            return
        self.settings.setValue("sign/last_cert", json.dumps(d, ensure_ascii=False))
        self.side.cert_card.show_cert(d)

    def scan_certs(self, lister=None):
        """Dò USB token / chứng thư trên máy, hiện chứng thư còn hạn đầu tiên lên thẻ."""
        import json
        from . import signing
        from .ui_sign import busy
        lister = lister or getattr(self, "cert_lister", None) or signing.list_certificates
        try:
            known = json.loads(self.settings.value("sign/known_libs", "") or "null")
        except (TypeError, ValueError):
            known = None
        try:
            certs, libs = busy(self, "Đang dò USB token…", lambda: lister(known_libs=known if isinstance(known, list)
                                                                         else None))
            if not certs and known:
                certs, libs = busy(self, "Đang dò USB token…", lambda: lister(refresh=True, known_libs=None))
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không đọc được USB token:\n{e}")
            return
        self.settings.setValue("sign/known_libs", json.dumps(libs))
        ok = [c for c in certs if not c.expired] or certs
        self.side.cert_card.show_cert(self._cert_dict(ok[0]) if ok else None, found=len(certs))
        self._flash(f"Tìm thấy {len(certs)} chứng thư ký số." if certs else "Không thấy chứng thư ký số nào.")

    def show_developer(self):
        from .ui_license import DeveloperDialog
        DeveloperDialog(self).exec()

    def _build_status(self):
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.lbl_page = PageJump()
        self.lbl_page.jump.connect(lambda n: self._view_call("go_to", n))
        self.lbl_paper = QLabel("")
        self.lbl_kind = QLabel("", objectName="badge")
        self.lbl_msg = QLabel("")
        # thông báo dài không được bắt cửa sổ rộng ra (chia đôi màn hình): co lại, rê chuột xem đủ
        self.lbl_msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_msg.setMinimumWidth(40)
        self.lbl_paper.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_paper.setMinimumWidth(30)
        for w in (self.lbl_page, self.lbl_paper, self.lbl_kind):
            sb.addWidget(w)
        sb.addWidget(self.lbl_msg, 1)
        self.btn_fitpage = self._sbtn("fitpage", "Vừa trang (Ctrl+0)", lambda: self._view_call("fit_page"))
        self.btn_fitwidth = self._sbtn("fitwidth", "Vừa chiều rộng (Ctrl+2)", lambda: self._view_call("fit_width"))
        self.btn_zout = self._sbtn("zout", "Thu nhỏ (Ctrl+−)", lambda: self._view_call("zoom_step", -1))
        self.slider = QSlider(Qt.Horizontal, minimum=10, maximum=400, fixedWidth=140)
        self.slider.valueChanged.connect(self._slider_moved)
        self.btn_zin = self._sbtn("zin", "Phóng to (Ctrl++)", lambda: self._view_call("zoom_step", 1))
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setFixedWidth(52)
        for w in (self.btn_fitpage, self.btn_fitwidth, self.btn_zout, self.slider, self.btn_zin, self.lbl_zoom):
            sb.addPermanentWidget(w)

    def _sbtn(self, ic, tip, fn) -> QToolButton:
        b = QToolButton(toolTip=tip)
        b.setProperty("icon_name", ic)
        b.setIconSize(QSize(16, 16))
        b.clicked.connect(fn)
        return b

    def _build_shortcuts(self):
        def sc(keys, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)
        sc(["Ctrl+O"], lambda: self.run("open"))
        sc(["Ctrl+S"], lambda: self.run("save"))
        sc(["Ctrl+Shift+S"], self.save_as)
        sc(["Ctrl+P"], lambda: self.run("print"))
        sc(["Ctrl+Z"], lambda: self.run("undo"))
        sc(["Ctrl+Y", "Ctrl+Shift+Z"], lambda: self.run("redo"))
        sc(["Ctrl+W", "Ctrl+F4"], lambda: self.close_tab(self.tabs.currentIndex()))
        sc(["Ctrl++", "Ctrl+="], lambda: self._view_call("zoom_step", 1))
        sc(["Ctrl+-"], lambda: self._view_call("zoom_step", -1))
        sc(["Ctrl+0"], lambda: self._view_call("fit_page"))
        sc(["Ctrl+1"], lambda: self._view_call("set_zoom", 100))
        sc(["Ctrl+2"], lambda: self._view_call("fit_width"))
        sc(["Ctrl+F"], lambda: (self.search.setFocus(), self.search.selectAll()))
        sc(["F3"], lambda: self.search_doc(self.search.text()))
        sc(["Shift+F3"], lambda: self.search_doc(self.search.text(), backward=True))
        sc(["F11"], lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())
        sc(["Ctrl+G"], self.goto_page)
        sc(["Ctrl+K"], lambda: self.run("digisign"))
        sc(["Ctrl+F1"], self.toggle_ribbon)
        sc(["Ctrl+F2"], self.toggle_focus_view)

    # ---------- chủ đề ----------
    def apply_theme(self):
        c = self.colors
        app = QApplication.instance()
        css = theme.stylesheet(c)
        if app.styleSheet() != css:            # áp lại stylesheet cho toàn bộ widget rất tốn -> chỉ khi đổi
            app.setPalette(theme.palette(c))
            app.setStyleSheet(css)
        tl = tiles(c)
        for b, ic, cmd, primary in self.tool_buttons:
            b.ensurePolished()                  # bề ngang theo đúng phông của giao diện -> không bị cắt chữ khi hẹp
            b.setMinimumWidth(max(80 if primary else 56, b.sizeHint().width()))
            if primary:
                b.setIcon(icon(ic, c["onaccent"]))
            else:
                bg, fg = tl[TILE_OF.get(cmd, "gray")]
                b.setIcon(tile_icon(ic, bg, fg))
        self._edition_dirty = True
        if getattr(self, "_lic_cache", None):
            self.apply_edition_ui()
        for b, ic in self.mode_buttons:
            b.setIcon(icon(ic, "#FFFFFF" if b.isChecked() else c["railtext"]))
        for b in (self.btn_fitpage, self.btn_fitwidth, self.btn_zout, self.btn_zin):
            b.setIcon(icon(b.property("icon_name"), c["text"]))
        self.theme_btn.setIcon(icon("sun" if c is theme.DARK else "moon", c["railtext"]))
        self.dev_btn.setIcon(icon("info", c["railtext"]))
        self.ribbon_btn.setIcon(icon("chevup" if self.ribbon_visible() else "chevdown", c["text"]))
        self.ribbon_hide_btn.setIcon(icon("chevup", c["muted"] if "muted" in c else c["text"]))
        self.ribbon_handle.setIcon(icon("chevdown", c["text"]))
        for b, ic, _cmd in self.quick_buttons:
            b.setIcon(icon(ic, c["text"]))
        self.rail_btn.setIcon(icon("chevright" if self.rail_compact() else "chevleft", c["railtext"]))
        self.layout_btn.setIcon(icon("layout", c["text"]))
        self.empty.apply_colors(c)
        self.refresh_recent()
        bar = self.tabs.tabBar()
        for i in range(self.tabs.count()):
            self.tabs.setTabIcon(i, icon("page", c["accent"]))
            btn = bar.tabButton(i, bar.ButtonPosition.RightSide)
            if btn:
                btn.setIcon(icon("close", c["text"]))
            v = self.tabs.widget(i).view
            v.canvas_color = QColor(c["canvas"])
            v.canvas.update()

    def _rail_icons(self, *_):
        c = self.colors
        for b, ic in self.mode_buttons:
            b.setIcon(icon(ic, "#FFFFFF" if b.isChecked() else c["railtext"]))

    def toggle_theme(self):
        self.theme_pref = "light" if self.colors is theme.DARK else "dark"
        self.settings.setValue("theme", self.theme_pref)
        self.colors = theme.resolve(self.theme_pref)
        self.apply_theme()

    # ---------- tài liệu ----------
    def current(self) -> DocTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocTab) else None

    OPEN_FILTER = ("PDF, Word, Excel, PowerPoint, ảnh (*.pdf *.doc *.docx *.docm *.rtf *.odt *.xls *.xlsx *.xlsm *.xlsb "
                   "*.ods *.csv *.ppt *.pptx *.odp *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp);;PDF (*.pdf);;"
                   "Tất cả (*.*)")

    def convert_office(self, path: str, cached: bool = False, excel: dict | None = None):
        """Word/Excel/PowerPoint -> PDF bằng chính Office trên máy (giữ nguyên khổ giấy). Trả về đường dẫn PDF.
        excel: tùy chọn xuất Excel (sheet, vừa trang, hướng)."""
        from . import office
        from .ui_sign import busy
        kw = {"excel": excel} if excel and any(excel.values()) else {}
        try:
            pdf, used = busy(self, f"Đang chuyển {os.path.basename(path)} sang PDF (giữ nguyên khổ giấy)…",
                             lambda: office.cached_pdf(path, **kw) if cached else office.to_pdf(path, **kw))
        except office.OfficeError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return None
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không chuyển được {os.path.basename(path)}:\n{e}")
            return None
        self._flash(f"Đã chuyển {os.path.basename(path)} sang PDF bằng {used}.")
        return pdf

    def _open_office(self, path: str, excel: dict | None = None):
        pdf = self.convert_office(path, excel=excel)
        if not pdf:
            return
        with open(pdf, "rb") as f:
            doc = PdfDocument(data=f.read())
        doc.path = None
        title = os.path.splitext(os.path.basename(path))[0] + ".pdf"
        tab = self.add_document(doc, title)
        tab.save_dir = os.path.dirname(path)            # Lưu: mặc định cạnh file Word/Excel gốc
        tab.source_office = path
        doc.modified = True
        if not self._is_temp(path):
            self.add_recent(path)
        self._update_state()
        return tab

    def open_files(self, paths):
        from .office import is_office_file
        for path in paths:
            path = os.path.abspath(path)
            if is_office_file(path):
                self._open_office(path)
                continue
            for i in range(self.tabs.count()):  # đã mở thì chuyển sang
                if self.tabs.widget(i).doc.path == path:
                    self.tabs.setCurrentIndex(i)
                    break
            else:
                self._open_one(path)

    def import_files(self, paths, ask: bool | None = None):
        """9 – Mở / kéo thả: PDF, Word, Excel, PowerPoint, ảnh. Hiện bảng tích chọn file, Màu / Chữ đen / Xám /
        Đen trắng cho từng file, mở từng tab hoặc gộp một file (trừ khi người dùng chọn "Không hỏi lại")."""
        from .ui_import import IMAGE_EXT, ImportOptionsDialog, openable
        paths = [os.path.abspath(p) for p in paths if openable(p) and os.path.exists(p)]
        if not paths:
            return []
        st = self.settings
        if ask is None:
            ask = str(st.value("import/ask", "true")).lower() == "true" and \
                (len(paths) > 1 or not paths[0].lower().endswith(".pdf"))
        default = st.value("import/color", "color") or "color"
        if ask:
            dlg = ImportOptionsDialog(self, paths, st, "open")
            self._import_dlg = dlg
            if dlg.exec() != ImportOptionsDialog.Accepted:
                return []
            chosen, merge = dlg.chosen(), dlg.merge()
            excel_opts = dict(dlg.excel_opts)
            image_opts = dict(dlg.image_opts)
        else:
            excel_opts = {}
            try:
                import json as _json
                saved = _json.loads(st.value("import/image_opts", "") or "{}")
            except Exception:
                saved = {}
            image_opts = {p: saved for p, _m in chosen} if saved else {}
            chosen = [(p, "color" if p.lower().endswith(".pdf") else default) for p in paths]
            merge = len(chosen) > 1 and str(st.value("import/merge", "false")).lower() == "true"
        from .colormode import MODE_LABEL, convert_document
        from .office import is_office_file
        if merge:
            parts = []
            for p, mode in chosen:
                d = self._load_any(p, excel_opts.get(p), image_opts.get(p))
                if d is None:
                    continue
                convert_document(d, list(range(d.page_count)), mode, snapshot=False)
                parts.append((p, d))
            if not parts:
                return []
            out = PdfDocument(data=parts[0][1].to_bytes())
            out._drop_pages()
            for _p, d in parts[1:]:
                out.pdf.import_pages(d.pdf)
                out._drop_pages()
            for _p, d in parts:
                d.close()
            out.path = None
            out._undo.clear()
            title = f"Gop_{len(parts)}_file.pdf"
            tab = self.add_document(out, title)
            tab.save_dir = os.path.dirname(parts[0][0])
            out.modified = True
            self._flash(f"Đã gộp {len(parts)} file thành một ({out.page_count} trang). Lưu để đặt tên file.")
            self._update_state()
            return [tab]
        tabs = []
        for p, mode in chosen:
            if is_office_file(p):
                tab = self._open_office(p, excel_opts.get(p))
            elif p.lower().endswith(IMAGE_EXT):
                d = self._load_any(p, image=image_opts.get(p))
                if d is None:
                    continue
                tab = self.add_document(d, os.path.splitext(os.path.basename(p))[0] + ".pdf")
                tab.save_dir = os.path.dirname(p)
                d.modified = True
            else:
                tab = next((self.tabs.widget(i) for i in range(self.tabs.count())
                            if isinstance(self.tabs.widget(i), DocTab) and self.tabs.widget(i).doc.path == p), None)
                if tab is not None:
                    self.tabs.setCurrentWidget(tab)
                else:
                    tab = self._open_one(p)
            if tab is None:
                continue
            if mode != "color":
                if not tab.doc.can_modify:
                    self._flash(f"{os.path.basename(p)} được bảo vệ – không chuyển màu được, mở giữ nguyên.")
                else:
                    convert_document(tab.doc, list(range(tab.doc.page_count)), mode)
                    tab.refresh()
                    self._flash(f"Đã mở {os.path.basename(p)} ({MODE_LABEL[mode].lower()}). Ctrl+Z để về màu gốc.")
            tabs.append(tab)
        self._update_state()
        return tabs

    def _load_any(self, p: str, excel: dict | None = None, image: dict | None = None):
        """PdfDocument từ PDF / Word / Excel / PowerPoint / ảnh (ảnh TIFF nhiều trang -> nhiều trang)."""
        from .office import is_office_file
        from .ui_import import IMAGE_EXT
        try:
            if is_office_file(p):
                pdf = self.convert_office(p, excel=excel)
                if not pdf:
                    return None
                with open(pdf, "rb") as f:
                    return PdfDocument(data=f.read())
            if p.lower().endswith(IMAGE_EXT):
                from .ui_import import image_args
                return PdfDocument.from_images([p], **image_args(image))
            return PdfDocument(p)
        except PasswordRequired:
            pw, ok = QInputDialog.getText(self, "File có mật khẩu", f"Nhập mật khẩu mở {os.path.basename(p)}:",
                                          QLineEdit.Password)
            if ok and pw:
                try:
                    return PdfDocument(p, password=pw)
                except Exception:
                    QMessageBox.warning(self, APP_NAME, f"Sai mật khẩu: {os.path.basename(p)}")
            return None
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không mở được {os.path.basename(p)}:\n{e}")
            return None

    def _open_one(self, path: str, password: str | None = None):
        try:
            doc = PdfDocument(path, password=password)
        except PasswordRequired:
            pw, ok = QInputDialog.getText(self, "File có mật khẩu",
                                          f"Nhập mật khẩu mở {os.path.basename(path)}:",
                                          QLineEdit.Password)
            if ok and pw:
                return self._open_one(path, pw)
            return
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không mở được file:\n{path}\n\n{e}")
            return
        tab = self.add_document(doc)
        if not self._is_temp(path):
            self.add_recent(path)
        return tab

    def add_document(self, doc: PdfDocument, title: str | None = None) -> "DocTab":
        tab = DocTab(doc, self.colors, self)
        tab.title = title
        tab.thumbs.setVisible(self._bool_setting("ui/thumbs", True))
        tab.banner.buttons["verify"].clicked.connect(lambda: self.verify_doc(tab))
        tab.banner.buttons["sign"].clicked.connect(lambda: self.digital_sign(tab))
        tab.banner.buttons["unprotect"].clicked.connect(lambda: self.password_doc(tab))
        self._analyze_sigs(tab)
        tab.view.zoomChanged.connect(self._zoom_changed)
        tab.view.currentPageChanged.connect(lambda i: self._update_state())
        idx = self.tabs.addTab(tab, icon("page", self.colors["accent"]), title or doc.name)
        self.tabs.setTabToolTip(idx, doc.path or (title or doc.name))
        close = QToolButton(objectName="tabclose", toolTip="Đóng (Ctrl+W)", autoRaise=True)
        close.setIcon(icon("close", self.colors["text"]))
        close.setIconSize(QSize(12, 12))
        close.clicked.connect(lambda: self.close_tab(self.tabs.indexOf(tab)))
        self.tabs.tabBar().setTabButton(idx, self.tabs.tabBar().ButtonPosition.RightSide, close)
        self.tabs.setCurrentIndex(idx)
        self.stack.setCurrentIndex(1)
        self.show_start_page(False)
        QTimer.singleShot(0, tab.view, tab.view.fit_page)
        return tab

    def close_tab(self, idx: int):
        if idx < 0:
            return
        tab = self.tabs.widget(idx)
        self._finish_object_edit(tab)
        if tab.doc.modified:
            r = QMessageBox.question(self, APP_NAME, f"Lưu thay đổi của “{tab.doc.name}”?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save(tab)):
                return
        self.tabs.removeTab(idx)
        if getattr(self, "recovery", None) and getattr(tab, "recovery_key", None):
            self.recovery.discard(tab.recovery_key)
        tab.doc.close()
        tab.deleteLater()
        if not self.tabs.count():
            self.stack.setCurrentIndex(0)
        self._update_state()

    # ---------- nhiều cửa sổ: mỗi file một cửa sổ riêng (so sánh trên 2 màn hình / chia đôi màn hình) ----------
    _windows: list = []                        # giữ tham chiếu các cửa sổ phụ (không bị thu hồi bộ nhớ)

    def _tab_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        bar = self.tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            return
        m = QMenu(self)
        m.addAction(icon("window", self.colors["text"]), "Mở ở cửa sổ riêng", lambda: self.detach_tab(idx))
        m.addAction("Xếp các cửa sổ cạnh nhau", self.tile_windows)
        m.addSeparator()
        m.addAction("Đóng", lambda: self.close_tab(idx))
        m.exec(bar.mapToGlobal(pos))

    def new_window(self) -> "MainWindow":
        """Cửa sổ phụ: cùng phần mềm, cùng bản quyền; máy in ảo, khôi phục, thư mục tự xử lý vẫn ở cửa sổ chính."""
        from PySide6.QtCore import Qt as _Qt
        w = MainWindow(self.library_path)
        w.setAttribute(_Qt.WA_DeleteOnClose)
        w.primary = self
        MainWindow._windows.append(w)
        w.destroyed.connect(lambda *_: MainWindow._windows.remove(w) if w in MainWindow._windows else None)
        w._lic_cache = getattr(self, "_lic_cache", None)
        w.resize(self.size())
        g = self.geometry()
        w.move(g.x() + 40, g.y() + 40)
        w.show()
        w._update_state()
        return w

    def detach_tab(self, idx: int) -> "MainWindow | None":
        """Chuyển tab sang cửa sổ mới (giữ nguyên tài liệu, chưa lưu vẫn giữ, hoàn tác vẫn dùng được)."""
        tab = self.tabs.widget(idx) if idx >= 0 else None
        if not isinstance(tab, DocTab):
            return None
        self._finish_object_edit(tab)
        if tab.view.placement is not None:
            tab.view.cancel_placement()
        doc, title, page = tab.doc, getattr(tab, "title", None), tab.view.current_page()
        w = self.new_window()
        self.tabs.removeTab(idx)
        if getattr(self, "recovery", None) and getattr(tab, "recovery_key", None):
            self.recovery.discard(tab.recovery_key)
        nt = w.add_document(doc, title)
        nt.sig_ack = tab.sig_ack
        QTimer.singleShot(50, lambda: nt.view.go_to(page))
        tab.deleteLater()
        if not self.tabs.count():
            self.stack.setCurrentIndex(0)
        self._update_state()
        self.tile_windows([self, w])
        return w

    def detach_current_tab(self):
        if self.tabs.count():
            return self.detach_tab(self.tabs.currentIndex())
        self._flash("Chưa mở tài liệu nào.")
        return None

    def open_in_new_window(self, paths=None) -> "MainWindow | None":
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "Mở ở cửa sổ mới", self.settings.value("open_dir", ""),
                                                    self.OPEN_FILTER)
            if not paths:
                return None
        w = self.new_window()
        w.open_files(paths)
        return w

    def tile_windows(self, wins=None):
        """Xếp các cửa sổ cạnh nhau trên màn hình hiện tại (2 cửa sổ: mỗi cửa sổ nửa màn hình)."""
        wins = [x for x in (wins or self.all_windows()) if x.isVisible()]
        if len(wins) < 2:
            return
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        n = len(wins)
        cols = n if n <= 3 else (n + 1) // 2
        rows = 1 if n <= 3 else 2
        cw, ch = scr.width() // cols, scr.height() // rows
        for k, w in enumerate(wins):
            if w.isMaximized() or w.isFullScreen():
                w.showNormal()
            r, c = divmod(k, cols)
            self._place_framed(w, scr.x() + c * cw, scr.y() + r * ch, cw, ch)
        # Windows chỉ biết đúng độ dày khung / thanh tiêu đề sau khi cửa sổ hiện ra -> đặt lại lần nữa
        QTimer.singleShot(200, lambda: [self._place_framed(w, scr.x() + divmod(k, cols)[1] * cw,
                                                           scr.y() + divmod(k, cols)[0] * ch, cw, ch)
                                        for k, w in enumerate(wins) if w.isVisible()])

    @staticmethod
    def _place_framed(w, x, y, cw, ch):
        """1.0.22: đặt CẢ cửa sổ (gồm thanh tiêu đề có nút thu nhỏ / phóng to / đóng) vào ô (x, y, cw, ch).
        setGeometry chỉ tính phần ruột -> trước đây thanh tiêu đề bị đẩy lên khỏi mép trên màn hình."""
        fg, g = w.frameGeometry(), w.geometry()
        left, top = g.x() - fg.x(), g.y() - fg.y()
        right, bottom = fg.right() - g.right(), fg.bottom() - g.bottom()
        if top <= 0 and not w.isFullScreen():              # chưa có khung thật: ước lượng theo kiểu giao diện
            from PySide6.QtWidgets import QStyle
            top = QApplication.style().pixelMetric(QStyle.PM_TitleBarHeight) + 8
            left = right = bottom = 8 if sys.platform == "win32" else 0
        w.setGeometry(x + left, y + top, max(200, cw - left - right), max(200, ch - top - bottom))

    def all_windows(self) -> list:
        main = getattr(self, "primary", None) or self
        return [main] + [w for w in MainWindow._windows if w is not main]

    def closeEvent(self, ev):
        while self.tabs.count():
            n = self.tabs.count()
            self.close_tab(self.tabs.currentIndex())
            if self.tabs.count() == n:  # người dùng bấm Hủy
                ev.ignore()
                return
        ev.accept()

    # ---------- bản quyền ----------
    def license_status(self, fresh: bool = False):
        import time as _t
        from . import license as L
        cached = getattr(self, "_lic_cache", None)
        if fresh or not cached or _t.time() - cached[0] > 600:
            st = L.status()
            if st.kind == L.NEW:                       # lần đầu dùng: bắt đầu tính 15 ngày dùng thử
                st = L.start_trial()
            self._lic_cache = (_t.time(), st)
        return self._lic_cache[1]

    def license_ok(self) -> bool:
        st = self.license_status()
        if st.usable:
            return True
        self.show_license(st.message + "\nPhần mềm vẫn mở xem, in và kiểm tra chữ ký được; để lưu, ký, ghép, chỉnh sửa "
                          "cần mã kích hoạt.")
        return self.license_status(fresh=True).usable

    # ---------- gói Tiêu chuẩn / Chuyên nghiệp / Doanh nghiệp ----------
    def edition_level(self) -> int:
        from . import editions
        return editions.current(self.license_status())

    def edition_ok(self, feature: str, label: str | None = None, ask: bool = True) -> bool:
        """Tính năng thuộc gói đang dùng? Không thì báo gói cần có + nút nhập mã nâng cấp."""
        from . import editions
        if feature not in editions.FEATURES:
            return True
        level = self.edition_level()
        if editions.allowed(feature, level):
            return True
        if not ask:
            return False
        box = QMessageBox(QMessageBox.Information, "Nâng cấp gói phần mềm",
                          editions.locked_message(feature, label, level), parent=self)
        up = box.addButton("Nhập mã nâng cấp…", QMessageBox.AcceptRole)
        box.addButton("Đóng", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is up:
            self.show_license()
            return editions.allowed(feature, self.edition_level())
        return False

    def apply_edition_ui(self):
        """Nút của tính năng ngoài gói: thêm ổ khóa nhỏ + ghi chú gói cần có (vẫn bấm được để xem thông báo)."""
        from . import editions
        from PySide6.QtGui import QIcon
        level = self.edition_level()
        if getattr(self, "_edition_shown", None) == level and not getattr(self, "_edition_dirty", False):
            return
        self._edition_shown, self._edition_dirty = level, False
        c = self.colors
        tl = tiles(c)
        for b, ic, cmd, primary in self.tool_buttons:
            need = editions.required(cmd)
            base = icon(ic, c["onaccent"]) if primary else tile_icon(ic, *tl[TILE_OF.get(cmd, "gray")])
            tip = b.property("base_tip")
            if tip is None:
                tip = b.toolTip() or ""
                b.setProperty("base_tip", tip)
            if need > level:
                pm = base.pixmap(64, 64)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#b8322a"))
                p.drawEllipse(40, 40, 24, 24)
                p.setBrush(QColor("#ffffff"))
                p.drawRoundedRect(46, 50, 12, 9, 2, 2)
                pen = p.pen()
                from PySide6.QtGui import QPen
                p.setPen(QPen(QColor("#ffffff"), 2.2))
                p.setBrush(Qt.NoBrush)
                p.drawArc(48, 43, 8, 11, 0, 180 * 16)
                p.setPen(pen)
                p.end()
                b.setIcon(QIcon(pm))
                b.setToolTip((tip + "\n" if tip else "") + f"🔒 Thuộc gói {editions.NAMES[need]}")
            else:
                b.setIcon(base)
                b.setToolTip(tip)
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.apply_edition(level)

    def show_license(self, reason: str = ""):
        from .ui_license import ActivateDialog
        ActivateDialog(self, reason).exec()
        self.license_status(fresh=True)
        self._update_state()

    def _finish_object_edit(self, tab):
        """Đang sửa một ảnh đã chèn mà bấm lệnh khác/lưu/đóng: trả ảnh về chỗ cũ trước."""
        pl = tab.view.placement if tab else None
        if tab is not None:
            tab.view._finish_inline()
        if pl is not None and pl.commit_outside:          # nội dung / ghi chú đang chọn: giữ thay đổi
            tab.view.commit_placement()
        elif pl is not None and pl.on_cancel:
            tab.view.cancel_placement()

    def save(self, tab: DocTab | None = None) -> bool:
        tab = tab or self.current()
        if not tab or not self.license_ok():
            return False
        self._finish_object_edit(tab)
        if not tab.doc.path:
            return self.save_as()
        if tab.doc.signature_count() and tab.doc.modified and not self._confirm_save_signed(tab):
            return False
        from .retention import keeps
        if keeps(self.settings, "versions") and self.settings.value("history/on", True) not in (False, "false"):
            try:
                from .tools import keep_version
                keep_version(tab.doc.path)            # cất bản trước khi ghi đè (lịch sử phiên bản)
            except Exception:
                pass
        try:
            tab.doc.save()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không lưu được:\n{e}")
            return False
        self._flash("Đã lưu")
        self._update_state()
        return True

    def _confirm_save_signed(self, tab) -> bool:
        st = tab.sig_state
        who = f" của {', '.join(st.names)}" if st and st.names else ""
        r = QMessageBox.warning(self, "Cảnh báo – lưu file đã ký số",
                                f"File này đã có chữ ký số{who}. Bạn đã thay đổi nội dung, nếu lưu thì chữ ký sẽ báo "
                                "KHÔNG HỢP LỆ (“tài liệu đã bị sửa sau khi ký”).\n\nVẫn lưu?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def save_as(self) -> bool:
        tab = self.current()
        if not tab or not self.license_ok():
            return False
        self._finish_object_edit(tab)
        if tab.doc.signature_count() and tab.doc.modified and not self._confirm_save_signed(tab):
            return False
        default = tab.doc.path or os.path.join(getattr(tab, "save_dir", None) or self.settings.value("last_dir", "") or "",
                                               getattr(tab, "title", None) or tab.doc.name)
        path, _ = QFileDialog.getSaveFileName(self, "Lưu thành", default, "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            tab.doc.save(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không lưu được:\n{e}")
            return False
        self.tabs.setTabToolTip(self.tabs.currentIndex(), path)
        self._update_state()
        return True

    # ---------- lệnh ----------
    def run(self, cmd: str):
        tab = self.current()
        if cmd == "open":
            last = self.settings.value("last_dir", "")
            paths, _ = QFileDialog.getOpenFileNames(self, "Mở PDF / Word / Excel / ảnh", last, self.OPEN_FILTER)
            if paths:
                self.settings.setValue("last_dir", os.path.dirname(paths[0]))
                self.import_files(paths)
            return
        if cmd == "importopts":
            from .ui_import import ImportSettingsDialog
            ImportSettingsDialog(self, self.settings).exec()
            return
        if cmd == "license":
            self.show_license()
            return
        if cmd == "about":
            from .ui_license import AboutDialog
            AboutDialog(self).exec()
            return
        if cmd == "clearhistory":
            self.clear_history_dialog()
            return
        if cmd in ("recentclear", "recentprune"):
            self.clear_recent(missing_only=cmd == "recentprune")
            return
        if cmd not in FREE_CMDS and cmd in READY and not self.license_ok():
            return
        if not self.edition_ok(cmd, CMD_LABEL.get(cmd)):      # tính năng thuộc gói cao hơn
            return
        if cmd in NOT_SUPPORTED:
            QMessageBox.information(self, APP_NAME, NOT_SUPPORTED[cmd])
            return
        if cmd == "batchsign":
            self.batch_sign()
            return
        if cmd == "autofolder":
            self.autofolder_dialog()
            return
        if cmd == "backup":
            self.backup_menu()
            return
        if cmd not in READY:
            ph = PHASE_OF.get(cmd, 6)
            self._flash(f"Tính năng này sẽ có ở giai đoạn {ph} của lộ trình.")
            return
        if cmd in ("tray", "merge", "mergesign"):
            self.show_tray()
            return
        if cmd == "toc":
            t = self.show_tray()
            t.cb_cover.setChecked(True)
            t.cb_toc.setChecked(True)
            return
        if cmd == "trayadd":
            self.show_tray().add_files_dialog()
            return
        if cmd == "traytabs":
            self.show_tray()._add_open_tabs()
            return
        if not tab:
            self._flash("Hãy mở một file PDF trước.")
            return
        self._finish_object_edit(tab)
        if cmd == "select":
            self.stop_tool()
            self._flash("Chế độ Chọn: bấm vào hộp chữ, hình vẽ, nét vẽ, ký hiệu, ghi chú, ảnh đã thêm để di chuyển, "
                        "đổi cỡ, xoay hoặc xóa. Nháy đúp hộp chữ để sửa chữ.")
            return
        if cmd == "notes":
            self.toggle_notes_panel()
            return
        if cmd in MODIFY_CMDS and not self._writable(tab, None if cmd in SIG_SAFE_CMDS else CMD_LABEL.get(cmd, cmd)):
            return
        doc, view = tab.doc, tab.view
        pages = tab.thumbs.selected_pages() or [view.current_page()]
        if cmd == "save":
            self.save()
            return
        if cmd == "print":
            self.print_doc(tab)
            return
        if cmd == "undo" and not doc.undo():
            return
        if cmd == "redo" and not doc.redo():
            return
        if cmd == "rotate":
            doc.rotate_pages(pages, 90)
        elif cmd == "rotateleft":
            doc.rotate_pages(pages, 270)
        elif cmd == "autorotate":
            from .ui_pages import AutoRotateDialog
            sel = tab.thumbs.selected_pages()
            dlg = AutoRotateDialog(self, doc, sel if len(sel) > 1 else None)
            if dlg.exec() != AutoRotateDialog.Accepted:
                return
            plan = dlg.chosen()
            doc.set_rotations(plan)
            self._flash(f"Đã xoay {len(plan)} trang: {format_ranges(sorted(plan))}. Ctrl+Z để hoàn tác.")
        elif cmd == "split":
            self.split_dialog(tab, pages)
            return
        elif cmd == "resize":
            from .pagetools import ResizeDialog
            dlg = ResizeDialog(self, len(pages), doc.page_count)
            if dlg.exec() != ResizeDialog.Accepted:
                return
            v = dlg.values()
            targets = list(range(doc.page_count)) if v.pop("all_pages") else pages
            doc.resize_pages(targets, **v)
        elif cmd == "image":
            self.insert_image(tab)
            return
        elif cmd in ("stamp", "sigimg"):
            from .library import SIGNATURE, STAMP
            m = self.library_menu(STAMP if cmd == "stamp" else SIGNATURE)
            if m:
                btn = next((b for b, ic, c, _ in self.tool_buttons if c == cmd and b.isVisible()), None)
                m.exec(btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.cursor().pos())
            return
        elif cmd == "seam":
            self.seam_dialog(tab)
            return
        elif cmd in ("textbox", "note", "erase", "edittext"):
            self.start_tool(cmd)
            return
        elif cmd in ("symbol", "shape", "pen"):
            self.tool_menu(cmd)
            return
        elif cmd == "find":
            self.find_dialog(tab)
            return
        elif cmd == "hand":
            self.hand_write(tab)
            return
        elif cmd in ("protect", "printperm", "presets"):
            self.protect_doc(tab)
            return
        elif cmd == "password":
            self.password_doc(tab)
            return
        elif cmd == "compress":
            self.compress_doc(tab)
            return
        elif cmd == "compare":
            self.compare_doc(tab)
            return
        elif cmd == "stamptext":
            self.stamp_text_doc(tab)
            return
        elif cmd == "flow":
            self.flow_prepare(tab)
            return
        elif cmd == "batchxl":
            self.batch_excel(tab)
            return
        elif cmd == "history":
            self.history_dialog(tab)
            return
        elif cmd == "digisign":
            self.digital_sign(tab)
            return
        elif cmd == "verify":
            self.verify_doc(tab)
            return
        elif cmd == "delete":
            from .ui_pages import DeletePagesDialog
            if doc.page_count <= 1:
                self._flash("Không thể xóa hết tất cả các trang.")
                return
            dlg = DeletePagesDialog(self, doc, view.current_page(), tab.thumbs.selected_pages(),
                                    preset=getattr(self, "_delete_preset", None))
            self._delete_preset = None
            if dlg.exec() != DeletePagesDialog.Accepted:
                return
            pages = dlg.pages()
            if not pages or len(set(pages)) >= doc.page_count:
                self._flash("Không thể xóa hết tất cả các trang.")
                return
            doc.delete_pages(pages)
            self._flash(f"Đã xóa {len(set(pages))} trang: {format_ranges(sorted(set(pages)))}. Ctrl+Z để hoàn tác.")
        elif cmd == "blank":
            from .ui_pages import BlankPagesDialog
            dlg = BlankPagesDialog(self, doc.page_count, view.current_page())
            if dlg.exec() != BlankPagesDialog.Accepted:
                return
            after, count = dlg.values()
            if dlg.mode() == "every":
                n_ins = doc.insert_blank_every(dlg.every(), count, dlg.size())
                self._flash(f"Đã chèn {n_ins} trang trắng (sau mỗi {dlg.every()} trang). Ctrl+Z để hoàn tác.")
            else:
                doc.insert_blank(after, count, dlg.size())
                self._flash(f"Đã chèn {count} trang trắng ({'đầu file' if after < 0 else f'sau trang {after + 1}'}).")
        elif cmd == "colormode":
            from .colormode import MODE_LABEL, convert_document
            from .ui_import import ColorModeDialog
            dlg = ColorModeDialog(self, doc.page_count, view.current_page(), tab.thumbs.selected_pages())
            if dlg.exec() != ColorModeDialog.Accepted or not dlg.pages():
                return
            pages_c = dlg.pages()
            convert_document(doc, pages_c, dlg.mode())
            self._flash(f"Đã chuyển {len(pages_c)} trang sang {MODE_LABEL[dlg.mode()].lower()}. Ctrl+Z để hoàn tác.")
        elif cmd == "insertpdf":
            if not self.insert_pages_dialog(tab, getattr(self, "_insert_path", None)):
                return
        tab.refresh()
        self._update_state()

    def insert_pages_dialog(self, tab, path: str | None = None) -> bool:
        """17 – Chèn trang từ file PDF / Word / Excel / ảnh, trang trắng, tab đang mở, khay ghép."""
        from .office import is_office_file
        from .ui_pages import InsertPagesDialog
        doc = tab.doc

        def open_source(p):
            if is_office_file(p):
                pdf = self.convert_office(p)
                if not pdf:
                    return None
                with open(pdf, "rb") as f:
                    return PdfDocument(data=f.read())
            return PdfDocument(p)
        tabs = []
        for k in range(self.tabs.count()):
            w = self.tabs.widget(k)
            if isinstance(w, DocTab) and w is not tab:
                tabs.append((getattr(w, "title", None) or w.doc.name, w.doc))
        tray = getattr(self, "_tray", None)
        tray_items = [it for it in (tray.items if tray is not None else []) if it.checked]
        dlg = InsertPagesDialog(self, doc, tab.view.current_page(), tabs, tray_items, open_source, path)
        ok = dlg.exec() == InsertPagesDialog.Accepted
        v = dlg.values()
        file_doc = getattr(dlg, "_file_doc", None)
        try:
            if not ok or not v["pages"] or v["src"] is None:
                return False
            cur = tab.view.current_page()
            new = doc.insert_pages(v["src"], v["pages"], v["index"], v["mode"], v["every"], v["reverse"],
                                   fit_to=cur if v["fit"] else None)
            self._flash(f"Đã chèn {len(new)} trang (vị trí {format_ranges(new)}). Ctrl+Z để hoàn tác.")
            if new:
                QTimer.singleShot(0, lambda: tab.view.go_to(new[0]))
            return True
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không chèn được trang:\n{e}")
            return False
        finally:
            for d in {id(x): x for x in (v["src"] if v["own"] else None, file_doc) if x is not None}.values():
                if all(d is not t[1] for t in tabs):
                    try:
                        d.close()
                    except Exception:
                        pass

    def insert_files_at(self, tab, paths: list[str], at: int) -> int:
        """17e – kéo file (PDF, Word, Excel, ảnh) vào cột ảnh thu nhỏ: chèn tất cả trang vào đúng chỗ thả."""
        from .ui_import import openable
        paths = [os.path.abspath(p) for p in paths if openable(p) and os.path.exists(p)]
        if not paths or not self._writable(tab, "Chèn trang"):
            return 0
        doc = tab.doc
        parts = []
        for p in paths:
            d = self._load_any(p)
            if d is not None:
                parts.append(d)
        if not parts:
            return 0
        src = parts[0]
        if len(parts) > 1:                             # nhiều file -> ghép tạm theo thứ tự thả, chèn một lần
            for d in parts[1:]:
                src.pdf.import_pages(d.pdf)
                src._drop_pages()
        try:
            new = doc.insert_pages(src, None, at)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không chèn được trang:\n{e}")
            return 0
        finally:
            for d in parts:
                d.close()
        tab.refresh()
        self._update_state()
        self._flash(f"Đã chèn {len(new)} trang từ {len(paths)} file vào vị trí {at + 1}. Ctrl+Z để hoàn tác.")
        return len(new)

    def rotate_page_quick(self, page: int, angle: int):
        """Nút ⟲ ⟳ trên ảnh thu nhỏ (hiện khi di chuột qua)."""
        tab = self.current()
        if not tab or not self._writable(tab, "Xoay trang"):
            return
        tab.doc.rotate_pages([page], angle)
        tab.refresh()
        self._update_state()
        self._flash(f"Đã xoay trang {page + 1} {'phải' if angle == 90 else 'trái'} 90°. Ctrl+Z để hoàn tác.")

    def delete_selected_pages(self):
        """Phím Delete trên cột ảnh thu nhỏ: mở hộp Xóa trang, chọn sẵn các trang đang chọn."""
        self._delete_preset = "selected"
        self.run("delete")

    # ---------- giai đoạn 2: trang, ảnh, khay ghép ----------
    def move_pages(self, rows: list, dest: int):
        tab = self.current()
        if not tab or not self._writable(tab, "Sắp xếp lại trang"):
            if tab:
                tab.refresh()
            return
        tab.doc.move_pages(rows, dest)
        tab.refresh()
        tab.thumbs.clearSelection()
        for k in range(len(rows)):
            tab.thumbs.item(dest + k).setSelected(True)
        self._update_state()

    def page_menu(self, global_pos):
        m = self.build_page_menu()
        if m:
            m.exec(global_pos)

    def build_page_menu(self):
        from PySide6.QtWidgets import QMenu
        tab = self.current()
        if not tab:
            return None
        m = QMenu(self)
        c = self.colors["text"]
        for cmd, label, ic in (("rotate", "Xoay phải 90°", "rotate"), ("rotateleft", "Xoay trái 90°", "rotate"),
                               ("autorotate", "Tự xoay đúng hướng", "autorotate"), (None, None, None),
                               ("blank", "Chèn trang trắng…", "page"),
                               ("insertpdf", "Chèn trang từ file PDF…", "pageadd"),
                               ("split", "Trích / tách trang…", "split"), ("resize", "Đổi kích thước…", "resize"),
                               (None, None, None), ("delete", "Xóa trang…", "delete")):
            if cmd is None:
                m.addSeparator()
                continue
            m.addAction(icon(ic, c), label, lambda cmd=cmd: self.run(cmd))
        if tab.doc.path:
            m.addSeparator()
            m.addAction(icon("merge", c), "Thêm file này vào khay ghép",
                        lambda: self.show_tray().add_paths([tab.doc.path]))
        return m

    def split_dialog(self, tab: "DocTab", pages: list):
        from .pagetools import SplitDialog, write_split
        if tab.doc.signature_count() and QMessageBox.question(
                self, APP_NAME, "File này có chữ ký số. Các file tách ra là file mới, KHÔNG còn chữ ký số (người nhận "
                "không kiểm tra được chữ ký gốc). File gốc vẫn giữ nguyên.\n\nTiếp tục tách?") != QMessageBox.Yes:
            return
        dlg = SplitDialog(self, tab.doc, pages)
        if dlg.exec() != SplitDialog.Accepted:
            return
        try:
            files = write_split(tab.doc, dlg.groups(), dlg.ed_folder.text(), dlg.ed_base.text() or "tach")
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không tách được:\n{e}")
            return
        self._flash(f"Đã tạo {len(files)} file trong {dlg.ed_folder.text()}")

    def insert_image(self, tab: "DocTab", path: str | None = None):
        from PySide6.QtGui import QImage
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh", self.settings.value("img_dir", ""),
                                                  "Ảnh (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
            if not path:
                return
            self.settings.setValue("img_dir", os.path.dirname(path))
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "Không đọc được ảnh.")
            return
        is_jpeg = path.lower().endswith((".jpg", ".jpeg"))
        width_pt = None
        try:
            from .imaging import scan_dpi
            with open(path, "rb") as f:
                dpi = scan_dpi(f.read())
            if dpi:                               # ảnh scan: chèn đúng kích thước thật (vd. 600 dpi)
                width_pt = img.width() / dpi * 72
        except Exception:
            pass

        def commit(page, rect, src, angle, layer, scope):
            doc = tab.doc
            pages = self._scope_pages(tab, page, scope)
            o = self.img_opts
            # giới hạn 300 dpi theo kích thước đặt -> file không phình to
            max_w = max(1, int(self._unrotated_width_pt(rect, src, angle) / 72 * 300))
            if len(pages) == 1 and is_jpeg and o.opacity >= 100 and not o.remove_bg and img.width() <= max_w * 1.2:
                with open(path, "rb") as f:
                    doc.insert_image(page, rect, b"", 0, 0, jpeg=f.read(), angle=angle, layer=layer)
            else:
                if src.width() > max_w:
                    src = src.scaledToWidth(max_w, Qt.SmoothTransformation)
                if len(pages) == 1 and not img.hasAlphaChannel() and o.opacity >= 100 and not o.remove_bg:
                    # ảnh không trong suốt -> lưu JPEG chất lượng cao, nhỏ hơn nhiều
                    from PySide6.QtCore import QBuffer, QIODevice
                    buf = QBuffer()
                    buf.open(QIODevice.WriteOnly)
                    src.save(buf, "JPG", 90)
                    doc.insert_image(page, rect, b"", 0, 0, jpeg=bytes(buf.data()), angle=angle, layer=layer)
                else:
                    argb = src.convertToFormat(QImage.Format_ARGB32)
                    doc.stamp_pages(pages, rect, bytes(argb.constBits()), argb.width(), argb.height(),
                                    argb.bytesPerLine(), angle=angle, layer=layer)
            tab.refresh()
            self._update_state()
            self._flash(self._layer_note(doc, page, layer) or
                        (f"Đã chèn ảnh lên {len(pages)} trang. Ctrl+Z để hoàn tác." if len(pages) > 1 else
                         "Đã chèn ảnh. Bấm vào ảnh để sửa, Ctrl+Z để hoàn tác."))

        self.begin_image_placement(tab, img, commit, width_pt=width_pt,
                                   label="Ảnh (kích thước thật)" if width_pt else "Ảnh", scope=True, remove_bg=True)

    # ---------- tùy chọn ảnh: lớp, độ đậm, xoay, xóa nền, nhiều trang ----------
    @staticmethod
    def _unrotated_width_pt(rect, src, angle) -> float:
        import math
        a = math.radians(angle or 0)
        bw = src.width() * abs(math.cos(a)) + src.height() * abs(math.sin(a))
        return (rect[2] - rect[0]) * src.width() / max(1.0, bw)

    @staticmethod
    def _scope_pages(tab, page: int, scope: str) -> list[int]:
        doc = tab.doc
        n = doc.page_count
        if scope == "all":
            pages = list(range(n))
        elif scope == "selected":
            pages = sorted(set(tab.thumbs.selected_pages()) | {page})
        elif scope == "but_last":                                # 4d: ký nháy mọi trang, trang cuối ký chính thức
            pages = list(range(max(1, n - 1)))
        elif scope == "odd":
            pages = list(range(0, n, 2))
        elif scope == "even":
            pages = list(range(1, n, 2))
        else:
            pages = [page]
        if page not in pages:
            return pages or [page]
        return [page] + [p for p in pages if p != page]         # trang đặt khung làm chuẩn vị trí

    @staticmethod
    def _layer_note(doc, page: int, layer: str) -> str:
        if layer == "behind" and doc.layer_for(page, "behind") != "behind":
            why = "file đã có chữ ký số" if doc.signature_count() else "trang scan (cả trang là một ảnh)"
            return f"Đã đặt ảnh kiểu “Hòa trộn” vì {why} – chữ vẫn hiện xuyên qua như chìm dưới chữ."
        return ""

    def _img_preview(self):
        from .ui_edit import process_image
        ctx = self._img_ctx
        o = self.img_opts
        return process_image(ctx["preview_base"], o.opacity, o.remove_bg)   # xoay: khung đặt tự xoay (núm tròn)

    def begin_image_placement(self, tab, img, commit, width_pt=None, label: str = "", page=None, center=None,
                              scope: bool = True, remove_bg: bool = False):
        """Đặt ảnh lên trang kèm bảng Tùy chọn ảnh. commit(page, rect, ảnh_đã_xử_lý, góc, lớp, phạm_vi)."""
        i = tab.view.current_page() if page is None else page
        if width_pt is None:                       # cỡ mặc định như trước (40% bề rộng trang, tối đa 80% chiều cao)
            pw, ph = tab.doc.page_size_pt(i)
            ratio = img.height() / max(1, img.width())
            width_pt = min(pw * 0.4, img.width() * 72 / 150)
            if width_pt * ratio > ph * 0.8:
                width_pt = ph * 0.8 / ratio
        base = img if img.width() <= 900 else img.scaledToWidth(900, Qt.SmoothTransformation)
        self._img_ctx = {"tab": tab, "base": img, "preview_base": base}
        self.img_opts.show_for(label or "Tùy chọn ảnh", scope=scope, remove_bg=remove_bg)
        o = self.img_opts

        def wrapped(pg, rect, angle=0.0):
            from .ui_edit import process_image
            from .viewer import rotated_bbox
            src = process_image(img, o.opacity, o.remove_bg)
            ang = float(angle or 0) % 360
            if ang > 180:
                ang -= 360
            # khung đặt là khung CHƯA xoay -> quy về khung bao của ảnh đã xoay như các hàm chèn cần
            commit(pg, rotated_bbox(rect, ang), src, ang, o.layer, o.scope)
        tab.view.begin_placement(self._img_preview(), wrapped, width_pt=width_pt, label=label, page=i,
                                 center_pt=center)
        pl = tab.view.placement
        if pl is not None:                         # xoay trực tiếp: kéo núm tròn phía trên khung (như Word)
            pl.rotatable = True
            pl.angle = o.angle % 360
            pl.on_change = lambda p: self.img_opts.set_angle(p.angle)

    def _img_opts_changed(self):
        ctx = self._img_ctx
        if not ctx:
            return
        tab = ctx["tab"]
        pl = tab.view.placement
        if pl is None:
            return
        if pl.rotatable:
            pl.angle = self.img_opts.angle % 360
        if ctx.get("edit"):                        # ảnh đã chèn: giữ đúng khung (ảnh có thể bị kéo méo tỉ lệ)
            tab.view.replace_placement_image(self._img_preview(), rect_pt=pl.rect)
        else:
            tab.view.replace_placement_image(self._img_preview())

    def _placement_ended(self):
        self._img_ctx = None
        self.img_opts.setVisible(False)

    def show_tray(self):
        from .tray import TrayDialog
        if getattr(self, "_tray", None) is None:
            self._tray = TrayDialog(self, self.settings, self.colors)
            self._tray.mergedReady.connect(self._merged)
        self._tray.apply_edition(self.edition_level())
        self._tray.show()
        self._tray.raise_()
        self._tray.activateWindow()
        return self._tray

    def _merged(self, doc, for_sign: bool):
        import time as _t
        saved = bool(doc.path)
        tab = self.add_document(doc, None if saved else _t.strftime("Ghep_%Y%m%d_%H%M.pdf"))
        if saved:
            tab.doc.modified = False
            self.add_recent(doc.path)
        self._update_state()
        where = f" Đã lưu: {doc.path}" if saved else " Nhớ Lưu (Ctrl+S)."
        if for_sign:
            self.mode_group.button(3).click()
            self._flash("Đã ghép." + where + (" Chọn chứng thư để ký số." if saved else ""))
            if self.auto_sign:
                QTimer.singleShot(200, self, lambda: self.current() is tab and self.digital_sign(tab))
        else:
            self._flash(f"Đã ghép {doc.page_count} trang." + where)
        return tab

    def start_spool(self, root: str | None = None):
        from .spool import SpoolWatcher
        self.spool = SpoolWatcher(root, self)
        if sys.platform == "darwin" and root is None:    # macOS: "máy in ảo" = mục trong nút PDF ▾ khi In
            try:
                from .macintegration import install_pdf_services
                install_pdf_services(self.spool.root)
            except Exception:
                pass
        self.spool.fileArrived.connect(self._spool_file)

    @staticmethod
    def spool_page_report(path: str) -> tuple[str, bool]:
        """Tóm tắt khổ giấy của bản in + cảnh báo khi nghi bị đổi khổ (Letter thay vì A4)."""
        try:
            d = PdfDocument(path)
        except Exception:
            return "", False
        try:
            sizes = {}
            for i in range(d.page_count):
                info = d.page_info(i)
                key = f"{info.paper} {'ngang' if info.landscape else 'dọc'}"
                sizes[key] = sizes.get(key, 0) + 1
        finally:
            d.close()
        text = ", ".join(f"{k}: {n} trang" for k, n in sizes.items())
        return text, any(k.startswith("Letter") for k in sizes)

    def _spool_file(self, kind: str, path: str):
        if not self.edition_ok("spool"):
            return
        report, letter = self.spool_page_report(path)
        if letter:
            QMessageBox.warning(self, APP_NAME, "Bản in vừa nhận có trang khổ Letter (Mỹ), không phải A4:\n"
                                f"{report}\n\nNếu văn bản gốc là A4: trong Word chọn In → Thuộc tính máy in (Printer "
                                "Properties) → khổ giấy A4, và mục \"Co giãn theo khổ giấy\" để \"Không co giãn\", rồi in "
                                "lại. Hoặc dùng Word → Lưu thành PDF.")
        if kind == "tray":
            self.show_tray().add_paths([path])
            self._flash("Đã nhận bản in vào khay ghép" + (f" ({report})." if report else "."))
        elif kind == "open":                 # 1.0.22: máy in "PDF Ky so - Mo file": chỉ mở thành PDF, không ký
            self.open_files([path])
            self.raise_()
            self.activateWindow()
            tab = self.current()
            if tab:
                tab.from_spool = True
            self._flash("Đã mở bản in thành PDF" + (f" ({report})" if report else "") +
                        " – bấm Lưu (Ctrl+S) để chọn nơi lưu.")
        else:
            self.open_files([path])
            self.mode_group.button(3).click()
            self.raise_()
            self.activateWindow()
            tab = self.current()
            if report:
                self._flash(f"Đã nhận bản in: {report}")
            if tab:
                tab.from_spool = True
                if self.auto_sign:
                    QTimer.singleShot(300, self, lambda: self.current() is tab and self.digital_sign(tab))

    # ---------- giai đoạn 3: con dấu, chữ ký ảnh ----------
    def _init_library(self):
        if self.library is not None:
            return
        from .library import Library
        from .ui_library import LibraryPanel
        self.library, msg = Library.open_safe(self.library_path)
        if msg:
            QMessageBox.warning(self, APP_NAME, msg)
        self.lib_panel = LibraryPanel(self.library, self.colors)
        self.lib_panel.itemActivated.connect(lambda iid: self.place_library_item(iid))
        self.side.layout().insertWidget(self.side.layout().indexOf(self.side.cert_card) + 1, self.lib_panel)
        from .ui_edit import fit_side_panel
        fit_side_panel(self.lib_panel)

    def place_library_item(self, item_id: str, page: int | None = None, x_pt: float | None = None,
                           y_pt: float | None = None):
        from .ui_library import qimage_from_png, unlock_if_needed
        tab = self.current()
        if not tab:
            self._flash("Hãy mở một file PDF trước.")
            return
        if not self.edition_ok("library", "Đóng dấu / chữ ký từ thư viện"):
            return
        self._init_library()
        if not unlock_if_needed(self, self.library):
            return
        if not self._writable(tab, "Đóng dấu / chèn chữ ký ảnh"):
            return
        it = self.library.get(item_id)
        from .library import HANDSET
        if it.kind == HANDSET:                         # bộ chữ tay: mở hộp thoại viết chữ tay
            self.hand_write(tab, it.id)
            return
        img = qimage_from_png(self.library.image(item_id))
        center = (x_pt, y_pt) if x_pt is not None else None
        scope = self.lib_panel.scope_value()

        def commit(pg, rect, src, angle, layer, _scope):
            doc = tab.doc
            pages = self._scope_pages(tab, pg, scope)
            max_px = max(1, int(self._unrotated_width_pt(rect, src, angle) / 72 * 600))   # đủ nét khi in 600 dpi
            if src.width() > max_px:
                src = src.scaledToWidth(max_px, Qt.SmoothTransformation)
            argb = src.convertToFormat(src.Format.Format_ARGB32)
            doc.stamp_pages(pages, rect, bytes(argb.constBits()), argb.width(), argb.height(), argb.bytesPerLine(),
                            angle=angle, layer=layer)
            from .library import log_usage
            try:
                log_usage(it, doc.path or doc.name, sorted(pages))
            except OSError:
                pass
            tab.refresh()
            self._update_state()
            self._flash(self._layer_note(doc, pg, layer) or
                        f"Đã đóng “{it.name}” lên {len(pages)} trang. Ctrl+Z để hoàn tác.")

        self.begin_image_placement(tab, img, commit, width_pt=it.width_mm * 72 / 25.4, label=it.name,
                                   page=page, center=center, scope=False)

    def library_menu(self, kind: str):
        from PySide6.QtWidgets import QMenu
        from .ui_library import unlock_if_needed
        self._init_library()
        if not self.library or not unlock_if_needed(self, self.library):
            return None
        m = QMenu(self)
        items = self.library.of_kind(kind)
        for it in items:
            m.addAction(it.name, lambda iid=it.id: self.place_library_item(iid))
        if items:
            m.addSeparator()
        m.addAction(icon("plus", self.colors["text"]), "Thêm ảnh vào thư viện…", self.lib_panel.import_image)
        return m

    def seam_dialog(self, tab: "DocTab"):
        from .library import STAMP
        from .ui_library import SeamDialog, qimage_from_png, unlock_if_needed
        self._init_library()
        if not unlock_if_needed(self, self.library):
            return
        if not self.library.of_kind(STAMP):
            QMessageBox.information(self, APP_NAME, "Thư viện chưa có con dấu. Hãy thêm ảnh con dấu trước.")
            self.lib_panel.import_image()
            return
        if tab.doc.page_count < 2:
            self._flash("Đóng giáp lai cần tài liệu từ 2 trang trở lên.")
            return
        dlg = SeamDialog(self, self.library, tab.doc.page_count, tab.thumbs.selected_pages())
        if dlg.exec() != SeamDialog.Accepted:
            return
        v = dlg.values()
        pages = list(range(tab.doc.page_count)) if v["scope"] == "all" else tab.thumbs.selected_pages()
        img = qimage_from_png(self.library.image(v["item_id"]))
        max_px = int(v["diameter_pt"] / 72 * 600)
        if img.width() > max_px:
            img = img.scaledToWidth(max_px, Qt.SmoothTransformation)
        diameter = v["diameter_pt"]
        if v.get("angle"):                                 # dấu đóng tay hơi nghiêng: xoay cả con dấu rồi mới chia
            from PySide6.QtGui import QTransform
            w0 = img.width()
            img = img.convertToFormat(img.Format.Format_ARGB32).transformed(QTransform().rotate(v["angle"]),
                                                                           Qt.SmoothTransformation)
            diameter = diameter * img.width() / max(1, w0)
        argb = img.convertToFormat(img.Format.Format_ARGB32)
        tab.doc.seam_stamp(pages, bytes(argb.constBits()), argb.width(), argb.height(), argb.bytesPerLine(),
                           diameter, v["center_y"], v["edge"], v["reverse"], natural=v.get("natural", False),
                           group_size=v.get("group_size", 0), margin_pt=v.get("margin_pt", 0.0))
        from .library import log_usage
        try:
            log_usage(self.library.get(v["item_id"]), tab.doc.path or tab.doc.name, pages, "giáp lai")
        except OSError:
            pass
        tab.refresh()
        self._update_state()
        self._flash(f"Đã đóng giáp lai qua {len(pages)} trang.")

    # ---------- giai đoạn 5 + đợt 2: chỉnh sửa nội dung ----------
    TOOL_INFO = {
        "textbox": ("Hộp chữ", "Kéo một khung trên trang (hoặc bấm) rồi gõ chữ. Chữ thật, tìm kiếm được. "
                    "Sau này bấm vào để di chuyển, nháy đúp để sửa chữ.", False, True),
        "note": ("Ghi chú", "Bấm vào chỗ cần ghi chú. Bấm lại vào biểu tượng để sửa / kéo để dời.", False, False),
        "pen": ("Vẽ tay", "Giữ chuột trái và vẽ. Nét vector mềm, in sắc nét. Chọn loại bút, màu, độ dày bên dưới.",
                True, False),
        "erase": ("Tẩy vùng", "Khoanh vùng cần xóa. Vùng đỏ là phần sẽ tẩy – chỉnh khung rồi Enter hoặc bấm ra ngoài "
                  "để tẩy (Esc: bỏ). Cục tẩy cọ: tẩy ngay.",
                  False, False),
        "edittext": ("Sửa chữ", "Bấm vào chữ cần sửa rồi gõ ngay trên trang (Ctrl+Enter hoặc bấm ra ngoài: xong, Esc: "
                     "bỏ). Chọn sửa mảnh chữ / cả dòng / cả đoạn, đậm, nghiêng, cỡ, màu ở dưới. Trang scan: kéo khung "
                     "quanh chữ cần sửa.", False, True),
        "scanedit": ("Sửa chữ trên trang scan", "Kéo khung quanh chữ cần sửa: phần mềm phủ màu nền giấy rồi cho gõ chữ "
                     "mới đúng chỗ, cùng cỡ.", False, False),
        "rect": ("Hình chữ nhật", "Kéo để vẽ. Giữ Shift: hình vuông.", True, False),
        "ellipse": ("Hình elip", "Kéo để vẽ. Giữ Shift: hình tròn.", True, False),
        "line": ("Đường thẳng", "Kéo để vẽ. Giữ Shift: bắt góc 45°.", True, False),
        "arrow": ("Mũi tên", "Kéo từ gốc tới đầu mũi tên. Giữ Shift: bắt góc 45°.", True, False),
        "highlight": ("Bút dạ quang", "Kéo phủ lên dòng chữ cần đánh dấu.", False, False),
        "inkerase": ("Tẩy nét vẽ tay", "Kéo qua nét vẽ tay cần xóa – chỉ nét chạm vào bị gỡ, nét khác giữ nguyên.",
                     False, True),
        "check": ("Dấu tích ✓", "Bấm vào chỗ cần đánh dấu.", True, True), "cross": ("Dấu nhân ✗", "Bấm để đặt.", True, True),
        "dot": ("Chấm tròn ●", "Bấm để đặt.", False, True), "circle": ("Vòng tròn ○", "Bấm để đặt.", True, True),
        "box": ("Ô trống ☐", "Bấm để đặt.", True, True), "boxcheck": ("Ô đã tích ☑", "Bấm để đặt.", True, True),
    }
    OLD_SHAPES = {"rect": "rect", "ellipse": "ellipse", "line": "line", "arrow": "arrow", "highlight": "highlight"}
    SYMBOL_KINDS = ("check", "cross", "dot", "circle", "box", "boxcheck")

    def start_tool(self, kind: str):
        from . import items
        from .viewer import Tool
        tab = self.current()
        if not tab:
            self._flash("Hãy mở một file PDF trước.")
            return
        if tab.view.placement is not None:
            tab.view.commit_placement() if tab.view.placement.commit_outside else tab.view.cancel_placement()
        shape, pen = "", ""
        if kind.startswith("shape:"):
            shape = kind[6:]
            if shape == "freeform":
                kind, shape = "pen", ""
            elif shape in ("polyline", "polygon"):
                kind = shape
            elif shape in self.OLD_SHAPES and shape not in ("line", "arrow"):
                kind = shape
            else:
                kind = "shape"
        if kind.startswith("pen:"):
            kind, pen = "pen", kind[4:]
        o = self.tool_opts
        if kind == "shape" or kind in ("polyline", "polygon"):
            label = items.SHAPE_LABEL.get(shape, "Hình vẽ")
            if kind in ("polyline", "polygon"):
                hint = "Bấm từng điểm; nháy đúp hoặc Enter để kết thúc, Backspace bỏ điểm vừa bấm. Giữ Shift: góc 45°."
            elif shape in items.LINE_SHAPES:
                hint = "Kéo từ điểm đầu tới điểm cuối. Giữ Shift: bắt góc 45°."
            else:
                hint = "Kéo để vẽ (bấm: cỡ mặc định). Giữ Shift: giữ đúng tỉ lệ (vuông / tròn)."
            title = label
        elif kind in self.TOOL_INFO:
            title, hint = self.TOOL_INFO[kind][:2]
        else:
            return
        tool = Tool("ink" if kind == "pen" else kind,  # noqa: E501
                    lambda pg, data, k=kind: self._tool_done(k, pg, data), o.color, o.width,
                    sticky=True)
        tool.shape = shape or (kind if kind in ("polyline", "polygon") else "")
        width_flag, size_flag = (self.TOOL_INFO.get(kind, ("", "", True, False))[2:4])
        line_like = kind in ("line", "arrow", "polyline") or shape in items.LINE_SHAPES
        if kind in ("shape", "rect", "ellipse", "line", "arrow", "polyline", "polygon"):
            rows = {"colors", "width", "opacity", "dash", "grid", "styles"} | ({"heads"} if line_like else
                                                                               {"fill", "shadow", "radius"})
        elif kind == "highlight":
            rows = {"colors", "opacity"}
        elif kind in self.SYMBOL_KINDS:
            rows = {"colors", "width", "size"} if width_flag else {"colors", "size"}
        elif kind == "pen":
            rows = {"pen", "colors", "width", "opacity", "smooth"}
        elif kind == "inkerase":
            rows = {"size"}
        elif kind == "erase":
            rows = {"erase"}
        elif kind == "textbox":
            rows = {"colors", "size"}
        elif kind == "edittext":
            rows = {"editscope", "fmt", "colors", "size"}
        else:
            rows = set()
        o.show_for(title, hint + " Esc để tắt.", width_flag, size_flag, rows=rows)
        if pen:
            o.cb_pen.setCurrentIndex(max(0, o.cb_pen.findData(pen)))
        if kind in ("line", "arrow") or shape in ("line", "arrow", "darrow", "curve", "carrow"):
            o.cb_heads.blockSignals(True)
            o.cb_heads.setCurrentIndex(max(0, o.cb_heads.findData(items.default_heads(shape or kind))))
            o.cb_heads.blockSignals(False)
        if size_flag:
            o.lbl_size.setText("Cỡ ký hiệu:" if kind in self.SYMBOL_KINDS else
                               ("Cỡ cục tẩy:" if kind == "inkerase" else
                                "Cỡ chữ:"))
        if kind == "edittext":
            o._quiet = True
            o.sp_size.setMinimum(0)
            o.sp_size.setValue(0)
            o.cb_family.setCurrentIndex(0)
            o.btn_bold.setChecked(False)
            o.btn_italic.setChecked(False)
            o._edit_color = None
            self._edit_color_seen = o.color
            o._quiet = False
        else:
            o.sp_size.setMinimum(4)
        tab.view.set_tool(tool)
        self._sync_tool(tab)

    def _sync_tool(self, tab):
        """Đưa tùy chọn trên bảng vào công cụ đang bật (màu, nét, bút, tẩy, lưới)."""
        t = tab.view.tool
        o = self.tool_opts
        tab.view.snap_grid = o.grid_pt if o.rows["grid"].isVisibleTo(o) else 0.0
        tab.view.show_grid = bool(tab.view.snap_grid and o.chk_show_grid.isChecked())
        if not t:
            tab.view.canvas.update()
            return
        t.color = o.color
        t.width = o.width
        t.pen = o.pen if t.kind == "ink" else ""
        st = o.style()
        t.fill = st["fill"]
        e = o.erase_opts()
        t.erase_shape, t.size, t.magnifier = e["shape"], e["size"], e["magnifier"]
        if t.kind == "inkerase":
            t.size = o.size
        tab.view.canvas.update()

    def stop_tool(self):
        tab = self.current()
        if tab and tab.view.tool:
            tab.view.set_tool(None)
        if tab:
            tab.view.snap_grid = 0.0
            tab.view.show_grid = False
            tab.view.canvas.update()
        self.tool_opts.setVisible(False)

    def _opts_close(self):
        tab = self.current()
        if tab and tab.view._inline is not None:          # đang gõ sửa chữ: ✕ = xong (giữ chữ đã gõ)
            tab.view._finish_inline(True)
            return
        if getattr(self, "_sel", None) and tab and tab.view.placement is not None:
            tab.view.commit_placement()
            return
        self.stop_tool()

    def _tool_changed(self, kind: str):
        if not kind and not getattr(self, "_sel", None):
            self.tool_opts.setVisible(False)
            tab = self.current()
            if tab:
                tab.view.snap_grid = 0.0
                tab.view.show_grid = False

    def _tool_opts_changed(self):
        tab = self.current()
        if not tab:
            return
        if tab.view.tool is not None and tab.view.tool.kind == "edittext":
            # chỉ đổi màu chữ khi người dùng thật sự chọn màu khác (đổi cỡ / đậm không được tô đỏ chữ)
            if self.tool_opts.color != getattr(self, "_edit_color_seen", None):
                self.tool_opts._edit_color = self.tool_opts.color
                self._edit_color_seen = self.tool_opts.color
        if tab.view._inline is not None:                 # đang gõ sửa chữ: xem ngay kiểu chữ mới
            self._restyle_inline(tab)
            return
        if getattr(self, "_sel", None) and tab.view.placement is not None:
            if not self._sel.get("group"):
                self._restyle_selection()
            return
        self._sync_tool(tab)

    def tool_menu(self, which: str):
        from PySide6.QtWidgets import QMenu, QWidgetAction
        from .items import PENS
        from .ui_edit import SHAPES, SYMBOLS, ShapeGallery, pen_icon
        m = QMenu(self)
        if which == "shape":
            wa = QWidgetAction(m)
            gal = ShapeGallery(m)
            gal.picked.connect(lambda k: (m.close(), self.start_tool("shape:" + k)))
            wa.setDefaultWidget(gal)
            m.addAction(wa)
            self._shape_gallery = gal
        elif which == "pen":
            for kind, label in PENS:
                m.addAction(pen_icon(kind), label, lambda k=kind: self.start_tool("pen:" + k))
            m.addSeparator()
            m.addAction(icon("erase", self.colors["text"]), "Cục tẩy nét vẽ tay", lambda: self.start_tool("inkerase"))
        else:
            for kind, label in (SYMBOLS if which == "symbol" else SHAPES):
                m.addAction(label, lambda k=kind: self.start_tool(k))
        self._last_menu = m
        btn = next((b for b, ic, c, _ in self.tool_buttons if c == which and b.isVisible()), None)
        m.popup(btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.cursor().pos())
        return m

    def _tool_done(self, kind: str, page: int, data):
        from . import editing, items
        tab = self.current()
        if not tab:
            return
        doc = tab.doc
        o = self.tool_opts
        t = tab.view.tool
        try:
            st = o.style()
            if kind in ("shape", "rect", "ellipse", "line", "arrow", "polyline", "polygon", "highlight"):
                shape = (t.shape if t is not None and t.shape else self.OLD_SHAPES.get(kind, kind))
                if kind == "highlight":
                    spec = items.shape_spec("highlight", data, {"fill": o.color if o.color.lower() not in (
                        "#d32f2f", "#1b1b1b", "#0d47a1") else "#ffe600", "opacity": o.opacity})
                elif kind in ("polyline", "polygon"):
                    spec = items.shape_spec(shape, items.bbox(data), st, data) if shape == "polygon" else \
                        items.line_spec("polyline", None, None, st, data)
                elif shape in items.LINE_SHAPES:
                    x0, y0, x1, y1 = data
                    spec = items.line_spec(shape, (x0, y0), (x1, y1), st)
                else:
                    spec = items.shape_spec(shape, data, st)
                items.add_item(doc, page, spec)
            elif kind in self.SYMBOL_KINDS:
                x, y = data
                h = o.size / 2
                items.add_item(doc, page, items.shape_spec(kind, (x - h, y - h, x + h, y + h),
                                                           {"stroke": o.color, "width": o.width}))
            elif kind == "pen":
                samples = list(getattr(t, "last_samples", None) or [])
                if len(samples) < len(data) - 1 or not samples:
                    samples = [(p[0], p[1], k * 0.01, None) for k, p in enumerate(data)]
                else:
                    samples.append((data[-1][0], data[-1][1], samples[-1][2] + 0.01, samples[-1][3]))
                pen = o.cb_pen.currentData() or "ball"
                rec = items.recognize(list(data)) if o.chk_recognize.isChecked() and pen != "highlighter" else None
                if rec:                                     # 15e: tự nắn thành hình chuẩn
                    shape, geo = rec
                    st2 = {"stroke": o.color, "width": o.width, "opacity": o.opacity}
                    if shape in ("line", "arrow"):
                        spec = items.line_spec(shape, geo[0], geo[1], st2)
                    else:
                        spec = items.shape_spec(shape, geo, st2)
                    items.add_item(doc, page, spec)
                    self._flash(f"Đã nắn thành {items.SHAPE_LABEL.get(shape, shape).lower()}. Ctrl+Z để hoàn tác.")
                else:
                    sp = items.ink_spec([samples], {"pen": pen, "stroke": o.color, "width": o.width,
                                                    "opacity": o.opacity})
                    sp["smooth"] = o.cb_smooth.currentData()
                    items.add_item(doc, page, sp)
            elif kind == "inkerase":
                n = items.erase_strokes(doc, page, list(data), max(2.0, o.size / 2))
                self._flash(f"Đã xóa {n} nét vẽ tay." if n else "Không chạm nét vẽ tay nào.")
            elif kind == "erase":
                e = o.erase_opts()
                shape = e["shape"] if t is None else t.erase_shape
                if shape in ("lasso", "brush"):
                    if len(data) < 2 and shape == "lasso":
                        return
                    region = {"shape": shape, "pts": list(data), "size": e["size"]}
                else:
                    region = {"shape": shape, "rect": tuple(data)}
                if e["preview"] and shape != "brush":   # cục tẩy cọ: tẩy ngay như cục tẩy thật (Ctrl+Z hoàn tác)
                    self._erase_preview(tab, page, region, e)
                    return
                self._apply_erase(tab, page, region, e)
            elif kind == "textbox":
                if not self._text_box(tab, page, data):
                    return
            elif kind == "note":
                from .notes import add_note
                from .ui_edit import NoteDialog
                dlg = NoteDialog(self, self.settings.value("note/author", "") or os.environ.get("USERNAME", ""),
                                 settings=self.settings)
                if dlg.exec() != NoteDialog.Accepted:
                    return
                v = dlg.values()
                self.settings.setValue("note/author", v["author"])
                self.settings.setValue("note/color", v["color"])
                self.settings.setValue("note/icon", v["icon"])
                add_note(doc, page, data[0], data[1], v["text"], v["author"], v["color"], v["icon"], v["opacity"])
            elif kind == "edittext":
                if not self._edit_text(tab, page, *data):
                    return
            elif kind == "scanedit":
                self._scan_edit(tab, page, data)
                return
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không thực hiện được:\n{e}")
            return
        tab.refresh()
        self._update_state()

    # ---------- tẩy vùng: xem trước, chỉnh khung, áp dụng ----------
    def _region_image(self, region, bounds, scale=3.0):
        from PySide6.QtGui import QPainterPath, QPen
        from .editing import region_polygon
        x0, y0, x1, y1 = bounds
        w, h = max(1, int((x1 - x0) * scale)), max(1, int((y1 - y0) * scale))
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        fill = QColor(229, 57, 53, 80)
        edge = QPen(QColor(229, 57, 53), 1.5, Qt.DashLine)

        def q(pt):
            return QPointF((pt[0] - x0) * scale, (pt[1] - y0) * scale)
        if region["shape"] == "brush":
            pts = region["pts"]
            path = QPainterPath(q(pts[0]))
            for pt in pts[1:]:
                path.lineTo(q(pt))
            p.setPen(QPen(fill, max(2.0, region.get("size", 12) * scale), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        else:
            poly = region_polygon(region)
            path = QPainterPath(q(poly[0]))
            for pt in poly[1:]:
                path.lineTo(q(pt))
            path.closeSubpath()
            p.setPen(edge)
            p.setBrush(fill)
            p.drawPath(path)
        p.end()
        return img

    def _erase_preview(self, tab, page, region, e):
        """16d – vùng sẽ tẩy hiện đỏ mờ; kéo dời, kéo góc chỉnh, Enter để tẩy, Esc/bấm ra ngoài để bỏ."""
        from .editing import region_bounds
        b = region_bounds(region)
        if b[2] - b[0] < 1 or b[3] - b[1] < 1:
            return
        img = self._region_image(region, b)

        def commit(pg, rect):
            nx0, ny0, nx1, ny1 = rect
            kx = (nx1 - nx0) / max(1e-6, b[2] - b[0])
            ky = (ny1 - ny0) / max(1e-6, b[3] - b[1])

            def mp(pt):
                return nx0 + (pt[0] - b[0]) * kx, ny0 + (pt[1] - b[1]) * ky
            r = dict(region)
            if "rect" in r:
                r["rect"] = (nx0 + (r["rect"][0] - b[0]) * kx, ny0 + (r["rect"][1] - b[1]) * ky,
                             nx0 + (r["rect"][2] - b[0]) * kx, ny0 + (r["rect"][3] - b[1]) * ky)
            if "pts" in r:
                r["pts"] = [mp(pt) for pt in r["pts"]]
                r["size"] = r.get("size", 12) * (kx + ky) / 2
            self._apply_erase(tab, pg, r, e)
            tab.refresh()
            self._update_state()
        pl = tab.view.begin_edit(img, page, b, commit, None, lambda: None, "Vùng sẽ tẩy",
                                 keep_ratio=False, resizable=region["shape"] in ("rect", "ellipse", "lasso"))
        # bấm ra ngoài / lưu / đổi công cụ = TẨY LUÔN (trước đây là bỏ -> người dùng tưởng tẩy không lưu)
        pl.commit_outside = True
        pl.hint = "Vùng đỏ sẽ bị tẩy · kéo để dời, kéo góc để chỉnh · Enter, nháy đúp hoặc bấm ra ngoài: tẩy · Esc: bỏ"

    def _erase_pages(self, tab, page, scope) -> list[int]:
        n = tab.doc.page_count
        if scope == "all":
            return list(range(n))
        if scope == "odd":
            return list(range(0, n, 2))
        if scope == "even":
            return list(range(1, n, 2))
        if scope == "selected":
            return sorted(set(tab.thumbs.selected_pages()) | {page})
        return [page]

    def _apply_erase(self, tab, page, region, e):
        from . import editing
        doc = tab.doc
        pages = self._erase_pages(tab, page, e.get("scope", "page"))
        if len(pages) > 1:                             # 16e: cùng vùng trên nhiều trang – 1 bước hoàn tác
            b = editing.region_bounds(region)
            doc._snapshot()
            total = {"text": 0, "image": 0, "path": 0}
            done = 0
            for i in pages:
                pw, ph = doc.page_size_pt(i)
                if b[0] >= pw or b[1] >= ph:
                    continue
                r = editing.erase_region(doc, i, region, e["fill"], e["filter"], snapshot=False)
                for k in total:
                    total[k] += r.get(k, 0)
                done += 1
            doc._changed()
            parts = [f"{total[k]} {lbl}" for k, lbl in (("text", "đoạn chữ"), ("image", "ảnh"),
                                                         ("path", "hình / đường kẻ")) if total[k]]
            self._flash(f"Đã tẩy vùng trên {done} trang" + (" – gỡ " + ", ".join(parts) if parts else "") +
                        ". Ctrl+Z để hoàn tác.")
            return
        strokes = 0
        if region.get("shape") == "brush":                # cục tẩy cọ: gỡ luôn các nét vẽ tay chạm vào
            from . import items
            doc._snapshot()
            strokes = items.erase_strokes(doc, page, list(region["pts"]), max(2.0, region.get("size", 12) / 2),
                                          snapshot=False)
            res = editing.erase_region(doc, page, region, e["fill"], e["filter"], snapshot=False)
            doc._changed()
        else:
            res = editing.erase_region(doc, page, region, e["fill"], e["filter"])
        if strokes:
            res["path"] = res.get("path", 0) + strokes
        parts = [f"{res[k]} {lbl}" for k, lbl in (("text", "đoạn chữ"), ("image", "ảnh"), ("path", "hình / đường kẻ"))
                 if res.get(k)]
        msg = ("Đã gỡ " + ", ".join(parts) + ". " if parts else "") + \
            ("Đã phủ " + ("màu nền giấy" if e["fill"] == "sample" else "trắng") + " vùng chọn." if res.get("fill")
             else ("" if parts else "Không có đối tượng nào nằm trọn trong vùng."))
        if res.get("fill") and doc.page_kind(page) == "scan":
            msg += " (Trang scan: phần ảnh bên dưới được che đi.)"
        # tương thích thông báo cũ: "Đã xóa N đoạn chữ"
        if res.get("text"):
            msg = f"Đã xóa {res['text']} đoạn chữ. " + msg
        self._flash(msg.strip() + " Ctrl+Z để hoàn tác.")

    def _text_box(self, tab, page, rect) -> bool:
        """1.0.22 – hộp chữ gõ NGAY TRÊN TRANG (như Word): con trỏ nhấp nháy tại khung vừa kéo, thanh định dạng nổi
        phía trên (phông – cả phông viết tay, cỡ, đậm, nghiêng, màu, canh lề). Ctrl+Enter / bấm ra ngoài: xong."""
        from . import items
        from .ui_edit import qt_family, text_fonts
        st = self.settings
        x0, y0, x1, y1 = rect
        label = st.value("text/font")
        font = st.value("text/font_path") or ""
        if not font and label:
            font = next((p for lb, p in text_fonts() if lb == label), "")
        if not font or not os.path.exists(font):
            font = items.font_path({})
        spec = {"kind": "text", "rect": [x0, y0, x0 + max(40.0, x1 - x0), y1], "angle": 0, "text": "",
                "font": font, "size": float(self.tool_opts.size), "color": st.value("text/color", "#1b1b1b"),
                "align": st.value("text/align", "left") or "left",
                "bold": str(st.value("text/bold", "")).lower() in ("1", "true"),
                "italic": str(st.value("text/italic", "")).lower() in ("1", "true")}
        box = {"inline_spec": spec}
        self._new_box = box

        def done(text):
            self._new_box = None
            sp = box["inline_spec"]
            st.setValue("text/font_path", sp.get("font", ""))
            st.setValue("text/color", sp.get("color", "#1b1b1b"))
            st.setValue("text/align", sp.get("align", "left"))
            st.setValue("text/bold", bool(sp.get("bold")))
            st.setValue("text/italic", bool(sp.get("italic")))
            if not text or not text.strip():
                tab.view.canvas.update()
                return
            new = dict(sp, text=text.rstrip("\n"))
            new["rect"] = list(new["rect"])
            try:
                _, h = items.text_layout(new)
                new["rect"][3] = new["rect"][1] + h
                items.add_item(tab.doc, page, new)
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Không chèn được hộp chữ:\n{e}")
                return
            tab.refresh()
            self._update_state()
            self._flash("Đã chèn hộp chữ. Bấm vào để di chuyển / xoay, nháy đúp để sửa chữ. Ctrl+Z để hoàn tác.")
        bar = self._text_fmtbar(tab, box, "inline_spec")
        tab.view.begin_inline_text(page, (x0, y0, spec["rect"][2], max(y1, y0 + spec["size"] * 1.4)), "",
                                   qt_family(items.font_path(spec)), spec["size"], spec["color"], done,
                                   spec["align"], bold=spec["bold"], italic=spec["italic"], bar=bar)
        return False

    def _edit_text(self, tab, page, x, y) -> bool:
        """11a–11e – sửa chữ có sẵn: gõ ngay trên trang (mảnh chữ / cả dòng / cả đoạn), đổi phông, đậm, nghiêng,
        cỡ, màu; chữ dài hơn tự co cho vừa. Trang scan: chuyển sang kéo khung quanh chữ cần sửa."""
        from . import editing, fonts
        from .ui_edit import EditTextDialog, qt_family
        doc = tab.doc
        if doc.page_kind(page) != "text":
            self.start_tool("scanedit")
            self._flash("Trang scan: kéo khung quanh chữ cần sửa – phần mềm phủ màu nền giấy rồi cho gõ chữ mới.")
            return False
        runs = editing.text_runs(doc, page)
        run = editing.run_at(doc, page, x, y)
        if run is None:
            self._flash("Không có dòng chữ nào tại chỗ vừa bấm.")
            return False
        o = self.tool_opts
        scope = o.cb_scope.currentData() if o.rows["editscope"].isVisibleTo(o) else "line"
        if scope == "run":
            lines = [[run]]
        elif scope == "para":
            lines = editing.paragraph_of(runs, run)
        else:
            lines = [editing.line_of(runs, run)]
        (_x0, _b0), upright = editing.run_origin(doc, page, run)
        if not upright:                                  # chữ xoay nghiêng: sửa từng mảnh bằng hộp thoại
            fp = editing.replacement_font(run)
            dlg = EditTextDialog(self, run, fonts.FAMILY_LABEL.get(fonts.family_of(run.font_name), os.path.basename(fp)))
            if dlg.exec() != EditTextDialog.Accepted or dlg.text() == run.text:
                return False
            editing.replace_run(doc, page, run, dlg.text(), fp)
            self._flash("Đã sửa chữ. Ctrl+Z để hoàn tác.")
            return True
        old = editing.group_text(lines) if len(lines) > 1 else " ".join(r.text.strip() for r in lines[0])
        rs = [r for ln in lines for r in ln]
        rect = (min(r.rect[0] for r in rs), min(r.rect[1] for r in rs), max(r.rect[2] for r in rs),
                max(r.rect[3] for r in rs))
        color = "#%02x%02x%02x" % tuple(run.color[:3])
        # 1.0.22: giữ ĐÚNG phông gốc – phông nhúng trong file, không có thì phông cùng tên đã cài trên máy
        fp0, src0 = editing.original_font(run, old, doc, page)

        col0 = getattr(o, "_edit_color", None)

        # 1.0.22: ô cỡ chữ (bảng phải + thanh nổi) hiện đúng cỡ gốc của dòng đang sửa thay vì 0
        o._quiet = True
        try:
            o.sp_size.setValue(float(run.size))
        finally:
            o._quiet = False
        if run.orig_size and abs(run.orig_size - run.size) > 0.05:
            self._flash(f"Dòng này đã đổi cỡ chữ: hiện {run.size:g} pt, cỡ gốc {run.orig_size:g} pt "
                        "(bấm ↺ trên thanh định dạng để về cỡ gốc).")

        def chosen_size():
            v = o.sp_size.value()
            return v if v and abs(v - run.size) > 0.05 else None

        def done(text):
            restyled = bool(o.cb_family.currentData() or o.btn_bold.isChecked() or o.btn_italic.isChecked()
                            or chosen_size() or getattr(o, "_edit_color", None) != col0)
            if text is None or (text.replace("\n", " ").strip() == old.strip() and not restyled):
                tab.view.canvas.update()
                return
            fam = o.cb_family.currentData() or None
            bold = o.btn_bold.isChecked() or None
            italic = o.btn_italic.isChecked() or None
            if fam or (bold and not run.bold) or (italic and not run.italic):
                fp = editing.styled_font(run, fam, bold or run.bold, italic or run.italic)
            else:                                   # không đổi kiểu chữ: dùng đúng phông gốc nếu đủ ký tự
                fp, src = editing.original_font(run, text, doc, page)
                if src == "family" and src0 != "family":
                    self._flash_later = ("Phông gốc trong file thiếu ký tự vừa gõ – đã dùng phông gần giống nhất "
                                         "trên máy.")
            size = chosen_size()
            col = getattr(o, "_edit_color", None)
            try:
                info = editing.replace_group(doc, page, lines, text, fp, size, col, fit=o.chk_fit.isChecked())
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Không sửa được:\n{e}")
                return
            msg = "Đã sửa chữ."
            if info["shrunk"]:
                msg += f" Dòng quá dài nên đã co chữ hẹp lại và còn cỡ {info['size']:g} pt cho vừa 1 dòng."
            elif info.get("condensed"):
                msg += " Gần hết chỗ bên phải nên đã co chữ hẹp lại một chút cho vừa 1 dòng (giữ nguyên cỡ chữ)."
            if info["overflow"]:
                msg += " ⚠ Chữ vẫn dài hơn chỗ trống (có thể đè lên chữ bên cạnh) – nên rút gọn lại."
            extra = getattr(self, "_flash_later", None)
            self._flash_later = None
            self._flash(msg + (" " + extra if extra else "") + " Ctrl+Z để hoàn tác.")
            tab.refresh()
            self._update_state()
        self._edit_done_cb = done
        self._edit_color_seen = o.color
        self._edit_base = {"family": qt_family(fp0), "size": run.size, "color": color,
                           "bold": bool(run.bold), "italic": bool(run.italic)}
        # 1 dòng: ô gõ không tự xuống dòng mà kéo dài sang phải tới chữ kế tiếp / lề phải trang (giữ cỡ chữ)
        room = editing.line_room(doc, page, lines, runs) if len(lines) == 1 else None
        tab.view.begin_inline_text(page, rect, old, qt_family(fp0), run.size, color, done, caret=(x, y),
                                   bold=False, italic=False, bar=self._edit_fmtbar(tab, run), grow_right=room)
        if any((o.cb_family.currentData(), o.btn_bold.isChecked(), o.btn_italic.isChecked(), chosen_size())):
            self._restyle_inline(tab)
        return False

    def _scan_edit(self, tab, page, rect) -> bool:
        """11e – trang scan: phủ màu nền giấy vùng chọn rồi gõ chữ mới cùng cỡ, đúng chỗ (thành hộp chữ sửa được)."""
        from . import editing, items
        from .ui_edit import qt_family
        doc = tab.doc
        x0, y0, x1, y1 = rect
        if x1 - x0 < 4 or y1 - y0 < 4:
            return False
        editing.erase_region(doc, page, {"shape": "rect", "rect": rect}, "sample", "all")
        tab.refresh()
        size = max(5.0, (y1 - y0) * 0.72)

        def done(text):
            if not text or not text.strip():
                doc.undo()                                  # bỏ: trả lại vùng scan như cũ
                tab.refresh()
                self._update_state()
                return
            spec = items.text_spec(x0, y0, max(20.0, x1 - x0), text, None, size, "#1f1f1f")
            h = spec["rect"][3] - spec["rect"][1]
            dy = ((y1 - y0) - h) / 2
            spec["rect"] = [x0, y0 + dy, spec["rect"][2], y0 + dy + h]
            try:
                items.add_item(doc, page, spec, snapshot=False)
                doc._changed()
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Không viết được chữ:\n{e}")
            tab.refresh()
            self._update_state()
            self._flash("Đã sửa chữ trên trang scan (bấm vào chữ mới để dời / đổi cỡ). Ctrl+Z để hoàn tác.")
        tab.view.begin_inline_text(page, rect, "", qt_family(items.font_path({})), size, "#1f1f1f", done)
        return True

    def search_doc(self, text: str, backward: bool = False) -> int | None:
        """Ô tìm kiếm trên cùng (như Foxit/Adobe): tô VÀNG mọi chỗ tìm thấy, chỗ đang xem tô CAM; Enter / F3: chỗ
        tiếp theo, Shift+Enter / Shift+F3: chỗ trước; Esc: bỏ tô. Trả về trang (0-based) của chỗ đang xem."""
        tab = self.current()
        text = (text or "").strip()
        if not tab or not text:
            if not tab:
                self._flash("Hãy mở một file PDF trước.")
            else:
                self.clear_search()
            return None
        doc = tab.doc
        key = (id(doc), doc.version, text)
        st = getattr(self, "_search", None)
        if st is None or st["key"] != key or st["tab"] is not tab:
            if st is not None and st["tab"] is not tab:
                self.clear_search()
            hits = doc.search_hits(text)
            if not hits:
                tab.view.set_marks("search", None)
                tab.view.set_marks("search_cur", None)
                self._search = None
                self._flash(f"Không tìm thấy “{text}” (trang scan chưa có lớp chữ thì không tìm được).")
                return None
            cur = tab.view.current_page()
            idx = next((k for k, (pg, _) in enumerate(hits) if pg >= cur), 0)
            if backward:
                idx = next((k for k in range(len(hits) - 1, -1, -1) if hits[k][0] <= cur), len(hits) - 1)
            st = self._search = {"key": key, "tab": tab, "hits": hits, "idx": idx, "text": text}
            marks = {}
            for pg, rects in hits:
                marks.setdefault(pg, []).extend(rects)
            tab.view.set_marks("search", marks)
        else:
            st["idx"] = (st["idx"] + (-1 if backward else 1)) % len(st["hits"])
        hits, idx = st["hits"], st["idx"]
        page, rects = hits[idx]
        tab.view.set_marks("search_cur", {page: rects})
        tab.view.show_rect(page, rects[0])
        pages = len({pg for pg, _ in hits})
        self._flash(f"“{text}”: chỗ {idx + 1}/{len(hits)} (trên {pages} trang) – trang {page + 1}. "
                    "Enter / F3: chỗ tiếp · Shift+Enter: chỗ trước · Esc: bỏ tô.")
        return page

    def clear_search(self):
        st = getattr(self, "_search", None)
        self._search = None
        tabs = [st["tab"]] if st else []
        tabs += [self.tabs.widget(i) for i in range(self.tabs.count())]
        for t in tabs:
            try:
                t.view.set_marks("search", None)
                t.view.set_marks("search_cur", None)
            except (AttributeError, RuntimeError):
                pass

    def find_dialog(self, tab):
        from .ui_edit import FindReplaceDialog
        dlg = FindReplaceDialog(self, tab.doc, on_goto=tab.view.go_to)
        dlg.exec()
        if dlg.replaced:
            tab.refresh()
            self._update_state()

    def hand_write(self, tab, handset_id: str | None = None):
        from . import editing, fonts
        from .ui_edit import HandDialog
        self._init_library()
        dlg = HandDialog(self, self.library, handset_id, self.settings)
        if dlg.exec() != HandDialog.Accepted:
            return
        v = dlg.values()
        img, w_pt = dlg.render()
        doc = tab.doc

        def commit(page, rect):
            x0, y0, x1, y1 = rect
            lines = v["text"].split("\n")           # phông viết tay -> chữ thật (vector)
            base_w = max(fonts.measure(v["font_path"], l, v["size"]) for l in lines) + 2
            size = v["size"] * (x1 - x0) / max(1.0, base_w)
            # 1.0.22: thành hộp chữ (phông viết tay) -> sau này nháy đúp để gõ sửa ngay trên trang như hộp chữ
            from . import items
            w = fonts.measure(v["font_path"], max(lines, key=len) or " ", size) + size
            w = max(w, max(fonts.measure(v["font_path"], l, size) for l in lines) + size * 0.5)
            items.add_item(doc, page, items.text_spec(x0, y0, w, v["text"], v["font_path"], size, v["color"],
                                                      wrap=False))
            tab.refresh()
            self._update_state()
            self._flash("Đã chèn chữ viết tay. Bấm vào để sửa vị trí, Ctrl+Z để hoàn tác.")

        def commit_img(page, rect, src, angle, layer, scope):   # nét chữ của chính mình -> ảnh trong suốt
            argb = src.convertToFormat(src.Format.Format_ARGB32)
            doc.stamp_pages(self._scope_pages(tab, page, scope), rect, bytes(argb.constBits()), argb.width(),
                            argb.height(), argb.bytesPerLine(), angle=angle, layer=layer)
            tab.refresh()
            self._update_state()
            self._flash(self._layer_note(doc, page, layer) or
                        "Đã chèn chữ viết tay. Bấm vào để sửa vị trí, Ctrl+Z để hoàn tác.")

        if v["font_path"]:
            tab.view.begin_placement(img, commit, width_pt=w_pt, label="Chữ viết tay")
        else:
            self.begin_image_placement(tab, img, commit_img, width_pt=w_pt, label="Chữ viết tay", scope=True)

    # ---------- đợt 2: bấm chọn nội dung đã thêm / ghi chú / ảnh ----------
    def _hover_kind(self, tab, page, x, y):
        """Con trỏ theo ngữ cảnh (13c): 4 mũi tên trên đối tượng chọn được, chữ I trên chữ sửa được."""
        from . import items, notes
        if tab.view.tool is not None or tab.view.placement is not None:
            return None
        doc = tab.doc
        try:
            if notes.note_at(doc, page, x, y):
                return "note"
            if items.item_at(doc, page, x, y):
                return "item"
            if doc.page_kind(page) == "text" and self._run_at_cached(doc, page, x, y):
                return "text"
        except Exception:
            return None
        return None

    def _run_at_cached(self, doc, page, x, y):
        from . import editing
        key = (id(doc), doc.version, page)
        cache = getattr(self, "_runs_cache", None)
        if not cache or cache[0] != key:
            try:
                rects = [r.rect for r in editing.text_runs(doc, page)]
            except Exception:
                rects = []
            self._runs_cache = cache = (key, rects)
        return any(x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1 for x0, y0, x1, y1 in cache[1])

    def _guides(self, tab, page):
        from . import items
        xs, ys = [], []
        for it in items.find_items(tab.doc, page):
            x0, y0, x1, y1 = it.rect
            xs += [x0, (x0 + x1) / 2, x1]
            ys += [y0, (y0 + y1) / 2, y1]
        return xs, ys

    def page_pressed(self, page: int, x: float, y: float):
        """Bấm vào ghi chú / nội dung đã thêm (hộp chữ, hình, nét vẽ, ký hiệu) / ảnh, con dấu, chữ ký đã chèn
        -> chọn để di chuyển, đổi cỡ, xoay, sửa hoặc xóa."""
        from . import editing, items, notes
        tab = self.current()
        if not tab or tab.view.placement is not None or tab.view.tool is not None:
            return
        n = notes.note_at(tab.doc, page, x, y)          # đọc ghi chú: được cả với file đã ký / bị khóa sửa
        if n is not None:
            self._select_note(tab, page, n)
            return
        if not tab.doc.can_modify:
            return
        it = items.item_at(tab.doc, page, x, y)
        if it is not None:
            from PySide6.QtWidgets import QApplication
            last = getattr(self, "_last_sel", None)
            if QApplication.keyboardModifiers() & Qt.ControlModifier and last and last[0] is tab and last[1] == page:
                ids = [i for i in last[2] if i != it.id] + [it.id]        # 13d: Ctrl+bấm – thêm vào nhóm chọn
                group = [x for x in items.find_items(tab.doc, page) if x.id in ids]
                if len(group) > 1:
                    self._select_group(tab, page, group)
                    return
            self._select_item(tab, page, it)
            return
        info = editing.image_at(tab.doc, page, x, y)
        if info is None:
            return
        self._select_image(tab, page, info)

    def page_double_clicked(self, page: int, x: float, y: float):
        """Nháy đúp lên dòng chữ có sẵn mà không chọn được từ (1.0.22: nháy đúp lên chữ = chọn từ để copy;
        sửa chữ: công cụ Sửa chữ hoặc chuột phải -> Sửa chữ tại đây) -> sửa chữ."""
        tab = self.current()
        if not tab or tab.view.tool is not None or tab.view.placement is not None or not tab.doc.can_modify:
            return
        if tab.doc.page_kind(page) == "text" and self._run_at_cached(tab.doc, page, x, y):
            if self._writable(tab, "Sửa chữ") and self._edit_text(tab, page, x, y):
                tab.refresh()
                self._update_state()

    # --- nội dung đã thêm (13a, 13b, 13e) ---
    def _select_item(self, tab, page, item):
        from . import items
        from .ui_edit import pil_to_qimage
        if not self._writable(tab, "Sửa nội dung đã thêm"):
            return
        try:
            ed = items.ItemEdit(tab.doc, page, item)
        except Exception as e:
            self._flash(f"Không chọn được: {e}")
            return
        spec = ed.spec
        img, m = items.render_preview(spec)
        b = items.display_bounds(spec)
        frame = (b[0] - m, b[1] - m, b[2] + m, b[3] + m)
        ctx = {"tab": tab, "page": page, "ed": ed, "spec": spec, "m": m, "frame": frame, "label": item.label}
        self._sel = ctx
        tab.view.document_changed()

        def finish():
            self._sel = None
            self._last_sel = (tab, page, [item.id])
            self._end_item_panel()
            tab.refresh()
            self._update_state()

        def commit(pg, rect, angle=0.0):
            new = self._spec_from_frame(ctx, rect, angle)
            try:
                ed.commit(new, force=ctx.get("force", False))
            except Exception as e:
                ed.cancel()
                QMessageBox.warning(self, APP_NAME, f"Không cập nhật được:\n{e}")
            finish()
            if ed.done and new != ed.orig:
                self._flash(f"Đã cập nhật {ctx['label'].lower()}. Ctrl+Z để hoàn tác.")

        def delete():
            ed.delete()
            finish()
            self._flash(f"Đã xóa {ctx['label'].lower()}. Ctrl+Z để hoàn tác.")

        def cancel():
            ed.cancel()
            finish()
        pl = tab.view.begin_edit(pil_to_qimage(img), page, frame, commit, delete, cancel, item.label,
                                 keep_ratio=items.keep_ratio(spec), angle=float(spec.get("angle", 0) or 0),
                                 rotatable=True, commit_outside=True)
        pl.on_change = lambda _pl: self._sel_frame_changed()
        if spec.get("kind") == "text" or (spec.get("kind") == "shape" and spec.get("shape") not in
                                          items.LINE_SHAPES | items.SYMBOL_SHAPES | {"check", "cross", "highlight"}):
            pl.on_dblclick = lambda _pl: self._inline_edit_selected()
        self.tool_opts.show_item(spec, item.label)

    def _end_item_panel(self):
        o = self.tool_opts
        st = getattr(o, "_tool_state", None)
        if st is not None:
            o._tool_state = None
            o._restore(st)
            o._item_mode = False
        tab = self.current()
        if tab is None or tab.view.tool is None:
            o.setVisible(False)

    def _spec_from_frame(self, ctx, rect, angle):
        from . import items
        fx0, fy0, fx1, fy1 = ctx["frame"]
        x0, y0, x1, y1 = rect
        kx = (x1 - x0) / max(1e-6, fx1 - fx0)
        ky = (y1 - y0) / max(1e-6, fy1 - fy0)
        m = ctx["m"]
        inner = (x0 + m * kx, y0 + m * ky, x1 - m * kx, y1 - m * ky)
        spec = ctx["spec"]
        if abs(kx - 1) < 1e-6 and abs(ky - 1) < 1e-6:
            dx, dy = x0 - fx0, y0 - fy0
            r = items.spec_rect(spec)
            new = dict(spec)
            new["rect"] = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
        else:
            b = items.display_bounds(spec)
            r = items.spec_rect(spec)
            # khung chữ: display_bounds cao hơn rect lưu -> quy đổi theo tỉ lệ
            nx0 = inner[0] + (r[0] - b[0]) * kx
            ny0 = inner[1] + (r[1] - b[1]) * ky
            new = items.resized(spec, (nx0, ny0, nx0 + (r[2] - r[0]) * kx, ny0 + (r[3] - r[1]) * ky))
        new["angle"] = round(float(angle or 0) % 360, 2)
        return new

    def _sel_frame_changed(self):
        ctx = getattr(self, "_sel", None)
        tab = self.current()
        if not ctx or not tab or tab.view.placement is None:
            return
        o = self.tool_opts
        o._quiet = True
        o.sp_angle.setValue(tab.view.placement.angle)
        o._quiet = False

    def _restyle_selection(self):
        """Đổi màu / nét / độ mờ / góc... trên bảng thuộc tính -> cập nhật ngay khung xem trước."""
        from . import items
        from .ui_edit import pil_to_qimage
        ctx = self._sel
        tab = ctx["tab"]
        pl = tab.view.placement
        r = pl.rect
        spec = self._spec_from_frame(ctx, (r.left(), r.top(), r.right(), r.bottom()), pl.angle)
        spec = self.tool_opts.apply_to(spec)
        try:
            img, m = items.render_preview(spec)
        except Exception as e:
            self._flash(f"Không áp dụng được: {e}")
            return
        b = items.display_bounds(spec)
        frame = (b[0] - m, b[1] - m, b[2] + m, b[3] + m)
        ctx.update(spec=spec, m=m, frame=frame)
        pl.angle = float(spec.get("angle", 0) or 0)
        tab.view.replace_placement_image(pil_to_qimage(img), QRectF(frame[0], frame[1], frame[2] - frame[0],
                                                                   frame[3] - frame[1]))

    def _text_fmtbar(self, tab, holder: dict, key: str, is_shape: bool = False):
        """1.0.22 – thanh định dạng nổi (phông, cỡ, đậm, nghiêng, màu, canh lề) cho hộp chữ đang gõ tại chỗ.
        holder[key] là spec đang sửa; mỗi lần đổi: cập nhật spec, bảng bên phải và ô gõ trên trang."""
        from . import items
        from .ui_edit import InlineFormatBar, qt_family
        spec = holder[key]
        bar = InlineFormatBar(tab.view.canvas, "textbox")
        bar.set_state({"font": spec.get("font") or items.font_path({}),
                       "size": spec.get("text_size" if is_shape else "size", 12),
                       "color": spec.get("text_color" if is_shape else "color", "#1b1b1b"),
                       "bold": spec.get("bold"), "italic": spec.get("italic"),
                       "align": "center" if is_shape else spec.get("align", "left")})
        if is_shape:
            for b in bar.align_btns.values():
                b.setVisible(False)

        def changed(st):
            sp = dict(holder[key])
            sp["font"] = st["font"] or sp.get("font", "")
            sp["bold"], sp["italic"] = st["bold"], st["italic"]
            if is_shape:
                sp["text_size"], sp["text_color"] = st["size"], st["color"]
            else:
                sp["size"], sp["color"], sp["align"] = st["size"], st["color"], st["align"]
            holder[key] = sp
            o = self.tool_opts                       # bảng bên phải theo cùng giá trị (không phát tín hiệu)
            o._quiet = True
            try:
                o.sp_size.setValue(float(st["size"]))
                k = o.cb_font.findData(sp["font"])
                if k >= 0:
                    o.cb_font.setCurrentIndex(k)
                if not is_shape:
                    o.set_color(st["color"])
                    o.cb_align.setCurrentIndex(max(0, o.cb_align.findData(st["align"])))
            finally:
                o._quiet = False
            tab.view.restyle_inline(family=qt_family(items.font_path(sp)), size=float(st["size"]),
                                    color=st["color"], bold=st["bold"], italic=st["italic"],
                                    align=None if is_shape else st["align"])
        bar.changed.connect(changed)
        bar.accepted.connect(lambda: tab.view._finish_inline(True))
        bar.rejected.connect(lambda: tab.view._finish_inline(False))
        return bar

    def _edit_fmtbar(self, tab, run):
        """Thanh định dạng nổi khi sửa chữ có sẵn trong PDF: giữ phông gốc / đổi họ phông, cỡ, đậm, nghiêng, màu."""
        from .ui_edit import InlineFormatBar
        o = self.tool_opts
        bar = InlineFormatBar(tab.view.canvas, "edit")
        bar.set_state({"family": o.cb_family.currentData() or "", "size": o.sp_size.value(),
                       "bold": o.btn_bold.isChecked(), "italic": o.btn_italic.isChecked(),
                       "color": getattr(o, "_edit_color", None) or "#%02x%02x%02x" % tuple(run.color[:3])})
        bar.set_orig_size(run.orig_size or run.size)            # nút ↺ về cỡ gốc (nhớ cả sau khi lưu file)
        base_col = bar.state()["color"]

        def changed(st):
            o._quiet = True
            try:
                o.cb_family.setCurrentIndex(max(0, o.cb_family.findData(st["family"])))
                o.sp_size.setValue(float(st["size"]))
                o.btn_bold.setChecked(st["bold"])
                o.btn_italic.setChecked(st["italic"])
            finally:
                o._quiet = False
            if st["color"] != base_col:
                o._edit_color = st["color"]
                self._edit_color_seen = o.color
            self._restyle_inline(tab)
        bar.changed.connect(changed)
        bar.accepted.connect(lambda: tab.view._finish_inline(True))
        bar.rejected.connect(lambda: tab.view._finish_inline(False))
        return bar

    def _restyle_inline(self, tab):
        """Bảng bên phải đổi cỡ / màu / phông / đậm... trong lúc đang gõ sửa chữ tại chỗ."""
        from . import items
        from .ui_edit import qt_family
        o = self.tool_opts
        ctx = getattr(self, "_sel", None)
        if not (ctx and ctx.get("inline_spec") is not None):
            ctx = getattr(self, "_new_box", None)               # hộp chữ mới đang gõ
        if ctx and ctx.get("inline_spec") is not None:           # hộp chữ / chữ trong hình đã thêm
            spec = o.apply_to(ctx["inline_spec"])
            ctx["inline_spec"] = spec
            is_shape = spec.get("kind") == "shape"
            tab.view.restyle_inline(family=qt_family(items.font_path(spec)),
                                    size=float(spec.get("text_size" if is_shape else "size", 12)),
                                    color=spec.get("text_color", "#1b1b1b") if is_shape else spec.get("color"),
                                    align=None if is_shape else spec.get("align"),
                                    bold=bool(spec.get("bold")), italic=bool(spec.get("italic")))
            bar = getattr(tab.view, "_inline_bar", None)
            if bar is not None and bar.mode == "textbox":
                st = bar.state()
                bar.set_state(dict(st, font=spec.get("font") or st["font"],
                                   size=spec.get("text_size" if is_shape else "size", st["size"]),
                                   color=spec.get("text_color" if is_shape else "color", st["color"]),
                                   align=spec.get("align", st["align"])))
            return
        if tab.view.tool is not None and tab.view.tool.kind == "edittext":   # sửa chữ có sẵn trong PDF
            base = getattr(self, "_edit_base", None) or {}
            fam = o.cb_family.currentData()
            family = base.get("family")
            if fam:
                try:
                    from . import fonts
                    family = qt_family(fonts.system_font(fam))
                except Exception:
                    family = fam
            tab.view.restyle_inline(family=family, size=o.sp_size.value() or base.get("size"),
                                    color=getattr(o, "_edit_color", None) or base.get("color"),
                                    bold=o.btn_bold.isChecked() or base.get("bold", False),
                                    italic=o.btn_italic.isChecked() or base.get("italic", False))

    def _sel_z(self, z: str):
        from . import items
        ctx = getattr(self, "_sel", None)
        tab = self.current()
        if not ctx or not tab or tab.view.placement is None:
            return
        if z == "back" and not items.can_send_back(tab.doc, ctx["page"]):
            self._flash("Trang scan hoặc file đã ký số: không đưa xuống dưới chữ được (sẽ làm mất chữ ký / bị ảnh "
                        "scan che mất).")
            return
        ctx["spec"] = dict(ctx["spec"], z=z)
        ctx["force"] = True                     # luôn dựng lại (đổi lớp dù không đổi gì khác)
        tab.view.commit_placement()

    def _sel_delete(self):
        tab = self.current()
        if getattr(self, "_sel", None) and tab and tab.view.placement is not None:
            tab.view.delete_placement()

    def _inline_edit_selected(self):
        """13b – nháy đúp hộp chữ: gõ sửa ngay trên trang."""
        from . import items
        from .ui_edit import TextDialog, qt_family
        ctx = getattr(self, "_sel", None)
        tab = self.current()
        if not ctx or not tab or tab.view.placement is None:
            return
        pl = tab.view.placement
        r = pl.rect
        spec = self._spec_from_frame(ctx, (r.left(), r.top(), r.right(), r.bottom()), pl.angle)
        ed = ctx["ed"]
        tab.view.placement = None                # ẩn khung, giữ nguyên phiên sửa
        tab.view.canvas.update()

        is_shape = spec.get("kind") == "shape"
        ctx["inline_spec"] = spec

        def done(text):
            nonlocal spec
            spec = ctx.get("inline_spec") or spec             # cỡ / màu / phông đã đổi trên bảng bên phải
            self._sel = None
            if text is None:
                ed.cancel()
            elif is_shape:                               # 14d: chữ trong hình (để trống = bỏ chữ)
                try:
                    ed.commit(dict(spec, text=text.strip("\n")))
                    self._flash("Đã cập nhật chữ trong hình. Ctrl+Z để hoàn tác.")
                except Exception as e:
                    ed.cancel()
                    QMessageBox.warning(self, APP_NAME, f"Không sửa được:\n{e}")
            elif not text.strip():
                ed.delete()
                self._flash("Đã xóa hộp chữ (không còn chữ). Ctrl+Z để hoàn tác.")
            else:
                new = dict(spec, text=text)
                try:
                    _, h = items.text_layout(new)
                    x0, y0, x1, _y1 = items.spec_rect(new)
                    new["rect"] = [x0, y0, x1, y0 + h]
                    ed.commit(new)
                    self._flash("Đã sửa chữ. Ctrl+Z để hoàn tác.")
                except Exception as e:
                    ed.cancel()
                    QMessageBox.warning(self, APP_NAME, f"Không sửa được:\n{e}")
            self._end_item_panel()
            tab.refresh()
            self._update_state()
            tab.view.placementEnded.emit()

        if float(spec.get("angle", 0) or 0) % 360:
            size = float(spec.get("text_size" if is_shape else "size", 12))
            dlg = TextDialog(self, size=size, color=spec.get("text_color" if is_shape else "color", "#000000"))
            dlg.ed.setPlainText(spec.get("text", ""))
            done(dlg.values()["text"] if dlg.exec() == TextDialog.Accepted else None)
            return
        if is_shape:
            ts = items.shape_text_spec(dict(spec, text=spec.get("text") or "Chữ")) or {}
            x0, y0, x1, y1 = items.spec_rect(spec)
            tr = ts.get("rect") or [x0 + 4, y0 + 4, x1 - 4, y1 - 4]
            tab.view.begin_inline_text(ctx["page"], (tr[0], tr[1], tr[2], tr[3]), spec.get("text", ""),
                                       qt_family(items.font_path(spec)), float(spec.get("text_size", 11)),
                                       spec.get("text_color", "#1b1b1b"), done, "center",
                                       bold=bool(spec.get("bold")), italic=bool(spec.get("italic")),
                                       bar=self._text_fmtbar(tab, ctx, "inline_spec", True))
            return
        b = items.display_bounds(spec)
        bar = self._text_fmtbar(tab, ctx, "inline_spec", is_shape)
        tab.view.begin_inline_text(ctx["page"], b, spec.get("text", ""), qt_family(items.font_path(spec)),
                                   float(spec.get("size", 12)), spec.get("color", "#000000"), done,
                                   spec.get("align", "left"), bold=bool(spec.get("bold")),
                                   italic=bool(spec.get("italic")), bar=bar)

    # --- 13d: chọn nhiều, sao chép / dán ---
    def band_selected(self, tab, page, rect):
        from . import items
        if tab.view.tool is not None or not tab.doc.can_modify:
            return
        found = items.items_in_rect(tab.doc, page, rect) or items.items_in_rect(tab.doc, page, rect, partial=True)
        if not found:
            return
        if len(found) == 1:
            self._select_item(tab, page, found[0])
        else:
            self._select_group(tab, page, found)

    def _select_group(self, tab, page, group):
        from . import items
        from .ui_edit import pil_to_qimage
        if not self._writable(tab, "Sửa nội dung đã thêm"):
            return
        ge = items.GroupEdit(tab.doc, page, group)
        m = 4.0
        x0, y0, x1, y1 = ge.frame
        frame = (x0 - m, y0 - m, x1 + m, y1 + m)
        try:
            img = items.render_group(tab.doc.page_size_pt(page), ge.specs, frame)
        except Exception:
            ge.cancel()
            return
        ids = [it.id for it in group]
        ctx = {"tab": tab, "page": page, "group": ge, "frame": frame, "m": m, "ids": ids}
        self._sel = ctx
        tab.view.document_changed()

        def new_frame(rect):
            fx0, fy0, fx1, fy1 = frame
            kx = (rect[2] - rect[0]) / max(1e-6, fx1 - fx0)
            ky = (rect[3] - rect[1]) / max(1e-6, fy1 - fy0)
            return (rect[0] + m * kx, rect[1] + m * ky, rect[2] - m * kx, rect[3] - m * ky)

        def finish():
            self._sel = None
            self._last_sel = (tab, page, ids)
            self._end_item_panel()
            tab.refresh()
            self._update_state()

        def commit(pg, rect):
            ge.commit(new_frame(rect))
            finish()
            if ge.done:
                self._flash(f"Đã cập nhật {len(ids)} nội dung. Ctrl+Z để hoàn tác.")

        def delete():
            ge.delete()
            finish()
            self._flash(f"Đã xóa {len(ids)} nội dung. Ctrl+Z để hoàn tác.")

        def cancel():
            ge.cancel()
            finish()
        ctx["new_frame"] = new_frame
        pl = tab.view.begin_edit(pil_to_qimage(img), page, frame, commit, delete, cancel, f"{len(ids)} nội dung",
                                 keep_ratio=False, commit_outside=True)
        pl.hint = (f"Đang chọn {len(ids)} nội dung · kéo để dời, kéo góc để co giãn · Delete: xóa · "
                   "Ctrl+C / Ctrl+D: sao chép / nhân bản · Esc: bỏ")
        o = self.tool_opts
        if getattr(o, "_tool_state", None) is None:
            o._tool_state = o._state()
        o._item_mode = True
        o.title.setText(f"Đang chọn {len(ids)} nội dung")
        o.hint.setText("Kéo để dời cả nhóm, kéo góc để co giãn. Ctrl+bấm thêm/bớt nội dung, Ctrl+C / Ctrl+V / Ctrl+D "
                       "để sao chép / dán / nhân bản, Delete để xóa.")
        for k, w in o.rows.items():
            w.setVisible(k == "delete")
        o.setVisible(True)

    def _selection_specs(self, tab):
        """Spec các nội dung đang chọn (theo vị trí khung hiện tại) – để sao chép."""
        from . import items
        ctx = getattr(self, "_sel", None)
        pl = tab.view.placement
        if not ctx or pl is None or ctx.get("tab") is not tab:
            return None, None
        r = (pl.rect.left(), pl.rect.top(), pl.rect.right(), pl.rect.bottom())
        if ctx.get("group"):
            nf = ctx["new_frame"](r)
            return [items.group_transform(sp, ctx["group"].frame, nf) for sp in ctx["group"].specs], ctx["page"]
        return [self._spec_from_frame(ctx, r, pl.angle)], ctx["page"]

    # --- bôi chọn & sao chép chữ có sẵn (như Foxit / Adobe) ---
    def text_selected(self, tab):
        t = tab.view.selected_text()
        if t.strip():
            n = len(t.strip())
            self._flash(f"Đã chọn {n} ký tự – Ctrl+C để sao chép, bấm phải để xem thêm lựa chọn.")

    def copy_selected_text(self, tab) -> bool:
        from PySide6.QtWidgets import QApplication
        t = tab.view.selected_text()
        if not t.strip():
            return False
        QApplication.clipboard().setText(t)
        self._flash(f"Đã sao chép {len(t.strip())} ký tự vào bộ nhớ tạm – dán (Ctrl+V) sang Word, Zalo, email…")
        return True

    def page_context_menu(self, tab, page, x, y, gpos):
        from PySide6.QtWidgets import QMenu
        v = tab.view
        sel = v.text_sel
        inside = False
        if sel and sel[0] == page:
            pg, rects = v.selected_rects()
            inside = any(x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2 for x0, y0, x1, y1 in rects)
        if not inside and v.char_at(page, x, y) is not None and not sel:
            v.select_word(page, x, y)
            sel = v.text_sel
        m = QMenu(self)
        a_copy = m.addAction("Sao chép chữ\tCtrl+C")
        a_copy.setEnabled(bool(sel))
        a_all = m.addAction("Chọn hết chữ trên trang\tCtrl+A")
        a_find = m.addAction("Tìm đoạn đã chọn trong file")
        a_find.setEnabled(bool(sel))
        m.addSeparator()
        can_edit = tab.doc.can_modify and tab.doc.page_kind(page) == "text" and self._run_at_cached(tab.doc, page, x, y)
        a_edit = m.addAction("Sửa chữ tại đây…")
        a_edit.setEnabled(bool(can_edit))
        a_clear = m.addAction("Bỏ chọn\tEsc")
        a_clear.setEnabled(bool(sel))
        act = m.exec(gpos)
        if act is a_copy:
            self.copy_selected_text(tab)
        elif act is a_all:
            if v.select_page_text(page):
                self.text_selected(tab)
        elif act is a_find:
            t = " ".join(v.selected_text().split())[:200]
            if t:
                self.search.setText(t)
                self.search_doc(t)
        elif act is a_edit:
            v.clear_text_selection()
            if self._writable(tab, "Sửa chữ") and self._edit_text(tab, page, x, y):
                tab.refresh()
                self._update_state()
        elif act is a_clear:
            v.clear_text_selection()

    def clipboard_action(self, tab, act: str):
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        from . import items
        import json as _json
        mime = "application/x-pdfkyso-items"
        if act == "copy" and tab.view.placement is None and tab.view.text_sel and self.copy_selected_text(tab):
            return
        if act in ("copy", "cut", "dup"):
            specs, page = self._selection_specs(tab)
            if not specs:
                self._flash("Hãy chọn nội dung cần sao chép (bấm vào, hoặc kéo khung quanh nhiều nội dung).")
                return
            self._clip = {"specs": specs, "page": page, "doc": id(tab.doc)}
            md = QMimeData()
            md.setData(mime, _json.dumps({"specs": specs}).encode())
            md.setText(" ".join(sp.get("text", "") for sp in specs if sp.get("text")))
            QApplication.clipboard().setMimeData(md)
            if act == "cut":
                tab.view.delete_placement()
                self._flash(f"Đã cắt {len(specs)} nội dung – Ctrl+V để dán.")
                return
            if act == "copy":
                self._flash(f"Đã sao chép {len(specs)} nội dung – Ctrl+V để dán (cả sang trang / file khác).")
                return
        clip = getattr(self, "_clip", None)
        md = QApplication.clipboard().mimeData()
        if md is not None and md.hasFormat(mime):
            try:
                clip = dict(clip or {}, specs=_json.loads(bytes(md.data(mime)).decode())["specs"])
            except Exception:
                pass
        if not clip or not clip.get("specs"):
            return
        if tab.view.placement is not None:
            tab.view.commit_placement()
        if not self._writable(tab, "Dán nội dung"):
            return
        page = tab.view.current_page()
        same = clip.get("doc") == id(tab.doc) and clip.get("page") == page
        new = items.paste_items(tab.doc, page, clip["specs"], *((12, 12) if same else (0, 0)))
        tab.refresh()
        self._update_state()
        self._flash(f"Đã {'nhân bản' if act == 'dup' else 'dán'} {len(new)} nội dung. Ctrl+Z để hoàn tác.")
        if len(new) == 1:
            it = items.get_item(tab.doc, page, new[0]["id"])
            if it:
                self._select_item(tab, page, it)
        else:
            group = [x for x in items.find_items(tab.doc, page) if x.id in {s["id"] for s in new}]
            if len(group) > 1:
                self._select_group(tab, page, group)

    # --- ghi chú (12a) ---
    def _select_note(self, tab, page, n):
        from . import notes
        from .ui_edit import pil_to_qimage
        doc = tab.doc
        if not n.is_sticky or not doc.can_modify or doc.signature_count() or n.reply_to:
            # tô sáng / hộp chữ của phần mềm khác, hoặc file đã ký / bị khóa: mở ra đọc (sửa khi bấm Lưu)
            self._edit_note_dialog(tab, page, n.nm)
            return
        notes.set_hidden(doc, page, n.nm, True)
        tab.view.document_changed()
        img = pil_to_qimage(notes.icon_image(n.icon, n.color, n.done, n.opacity, 60))
        state = {"done": False}

        def unhide():
            if not state["done"]:
                state["done"] = True
                notes.set_hidden(doc, page, n.nm, False)

        def commit(pg, rect):
            unhide()
            if abs(rect[0] - n.rect[0]) > 0.5 or abs(rect[1] - n.rect[1]) > 0.5:
                notes.move_note(doc, page, n.nm, rect[0], rect[1])
                self._flash("Đã dời ghi chú. Ctrl+Z để hoàn tác.")
            tab.refresh()
            self._update_state()

        def delete():
            unhide()
            notes.delete_note(doc, page, n.nm)
            tab.refresh()
            self._update_state()
            self._flash("Đã xóa ghi chú. Ctrl+Z để hoàn tác.")

        def cancel():
            unhide()
            tab.refresh()

        def open_dialog(_pl=None):
            tab.view.cancel_placement()
            self._edit_note_dialog(tab, page, n.nm)
        w = n.rect[2] - n.rect[0]
        rect = (n.rect[0], n.rect[1], n.rect[0] + w * 23 / 20, n.rect[3])
        pl = tab.view.begin_edit(img, page, rect, commit, delete, cancel, "Ghi chú", resizable=False,
                                 commit_outside=True)
        pl.on_click = open_dialog
        pl.on_dblclick = open_dialog
        pl.hint = "Ghi chú · kéo để dời · bấm để mở / sửa · Delete: xóa · Esc: thôi"

    def _edit_note_dialog(self, tab, page, nm):
        from . import notes
        from .ui_edit import NoteDialog
        doc = tab.doc
        n = next((x for x in notes.list_notes(doc, [page]) if x.nm == nm), None)
        if n is None:
            n = next((r for x in notes.list_notes(doc, [page]) for r in x.replies if r.nm == nm), None)
        if n is None:
            return
        me = self.settings.value("note/author", "") or os.environ.get("USERNAME", "")
        dlg = NoteDialog(self, me, note=n, settings=self.settings, readonly=not doc.can_modify)
        if dlg.exec() != NoteDialog.Accepted or not doc.can_modify:
            return
        v = dlg.values()
        changed = (v["action"] == "delete" or v["reply"] or v["text"] != n.text or v["author"] != n.author or
                   v["done"] != n.done or (n.is_sticky and (v["color"] != n.color or v["icon"] != n.icon or
                                                            v["opacity"] != n.opacity)))
        if not changed or not self._writable(tab, "Sửa ghi chú"):
            return
        if v["action"] == "delete":
            notes.delete_note(doc, page, nm)
            self._flash("Đã xóa ghi chú. Ctrl+Z để hoàn tác.")
        else:
            doc._snapshot()
            notes.update_note(doc, page, nm, v["text"], v["author"], v["color"], v["icon"], v["opacity"], v["done"],
                              snapshot=False)
            if v["reply"]:
                notes.add_note(doc, page, n.rect[0], n.rect[1], v["reply"], me, n.color, "comment", 100,
                               reply_to=nm, snapshot=False)
            doc._changed()
            self._flash("Đã cập nhật ghi chú. Ctrl+Z để hoàn tác.")
        tab.refresh()
        self._update_state()

    # --- danh sách ghi chú (12b) ---
    def toggle_notes_panel(self, show: bool | None = None):
        p = self.notes_panel
        show = (not p.isVisible()) if show is None else show
        p.setVisible(show)
        if show:
            self._refresh_notes()

    def _refresh_notes(self):
        from . import notes
        p = getattr(self, "notes_panel", None)
        if p is None or not p.isVisible():
            return
        tab = self.current()
        try:
            p.set_notes(notes.list_notes(tab.doc) if tab else [])
        except Exception:
            p.set_notes([])

    def show_notes_on_page(self, on: bool):
        """12e – ẩn / hiện biểu tượng ghi chú khi xem (mọi tab; không đổi nội dung file)."""
        for k in range(self.tabs.count()):
            w = self.tabs.widget(k)
            if isinstance(w, DocTab):
                w.doc.hide_notes = not on
                w.view.document_changed()
        self._flash("Đã hiện biểu tượng ghi chú." if on else "Đã ẩn biểu tượng ghi chú (file không đổi).")

    def export_notes(self, kind: str) -> str | None:
        """12c – xuất tổng hợp ghi chú (theo bộ lọc đang chọn) ra Excel / PDF."""
        from . import notes
        if not self.edition_ok("notes_export"):
            return None
        tab = self.current()
        if not tab:
            return None
        lst = self.notes_panel.filtered() if self.notes_panel.isVisible() else notes.list_notes(tab.doc)
        if not lst:
            self._flash("Không có ghi chú nào để xuất.")
            return None
        base = os.path.splitext(tab.doc.name)[0]
        start = os.path.join(getattr(tab, "save_dir", None) or os.path.dirname(tab.doc.path or "") or
                             os.path.expanduser("~"), f"{base}_ghi-chu.{kind}")
        path = getattr(self, "_export_path", None) or QFileDialog.getSaveFileName(
            self, "Xuất tổng hợp ghi chú", start, "Excel (*.xlsx)" if kind == "xlsx" else "PDF (*.pdf)")[0]
        self._export_path = None
        if not path:
            return None
        title = f"Tổng hợp ghi chú – {tab.doc.name}"
        try:
            (notes.export_xlsx if kind == "xlsx" else notes.export_pdf)(lst, path, title)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không xuất được:\n{e}")
            return None
        self._flash(f"Đã xuất {len(lst)} ghi chú: {path}")
        return path

    def _note_goto(self, page, nm):
        from . import notes
        tab = self.current()
        if not tab:
            return
        tab.view.go_to(page)
        n = notes.get_note(tab.doc, page, nm)
        if n is not None:
            r = tab.view._rects[page]
            tab.view.verticalScrollBar().setValue(int(r.top() + n.rect[1] * tab.view.scale - 120))

    def _note_reply(self, page, nm):
        from . import notes
        from .ui_edit import NoteDialog
        tab = self.current()
        if not tab or not self._writable(tab, "Trả lời ghi chú"):
            return
        n = next((x for x in notes.list_notes(tab.doc, [page]) if x.nm == nm), None)
        if n is None:
            return
        me = self.settings.value("note/author", "") or os.environ.get("USERNAME", "")
        dlg = NoteDialog(self, me, note=n, reply_mode=True)
        if dlg.exec() != NoteDialog.Accepted:
            return
        v = dlg.values()
        self.settings.setValue("note/author", v["author"])
        notes.add_note(tab.doc, page, n.rect[0], n.rect[1], v["text"], v["author"], n.color, "comment",
                       reply_to=nm)
        tab.refresh()
        self._update_state()
        self._flash("Đã trả lời ghi chú.")

    def _note_toggle_done(self, page, nm):
        from . import notes
        tab = self.current()
        if not tab or not self._writable(tab, "Đánh dấu ghi chú"):
            return
        n = notes.get_note(tab.doc, page, nm)
        if n is None:
            return
        notes.update_note(tab.doc, page, nm, done=not n.done)
        tab.refresh()
        self._update_state()
        self._flash("Đã đánh dấu đã xử lý." if not n.done else "Đã bỏ đánh dấu đã xử lý.")

    def _note_delete(self, page, nm):
        from . import notes
        tab = self.current()
        if not tab or not self._writable(tab, "Xóa ghi chú"):
            return
        notes.delete_note(tab.doc, page, nm)
        tab.refresh()
        self._update_state()
        self._flash("Đã xóa ghi chú. Ctrl+Z để hoàn tác.")

    # --- ảnh / con dấu / chữ ký đã chèn ---
    def _select_image(self, tab, page, info):
        from . import editing
        from .ui_edit import pil_to_qimage
        if not self._writable(tab, "Sửa ảnh đã chèn"):
            return
        try:
            fr = editing.image_frame(tab.doc, page, info.index)    # khung chưa xoay + góc (None: ảnh bị lật)
            raw = editing.image_preview(tab.doc, page, info.index, upright=fr is not None)
            preview = pil_to_qimage(raw)
        except Exception:
            return
        cur_layer = editing.image_layer(tab.doc, page, info.index)
        ed = editing.ObjectEdit(tab.doc, page, info)
        rect0, ang0, rotatable = info.rect, 0.0, fr is not None
        if fr is not None:
            rect0, ang0 = fr
        tab.view.document_changed()

        def done(_=None, rect=None):
            tab.refresh()
            self._update_state()

        def commit(pg, rect, angle=None):
            if pg != page:                       # kéo sang trang khác: giữ trang cũ, chỉ đổi vị trí
                pw, ph = tab.doc.page_size_pt(page)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                rect = (min(rect[0], pw - w), min(rect[1], ph - h), min(rect[0], pw - w) + w, min(rect[1], ph - h) + h)
            o = self.img_opts
            note = ""
            if o.edit_changed():                 # đổi lớp / độ đậm: đặt lại ảnh (vẫn 1 bước hoàn tác)
                from .ui_edit import process_image
                from .viewer import rotated_bbox
                src = process_image(pil_to_qimage(raw), o.opacity)
                ed.delete()
                argb = src.convertToFormat(src.Format.Format_ARGB32)
                ang = float(angle or 0)
                tab.doc.insert_image(page, rotated_bbox(rect, ang), bytes(argb.constBits()), argb.width(),
                                     argb.height(), argb.bytesPerLine(), order="bgra", snapshot=False,
                                     layer=o.layer, angle=ang)
                note = self._layer_note(tab.doc, page, o.layer)
            elif angle is not None:
                ed.commit(rect, angle)
            else:
                ed.commit(rect)
            done()
            self._flash(note or "Đã cập nhật ảnh. Ctrl+Z để hoàn tác.")

        def delete():
            ed.delete()
            done()
            self._flash("Đã xóa ảnh. Ctrl+Z để hoàn tác.")

        def cancel():
            ed.cancel()
            done()
        self._img_ctx = {"tab": tab, "base": preview, "preview_base": preview, "edit": True}
        self.img_opts.show_for("Ảnh đã chèn", edit=True, current_layer=cur_layer, angle=ang0,
                               rotate=rotatable)
        pl = tab.view.begin_edit(preview, page, rect0, commit, delete, cancel, "Ảnh đã chèn", angle=ang0,
                                 rotatable=rotatable)
        pl.on_change = lambda p: self.img_opts.set_angle(p.angle)
        self._flash("Kéo để di chuyển, kéo góc đổi cỡ, kéo núm tròn để xoay, Delete để xóa, Enter để xong, "
                    "Esc để giữ nguyên.")

    # ---------- giai đoạn 6: bảo vệ, công cụ ----------
    def _writable(self, tab, action: str | None = None) -> bool:
        """Được sửa nội dung không? Chặn file được bảo vệ; cảnh báo rõ khi file đã có chữ ký số (của đối tác...)."""
        if not tab.doc.can_modify:
            QMessageBox.information(self, APP_NAME, "Tài liệu này được người gửi bảo vệ: chỉ cho xem"
                                    + (", in" if tab.doc.can_print else "") + ".\nKhông sửa được nội dung. Nếu bạn là chủ "
                                    "sở hữu, dùng Bảo vệ → Mật khẩu để gỡ bảo vệ bằng mật khẩu chủ sở hữu.")
            return False
        if action and not tab.sig_ack:
            if tab.sig_state is None and tab.doc.signature_count():
                self._analyze_sigs(tab)
            if tab.sig_state is not None:
                choice, dont_ask = self._ask_signed_edit(tab, action)
                if choice == "sign":
                    self.digital_sign(tab)
                    return False
                if choice != "go":
                    self._flash("Đã hủy – giữ nguyên chữ ký số trong file.")
                    return False
                tab.sig_ack = dont_ask
        return True

    def _signed_edit_text(self, tab, action: str) -> tuple[str, str]:
        st = tab.sig_state
        head = f"<b>{action}</b> sẽ thay đổi nội dung file đã có <b>{st.short()}</b>."
        if st.locked:
            body = (f"⛔ File đã được <b>KHÓA</b> bởi chữ ký của <b>{st.locked_by}</b> (không cho phép bất kỳ thay đổi "
                    "nào sau khi ký). Nếu tiếp tục, chữ ký đó sẽ <b>mất hiệu lực</b> và bạn cũng không ký thêm được.")
        elif st.invalid:
            body = (f"⛔ Chữ ký của <b>{', '.join(st.invalid)}</b> hiện đã <b>KHÔNG HỢP LỆ</b> (file bị sửa sau khi ký). "
                    "Nên đề nghị bên gửi cung cấp lại bản gốc trước khi làm tiếp.")
        else:
            body = ("⚠ Sau khi sửa và lưu, các chữ ký này sẽ báo <b>KHÔNG HỢP LỆ</b> (“tài liệu đã bị sửa sau khi ký”) "
                    "khi đối tác hoặc cơ quan kiểm tra.")
        tip = ("<br><br>Muốn thêm con dấu / chữ ký của mình mà vẫn giữ chữ ký của đối tác: dùng <b>Ký số</b> và chọn "
               "con dấu, chữ ký trong khung ký số (hoặc ký vào ô đã chuẩn bị bằng Luồng ký).")
        return head, body + ("" if st.locked else tip)

    def _ask_signed_edit(self, tab, action: str) -> tuple[str, bool]:
        """Hỏi trước khi sửa file đã ký số. Trả về ("cancel" | "sign" | "go", không_hỏi_lại)."""
        from PySide6.QtWidgets import QCheckBox
        head, body = self._signed_edit_text(tab, action)
        box = QMessageBox(QMessageBox.Warning, "Cảnh báo – file đã có chữ ký số", head, parent=self)
        box.setTextFormat(Qt.RichText)
        box.setInformativeText(body)
        b_cancel = box.addButton("Hủy – giữ nguyên chữ ký", QMessageBox.RejectRole)
        b_sign = None
        if not tab.sig_state.locked and tab.doc.can_modify:
            b_sign = box.addButton("Ký số (giữ chữ ký của đối tác)…", QMessageBox.ActionRole)
        b_go = box.addButton("Vẫn sửa (chữ ký sẽ mất hiệu lực)", QMessageBox.DestructiveRole)
        box.setDefaultButton(b_cancel)
        box.setEscapeButton(b_cancel)
        chk = QCheckBox("Không hỏi lại với file này trong lần mở này")
        box.setCheckBox(chk)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_go:
            return "go", chk.isChecked()
        if b_sign is not None and clicked is b_sign:
            return "sign", False
        return "cancel", False

    def _analyze_sigs(self, tab):
        """Đọc tình trạng chữ ký số có sẵn (chỉ khi file có chữ ký) -> dải cảnh báo + hỏi trước khi sửa/ký."""
        from .signing import analyze_signatures
        doc = tab.doc
        tab.sig_state = None
        if not doc.signature_count():
            return None
        try:
            if doc.path and not doc.modified and os.path.exists(doc.path):
                with open(doc.path, "rb") as f:
                    data = f.read()
            else:
                data = doc.to_bytes()
            tab.sig_state = analyze_signatures(data)
        except Exception:
            tab.sig_state = None
        return tab.sig_state

    def _refresh_banner(self, tab):
        doc, st, b = tab.doc, tab.sig_state, tab.banner
        parts, level, buttons = [], "", []
        if not doc.can_modify:
            level = "warn"
            parts.append("<b>File được người gửi bảo vệ</b>: chỉ cho xem" + (", in" if doc.can_print else "") +
                         ". Không sửa, đóng dấu, chèn được nội dung.")
            if doc.encrypted:
                buttons.append("unprotect")
        if st is not None:
            buttons.append("verify")
            if st.invalid:
                level = "danger"
                parts.append(f"<b>Chữ ký KHÔNG HỢP LỆ: {', '.join(st.invalid)}</b> – nội dung đã bị thay đổi sau khi ký "
                             "hoặc chữ ký bị hỏng. Không nên ký hay đóng dấu lên bản này; đề nghị bên gửi cung cấp lại "
                             "bản gốc.")
            elif doc.modified:
                level = "danger"
                parts.append(f"<b>Bạn đã sửa nội dung file đã ký số</b> ({st.short()}). Nếu lưu, các chữ ký này sẽ báo "
                             "KHÔNG HỢP LỆ. Nhấn Ctrl+Z để hoàn tác, hoặc đóng tab và chọn không lưu.")
            elif st.locked:
                level = "danger"
                parts.append(f"<b>File đã được KHÓA</b> bởi chữ ký của <b>{st.locked_by}</b>: không cho sửa và không "
                             "ký thêm được. Mọi thay đổi sẽ làm chữ ký này mất hiệu lực.")
            else:
                level = level or "warn"
                lock = (f" {st.forms_only_by} đã ký chứng nhận: chỉ cho ký thêm, điền biểu mẫu." if st.forms_only_by
                        else "")
                parts.append(f"File đã có <b>{st.short()}</b>.{lock} <b>Không đóng dấu, chèn ảnh, sửa chữ, thêm/xóa/"
                             "xoay trang</b> – chữ ký sẽ báo không hợp lệ. Muốn đóng dấu của mình: bấm <b>Ký số</b> và "
                             "chọn con dấu trong khung ký.")
                if doc.can_modify:
                    buttons.append("sign")
            if st.untrusted and not st.invalid:
                parts.append(f"<i>Chưa xác minh được nhà cung cấp chứng thư của {', '.join(st.untrusted)} (máy thiếu "
                             "chứng thư gốc) – nội dung vẫn nguyên vẹn.</i>")
        if parts:
            b.show_message(level, "<br>".join(parts), buttons)
        else:
            b.clear()

    def _doc_bytes(self, tab) -> bytes:
        d = tab.doc
        if d.path and not d.modified and os.path.exists(d.path):
            with open(d.path, "rb") as f:
                return f.read()
        return d.to_bytes()

    def _ask_save_path(self, tab, suffix: str, title: str) -> str | None:
        base = tab.doc.path or os.path.join(self.settings.value("last_dir", "") or "", getattr(tab, "title", None) or tab.doc.name)
        stem = os.path.splitext(base)[0]
        path, _ = QFileDialog.getSaveFileName(self, title, stem + suffix + ".pdf", "PDF (*.pdf)")
        if not path:
            return None
        return path if path.lower().endswith(".pdf") else path + ".pdf"

    def protect_doc(self, tab, focus: str = ""):
        from .protect import ProtectError, protect_pdf
        from .signing import write_atomic
        from .ui_sign import busy
        from .ui_tools import ProtectDialog
        if tab.doc.encrypted:
            QMessageBox.information(self, APP_NAME, "Tài liệu đã được bảo vệ. Muốn đổi quyền, hãy gỡ bảo vệ trước "
                                    "(Bảo vệ → Mật khẩu).")
            return
        data = self._doc_bytes(tab)
        dlg = ProtectDialog(self, self.settings, tab.doc.page_count, focus)
        if dlg.exec() != ProtectDialog.Accepted:
            return
        opts = dlg.options()
        path = self._ask_save_path(tab, "_bao_ve", "Lưu bản có bảo vệ")
        if not path:
            return
        try:
            out, _owner = busy(self, "Đang tạo bản có bảo vệ…", lambda: protect_pdf(data, opts))
            write_atomic(path, out)
        except ProtectError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không tạo được bản bảo vệ:\n{e}")
            return
        self.last_output = path
        self._flash(f"Đã lưu bản có bảo vệ: {os.path.basename(path)} ({len(out) // 1024} KB)")

    def password_doc(self, tab):
        from .protect import ProtectError, remove_protection
        from .signing import write_atomic
        if not tab.doc.encrypted:
            self.protect_doc(tab, focus="password")
            return
        if tab.doc.signature_count() and QMessageBox.question(
                self, APP_NAME, "File này có chữ ký số. Bản đã gỡ bảo vệ là file mới, KHÔNG còn chữ ký số hợp lệ. File "
                "gốc vẫn giữ nguyên.\n\nTiếp tục?") != QMessageBox.Yes:
            return
        pw, ok = QInputDialog.getText(self, "Gỡ bảo vệ", "Nhập mật khẩu chủ sở hữu:", QLineEdit.Password)
        if not ok:
            return
        try:
            out = remove_protection(self._doc_bytes(tab), pw)
        except ProtectError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        path = self._ask_save_path(tab, "_go_bao_ve", "Lưu bản đã gỡ bảo vệ")
        if not path:
            return
        write_atomic(path, out)
        self.open_files([path])
        self._flash("Đã gỡ bảo vệ.")

    def compress_doc(self, tab):
        from .signing import write_atomic
        from .tools import compress_to_size
        from .ui_sign import busy
        from .ui_tools import CompressDialog
        data = self._doc_bytes(tab)
        if b"/ByteRange" in data and tab.doc.signature_count():
            who = f" của {', '.join(tab.sig_state.names)}" if tab.sig_state else ""
            if QMessageBox.question(self, "Cảnh báo – file đã ký số",
                                    f"File này có chữ ký số{who}. Bản nén là file mới, chữ ký số trong đó sẽ MẤT HIỆU "
                                    "LỰC (file gốc vẫn giữ nguyên).\n\nVẫn nén?") != QMessageBox.Yes:
                return
        dlg = CompressDialog(self, len(data))
        if dlg.exec() != CompressDialog.Accepted:
            return
        v = dlg.values()
        out, desc = busy(self, "Đang nén…", lambda: compress_to_size(data, v["target"], v["gray"], v["level"]))
        if len(out) >= len(data):
            QMessageBox.information(self, APP_NAME, "File đã gọn, không nén thêm được (thường là file văn bản không có "
                                    "ảnh scan).")
            return
        if v["target"] and len(out) > v["target"]:
            QMessageBox.information(self, APP_NAME, f"Đã nén tối đa nhưng vẫn còn {len(out) / 1048576:.2f} MB (chưa đạt "
                                    "mức mong muốn). Có thể thử thang xám hoặc tách file.")
        path = self._ask_save_path(tab, "_nen", "Lưu bản đã nén")
        if not path:
            return
        write_atomic(path, out)
        self.last_output = path
        self._flash(f"Đã nén {len(data) // 1024} KB → {len(out) // 1024} KB ({desc}): {os.path.basename(path)}")

    def compare_doc(self, tab, other_path: str | None = None):
        from .tools import compare_docs, make_compare_report
        from .ui_sign import busy
        from .ui_tools import CompareDialog
        if other_path is None:
            other_path, _ = QFileDialog.getOpenFileName(self, "Chọn bản CŨ để so với bản đang mở", "", "PDF (*.pdf)")
            if not other_path:
                return
        try:
            old = PdfDocument(other_path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không mở được file:\n{e}")
            return
        diffs, summary = busy(self, "Đang so sánh…", lambda: compare_docs(old, tab.doc))
        self.last_compare = (diffs, summary)

        def report():
            rep = make_compare_report(old, tab.doc, diffs, summary)
            self.add_document(rep, "So_sanh_" + tab.doc.name)
        dlg = CompareDialog(self, diffs, summary, tab.view.go_to, report)
        dlg.exec()

    def stamp_text_doc(self, tab):
        from .tools import text_stamp
        from .ui_tools import StampTextDialog
        sel = tab.thumbs.selected_pages()
        dlg = StampTextDialog(self, len(sel) > 1)
        if dlg.exec() != StampTextDialog.Accepted:
            return
        v = dlg.values()
        pages = {"all": list(range(tab.doc.page_count)), "current": [tab.view.current_page()],
                 "selected": sel}[v["scope"]]
        text_stamp(tab.doc, pages, v["text"], v["style"], v["color"], v["opacity"], position=v["position"])
        tab.refresh()
        self._update_state()
        self._flash(f"Đã đóng dấu chữ “{v['text']}” lên {len(pages)} trang. Ctrl+Z để hoàn tác.")

    def batch_sign(self, files=None):
        from . import signing
        from .document import PdfDocument as _D
        from .ui_sign import LAYOUT_HIDDEN, SignDialog, ask_pin, busy, pin_warning, qimage_to_png
        from .ui_tools import BatchSignDialog
        tab = self.current()
        if files is None:
            files = [tab.doc.path] if tab and tab.doc.path and not tab.doc.modified else []
        bd = BatchSignDialog(self, files, self.settings)
        if bd.exec() != BatchSignDialog.Accepted:
            return
        self._init_library()
        dlg = SignDialog(self, self.library, self.settings)
        dlg.load()
        if dlg.exec() != SignDialog.Accepted:
            return
        v = dlg.values()
        pos = bd.position()
        png = None if pos == "hidden" or v["layout"] == LAYOUT_HIDDEN else qimage_to_png(dlg.appearance())
        w, h = v["size_pt"] or (210, 78)
        items, skipped = [], []
        for src in bd.files():
            try:
                with open(src, "rb") as f:
                    data = f.read()
            except OSError as e:
                skipped.append((src, str(e)))
                continue
            opts = signing.SignOptions(reason=v["reason"], location=v["location"], tsa_url=v["tsa_url"],
                                       ltv=v["ltv"], certify=v["certify"])
            use_auto = pos == "auto"
            if png and pos == "field":
                flds = signing.empty_fields(data)
                if flds:                               # ô ký đã chuẩn bị sẵn
                    opts.field_name, opts.page, opts.appearance_png = flds[0].name, flds[0].page, png
                else:                                  # file không có ô ký -> tự tìm chỗ ký
                    use_auto = True
            if png and use_auto:
                d = _D(data=data)
                try:
                    pg, cx, cy = d.find_sign_spot()
                finally:
                    d.close()
                opts.page, opts.rect_pt, opts.appearance_png = pg, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), png
            items.append((src, bd.output_for(src), opts))
        cert = v["cert"]
        warning = ""
        while True:
            pin = None
            if cert.backend == signing.PKCS11 and not cert.extra.get("protected"):
                pin = ask_pin(self, cert, warning)
                if pin is None:
                    return

            def job():
                signer, close = signing.open_signer(cert, pin, int(self.winId()))
                try:
                    return signing.sign_many(items, signer)
                finally:
                    close()
            try:
                results = busy(self, f"Đang ký {len(items)} file…", job)
                break
            except signing.PinIncorrect as e:
                warning = pin_warning(e)
                if cert.backend != signing.PKCS11:
                    QMessageBox.warning(self, APP_NAME, str(e))
                    return
            except signing.SigningError as e:
                QMessageBox.warning(self, APP_NAME, f"Không ký được:\n{e}")
                return
        ok = [r for r in results if r[1] is None]
        bad = [r for r in results if r[1]] + skipped
        self.last_batch = results
        msg = f"Đã ký {len(ok)}/{len(items) + len(skipped)} file."
        if bad:
            msg += "\n\nKhông ký được:\n" + "\n".join(f"• {os.path.basename(p)}: {e}" for p, e in bad[:12])
        QMessageBox.information(self, APP_NAME, msg)

    def flow_prepare(self, tab):
        from .signing import add_signature_fields, empty_fields, write_atomic
        from .ui_tools import FlowDialog
        if not self._ready_to_sign(tab):
            return
        st = self._analyze_sigs(tab)               # thêm ô ký sau chữ ký có sẵn vẫn hợp lệ (lưu nối tiếp)...
        if st is not None and st.locked:           # ...trừ khi người ký trước đã khóa tài liệu
            QMessageBox.warning(self, "Không thêm được ô ký",
                                f"File đã được KHÓA bởi chữ ký của {st.locked_by} (không cho phép thay đổi sau khi "
                                "ký). Thêm ô ký sẽ làm chữ ký đó mất hiệu lực.\n\nĐề nghị bên gửi cung cấp bản chưa khóa.")
            return
        with open(tab.doc.path, "rb") as f:
            data = f.read()
        existing = [f.name for f in empty_fields(data)]
        dlg = FlowDialog(self, existing)
        if dlg.exec() != FlowDialog.Accepted:
            return
        names = [n for n in dlg.names() if n not in existing]
        specs = []
        page0, cx0, cy0 = tab.doc.find_sign_spot()

        def box_image(name):
            from PySide6.QtGui import QImage, QPainter, QPen
            img = QImage(630, 234, QImage.Format_ARGB32_Premultiplied)
            img.fill(QColor(0, 95, 184, 28))
            p = QPainter(img)
            p.setPen(QPen(QColor("#005fb8"), 4, Qt.DashLine))
            p.drawRect(2, 2, 626, 230)
            f = p.font()
            f.setPixelSize(40)
            p.setFont(f)
            p.drawText(img.rect(), Qt.AlignCenter, f"Ô ký: {name}")
            p.end()
            return img

        def place(k):
            if k >= len(names):
                finish()
                return
            off = (k - (len(names) - 1) / 2) * 220
            tab.view.begin_placement(box_image(names[k]), lambda pg, rect: (specs.append((names[k], pg, rect)),
                                                                            place(k + 1)),
                                     width_pt=200, label=f"Ô ký của “{names[k]}” ({k + 1}/{len(names)})",
                                     page=page0, center_pt=(min(max(cx0 + off, 110), tab.doc.page_size_pt(page0)[0] - 110), cy0))

        def finish():
            if not specs:
                return
            try:
                out = add_signature_fields(data, specs)
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Không tạo được ô ký:\n{e}")
                return
            path = tab.doc.path

            # Làm SAU khi khung đặt ô ký kết thúc hẳn (đang ở trong commit_placement của chính tab này: đóng tài
            # liệu ngay sẽ làm vùng xem vẽ trên tài liệu đã đóng -> Windows báo "access violation").
            # Đóng tab trước rồi mới ghi file: Windows không cho ghi đè file đang mở.
            def write_and_reopen():
                self.close_tab(self.tabs.indexOf(tab))
                if self.tabs.indexOf(tab) >= 0:             # người dùng bấm Hủy khi hỏi lưu
                    return
                try:
                    from .tools import keep_version
                    keep_version(path)
                    write_atomic(path, out)
                except Exception as e:
                    QMessageBox.warning(self, APP_NAME, f"Không tạo được ô ký:\n{e}")
                    self.open_files([path])
                    return
                self.open_files([path])
                self._flash(f"Đã chuẩn bị {len(specs)} ô ký. Gửi file cho từng người: mở file → Ký số → chọn đúng ô "
                            "của mình.")
            QTimer.singleShot(0, write_and_reopen)
        if names:
            self._flash("Đặt lần lượt ô ký của từng người lên trang, Enter để xác nhận từng ô.")
            place(0)

    def batch_excel(self, tab):
        from .tools import batch_from_table, placeholders
        from .ui_sign import busy
        from .ui_tools import BatchExcelDialog
        fields = placeholders(tab.doc)
        if not fields:
            QMessageBox.information(self, APP_NAME, "Mẫu đang mở chưa có chỗ cần điền dạng {{Tên cột}}.\n"
                                    "Hãy soạn mẫu trong Word, gõ {{Họ tên}}, {{Địa chỉ}}… vào chỗ cần điền, in ra PDF rồi "
                                    "mở mẫu đó.")
            return
        dlg = BatchExcelDialog(self, fields)
        if dlg.exec() != BatchExcelDialog.Accepted:
            return
        v = dlg.values()
        tpl = self._doc_bytes(tab)
        made, warns = busy(self, f"Đang tạo {len(v['rows'])} file…",
                           lambda: batch_from_table(tpl, v["head"], v["rows"], v["out"], v["name_col"]))
        self.last_output = v["out"]
        msg = f"Đã tạo {len(made)} file trong thư mục:\n{v['out']}"
        if warns:
            msg += "\n\nLưu ý:\n" + "\n".join(warns[:8])
        QMessageBox.information(self, APP_NAME, msg)

    def history_dialog(self, tab):
        import shutil
        from .tools import keep_version
        from .ui_tools import HistoryDialog
        if not tab.doc.path:
            self._flash("Tài liệu chưa lưu nên chưa có lịch sử.")
            return
        dlg = HistoryDialog(self, tab.doc.path)
        if dlg.exec() != HistoryDialog.Accepted or not dlg.choice:
            return
        act, ver = dlg.choice
        if act == "open":
            with open(ver["file"], "rb") as f:
                d = PdfDocument(data=f.read())
            self.add_document(d, f"(Bản cũ {ver['label']}) {tab.doc.name}")
            return
        if QMessageBox.question(self, APP_NAME, f"Khôi phục bản lưu lúc {ver['label']}? Bản hiện tại sẽ được cất "
                                "vào lịch sử.") != QMessageBox.Yes:
            return
        path = tab.doc.path
        tab.doc.modified = False
        self.close_tab(self.tabs.indexOf(tab))
        keep_version(path)
        shutil.copy2(ver["file"], path)
        self.open_files([path])
        self._flash("Đã khôi phục phiên bản cũ.")

    def _settings_dict(self) -> dict:
        st = self.settings
        if hasattr(st, "allKeys"):
            return {k: st.value(k) for k in st.allKeys() if not k.startswith("sign/known_libs")}
        return {k: v for k, v in dict(st).items() if not str(k).startswith("sign/known_libs")}

    def backup_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Sao lưu thư viện dấu, mẫu, cài đặt…", self.do_backup)
        m.addAction("Khôi phục từ bản sao lưu…", self.do_restore)
        self._last_menu = m
        btn = next((b for b, ic, c, _ in self.tool_buttons if c == "backup" and b.isVisible()), None)
        m.popup(btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.cursor().pos())
        return m

    def do_backup(self, path: str | None = None):
        import time as _t
        from .tools import backup
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Lưu bản sao lưu", _t.strftime("PdfKySo_saoluu_%Y%m%d.zip"),
                                                  "Sao lưu (*.zip)")
            if not path:
                return
        names = backup(path, self._settings_dict())
        self._flash(f"Đã sao lưu {len(names)} mục vào {os.path.basename(path)}")
        return path

    def do_restore(self, path: str | None = None):
        from .tools import restore
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn bản sao lưu", "", "Sao lưu (*.zip)")
            if not path:
                return
        try:
            st = restore(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không khôi phục được:\n{e}")
            return
        for k, val in st.items():
            self.settings.setValue(k, val)
        if self.library is not None:
            from .library import Library
            self.library, _ = Library.open_safe(self.library.path)
            self.lib_panel.lib = self.library
            self.lib_panel.refresh()
        QMessageBox.information(self, APP_NAME, "Đã khôi phục thư viện dấu và cài đặt. Nếu thư viện có mật khẩu, "
                                "dùng mật khẩu cũ để mở. Bản quyền cần kích hoạt lại trên máy mới.")

    def autofolder_dialog(self):
        from .autofolder import AutoConfig
        from .ui_tools import AutoFolderDialog
        cfg = AutoConfig.from_json(self.settings.value("auto/config"))
        dlg = AutoFolderDialog(self, cfg, self.settings)
        if dlg.exec() != AutoFolderDialog.Accepted:
            return
        cfg = dlg.config()
        self.settings.setValue("auto/config", cfg.to_json())
        self.start_autofolder()
        self._flash(f"Thư mục tự xử lý: {'BẬT' if cfg.enabled else 'tắt'} – {cfg.summary()}")

    def start_autofolder(self):
        from .autofolder import AutoConfig, Watcher
        cfg = AutoConfig.from_json(self.settings.value("auto/config"))
        timer = getattr(self, "_auto_timer", None)
        if timer:
            timer.stop()
        self.auto_watcher = None
        if not cfg.enabled or not cfg.folder or not self.edition_ok("autofolder", ask=False):
            return
        self.auto_watcher = Watcher(cfg, on_done=lambda s, o: self._flash(f"Tự xử lý xong: {os.path.basename(o)}"),
                                    on_error=lambda s, e: self._flash(f"Lỗi tự xử lý {os.path.basename(s)}: {e}"))
        self._auto_timer = QTimer(self, interval=3000, timeout=self.auto_watcher.scan)
        self._auto_timer.start()

    # ---------- giai đoạn 4: ký số bằng USB token ----------
    def _ready_to_sign(self, tab: "DocTab") -> bool:
        """Ký trên đúng bytes của file đã lưu (giữ nguyên chữ ký cũ nếu có)."""
        doc = tab.doc
        if doc.path and not doc.modified and os.path.exists(doc.path):
            return True
        r = QMessageBox.question(self, APP_NAME, "Cần lưu tài liệu trước khi ký số. Lưu ngay?",
                                 QMessageBox.Yes | QMessageBox.No)
        return r == QMessageBox.Yes and self.save(tab) and bool(doc.path)

    def _sign_output(self, tab: "DocTab") -> str | None:
        from .signing import default_output
        src = tab.doc.path
        if getattr(tab, "from_spool", False):        # bản in từ máy in ảo: hỏi nơi lưu
            base = os.path.join(self.settings.value("last_dir", "") or os.path.expanduser("~"),
                                os.path.basename(default_output(src)))
            path, _ = QFileDialog.getSaveFileName(self, "Lưu file đã ký", base, "PDF (*.pdf)")
            if not path:
                return None
            return path if path.lower().endswith(".pdf") else path + ".pdf"
        return default_output(src)

    def _check_before_sign(self, tab) -> bool:
        """File đối tác gửi đã có chữ ký: báo rõ trước khi ký tiếp (đã khóa -> không ký; chữ ký hỏng -> hỏi)."""
        st = self._analyze_sigs(tab)
        self._refresh_banner(tab)
        if st is None:
            return True
        if st.locked:
            QMessageBox.warning(self, "Không ký được – tài liệu đã bị khóa",
                                f"File đã được KHÓA bởi chữ ký của {st.locked_by}: người ký đã chọn “không cho phép "
                                "thay đổi sau khi ký”, nên không thể ký thêm mà không làm chữ ký đó mất hiệu lực.\n\n"
                                "Đề nghị bên gửi cung cấp bản chưa khóa (bỏ tùy chọn khóa tài liệu khi ký) để các bên "
                                "cùng ký.")
            return False
        if st.invalid:
            r = QMessageBox.warning(self, "Cảnh báo – chữ ký có sẵn không hợp lệ",
                                    f"Chữ ký của {', '.join(st.invalid)} trong file này đã KHÔNG HỢP LỆ (file bị sửa "
                                    "sau khi ký hoặc chữ ký hỏng).\n\nKý tiếp không làm chữ ký đó hợp lệ lại; người nhận "
                                    "vẫn thấy cảnh báo. Nên đề nghị bên gửi cung cấp lại bản gốc.\n\nVẫn ký?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return r == QMessageBox.Yes
        self._flash(f"File đã có {st.short()}. Chữ ký của bạn được thêm nối tiếp – chữ ký cũ vẫn giữ hiệu lực.")
        return True

    def digital_sign(self, tab: "DocTab | None" = None):
        from .ui_sign import LAYOUT_HIDDEN, SignDialog
        from .ui_library import unlock_if_needed
        tab = tab or self.current()
        if not tab:
            self._flash("Hãy mở một file PDF trước.")
            return
        if tab.view.placement is not None:
            tab.view.cancel_placement()
        if not self._ready_to_sign(tab):
            return
        if not self._check_before_sign(tab):
            return
        self._init_library()
        lib = self.library
        if lib is not None and lib.locked:
            unlock_if_needed(self, lib)                  # hủy thì vẫn ký được, chỉ không có ảnh dấu
        from .signing import empty_fields
        try:
            with open(tab.doc.path, "rb") as f:
                fields = empty_fields(f.read())
        except OSError:
            fields = []
        dlg = SignDialog(self, lib, self.settings, fields=fields, page_count=tab.doc.page_count,
                         current_page=tab.view.current_page())
        dlg.load()
        if dlg.exec() != SignDialog.Accepted:
            return
        v = dlg.values()
        if v.get("field_name"):                       # ký vào ô đã chuẩn bị sẵn
            fld = next(f for f in fields if f.name == v["field_name"])
            self._do_sign(tab, v, fld.page, None, None if v["layout"] == LAYOUT_HIDDEN else dlg)
            return
        if v["layout"] == LAYOUT_HIDDEN:
            self._do_sign(tab, v, 0, None, None)
            return
        img = dlg.appearance()
        mode, want = v.get("page_mode", "auto"), v.get("page", -1)
        if mode == "keyword" and v.get("keyword"):      # 4c: tìm theo cụm chữ người dùng nhập, từ trang cuối lên
            page, cx, cy, found = tab.doc.find_text_spot(v["keyword"])
            if not found:
                self._flash(f"Không thấy “{v['keyword']}” trong tài liệu – đặt khung ở trang cuối, kéo tới chỗ ký.")
        else:
            page, cx, cy = tab.doc.find_sign_spot(page=None if mode in ("auto", "keyword") or want < 0 else want)
        tab.view.go_to(page)
        self._flash("Kéo khung ký tới chỗ cần ký (bấm vào trang khác để chuyển khung sang trang đó), kéo góc để đổi cỡ, Enter hoặc nháy đúp để ký, Esc để hủy.")
        tab.view.begin_placement(img, lambda pg, rect: self._do_sign(tab, v, pg, rect, dlg),
                                 width_pt=v["size_pt"][0], label="Khung ký số", page=page, center_pt=(cx, cy))

    def _do_sign(self, tab: "DocTab", v: dict, page: int, rect, dlg=None):
        from .signing import SignOptions, write_atomic
        from .ui_sign import qimage_to_png, sign_with_ui
        png = None
        if dlg is not None and (rect is not None or v.get("field_name")):
            png = qimage_to_png(dlg.appearance())        # dựng lại để giờ ký trên khung là giờ thật
        out_path = self._sign_output(tab)
        if not out_path:
            return
        try:
            with open(tab.doc.path, "rb") as f:
                data = f.read()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Không đọc được file:\n{e}")
            return
        owner = ""
        from .signing import is_encrypted
        if is_encrypted(data):                      # file đã "Lưu có bảo vệ"
            owner, ok = QInputDialog.getText(self, "File được bảo vệ",
                                             "Nhập mật khẩu chủ sở hữu (đã đặt khi bảo vệ file) để ký số:",
                                             QLineEdit.Password)
            if not ok:
                return
        opts = SignOptions(page=page, rect_pt=rect, appearance_png=png, reason=v["reason"],
                           location=v["location"], tsa_url=v["tsa_url"], ltv=v["ltv"], certify=v["certify"],
                           owner_password=owner, field_name=v.get("field_name", ""))
        signed = sign_with_ui(self, v["cert"], data, opts, hwnd=int(self.winId()))
        if not signed:
            return
        try:
            write_atomic(out_path, signed)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Đã ký nhưng không lưu được file:\n{out_path}\n\n{e}\n\n"
                                "Hãy đóng file nếu đang mở ở phần mềm khác rồi ký lại.")
            return
        if rect is not None and self.library is not None and not self.library.locked:
            from .library import log_usage
            for iid in (v.get("stamp_id"), v.get("sig_id")):
                if iid:
                    try:
                        log_usage(self.library.get(iid), out_path, [page], "ký số")
                    except Exception:
                        pass
        self.remember_cert(v["cert"])
        before = tab.sig_state
        self.open_files([out_path])
        self._update_state()
        new_tab = self.current()
        msg = f"Đã ký số thành công: {os.path.basename(out_path)}"
        if before is not None and new_tab is not None and new_tab.sig_state is not None:
            broken = [n for n in new_tab.sig_state.invalid if n not in before.invalid]
            if broken:
                QMessageBox.warning(self, APP_NAME, "Đã ký, nhưng chữ ký có sẵn sau đây báo KHÔNG HỢP LỆ: "
                                    + ", ".join(broken) + ".\nHãy kiểm tra lại (Ký & Dấu → Kiểm tra chữ ký).")
            else:
                msg += f" · Chữ ký có sẵn ({', '.join(before.names)}) vẫn hợp lệ."
        self._flash(msg)

    def verify_doc(self, tab: "DocTab"):
        from .signing import verify_pdf
        from .ui_sign import VerifyDialog, busy
        doc = tab.doc
        if doc.path and os.path.exists(doc.path) and not doc.modified:
            with open(doc.path, "rb") as f:
                data = f.read()
        else:
            data = doc.to_bytes()
        try:
            reports = busy(self, "Đang kiểm tra chữ ký…", lambda: verify_pdf(data))
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Không kiểm tra được:\n{e}")
            return
        self.last_verify = reports
        VerifyDialog(self, reports, doc.name).exec()

    # ---------- bản khôi phục sau sự cố ----------
    def enable_recovery(self, folder: str | None = None):
        from .stability import Recovery
        self.recovery = Recovery(self._recovery_docs, folder, self)
        pending = self.recovery.pending()
        if not pending:
            return
        names = "\n".join(f"• {d.get('title') or os.path.basename(d.get('path') or '')}" for d in pending)
        r = QMessageBox.question(self, APP_NAME, "Lần trước phần mềm bị tắt đột ngột khi còn tài liệu chưa lưu:\n"
                                 f"{names}\n\nMở lại các bản khôi phục?", QMessageBox.Yes | QMessageBox.No)
        for d in pending:
            if r == QMessageBox.Yes:
                with open(d["file"], "rb") as f:
                    doc = PdfDocument(data=f.read())
                doc.path = d.get("path")
                doc.modified = True
                self.add_document(doc, "(Khôi phục) " + (d.get("title") or doc.name))
            self.recovery.discard(d["key"])
        self._update_state()

    def _recovery_docs(self):
        import uuid
        out = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not getattr(tab, "recovery_key", None):
                tab.recovery_key = uuid.uuid4().hex
            out.append((tab.recovery_key, tab.doc, getattr(tab, "title", None) or tab.doc.name))
        return out

    def print_doc(self, tab: DocTab):
        """1.0.22: hộp thoại In riêng – xem trước, tỉ lệ %, nhiều trang/tờ, khổ giấy, đen trắng… (kiểu Foxit)."""
        from .print_dialog import PrintDialog
        if not tab.doc.can_print:
            QMessageBox.information(self, APP_NAME, "Người gửi tài liệu này không cho phép in.")
            return
        dlg = PrintDialog(self, tab.doc, tab.view.current_page(), self.settings, getattr(tab, "title", None) or "")
        if dlg.exec() == PrintDialog.Accepted:
            self._flash(f"Đã gửi {getattr(dlg, 'printed', 0)} tờ tới máy in.")

    def goto_page(self):
        """Ctrl+G: con trỏ nhảy vào ô số trang ở thanh dưới, gõ số rồi Enter."""
        if self.current():
            self.lbl_page.focus_edit()

    # ---------- trạng thái ----------
    def _view_call(self, name, *args):
        tab = self.current()
        if tab:
            getattr(tab.view, name)(*args)

    def _slider_moved(self, v):
        tab = self.current()
        if tab and tab.view.zoom != v:
            tab.view.set_zoom(v)

    def _zoom_changed(self, z):
        self.lbl_zoom.setText(f"{z}%")
        self.slider.blockSignals(True)
        self.slider.setValue(min(z, 400))
        self.slider.blockSignals(False)

    def _tab_changed(self, _):
        tab = self.current()
        if not tab or not tab.view.tool:
            self.tool_opts.setVisible(False)
        if tab:
            self._zoom_changed(tab.view.zoom)
        self._update_state()

    def _flash(self, msg: str):
        if sys.platform == "darwin":
            from .osutil import kbd
            msg = kbd(msg)
        self.lbl_msg.setText(msg)
        self.lbl_msg.setToolTip(msg)
        QTimer.singleShot(4000, self.lbl_msg, lambda: self.lbl_msg.text() == msg and self.lbl_msg.setText(""))

    def _update_license_view(self):
        c = getattr(self, "_lic_cache", None)
        if not c:
            return
        from . import license as L
        st = c[1]
        state = "ok" if st.kind == L.ACTIVE else ("warn" if st.kind == L.TRIAL else "bad")
        self.lic_chip.setText("Đã kích hoạt" if state == "ok" else
                              f"Dùng thử · còn {st.days_left} ngày" if state == "warn" else "Chưa kích hoạt")
        self.lic_chip.setProperty("state", state)
        self.lic_chip.style().unpolish(self.lic_chip)
        self.lic_chip.style().polish(self.lic_chip)
        self.lic_chip.setVisible(True)
        self.empty.set_license(st.short, state)
        self._lic_short = (st.short, state)
        if getattr(self, "start_overlay", None) is not None:
            self.start_overlay.set_license(st.short, state)
        self.apply_edition_ui()

    def _update_state(self):
        self._update_license_view()
        self._refresh_notes()
        tab = self.current()
        if tab is not None:
            self._refresh_banner(tab)
        if not tab:
            self.side.show_page(None, 0)
            for w in (self.lbl_page, self.lbl_paper, self.lbl_kind):
                w.setText("")
            self.lbl_kind.setVisible(False)
            self.setWindowTitle(APP_NAME + self._license_suffix())
            return
        doc = tab.doc
        i = min(tab.view.current_page(), doc.page_count - 1)
        info = doc.page_info(i)
        self.lbl_page.setText(f"Trang {i + 1} / {doc.page_count}")
        self.lbl_paper.setText(info.label)
        self.lbl_kind.setText(KIND_LABEL[info.kind])
        self.lbl_kind.setVisible(True)
        self.side.show_page(doc, i)
        idx = self.tabs.currentIndex()
        name = doc.name if doc.path else (getattr(tab, "title", None) or doc.name)
        self.tabs.setTabText(idx, ("● " if doc.modified else "") + name)
        self.setWindowTitle(f"{doc.name}{' *' if doc.modified else ''} – {APP_NAME}{self._license_suffix()}")

    def _license_suffix(self) -> str:
        c = getattr(self, "_lic_cache", None)
        if not c:
            return ""
        from . import license as L
        st = c[1]
        return f" (Dùng thử – còn {st.days_left} ngày)" if st.kind == L.TRIAL else ("" if st.usable else " (Chưa kích hoạt)")

    @staticmethod
    def _is_temp(path: str) -> bool:
        import tempfile
        try:
            from .spool import spool_root
            roots = [tempfile.gettempdir(), spool_root()]
        except Exception:
            roots = [tempfile.gettempdir()]
        # so cả đường dẫn thật: macOS /var/folders/... thực chất là /private/var/folders/...
        ps = {os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.realpath(path))}
        rs = set()
        for r in roots:
            if r:
                rs.add(os.path.normcase(os.path.abspath(r)))
                rs.add(os.path.normcase(os.path.realpath(r)))
        return any(p.startswith(r + os.sep) for p in ps for r in rs)

    # ---------- kéo thả ----------
    @staticmethod
    def _openable(path: str) -> bool:
        from .ui_import import openable
        return openable(path)

    def dragEnterEvent(self, ev):
        if any(self._openable(u.toLocalFile()) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if self._openable(u.toLocalFile())]
        self.import_files(paths)

    def receive_files(self, items: list[str]):
        """Từ dòng lệnh / phiên khác / menu chuột phải / Finder (macOS): "tray:<file>" = thêm vào khay ghép,
        còn lại = mở (1 file PDF mở luôn; nhiều file hoặc Word/Excel/ảnh: bảng tùy chọn)."""
        tray = [x[5:] for x in items if x.startswith("tray:")]
        opens = [x for x in items if not x.startswith("tray:")]
        if opens:
            if all(p.lower().endswith(".pdf") for p in opens) and len(opens) == 1:
                self.open_files(opens)
            else:
                self.import_files(opens)
        if tray:
            self.show_tray().add_paths(tray)
