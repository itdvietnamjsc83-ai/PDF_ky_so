"""Giao diện ký số: chọn chứng thư trên USB token, dựng hình hiển thị (dấu + chữ ký + thông tin),
nhập PIN, ký trong luồng nền, kiểm tra chữ ký."""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize, Qt, QThread
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from . import APP_NAME
from . import signing
from .signing import PKCS11, CertInfo, PinIncorrect, PinLocked, SigningError, TokenRemoved

log = logging.getLogger(__name__)

# thứ tự cũng là chỉ số trong hộp chọn
LAYOUT_FULL, LAYOUT_IMAGE, LAYOUT_TEXT, LAYOUT_HIDDEN = "full", "image", "text", "hidden"
LAYOUTS = [(LAYOUT_FULL, "Dấu + chữ ký + thông tin người ký"), (LAYOUT_IMAGE, "Chỉ dấu và chữ ký"),
           (LAYOUT_TEXT, "Chỉ thông tin người ký"), (LAYOUT_HIDDEN, "Ký ẩn (không hiện trên trang)")]
PAGE_MODES = [("auto", "Gợi ý tự động (tìm chỗ ký ở các trang cuối)"),
              ("keyword", "Tìm theo cụm chữ tự nhập…"),
              ("current", "Trang đang xem"), ("first", "Trang đầu"), ("last", "Trang cuối"),
              ("number", "Trang số…")]
SIZE_PT = {LAYOUT_FULL: (210, 78), LAYOUT_IMAGE: (140, 80), LAYOUT_TEXT: (180, 52)}
REASONS = ["Phê duyệt tài liệu", "Xác nhận nội dung", "Tôi là người lập tài liệu", "Đồng ý ký kết"]
TSA_URLS = ["http://timestamp.digicert.com", "http://timestamp.sectigo.com",
            "http://rfc3161timestamp.globalsign.com/advanced", "http://time.certum.pl"]
TEXT_COLORS = {"Xanh": "#0b3d91", "Đỏ": "#b3261e", "Đen": "#1b1b1b"}
DPI = 300


# ------------------------------------------------------------------ hình hiển thị
def appearance_lines(cert: CertInfo | None, reason: str = "", location: str = "", when: float | None = None):
    who = cert.subject if cert else "(chưa chọn chứng thư)"
    t = time.strftime("%d/%m/%Y %H:%M", time.localtime(when or time.time()))
    lines = [f"Ký bởi: {who}"]
    if cert and cert.organization and cert.organization.lower() not in who.lower():
        lines.append(f"Đơn vị: {cert.organization}")
    lines.append(f"Ngày ký: {t}")
    if reason:
        lines.append(f"Lý do: {reason}")
    if location:
        lines.append(f"Nơi ký: {location}")
    return lines


def _fit(img: QImage, box: QRectF) -> QRectF:
    if img.isNull() or box.width() <= 0 or box.height() <= 0:
        return QRectF()
    r = min(box.width() / img.width(), box.height() / img.height())
    w, h = img.width() * r, img.height() * r
    return QRectF(box.x() + (box.width() - w) / 2, box.y() + (box.height() - h) / 2, w, h)


