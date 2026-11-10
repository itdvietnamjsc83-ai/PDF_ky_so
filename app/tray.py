"""Cửa sổ Khay ghép PDF (theo bản mẫu giao diện)."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QTableWidget, QToolButton, QVBoxLayout, QWidget)

from .document import PasswordRequired, PdfDocument, format_ranges, parse_ranges
from .icons import icon
from .merge import MergeOptions, TrayItem, count_pages, load_template, merge, plan, save_template, sheets
from .viewer import to_qimage
from .colormode import MODES as COLOR_MODES, MODE_TIP, TRAY_MODES

COLS = ["", "#", "Tên file", "Số trang", "Chế độ", "Trang chọn", "Vị trí file ghép", "Trang trắng", "Thứ tự", "Màu"]
FILE_COLORS = [("", "Theo chung")]
PAPERS = [("Giữ nguyên như gốc", None), ("A4 – co vừa", "A4"), ("A3 – co vừa", "A3"),
          ("A5 – co vừa", "A5"), ("Letter – co vừa", "Letter")]


def _has_signature(path: str) -> bool:
    """File PDF đã có chữ ký số? (đọc nhanh, không mở hẳn file)"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    return b"/ByteRange" in data and b"/Sig" in data


class TrayDialog(QDialog):
    mergedReady = Signal(object, bool)   # (PdfDocument, mở để ký?)

    def __init__(self, parent, settings, colors: dict):
        super().__init__(parent)
        self.setWindowTitle("Khay ghép PDF")
        self.setWindowIcon(icon("merge", colors["accent"]))
        self.resize(1420, 820)
        self.settings = settings
        self.colors = colors
        self.items: list[TrayItem] = []
        self.opts = MergeOptions()
        self._picker_row = -1
        self._source: dict[str, str] = {}       # PDF đã chuyển -> file Word/Excel gốc (để gợi ý thư mục lưu)
        self._name_manual = False
        self.last_saved = None
        self.setAcceptDrops(True)               # kéo thả file từ thư mục vào khay

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        for text, ic, fn in (("Thêm file", "open", self.add_files_dialog),
                             ("Thêm tab đang mở", "tabs", self._add_open_tabs),
                             ("Nhân bản file", "dup", self.duplicate_selected),
                             ("Xóa khỏi khay", "delete", self.remove_selected)):
            b = QPushButton(icon(ic, colors["text"]), text)
            b.clicked.connect(fn)
            top.addWidget(b)
            if fn == self.duplicate_selected:
                self.btn_dup = b
                b.setToolTip("1 file dùng ở nhiều đoạn: nhân bản thành 2, 3… dòng ngay bên dưới, mỗi dòng chọn trang "
                             "riêng rồi kéo tới đúng chỗ (Ctrl+D)")
        # 1.0.22: hoàn tác / làm lại mọi thao tác trong khay (thêm, xóa, nhân bản, cắt đoạn, chọn trang, xoay…)
        self.btn_undo = QPushButton(icon("undo", colors["text"]), "Hoàn tác")
        self.btn_undo.setToolTip("Hoàn tác thao tác vừa làm trong khay (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton(icon("redo", colors["text"]), "Làm lại")
        self.btn_redo.setToolTip("Làm lại (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo)
        top.addWidget(self.btn_undo)
        top.addWidget(self.btn_redo)
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._last_state = None
        top.addStretch()
        b = QPushButton("Mở mẫu khay…")
        b.clicked.connect(self.open_template)
        top.addWidget(b)
        self.btn_tpl_open = b
        b = QPushButton(icon("save", colors["text"]), "Lưu mẫu")
        b.clicked.connect(self.save_template)
        top.addWidget(b)
        self.btn_tpl_save = b
        self.edition_level = 3
        v.addLayout(top)

        # --- tùy chọn ---
        opt = QFrame(objectName="card")
        oh = QHBoxLayout(opt)
        oh.setContentsMargins(14, 8, 14, 8)
        oh.setSpacing(18)
        self.cb_duplex = QCheckBox("In 2 mặt – mỗi file bắt đầu ở trang lẻ", checked=True)
        self.cb_rotate = QCheckBox("Tự xoay đúng hướng", checked=True)
        self.cb_book = QCheckBox("Bookmark theo tên file")
        self.cb_even = QCheckBox("Làm chẵn tổng số trang")
        for cb in (self.cb_duplex, self.cb_rotate, self.cb_book, self.cb_even):
            cb.toggled.connect(self._options_changed)
            oh.addWidget(cb)
        oh.addStretch()
        oh.addWidget(QLabel("Kích thước trang:", objectName="lbl"))
        self.cmb_paper = QComboBox()
        for label, _ in PAPERS:
            self.cmb_paper.addItem(label)
        self.cmb_paper.currentIndexChanged.connect(self._options_changed)
        oh.addWidget(self.cmb_paper)
        oh.addWidget(QLabel("Màu khi ghép:", objectName="lbl"))
        self.cmb_color = QComboBox()
        for k, lbl in TRAY_MODES:
            self.cmb_color.addItem(lbl, k)
            self.cmb_color.setItemData(self.cmb_color.count() - 1, MODE_TIP[k], Qt.ToolTipRole)
        self.cmb_color.setToolTip("Áp dụng cho mọi file (file / trang đặt riêng ở cột Màu hoặc ô xem trước được ưu tiên)")
        self.cmb_color.currentIndexChanged.connect(self._options_changed)
        oh.addWidget(self.cmb_color)
        v.addWidget(opt)
        # --- giai đoạn 6c: bìa, mục lục, số trang ---
        opt2 = QFrame(objectName="card")
        o2 = QHBoxLayout(opt2)
        o2.setContentsMargins(14, 8, 14, 8)
        o2.setSpacing(18)
        self.cb_cover = QCheckBox("Trang bìa")
        self.btn_cover = QPushButton("Nội dung bìa…")
        self.btn_cover.setEnabled(False)
        self.btn_cover.clicked.connect(self.edit_cover)
        self.cb_toc = QCheckBox("Mục lục (bấm để nhảy tới từng tài liệu)")
        self.cb_num = QCheckBox("Đánh số trang “Trang x / y”")
        for w in (self.cb_cover, self.btn_cover, self.cb_toc, self.cb_num):
            o2.addWidget(w)
        for cb in (self.cb_cover, self.cb_toc, self.cb_num):
            cb.toggled.connect(self._options_changed)
        o2.addStretch()
        v.addWidget(opt2)

        # --- bảng file ---
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for c, w in ((0, 36), (1, 34), (3, 70), (4, 130), (5, 110), (6, 110), (7, 100), (8, 70), (9, 120)):
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+D"), self.table, self.duplicate_selected)
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence.Redo, self, self.redo)
        # 5b: kéo thả dòng để sắp thứ tự; thả file / thư mục vào đúng vị trí trong bảng
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDrop)
        self.table.setDropIndicatorShown(True)
        self.table.viewport().installEventFilter(self)
        from PySide6.QtWidgets import QSplitter
        from .tray_preview import TrayPreview
        self.preview = TrayPreview(self)
        self.preview.changed.connect(lambda: self._picker_changed(None))
        self.preview.colorsChanged.connect(self._page_colors_changed)
        self.preview.cutRequested.connect(self.cut_at)
        # tên cũ (giữ tương thích): khung chọn trang = bảng xem trước
        self.picker_box = self.preview
        self.picker = self.preview.picker
        self.picker_title = self.preview.title
        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.table)
        self.split.addWidget(self.preview)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([860, 520])
        v.addWidget(self.split, 1)

        # --- nơi lưu file ghép ---
        from PySide6.QtWidgets import QSizePolicy
        save = QFrame(objectName="card")
        sh = QHBoxLayout(save)
        sh.setContentsMargins(14, 8, 14, 8)
        sh.setSpacing(8)
        sh.addWidget(QLabel("Lưu vào:", objectName="lbl"))
        self.ed_dir = QLineEdit(placeholderText="Thư mục lưu file ghép")
        self.ed_dir.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sh.addWidget(self.ed_dir, 3)
        b = QPushButton("…")
        b.setToolTip("Chọn thư mục lưu")
        b.setFixedWidth(40)
        b.clicked.connect(self.choose_dir)
        sh.addWidget(b)
        sh.addWidget(QLabel("Tên file:", objectName="lbl"))
        self.ed_name = QLineEdit()
        self.ed_name.setToolTip("Tự đặt theo tiêu đề trang bìa hoặc tên file đầu tiên; sửa được")
        self.ed_name.textEdited.connect(lambda _t: setattr(self, "_name_manual", True))
        sh.addWidget(self.ed_name, 2)
        sh.addWidget(QLabel(".pdf", objectName="lbl"))
        self.cb_ask_save = QCheckBox("Hỏi nơi lưu khi bấm Ghép")
        self.cb_ask_save.setToolTip("Mỗi lần bấm Ghép hiện hộp thoại chọn thư mục và đặt tên file\n"
                                    "(tránh quên đổi thư mục / tên file của lần ghép trước)")
        ask = True if self.settings is None else self.settings.value("tray/ask_save", True)
        self.cb_ask_save.setChecked(ask if isinstance(ask, bool) else str(ask).lower() in ("1", "true", "yes"))
        self.cb_ask_save.toggled.connect(lambda on: self.settings is not None and
                                         self.settings.setValue("tray/ask_save", on))
        sh.addWidget(self.cb_ask_save)
        v.addWidget(save)
        srow = QHBoxLayout()
        self.lbl_saved = QLabel("", objectName="lbl")
        self.lbl_saved.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_open_dir = QPushButton("Mở thư mục chứa file")
        self.btn_open_dir.setVisible(False)
        self.btn_open_dir.clicked.connect(self.open_saved_folder)
        srow.addWidget(self.lbl_saved, 1)
        srow.addWidget(self.btn_open_dir)
        v.addLayout(srow)
        if self.settings is not None:
            d = self.settings.value("tray/out_dir", "") or ""
            if d and os.path.isdir(d):
                self.ed_dir.setText(d)

        # --- tổng kết + nút ---
        bottom = QHBoxLayout()
        col = QVBoxLayout()
        self.lbl_total = QLabel("", objectName="h")
        self.lbl_sub = QLabel("", objectName="lbl")
        col.addWidget(self.lbl_total)
        col.addWidget(self.lbl_sub)
        bottom.addLayout(col)
        bottom.addStretch()
        self.btn_stats = QPushButton("Đếm trang màu")
        self.btn_stats.setToolTip("Đếm số trang màu / đen trắng của file ghép (để tính chi phí in)")
        self.btn_stats.clicked.connect(self.show_color_stats)
        bottom.addWidget(self.btn_stats)
        self.btn_preview_all = QPushButton("Xem trước file ghép")
        self.btn_preview_all.clicked.connect(self.preview_merged)
        bottom.addWidget(self.btn_preview_all)
        self.cb_bw_copy = QCheckBox("Lưu thêm bản đen trắng")
        self.cb_bw_copy.setToolTip("Ghép xong lưu thêm một bản đen trắng cạnh bản chính (tên …_den-trang.pdf)")
        bottom.addWidget(self.cb_bw_copy)
        self.cb_clear = QCheckBox("Làm trống khay sau khi ghép")
        bottom.addWidget(self.cb_clear)
        b = QPushButton(icon("merge", colors["text"]), "Ghép")
        b.clicked.connect(lambda: self.do_merge(False))
        bottom.addWidget(b)
        b = QPushButton(icon("token", colors["onaccent"]), "Ghép + mở để ký")
        b.setProperty("accent", True)
        b.clicked.connect(lambda: self.do_merge(True))
        bottom.addWidget(b)
        v.addLayout(bottom)

        self._restore()
        self.refresh()
        self._last_state = (self._key(self.items), self._state())
        self._update_undo_buttons()

    # ---------- dữ liệu ----------
    def _office_colors(self, paths: list[str]) -> dict | None:
        """8a/8e – Word/Excel/PowerPoint thêm vào khay: chọn Màu / Chữ đen / Xám / Đen trắng (nhớ lựa chọn).
        Trả về {đường dẫn: chế độ} (chỉ file được tích) hoặc None nếu bấm Hủy."""
        from .office import is_office_file
        office = [os.path.abspath(p) for p in paths if is_office_file(p) and os.path.exists(p)]
        if not office:
            return {}
        st = self.settings
        ask = st is None or str(st.value("tray/ask_office", "true")).lower() == "true"
        default = (st.value("tray/office_color", "color") if st is not None else "color") or "color"
        self._excel_opts = {}
        if not ask or getattr(self, "quiet", False):
            return {p: "" if default == "color" else default for p in office}
        from .ui_import import ImportOptionsDialog
        dlg = ImportOptionsDialog(self, office, st, purpose="tray")
        self._import_dlg = dlg
        if dlg.exec() != QDialog.Accepted:
            return None
        self._excel_opts = dict(dlg.excel_opts)
        return dict(dlg.chosen())

    def add_paths(self, paths: list[str]) -> int:
        added = 0
        from .office import is_office_file
        paths = self.expand_paths(paths)
        colors = self._office_colors(paths)
        if colors is None:
            return 0
        for p in paths:
            p = os.path.abspath(p)
            color = ""
            if is_office_file(p) and os.path.exists(p):
                if p not in colors:
                    continue                          # bỏ tích trong bảng tùy chọn
                color = colors[p]                     # chọn trong bảng: giữ đúng lựa chọn cho file này
                # Word/Excel: chuyển bằng Office trên máy (giữ nguyên khổ giấy) rồi mới đưa vào khay
                xo = getattr(self, "_excel_opts", {}).get(p)
                par = self.parent()
                conv = (par.convert_office(p, cached=True, excel=xo) if xo else par.convert_office(p, cached=True)) \
                    if hasattr(par, "convert_office") else None
                if not conv:
                    continue
                self._source[os.path.abspath(conv)] = p
                p = os.path.abspath(conv)
            if not p.lower().endswith(".pdf") or not os.path.exists(p):
                continue
            pw = None
            try:
                n = count_pages(p)
            except Exception as e:
                if "password" in str(e).lower():
                    pw, ok = QInputDialog.getText(self, "File có mật khẩu",
                                                  f"Mật khẩu mở {os.path.basename(p)}:", QLineEdit.Password)
                    if not ok:
                        continue
                    try:
                        n = count_pages(p, pw)
                    except Exception:
                        QMessageBox.warning(self, "Khay ghép", f"Sai mật khẩu: {os.path.basename(p)}")
                        continue
                else:
                    QMessageBox.warning(self, "Khay ghép", f"Không đọc được {os.path.basename(p)}:\n{e}")
                    continue
            self.items.append(TrayItem(p, page_count=n, password=pw, color=color))
            added += 1
        if added:
            self.refresh()
            self._persist()
            signed = [os.path.basename(it.path) for it in self.items[-added:] if _has_signature(it.path)]
            if signed and not getattr(self, "quiet", False):
                QMessageBox.information(self, "Khay ghép – file đã có chữ ký số",
                                        "Các file sau đã có chữ ký số:\n" + "\n".join(f"• {n}" for n in signed[:12]) +
                                        "\n\nFile ghép là file mới: KHÔNG giữ được chữ ký số của các file này (người nhận "
                                        "không kiểm tra được chữ ký gốc). Nên gửi kèm bản gốc đã ký, hoặc ký số lại "
                                        "file ghép (Ghép + ký).")
        return added

    # ---------- kéo thả file / thư mục vào khay, kéo dòng để sắp thứ tự ----------
    @staticmethod
    def _droppable(path: str) -> bool:
        from .office import is_office_file
        return os.path.isdir(path) or path.lower().endswith(".pdf") or is_office_file(path)

    @staticmethod
    def expand_paths(paths: list[str]) -> list[str]:
        """5c – thư mục -> các file PDF/Word/Excel/PowerPoint bên trong (cả thư mục con), sắp theo tên tự nhiên."""
        import re
        from .office import is_office_file

        def natural(s):
            return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
        out = []
        for p in paths:
            if os.path.isdir(p):
                found = []
                for root, dirs, files in os.walk(p):
                    dirs.sort(key=natural)
                    for f in files:
                        fp = os.path.join(root, f)
                        if (f.lower().endswith(".pdf") or is_office_file(fp)) and not f.startswith("~$"):
                            found.append(fp)
                out += sorted(found, key=lambda x: natural(os.path.relpath(x, p)))
            else:
                out.append(p)
        return out

    def move_rows(self, rows: list[int], dest: int):
        """Chuyển các dòng (theo thứ tự) tới trước dòng dest."""
        rows = sorted(set(r for r in rows if 0 <= r < len(self.items)))
        if not rows:
            return
        moving = [self.items[r] for r in rows]
        dest -= sum(1 for r in rows if r < dest)
        rest = [it for k, it in enumerate(self.items) if k not in rows]
        dest = max(0, min(dest, len(rest)))
        self.items = rest[:dest] + moving + rest[dest:]
        self.refresh()
        self.table.clearSelection()
        for k in range(dest, dest + len(moving)):
            self.table.selectRow(k)
        self._persist()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.table.viewport() and ev.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            md = ev.mimeData()
            internal = ev.source() is self.table
            if ev.type() in (QEvent.DragEnter, QEvent.DragMove):
                if internal or (md.hasUrls() and any(self._droppable(u.toLocalFile()) for u in md.urls())):
                    ev.acceptProposedAction()
                    return True
                return False
            row = self.table.rowAt(int(ev.position().y()))
            if row < 0:
                row = len(self.items)
            elif ev.position().y() > self.table.visualRect(self.table.model().index(row, 0)).center().y():
                row += 1
            if internal:
                rows = sorted({i.row() for i in self.table.selectedIndexes()})
                ev.setDropAction(Qt.IgnoreAction)
                ev.accept()
                self.move_rows(rows, row)
                return True
            paths = [u.toLocalFile() for u in md.urls() if self._droppable(u.toLocalFile())]
            if paths:
                ev.acceptProposedAction()
                before = len(self.items)
                n = self.add_paths(paths)
                if n and row < before:
                    self.move_rows(list(range(before, before + n)), row)
                self.lbl_saved.setText(f"Đã thêm {n} file vào khay." if n else "Không thêm được file nào.")
                self.btn_open_dir.setVisible(False)
            return True
        return super().eventFilter(obj, ev)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() and any(self._droppable(u.toLocalFile()) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if self._droppable(u.toLocalFile())]
        if paths:
            ev.acceptProposedAction()
            n = self.add_paths(paths)
            self.lbl_saved.setText(f"Đã thêm {n} file vào khay." if n else "Không thêm được file nào.")
            self.btn_open_dir.setVisible(False)

    # ---------- nơi lưu, tên file ghép ----------
    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu file ghép", self.out_dir())
        if d:
            self.ed_dir.setText(d)
            if self.settings is not None:
                self.settings.setValue("tray/out_dir", d)

    def out_dir(self) -> str:
        d = self.ed_dir.text().strip()
        if d:
            return d
        for it in self.items:
            src = self._source.get(it.path, it.path)
            if it.checked and os.path.isdir(os.path.dirname(src)):
                return os.path.dirname(src)
        return os.path.join(os.path.expanduser("~"), "Documents")

    def suggest_name(self) -> str:
        import re
        import time as _t
        if self.opts.cover and (self.opts.cover_title or "").strip():
            base = self.opts.cover_title.strip()
        else:
            first = next((it for it in self.items if it.checked), None)
            if first is None:
                return ""
            base = os.path.splitext(os.path.basename(self._source.get(first.path, first.path)))[0] + "_ghep"
            if len([it for it in self.items if it.checked]) > 1:
                base += f"_{len([it for it in self.items if it.checked])}file"
        base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", base).strip(" .") or "Ghep"
        return f"{base}_{_t.strftime('%Y%m%d')}"

    def _update_name(self):
        if not self._name_manual:
            self.ed_name.setText(self.suggest_name())
        if not self.ed_dir.text().strip() and self.items:
            self.ed_dir.setPlaceholderText(self.out_dir())

    def target_path(self) -> str:
        name = (self.ed_name.text().strip() or self.suggest_name() or "Ghep").strip()
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        return os.path.join(self.out_dir(), name)

    def _free_path(self, path: str) -> str:
        base, ext = os.path.splitext(path)
        k = 2
        while os.path.exists(path):
            path = f"{base} ({k}){ext}"
            k += 1
        return path

    def open_saved_folder(self):
        if not self.last_saved:
            return
        from .osutil import reveal
        reveal(self.last_saved)

    def add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Thêm vào khay ghép", "", "PDF, Word, Excel (*.pdf *.doc *.docx *.rtf *.odt *.xls *.xlsx *.xlsm *.ods *.ppt *.pptx);;PDF (*.pdf)")
        self.add_paths(paths)

    def _add_open_tabs(self):
        mw = self.parent()
        paths = []
        for i in range(mw.tabs.count()):
            d = mw.tabs.widget(i).doc
            if d.path:
                paths.append(d.path)
        if not paths:
            QMessageBox.information(self, "Khay ghép", "Chưa có tab nào đã lưu thành file.")
        self.add_paths(paths)

    def duplicate_selected(self) -> int:
        """Nhân bản các file đang chọn (cùng file gốc, chọn trang riêng) – bản sao nằm ngay dưới bản gốc."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows and 0 <= self._picker_row < len(self.items):
            rows = [self._picker_row]
        if not rows:
            return 0
        new_rows = []
        shift = 0
        for r in rows:
            r += shift
            src = self.items[r]
            self.items.insert(r + 1, src.copy())
            new_rows.append(r + 1)
            shift += 1
        self.refresh()
        self.table.clearSelection()
        for r in new_rows:
            self.table.selectRow(r)
        self._persist()
        self.lbl_saved.setText(f"Đã nhân bản {len(rows)} file – chọn trang riêng cho bản sao rồi kéo dòng tới đúng chỗ.")
        self.btn_open_dir.setVisible(False)
        return len(rows)

    def _table_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        if r not in {i.row() for i in self.table.selectedIndexes()}:
            self.table.selectRow(r)
        m = QMenu(self)
        m.addAction("Nhân bản file (dùng ở đoạn khác)", self.duplicate_selected)
        m.addAction("Lên trên", lambda: self.move(r, -1))
        m.addAction("Xuống dưới", lambda: self.move(r, 1))
        m.addSeparator()
        m.addAction("Xóa khỏi khay", self.remove_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.items[r]
        self._picker_row = -1
        self.preview.clear()
        self.refresh()
        self._persist()

    def move(self, r: int, d: int):
        t = r + d
        if 0 <= t < len(self.items):
            self.items[r], self.items[t] = self.items[t], self.items[r]
            self.refresh()
            self.table.selectRow(t)
            self._persist()

    def apply_edition(self, level: int):
        """Khay ghép nâng cao (bìa, mục lục, số trang, trang trắng in 2 mặt, làm chẵn trang, mẫu khay) chỉ có ở
        gói Doanh nghiệp: gói thấp hơn thì khóa lại (bỏ tích) và ghi chú gói cần có."""
        from .editions import NAMES, required
        self.edition_level = level
        need = required("tray_advanced")
        ok = level >= need
        tip = "" if ok else f"🔒 Thuộc gói {NAMES[need]} – liên hệ nhà cung cấp để nâng cấp"
        for w in (self.cb_duplex, self.cb_even, self.cb_cover, self.cb_toc, self.cb_num, self.btn_tpl_open,
                  self.btn_tpl_save):
            if not ok and hasattr(w, "setChecked"):
                w.blockSignals(True)
                w.setChecked(False)
                w.blockSignals(False)
            w.setEnabled(ok)
            base = w.property("base_tip")
            if base is None:
                base = w.toolTip() or ""
                w.setProperty("base_tip", base)
            w.setToolTip(tip or base)
        if not ok:
            self.btn_cover.setEnabled(False)
        self._read_options()
        if hasattr(self, "table"):
            self.refresh()

    def _read_options(self):
        self.opts.duplex = self.cb_duplex.isChecked()
        self.opts.auto_rotate = self.cb_rotate.isChecked()
        self.opts.bookmarks = self.cb_book.isChecked()
        self.opts.even_total = self.cb_even.isChecked()
        self.opts.resize = PAPERS[self.cmb_paper.currentIndex()][1]
        self.opts.cover = self.cb_cover.isChecked()
        self.opts.toc = self.cb_toc.isChecked()
        self.opts.page_numbers = self.cb_num.isChecked()
        if hasattr(self, "cmb_color"):
            self.opts.color = self.cmb_color.currentData() or "color"
        if getattr(self, "edition_level", 3) < 3:        # gói thấp: không áp tùy chọn nâng cao (kể cả từ mẫu cũ)
            self.opts.duplex = self.opts.even_total = self.opts.cover = self.opts.toc = False
            self.opts.page_numbers = False
        self.btn_cover.setEnabled(self.opts.cover)

    def edit_cover(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Nội dung trang bìa")
        f = QFormLayout(dlg)
        eds = {}
        for key, label, ph in (("cover_org", "Đơn vị:", "CÔNG TY TNHH …"), ("cover_title", "Tiêu đề:", "HỒ SƠ …"),
                               ("cover_subtitle", "Dòng phụ:", "Dự án / gói thầu / kỳ báo cáo…"),
                               ("cover_date", "Ngày:", "để trống: ngày ghép")):
            eds[key] = QLineEdit(getattr(self.opts, key), placeholderText=ph)
            f.addRow(label, eds[key])
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        self._cover_dialog = dlg
        if dlg.exec() == QDialog.Accepted:
            for key, ed in eds.items():
                setattr(self.opts, key, ed.text().strip())
            self._persist()

    def _options_changed(self, *_):
        self._read_options()
        self.refresh()
        self._persist()
        if hasattr(self, "preview") and self.preview.default_color != self.opts.color:
            self.preview.set_default_color(self.opts.color)

    # ---------- bảng ----------
    def refresh(self):
        self._read_options()
        try:
            rows, total, blanks = plan(self.items, self.opts)
            err = None
        except ValueError as e:
            rows, total, blanks, err = [], 0, 0, str(e)
        info = {id(r.item): r for r in rows}
        self.table.blockSignals(True)
        sel = {i.row() for i in self.table.selectedIndexes()}
        self.table.setRowCount(0)            # xóa hẳn widget cũ trong ô (tránh sót lại khi dựng lại)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            cb = QCheckBox()
            cb.setChecked(it.checked)
            cb.toggled.connect(lambda v, it=it: self._set(it, checked=v))
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(10, 0, 0, 0)
            l.addWidget(cb)
            self.table.setCellWidget(r, 0, w)
            self._text(r, 1, str(r + 1))
            tint = QColor(self.file_color(it))
            c1 = self.table.item(r, 1)
            c1.setBackground(tint)
            c1.setForeground(QColor("#ffffff"))
            c1.setTextAlignment(Qt.AlignCenter)
            c1.setToolTip("Màu riêng của file này – trang của file trong ô xem trước có viền cùng màu")
            self._text(r, 2, it.name, tip=it.path)
            self.table.item(r, 2).setForeground(tint.darker(115))
            self._text(r, 3, str(it.page_count))
            mode = QComboBox()
            mode.addItems(["Cả file", "Chọn trang"])
            mode.setCurrentIndex(0 if it.whole else 1)
            mode.currentIndexChanged.connect(lambda k, it=it: self._set(it, whole=(k == 0)))
            self.table.setCellWidget(r, 4, mode)
            rng = QLineEdit(format_ranges(list(range(it.page_count))) if it.whole else it.ranges)
            rng.setEnabled(not it.whole)
            rng.setPlaceholderText("vd: 1-3, 5, 8-")
            rng.editingFinished.connect(lambda e=rng, it=it: self._set(it, ranges=e.text()))
            rng.textEdited.connect(lambda txt, e=rng, it=it: self._live_range(it, e, txt))
            self.table.setCellWidget(r, 5, rng)
            pr = info.get(id(it))
            if not it.checked:
                self._text(r, 6, "Không ghép")
                self._text(r, 7, "–")
            elif pr:
                n_out = pr.item.out_len()
                self._text(r, 6, f"{pr.start} – {pr.start + n_out - 1}")
                self._text(r, 7, f"+{pr.blanks_after} (trang {pr.start + n_out})" if pr.blanks_after else "0")
            else:
                self._text(r, 6, "Không có trang")
                self._text(r, 7, "–")
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(0)
            for ic, d, tip in (("up", -1, "Lên"), ("down", 1, "Xuống")):
                b = QToolButton(text="▲" if d < 0 else "▼", toolTip=tip, autoRaise=True)
                b.clicked.connect(lambda _=False, r=r, d=d: self.move(r, d))
                bl.addWidget(b)
            self.table.setCellWidget(r, 8, box)
            col = QComboBox()
            for k, lbl in FILE_COLORS + TRAY_MODES:
                col.addItem(lbl, k)
                col.setItemData(col.count() - 1, MODE_TIP.get(k, "Dùng lựa chọn “Màu khi ghép” ở trên"), Qt.ToolTipRole)
            col.setCurrentIndex(max(0, col.findData(it.color or "")))
            if it.page_colors:
                col.setToolTip(f"{len(it.page_colors)} trang đặt màu riêng (xem ở ô xem trước)")
                col.setItemText(col.currentIndex(), col.currentText() + " *")
            col.currentIndexChanged.connect(lambda k, it=it, c=col: self._set(it, color=c.itemData(k) or ""))
            self.table.setCellWidget(r, 9, col)
        if len(sel) == 1 and next(iter(sel)) < len(self.items):
            self.table.selectRow(next(iter(sel)))
        self.table.blockSignals(False)
        n_files = len(rows)
        if hasattr(self, "ed_name"):
            self._update_name()
        if hasattr(self, "preview") and 0 <= self._picker_row < len(self.items) and self.preview.item is \
                self.items[self._picker_row]:
            pr = info.get(id(self.preview.item))
            self.preview.out_start = pr.start if pr else None
        if err:
            self.lbl_total.setText(f"Lỗi dải trang: {err}")
            self.lbl_sub.setText("")
        else:
            self.lbl_total.setText(f"Tổng: {total} trang" + (f" ({blanks} trang trắng)" if blanks else "")
                                   + f" từ {n_files} file")
            self.lbl_sub.setText(f"{sheets(total, self.opts.duplex)} tờ khi in {'2 mặt' if self.opts.duplex else '1 mặt'}"
                                 " · định dạng trang " + ("giữ nguyên như gốc" if not self.opts.resize
                                                          else f"đổi về {self.opts.resize}"))

    def _live_range(self, it, ed, txt: str):
        """Đang gõ dải trang: ảnh xem trước tích / bỏ theo ngay, gõ sai (vượt số trang…) thì ô báo đỏ."""
        try:
            pages = parse_ranges(txt, it.page_count) if txt.strip() else []
            err = ""
        except ValueError as e:
            pages, err = None, str(e)
        ed.setStyleSheet("QLineEdit{border:1px solid #e53935;background:#fdecea;color:#b71c1c}" if err else "")
        ed.setToolTip(err or f"{len(pages)} trang: {format_ranges(pages) if pages else 'không trang nào'}")
        if err:
            self.lbl_total.setText(f"Dải trang chưa đúng: {err}")
        elif hasattr(self, "preview") and self.preview.item is it:
            self.preview.set_kept(pages, emit=False)

    def _text(self, r, c, text, tip=None):
        from PySide6.QtWidgets import QTableWidgetItem
        it = QTableWidgetItem(text)
        if tip:
            it.setToolTip(tip)
        self.table.setItem(r, c, it)

    def _set(self, it: TrayItem, **kw):
        if "ranges" in kw:
            try:
                parse_ranges(kw["ranges"], it.page_count)
            except ValueError as e:
                QMessageBox.warning(self, "Khay ghép", str(e))
                self.refresh()
                return
        for k, v in kw.items():
            setattr(it, k, v)
        if kw.get("whole") is False and not it.ranges:
            it.ranges = format_ranges(list(range(it.page_count)))
        self.refresh()
        self._persist()
        if self._picker_row >= 0 and self._picker_row < len(self.items) and self.items[self._picker_row] is it:
            self._load_picker(self._picker_row)
        elif 0 <= self._picker_row < len(self.items):
            self.preview.set_out_start(self._out_start(self.items[self._picker_row]))

    # ---------- xem trước / chọn trang ----------
    def _row_selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) == 1:
            self._load_picker(rows.pop())

    def _out_start(self, it) -> int | None:
        try:
            rows, _, _ = plan(self.items, self.opts)
        except ValueError:
            return None
        pr = next((r for r in rows if r.item is it), None)
        return pr.start if pr else None

    def _load_picker(self, r: int):
        it = self.items[r]
        self._picker_row = r
        self.preview.default_color = self.opts.color
        self.preview.file_tint = self.file_color(it)
        self.preview.load(it, self._out_start(it))

    def _picker_changed(self, _item):
        if not (0 <= self._picker_row < len(self.items)):
            return
        it = self.items[self._picker_row]
        sel = self.preview.kept()
        it.whole = len(sel) == it.page_count
        it.ranges = format_ranges(sel)
        self.refresh()
        self._persist()
        self.preview.set_out_start(self._out_start(it))

    def _page_colors_changed(self):
        self.refresh()
        self._persist()

    def _quick_pick(self, key: str):
        if self._picker_row < 0:
            return
        self.preview.quick(key)

    # ---------- ghép ----------
    def _ask_target(self) -> str | None:
        """Hộp thoại "Lưu file ghép": chọn thư mục + đặt tên NGAY khi bấm Ghép (gợi ý sẵn thư mục/tên đang có).
        Trả về đường dẫn (người dùng đã đồng ý ghi đè nếu trùng tên), None nếu hủy."""
        path, _ = QFileDialog.getSaveFileName(self, "Lưu file ghép – chọn thư mục và đặt tên file",
                                              self.target_path(), "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def do_merge(self, for_sign: bool):
        self._read_options()
        if not getattr(self, "quiet", False):
            from .merge import check_plan
            try:
                warns = check_plan(self.items, self.opts)
            except Exception:
                warns = []
            if warns and QMessageBox.question(
                    self, "Khay ghép – xem lại trước khi ghép",
                    "Trước khi ghép, nên xem lại:\n\n" + "\n\n".join(f"• {w}" for w in warns) + "\n\nVẫn ghép?") \
                    != QMessageBox.Yes:
                return None
        self._chosen_path = None
        if self.cb_ask_save.isChecked() and not getattr(self, "quiet", False):
            chosen = self._ask_target()
            if not chosen:
                return None
            if not chosen.lower().endswith(".pdf"):
                chosen += ".pdf"
            self._chosen_path = chosen
            self.ed_dir.setText(os.path.dirname(chosen))
            self.ed_name.setText(os.path.splitext(os.path.basename(chosen))[0])
            self._name_manual = True
        try:
            doc = self._merge_with_progress()
        except Exception as e:
            from .deps import explain
            hint = explain(e)
            QMessageBox.warning(self, "Khay ghép", f"Không ghép được:\n{e}" + (f"\n\n{hint}" if hint else ""))
            return None
        path = self._save_merged(doc)
        if path is False:                       # người dùng hủy khi trùng tên
            doc.close()
            return None
        if path and self.cb_bw_copy.isChecked():
            self.bw_copy = self._save_bw_copy(doc, path)
        self.mergedReady.emit(doc, for_sign)
        if self.cb_clear.isChecked():
            self.items.clear()
            self.refresh()
            self._persist()
        return doc

    def _merge_with_progress(self):
        """Ghép kèm thanh tiến độ (file lớn / nhiều file: thấy phần mềm đang chạy, không tưởng bị treo)."""
        from PySide6.QtWidgets import QApplication, QProgressDialog
        n = len([it for it in self.items if it.checked])
        dlg = None
        if n > 1 and not getattr(self, "quiet", False):
            dlg = QProgressDialog("Đang ghép file…", None, 0, n + 1, self)
            dlg.setWindowTitle("Khay ghép")
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(300)
            dlg.setCancelButton(None)

        def progress(k, total):
            if dlg is not None:
                dlg.setMaximum(total + 1)
                dlg.setValue(k)
                dlg.setLabelText(f"Đang ghép file {min(k + 1, total)}/{total}…" if k < total else
                                 "Đang hoàn tất (xoay trang, mục lục, nén)…")
                QApplication.processEvents()
        try:
            return merge(self.items, self.opts, progress=progress)
        finally:
            if dlg is not None:
                dlg.close()
                dlg.deleteLater()

    def _save_merged(self, doc):
        """Lưu file ghép vào thư mục đã chọn. Trả về đường dẫn, None nếu không lưu được (mở dạng chưa lưu),
        False nếu người dùng hủy."""
        chosen = getattr(self, "_chosen_path", None)       # đã chọn trong hộp thoại Lưu (hộp thoại đã hỏi ghi đè)
        self._chosen_path = None
        path = chosen or self.target_path()
        if os.path.exists(path) and not chosen:
            if getattr(self, "quiet", False):
                path = self._free_path(path)
            else:
                box = QMessageBox(QMessageBox.Question, "Khay ghép", f"Đã có file:\n{path}", parent=self)
                b_new = box.addButton("Lưu tên mới (thêm số)", QMessageBox.AcceptRole)
                b_over = box.addButton("Ghi đè", QMessageBox.DestructiveRole)
                box.addButton("Hủy", QMessageBox.RejectRole)
                box.setDefaultButton(b_new)
                box.exec()
                if box.clickedButton() is b_new:
                    path = self._free_path(path)
                elif box.clickedButton() is not b_over:
                    return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            doc.save(path)
        except Exception as e:
            QMessageBox.warning(self, "Khay ghép", f"Không lưu được vào:\n{path}\n\n{e}\n\n"
                                "File ghép sẽ mở ở dạng chưa lưu – hãy Lưu (Ctrl+S) vào thư mục khác.")
            self.lbl_saved.setText("")
            self.btn_open_dir.setVisible(False)
            return None
        self.last_saved = path
        if self.settings is not None:
            self.settings.setValue("tray/out_dir", os.path.dirname(path))
        self.lbl_saved.setText(f"Đã lưu file ghép: {path}")
        self.btn_open_dir.setVisible(True)
        self._name_manual = False
        return path

    def _save_bw_copy(self, doc, path: str) -> str | None:
        """10h – lưu thêm bản đen trắng cạnh bản chính."""
        from .colormode import convert_bytes
        out = self._free_path(os.path.splitext(path)[0] + "_den-trang.pdf")
        try:
            data = convert_bytes(doc.to_bytes(), {i: "bw" for i in range(doc.page_count)})
            with open(out, "wb") as f:
                f.write(data)
        except Exception as e:
            QMessageBox.warning(self, "Khay ghép", f"Không lưu được bản đen trắng:\n{e}")
            return None
        self.lbl_saved.setText(self.lbl_saved.text() + f"  ·  bản đen trắng: {os.path.basename(out)}")
        return out

    def color_stats(self) -> tuple[int, int]:
        from .merge import color_stats
        from .ui_sign import busy
        self._read_options()
        return busy(self, "Đang đếm trang màu…", lambda: color_stats(self.items, self.opts))

    def show_color_stats(self):
        try:
            c, m = self.color_stats()
        except Exception as e:
            QMessageBox.warning(self, "Khay ghép", f"Không đếm được:\n{e}")
            return None
        self.lbl_sub.setText(self.lbl_sub.text().split(" · Màu:")[0] + f" · Màu: {c} trang · Đen trắng/xám: {m} trang")
        return c, m

    def preview_merged(self):
        """6b – xem trước toàn bộ file ghép (chưa lưu); Ghép & lưu ngay trong cửa sổ xem."""
        from .ui_sign import busy
        self._read_options()
        try:
            doc = busy(self, "Đang dựng bản xem trước…", lambda: merge(self.items, self.opts))
        except Exception as e:
            QMessageBox.warning(self, "Khay ghép", f"Không xem trước được:\n{e}")
            return None
        dlg = MergedPreviewDialog(self, doc)
        self._preview_dlg = dlg
        r = dlg.exec()
        doc.close()
        if r == QDialog.Accepted:
            return self.do_merge(dlg.for_sign)
        return None

    # ---------- lưu trạng thái / mẫu ----------
    # ---------- hoàn tác trong khay ----------
    def _state(self) -> list:
        return [it.copy() for it in self.items]

    @staticmethod
    def _key(items) -> str:
        return json.dumps([it.to_json() for it in items], ensure_ascii=False, sort_keys=True)

    def _track(self):
        """Gọi sau mỗi thay đổi (qua _persist): có khác trạng thái trước -> cất trạng thái trước để Ctrl+Z."""
        if getattr(self, "_restoring", False) or not hasattr(self, "_undo_stack"):
            return
        cur = self._key(self.items)
        if self._last_state is not None and self._last_state[0] != cur:
            self._undo_stack.append(self._last_state[1])
            del self._undo_stack[:-100]
            self._redo_stack.clear()
        self._last_state = (cur, self._state())
        self._update_undo_buttons()

    def _update_undo_buttons(self):
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(bool(self._undo_stack))
            self.btn_redo.setEnabled(bool(self._redo_stack))

    def _apply_state(self, items):
        self._restoring = True
        try:
            row = self._picker_row
            self.items = [it.copy() for it in items]
            self.refresh()
            if 0 <= row < len(self.items):
                self.table.selectRow(row)
                self._load_picker(row)
            else:
                self._picker_row = -1
                self.preview.clear()
            self._persist()
        finally:
            self._restoring = False
        self._last_state = (self._key(self.items), self._state())
        self._update_undo_buttons()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._state())
        self._apply_state(self._undo_stack.pop())
        self.lbl_saved.setText("Đã hoàn tác. Ctrl+Y để làm lại.")
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._state())
        self._apply_state(self._redo_stack.pop())
        self.lbl_saved.setText("Đã làm lại.")
        return True

    # ---------- cắt đoạn ----------
    def cut_at(self, page: int) -> bool:
        """Cắt đoạn của file đang xem tại trang `page` (0-based): dòng hiện tại giữ các trang trước,
        dòng mới ngay bên dưới giữ từ trang đó trở đi -> kéo dòng mới tới chỗ cần xen file khác."""
        r = self._picker_row
        if not (0 <= r < len(self.items)):
            return False
        it = self.items[r]
        pages = it.pages()
        if page not in pages:
            later = [k for k, p in enumerate(pages) if p > page]
            idx = later[0] if later else len(pages)
        else:
            idx = pages.index(page)
        first, second = pages[:idx], pages[idx:]
        if not first or not second:
            QMessageBox.information(self, "Khay ghép", "Chọn một trang ở giữa đoạn (không phải trang đầu / sau trang "
                                                       "cuối) để cắt thành 2 đoạn.")
            return False
        tail = it.copy()
        it.whole, it.ranges = False, format_ranges(first)
        tail.whole, tail.ranges = False, format_ranges(second)
        self.items.insert(r + 1, tail)
        self.refresh()
        self.table.selectRow(r + 1)
        self._load_picker(r + 1)
        self._persist()
        self.lbl_saved.setText(f"Đã cắt {it.name} thành 2 đoạn: trang {format_ranges(first)} và "
                               f"{format_ranges(second)}. Kéo đoạn sau tới đúng chỗ. Ctrl+Z để hoàn tác.")
        self.btn_open_dir.setVisible(False)
        return True

    # ---------- màu riêng từng file ----------
    FILE_TINTS = ["#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00897b", "#e53935", "#6d4c41", "#3949ab",
                  "#c0ca33", "#d81b60"]

    def file_color(self, it) -> str:
        """Mỗi file một màu (bản nhân bản / đoạn cắt của cùng file cùng màu)."""
        order = []
        for x in self.items:
            k = os.path.normcase(os.path.abspath(x.path))
            if k not in order:
                order.append(k)
        k = os.path.normcase(os.path.abspath(it.path))
        return self.FILE_TINTS[(order.index(k) if k in order else 0) % len(self.FILE_TINTS)]

    def _persist(self):
        self._track()
        if self.settings is not None:
            import time as _t
            from dataclasses import asdict
            from .retention import keeps
            if not keeps(self.settings, "tray"):         # người dùng chọn "Không lưu" khay ghép
                return
            self.settings.setValue("tray_t", _t.time())
            self.settings.setValue("tray", json.dumps({"items": [it.to_json() for it in self.items],
                                                       "options": asdict(self.opts)}, ensure_ascii=False))

    def _restore(self):
        if self.settings is None:
            return
        raw = self.settings.value("tray", "")
        try:
            data = json.loads(raw) if raw else {}
            for d in data.get("items", []):
                if os.path.exists(d.get("path", "")):
                    self.items.append(TrayItem(**d))
            o = data.get("options") or {}
            for k in ("cover_title", "cover_subtitle", "cover_org", "cover_date"):
                if k in o:
                    setattr(self.opts, k, o[k])
            if o.get("color"):
                self.cmb_color.blockSignals(True)
                self.cmb_color.setCurrentIndex(max(0, self.cmb_color.findData(o["color"])))
                self.cmb_color.blockSignals(False)
                self.opts.color = o["color"]
        except Exception:
            pass

    def save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Lưu mẫu khay", "", "Mẫu khay (*.khay.json)")
        if path:
            if not path.endswith(".json"):
                path += ".khay.json"
            save_template(path, self.items, self.opts)
            try:                                          # nhớ để "Xóa lịch sử" xóa được mẫu khay
                lst = json.loads(self.settings.value("tray/template_files", "") or "[]")
                lst = [x for x in lst if x != path] + [path]
                self.settings.setValue("tray/template_files", json.dumps(lst[-50:]))
            except Exception:
                pass

    def open_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở mẫu khay", "", "Mẫu khay (*.json)")
        if not path:
            return
        items, opts = load_template(path)
        missing = [it.name for it in items if not os.path.exists(it.path)]
        self.items = [it for it in items if os.path.exists(it.path)]
        self.cb_duplex.setChecked(opts.duplex)
        self.cb_rotate.setChecked(opts.auto_rotate)
        self.cb_book.setChecked(opts.bookmarks)
        self.cb_even.setChecked(opts.even_total)
        self.cb_cover.setChecked(opts.cover)
        self.cb_toc.setChecked(opts.toc)
        self.cb_num.setChecked(opts.page_numbers)
        for k in ("cover_title", "cover_subtitle", "cover_org", "cover_date"):
            setattr(self.opts, k, getattr(opts, k))
        self.cmb_color.setCurrentIndex(max(0, self.cmb_color.findData(getattr(opts, "color", "color"))))
        self.refresh()
        self._persist()
        if missing:
            QMessageBox.information(self, "Khay ghép", "Không tìm thấy các file:\n" + "\n".join(missing))


class MergedPreviewDialog(QDialog):
    """6b – cửa sổ xem trước file ghép: cuộn / phóng to như vùng xem chính, kèm số trang, số trang màu."""

    def __init__(self, parent, doc):
        from .viewer import PageView
        super().__init__(parent)
        self.for_sign = False
        self.setWindowTitle("Xem trước file ghép")
        self.resize(900, 820)
        v = QVBoxLayout(self)
        n = doc.page_count
        self.info = QLabel(f"{n} trang – đây là bản xem trước, chưa lưu. Ctrl + lăn chuột để phóng to.",
                           objectName="h")
        v.addWidget(self.info)
        self.view = PageView(doc, "#d9d9d9")
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Đóng")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        b = QPushButton("Ghép & lưu")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        b = QPushButton("Ghép + mở để ký")
        b.setProperty("accent", True)
        b.clicked.connect(self._sign)
        row.addWidget(b)
        v.addLayout(row)
        QTimer.singleShot(0, self.view.fit_width)

    def _sign(self):
        self.for_sign = True
        self.accept()