def render_appearance(layout: str, stamp: QImage | None, sig: QImage | None, lines: list[str],
                      size_pt: tuple[float, float] | None = None, color: str = "#0b3d91") -> QImage:
    """Dựng khung ký 300 dpi, nền trong suốt. Dấu đóng trùm lên 1/3 bên trái chữ ký như ký tay."""
    w_pt, h_pt = size_pt or SIZE_PT.get(layout, SIZE_PT[LAYOUT_FULL])
    stamp = stamp if stamp is not None and not stamp.isNull() else None
    sig = sig if sig is not None and not sig.isNull() else None
    if layout == LAYOUT_FULL and not (stamp or sig):
        layout = LAYOUT_TEXT
        w_pt, h_pt = SIZE_PT[LAYOUT_TEXT]
    if layout == LAYOUT_IMAGE and not (stamp or sig):
        layout = LAYOUT_TEXT
        w_pt, h_pt = SIZE_PT[LAYOUT_TEXT]
    k = DPI / 72
    W, H = max(1, int(w_pt * k)), max(1, int(h_pt * k))
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
    if layout == LAYOUT_TEXT:
        img_box, text_box = QRectF(), QRectF(0, 0, W, H)
    elif layout == LAYOUT_IMAGE:
        img_box, text_box = QRectF(0, 0, W, H), QRectF()
    else:
        split = W * 0.46
        img_box, text_box = QRectF(0, 0, split, H), QRectF(split + 4 * k, 0, W - split - 4 * k, H)
    if not img_box.isNull():
        if stamp and sig:
            st = _fit(stamp, QRectF(img_box.x(), img_box.y(), img_box.height(), img_box.height()))
            sg_box = QRectF(img_box.x() + img_box.height() * 0.45, img_box.y() + img_box.height() * 0.15,
                            img_box.width() - img_box.height() * 0.45, img_box.height() * 0.7)
            p.drawImage(_fit(sig, sg_box), sig)
            p.setOpacity(0.92)
            p.drawImage(st, stamp)                      # dấu nằm trên chữ ký
            p.setOpacity(1.0)
        else:
            one = stamp or sig
            p.drawImage(_fit(one, img_box), one)
    if not text_box.isNull() and lines:
        text = "\n".join(lines)
        font = QFont("Segoe UI")
        font.setStyleHint(QFont.SansSerif)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        opt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        size = 9.0
        while size > 4:
            font.setPixelSize(max(1, int(size * k)))           # cỡ chữ pt ở 300 dpi
            p.setFont(font)
            need = p.boundingRect(text_box, int(Qt.TextWordWrap | Qt.AlignLeft), text)
            if need.height() <= text_box.height() and need.width() <= text_box.width() + 1:
                break
            size -= 0.5
        p.setPen(QColor(color))
        p.drawText(text_box, text, opt)
    p.end()
    return img


def qimage_to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


# ------------------------------------------------------------------ chạy nền có hộp chờ
class _Worker(QThread):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.fn()
        except BaseException as e:           # chuyển lỗi về luồng giao diện
            self.error = e


def busy(parent, text: str, fn):
    """Chạy fn ở luồng nền, hiện hộp chờ (giao diện không bị treo). Lỗi được ném lại ở đây."""
    from PySide6.QtCore import QEventLoop
    w = _Worker(fn)
    dlg = QProgressDialog(text, None, 0, 0, parent)
    dlg.setWindowTitle(APP_NAME)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(400)
    dlg.setCancelButton(None)
    loop = QEventLoop()
    w.finished.connect(loop.quit)
    w.start()
    if not w.isFinished():
        loop.exec()
    w.wait()
    dlg.close()
    dlg.deleteLater()
    if w.error is not None:
        raise w.error
    return w.result


# ------------------------------------------------------------------ PIN
def ask_pin(parent, cert: CertInfo, warning: str = "") -> str | None:
    msg = (f"Nhập mã PIN của USB token “{cert.token_label or cert.subject}”"
           f"\nđể ký bằng chứng thư: {cert.subject}")
    if warning:
        msg = f"⚠ {warning}\n\n" + msg
    pin, ok = QInputDialog.getText(parent, "Mã PIN USB token", msg, QLineEdit.Password)
    if not ok:
        return None
    return pin


def pin_warning(e: PinIncorrect) -> str:
    if e.final_try:
        return "Sai mã PIN. CHỈ CÒN 1 LẦN THỬ – nhập sai nữa token sẽ bị khóa."
    if e.count_low:
        return "Sai mã PIN. Số lần thử còn lại rất ít."
    return str(e) or "Sai mã PIN."


def sign_with_ui(parent, cert: CertInfo, data: bytes, opts: signing.SignOptions, hwnd: int = 0,
                 pin_provider=ask_pin) -> bytes | None:
    """Ký với đầy đủ tương tác: hỏi PIN (PKCS#11) hoặc để driver token tự hỏi (kho Windows),
    thử lại khi sai PIN, báo lỗi dễ hiểu. Trả về bytes đã ký, None nếu người dùng hủy/lỗi."""
    warning = ""
    while True:
        pin = None
        if cert.backend == PKCS11 and not cert.extra.get("protected"):
            pin = pin_provider(parent, cert, warning)
            if pin is None:
                return None
        hint = ("Đang ký số…" if cert.backend == PKCS11 and pin is not None else
                "Đang ký số… Nếu phần mềm của USB token hiện hộp thoại, hãy nhập mã PIN vào đó.")

        def job():
            signer, close = signing.open_signer(cert, pin, hwnd)
            try:
                return signing.sign_pdf(data, signer, opts)
            finally:
                close()
        try:
            return busy(parent, hint, job)
        except PinIncorrect as e:
            if cert.backend != PKCS11:
                if QMessageBox.question(parent, APP_NAME, f"{e}\nThử ký lại?") != QMessageBox.Yes:
                    return None
                continue
            warning = pin_warning(e)
        except PinLocked as e:
            QMessageBox.critical(parent, APP_NAME, str(e))
            return None
        except TokenRemoved as e:
            if QMessageBox.question(parent, APP_NAME, f"{e}\n\nCắm token xong bấm Có để ký lại.") != QMessageBox.Yes:
                return None
        except SigningError as e:
            QMessageBox.warning(parent, APP_NAME, f"Không ký được:\n{e}")
            return None
        except Exception as e:
            log.exception("Lỗi ký số")
            QMessageBox.warning(parent, APP_NAME, f"Không ký được:\n{e}")
            return None


# ------------------------------------------------------------------ hộp thoại ký
def _qimg(png: bytes | None) -> QImage | None:
    if not png:
        return None
    img = QImage()
    img.loadFromData(png)
    return img if not img.isNull() else None


class SignDialog(QDialog):
    """Chọn chứng thư và hình thức chữ ký. Không tự ký – trả về lựa chọn cho cửa sổ chính."""

    def __init__(self, parent, library=None, settings=None, lister=None, fields=(), page_count: int = 1,
                 current_page: int = 0):
        super().__init__(parent)
        self.fields = list(fields)          # ô ký chuẩn bị sẵn (luồng ký) còn trống
        self.page_count = max(1, page_count)
        self.current_page = current_page
        self.setWindowTitle("Ký số")
        self.setMinimumWidth(620)
        self.library = library
        self.settings = settings
        self.lister = lister or signing.list_certificates
        self.certs: list[CertInfo] = []
        self._preview_img: QImage | None = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        row = QHBoxLayout()
        self.cb_cert = QComboBox()
        self.cb_cert.setMinimumContentsLength(40)
        self.cb_cert.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.btn_refresh = QPushButton("Làm mới")
        self.btn_refresh.setToolTip("Dò lại USB token (sau khi cắm token hoặc cài driver mới)")
        self.btn_driver = QPushButton("Thêm driver…")
        self.btn_driver.setToolTip("Chọn file DLL PKCS#11 của hãng token nếu phần mềm không tự tìm thấy")
        row.addWidget(self.cb_cert, 1)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_driver)
        form.addRow("Chứng thư:", row)
        self.lbl_info = QLabel("", wordWrap=True, objectName="lbl")
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("", self.lbl_info)

        self.cb_field = QComboBox()
        self.cb_field.addItem("Chọn vị trí trên trang (phần mềm gợi ý)", "")
        for f in self.fields:
            self.cb_field.addItem(f"Ô ký “{f.name}” – trang {f.page + 1}", f.name)
        if self.fields:
            self.cb_field.setCurrentIndex(1)
            form.addRow("Ký vào:", self.cb_field)
        # ký ở trang nào (khi tự chọn vị trí trên trang)
        prow = QHBoxLayout()
        self.cb_page = QComboBox()
        for key, label in PAGE_MODES:
            self.cb_page.addItem(label, key)
        self.cb_page.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_page.setMinimumContentsLength(18)
        self.cb_page.setToolTip("Gợi ý tự động: tìm “GIÁM ĐỐC”, “ĐẠI DIỆN”, “(Ký, ghi rõ họ tên)”… ở các trang cuối.\nTrang đặt khung ký. Khi đặt khung vẫn bấm được sang trang khác để chuyển khung.")
        self.sp_page = QSpinBox(minimum=1, maximum=self.page_count, value=min(self.current_page + 1, self.page_count))
        self.sp_page.setPrefix("Trang ")
        self.sp_page.setSuffix(f" / {self.page_count}")
        self.cb_kw = QComboBox(editable=True)
        self.cb_kw.setToolTip("Cụm chữ đứng ngay trên chỗ ký, vd. “ĐẠI DIỆN BÊN B”, “Người lập biểu” – tìm từ trang cuối "
                              "lên. Phần mềm nhớ các cụm đã dùng.")
        self.cb_kw.setMinimumContentsLength(14)
        self.cb_kw.lineEdit().setPlaceholderText("vd. ĐẠI DIỆN BÊN B")
        try:
            import json as _json
            for kw in _json.loads(self._get("keywords", "[]") or "[]"):
                self.cb_kw.addItem(kw)
        except Exception:
            pass
        prow.addWidget(self.cb_page, 1)
        prow.addWidget(self.sp_page)
        prow.addWidget(self.cb_kw, 1)
        self.page_row = QWidget()
        self.page_row.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        self.lbl_page_row = QLabel("Ký ở trang:")
        form.addRow(self.lbl_page_row, self.page_row)
        self.cb_page.currentIndexChanged.connect(self._page_mode_changed)
        self.cb_field.currentIndexChanged.connect(self._page_mode_changed)
        self.cb_layout = QComboBox()
        for _, label in LAYOUTS:
            self.cb_layout.addItem(label)
        form.addRow("Hiển thị:", self.cb_layout)
        self.cb_stamp = QComboBox()
        self.cb_sig = QComboBox()
        self.cb_color = QComboBox()
        self.cb_color.addItems(list(TEXT_COLORS))
        irow = QHBoxLayout()
        irow.addWidget(QLabel("Con dấu"))
        irow.addWidget(self.cb_stamp, 1)
        irow.addWidget(QLabel("Chữ ký"))
        irow.addWidget(self.cb_sig, 1)
        irow.addWidget(QLabel("Màu chữ"))
        irow.addWidget(self.cb_color)
        form.addRow("Ảnh:", irow)

        self.cb_reason = QComboBox(editable=True)
        self.cb_reason.addItems(REASONS)
        form.addRow("Lý do ký:", self.cb_reason)
        self.ed_location = QLineEdit(placeholderText="Ví dụ: Hà Nội")
        form.addRow("Nơi ký:", self.ed_location)

        adv = QGridLayout()
        self.chk_tsa = QCheckBox("Gắn dấu thời gian (TSA)")
        self.chk_tsa.setToolTip("Chứng minh thời điểm ký bằng máy chủ thời gian tin cậy – cần Internet")
        self.cb_tsa = QComboBox(editable=True)
        self.cb_tsa.addItems(TSA_URLS)
        self.chk_ltv = QCheckBox("Xác thực dài hạn (LTV)")
        self.chk_ltv.setToolTip("Nhúng thông tin thu hồi chứng thư để chữ ký vẫn kiểm tra được sau khi chứng thư hết hạn – cần Internet")
        self.chk_certify = QCheckBox("Khóa tài liệu sau khi ký (không cho sửa, không cho ký thêm)")
        adv.addWidget(self.chk_tsa, 0, 0)
        adv.addWidget(self.cb_tsa, 0, 1)
        adv.addWidget(self.chk_ltv, 1, 0)
        adv.addWidget(self.chk_certify, 2, 0, 1, 2)
        form.addRow("Tùy chọn:", adv)
        lay.addLayout(form)

        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.preview.setStyleSheet("background:#ffffff;border:1px dashed #9aa0a6;border-radius:6px;")
        lay.addWidget(self.preview)
        self.lbl_hint = QLabel("Sau khi bấm “Chọn vị trí & ký”, phần mềm gợi ý chỗ ký trên trang – bạn kéo khung "
                               "tới chỗ mong muốn, kéo góc để đổi cỡ, rồi nhấn Enter (hoặc nháy đúp) để ký.",
                               wordWrap=True, objectName="lbl")
        lay.addWidget(self.lbl_hint)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = self.buttons.button(QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._fill_images()
        self._restore()
        k = self.cb_page.findData(self._get("page_mode", "auto") or "auto")
        self.cb_page.setCurrentIndex(max(0, k))
        self.cb_layout.currentIndexChanged.connect(self._page_mode_changed)
        self._page_mode_changed()
        self.btn_refresh.clicked.connect(lambda: self.load(refresh=True))
        self.btn_driver.clicked.connect(self.add_driver)
        for w in (self.cb_cert, self.cb_layout, self.cb_stamp, self.cb_sig, self.cb_color):
            w.currentIndexChanged.connect(self._changed)
        self.cb_reason.currentTextChanged.connect(self._changed)
        self.ed_location.textChanged.connect(self._changed)
        self.chk_tsa.toggled.connect(self.cb_tsa.setEnabled)
        self.cb_tsa.setEnabled(self.chk_tsa.isChecked())

    def _page_mode_changed(self, *_):
        choose = not (self.cb_field.currentData() or "") and self.layout_key() != LAYOUT_HIDDEN
        self.page_row.setVisible(choose)
        self.lbl_page_row.setVisible(choose)
        self.sp_page.setVisible(self.cb_page.currentData() == "number")
        self.cb_kw.setVisible(self.cb_page.currentData() == "keyword")

    def keyword(self) -> str:
        return self.cb_kw.currentText().strip() if self.cb_page.currentData() == "keyword" else ""

    def sign_page(self) -> tuple[str, int]:
        """(chế độ, trang 0-based) – chế độ: auto | current | first | last | number."""
        mode = self.cb_page.currentData()
        page = {"current": self.current_page, "first": 0, "last": self.page_count - 1,
                "number": self.sp_page.value() - 1}.get(mode, -1)
        return mode, page

    # ---- lưu/khôi phục lựa chọn
    def _get(self, key, default=None):
        if self.settings is None:
            return default
        v = self.settings.value("sign/" + key, default)
        return default if v is None else v

    def _set(self, key, value):
        if self.settings is not None:
            self.settings.setValue("sign/" + key, value)

    def _get_list(self, key) -> list | None:
        raw = self._get(key)
        if not raw:
            return None
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bool(v, default=False):
        if v is None:
            return default
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return bool(v)

    def _restore(self):
        self.cb_layout.setCurrentIndex(max(0, [k for k, _ in LAYOUTS].index(self._get("layout", LAYOUT_FULL))
                                           if self._get("layout", LAYOUT_FULL) in dict(LAYOUTS) else 0))
        self.cb_reason.setCurrentText(self._get("reason", REASONS[0]))
        self.ed_location.setText(self._get("location", ""))
        self.chk_tsa.setChecked(self._bool(self._get("tsa_on"), False))
        self.cb_tsa.setCurrentText(self._get("tsa_url", TSA_URLS[0]))
        self.chk_ltv.setChecked(self._bool(self._get("ltv"), False))
        self.cb_color.setCurrentText(self._get("color", "Xanh"))
        for cb, key in ((self.cb_stamp, "stamp"), (self.cb_sig, "sig")):
            iid = self._get(key)
            if iid:
                k = cb.findData(iid)
                if k >= 0:
                    cb.setCurrentIndex(k)

    def _save(self):
        c = self.cert()
        if c:
            self._set("cert", c.thumbprint)
        self._set("layout", self.layout_key())
        self._set("page_mode", self.cb_page.currentData())
        kw = self.keyword()
        if kw:
            import json as _json
            try:
                old = _json.loads(self._get("keywords", "[]") or "[]")
            except Exception:
                old = []
            self._set("keywords", _json.dumps(([kw] + [k for k in old if k != kw])[:15], ensure_ascii=False))
        self._set("reason", self.cb_reason.currentText())
        self._set("location", self.ed_location.text())
        self._set("tsa_on", self.chk_tsa.isChecked())
        self._set("tsa_url", self.cb_tsa.currentText())
        self._set("ltv", self.chk_ltv.isChecked())
        self._set("color", self.cb_color.currentText())
        self._set("stamp", self.cb_stamp.currentData() or "")
        self._set("sig", self.cb_sig.currentData() or "")

    # ---- ảnh từ thư viện dấu
    def _fill_images(self):
        from .library import SIGNATURE, STAMP
        self.cb_stamp.addItem("(không dùng)", None)
        self.cb_sig.addItem("(không dùng)", None)
        lib = self.library
        if lib is None or getattr(lib, "locked", False):
            return
        try:
            stamps, sigs = lib.of_kind(STAMP), lib.of_kind(SIGNATURE)
        except Exception:
            return
        for it in stamps:
            self.cb_stamp.addItem(it.name, it.id)
        for it in sigs:
            self.cb_sig.addItem(it.name, it.id)
        # không chọn gì trước đó -> lấy sẵn con dấu/chữ ký đầu tiên trong thư viện để hiển thị
        if stamps:
            self.cb_stamp.setCurrentIndex(1)
        if sigs:
            self.cb_sig.setCurrentIndex(1)

    def _image(self, cb) -> QImage | None:
        iid = cb.currentData()
        if not iid or self.library is None:
            return None
        try:
            return _qimg(self.library.image(iid))
        except Exception:
            return None

    # ---- chứng thư
    def load(self, refresh: bool = False, sync: bool = False):
        extra = self._get_list("extra_libs") or []
        known = None if refresh else self._get_list("known_libs")

        def job():
            return self.lister(extra_libs=extra, refresh=refresh, known_libs=known)
        try:
            certs, libs = job() if sync else busy(self, "Đang đọc chữ ký số trên USB token…", job)
        except Exception as e:
            log.exception("Dò chứng thư lỗi")
            certs, libs = [], []
            QMessageBox.warning(self, APP_NAME, f"Không đọc được USB token:\n{e}")
        if not certs and known is not None and not refresh:
            return self.load(refresh=True, sync=sync)      # driver mới/đổi token: quét lại toàn bộ
        self._set("known_libs", json.dumps(libs))
        self.set_certs(certs)

    def set_certs(self, certs: list[CertInfo]):
        self.certs = certs
        self.cb_cert.blockSignals(True)
        self.cb_cert.clear()
        for c in certs:
            self.cb_cert.addItem(c.label, c.thumbprint)
        last = self._get("cert")
        k = self.cb_cert.findData(last) if last else -1
        if k < 0:
            k = next((i for i, c in enumerate(certs) if not c.expired and not c.not_yet_valid), 0)
        self.cb_cert.setCurrentIndex(k if certs else -1)
        self.cb_cert.blockSignals(False)
        self._changed()

    def add_driver(self, path: str | None = None):
        if path is None:
            flt = "Driver PKCS#11 (*.dll)" if os.name == "nt" else "Thư viện PKCS#11 (*.so *.dylib *.dll)"
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file driver PKCS#11 của USB token",
                                                  os.environ.get("SystemRoot", "") + "\\System32" if os.name == "nt"
                                                  else ("/usr/local/lib" if sys.platform == "darwin" else "/usr/lib"),
                                                  flt)
            if not path:
                return
        if not signing.probe_lib(path):
            QMessageBox.warning(self, APP_NAME, "File này không phải driver PKCS#11 của USB token.")
            return
        extra = self._get_list("extra_libs") or []
        if path not in extra:
            extra.append(path)
        self._set("extra_libs", json.dumps(extra))
        self.load(refresh=True)

    def cert(self) -> CertInfo | None:
        k = self.cb_cert.currentIndex()
        return self.certs[k] if 0 <= k < len(self.certs) else None

    def layout_key(self) -> str:
        return LAYOUTS[self.cb_layout.currentIndex()][0]

    # ---- cập nhật
    def _changed(self, *_):
        c = self.cert()
        if not self.certs:
            self.lbl_info.setText("Không thấy chứng thư số nào. Hãy cắm USB token, đảm bảo đã cài phần mềm (driver) "
                                  "của hãng cung cấp chữ ký số, rồi bấm Làm mới. Nếu vẫn không thấy, bấm "
                                  "“Thêm driver…” và chọn file " + ("DLL" if os.name == "nt" else ".dylib" if sys.platform == "darwin"
                                                                      else ".so") + " PKCS#11 của hãng.")
            self.btn_ok.setEnabled(False)
        elif c:
            exp = time.strftime("%d/%m/%Y", time.localtime(c.not_after))
            if c.backend == PKCS11:
                via = f"Ký qua driver PKCS#11 của token: {os.path.basename(c.lib_path)}"
                via += " (nhập PIN trên bàn phím token)" if c.extra.get("protected") else " (phần mềm hỏi PIN)"
            else:
                via = f"Ký qua phần mềm token đã cài trên Windows: {c.provider or 'Windows'} (PIN do phần mềm token hỏi)"
            state = ""
            if c.expired:
                state = "<b style='color:#b3261e'>Chứng thư đã hết hạn – chữ ký sẽ không hợp lệ.</b><br>"
            elif c.not_yet_valid:
                state = "<b style='color:#b3261e'>Chứng thư chưa đến ngày hiệu lực.</b><br>"
            elif c.days_left <= 30:
                state = f"<b style='color:#b26a00'>Chứng thư còn {c.days_left} ngày sẽ hết hạn.</b><br>"
            self.lbl_info.setText(f"{state}Cấp bởi: {c.issuer} · Hiệu lực đến {exp} · Số hiệu {c.serial}<br>{via}")
            self.btn_ok.setEnabled(not c.expired and not c.not_yet_valid)
        hidden = self.layout_key() == LAYOUT_HIDDEN
        for w in (self.cb_stamp, self.cb_sig, self.cb_color):
            w.setEnabled(not hidden and (w is not self.cb_color or self.layout_key() != LAYOUT_IMAGE))
        self.btn_ok.setText("Ký ngay" if hidden else "Chọn vị trí && ký")
        self.lbl_hint.setVisible(not hidden)
        self._update_preview()

    def appearance(self, when: float | None = None) -> QImage | None:
        lay = self.layout_key()
        if lay == LAYOUT_HIDDEN:
            return None
        lines = appearance_lines(self.cert(), self.cb_reason.currentText().strip(), self.ed_location.text().strip(), when)
        return render_appearance(lay, self._image(self.cb_stamp), self._image(self.cb_sig), lines,
                                 color=TEXT_COLORS.get(self.cb_color.currentText(), "#0b3d91"))

    def _update_preview(self):
        img = self.appearance()
        self._preview_img = img
        if img is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Chữ ký số được nhúng vào file nhưng không hiện hình trên trang.")
            return
        pm = QPixmap.fromImage(img).scaled(QSize(460, 120), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setText("")
        self.preview.setPixmap(pm)

    def _accept(self):
        c = self.cert()
        if not c:
            return
        if self.chk_certify.isChecked():
            r = QMessageBox.question(self, APP_NAME, "Sau khi khóa, tài liệu không thể sửa hay ký thêm chữ ký nào "
                                     "khác (kể cả của đối tác). Chắc chắn khóa?")
            if r != QMessageBox.Yes:
                return
        self._save()
        self.accept()

    def values(self) -> dict:
        lay = self.layout_key()
        return {"cert": self.cert(), "layout": lay,
                "size_pt": SIZE_PT.get(lay), "stamp_id": self.cb_stamp.currentData(),
                "sig_id": self.cb_sig.currentData(), "reason": self.cb_reason.currentText().strip(),
                "location": self.ed_location.text().strip(),
                "tsa_url": self.cb_tsa.currentText().strip() if self.chk_tsa.isChecked() else "",
                "ltv": self.chk_ltv.isChecked(), "certify": self.chk_certify.isChecked(),
                "field_name": self.cb_field.currentData() or "",
                "page_mode": self.sign_page()[0], "page": self.sign_page()[1], "keyword": self.keyword()}


# ------------------------------------------------------------------ kiểm tra chữ ký
def report_html(reports: list[signing.SigReport]) -> str:
    if not reports:
        return "<p>Tài liệu này <b>chưa có chữ ký số</b>.</p>"
    parts = []
    for k, r in enumerate(reports, 1):
        if not r.intact or not r.valid:
            color, icon = "#b3261e", "✖"
        elif r.trusted:
            color, icon = "#1e7e34", "✔"
        else:
            color, icon = "#b26a00", "!"
        rows = [("Người ký", r.signer + (f" – {r.organization}" if r.organization and r.organization not in r.signer else "")),
                ("Nhà cung cấp chứng thư", r.issuer), ("Thời gian ký (theo máy người ký)", r.signing_time or "—"),
                ("Dấu thời gian tin cậy", r.timestamp or "không có"),
                ("Loại", "Ký chứng nhận (khóa tài liệu)" if r.certify else "Ký phê duyệt"),
                ("Phạm vi", "Toàn bộ tài liệu" if r.covers_whole else "Có nội dung thêm vào sau khi ký"),
                ("Trường chữ ký", r.field)]
        from .theme import ui_color
        muted = ui_color("text2")
        tbl = "".join(f"<tr><td style='color:{muted};padding-right:12px'>{a}</td><td>{b}</td></tr>" for a, b in rows)
        parts.append(f"<h3 style='color:{color};margin:8px 0 4px'>{icon} Chữ ký {k}: {r.summary}</h3>"
                     f"<table cellspacing=2>{tbl}</table>")
    return "".join(parts)


class VerifyDialog(QDialog):
    def __init__(self, parent, reports: list[signing.SigReport], name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Kiểm tra chữ ký – {name}" if name else "Kiểm tra chữ ký")
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setHtml(report_html(reports))
        lay.addWidget(self.view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


__all__ = ["SignDialog", "VerifyDialog", "render_appearance", "appearance_lines", "sign_with_ui", "busy",
           "qimage_to_png", "report_html"]
