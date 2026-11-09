"""Điểm khởi động.

    PdfKySo.exe [file1.pdf file2.pdf ...]   mở file (nếu phần mềm đang chạy: chuyển sang cửa sổ đó)
    PdfKySo.exe --selftest                  tự kiểm tra bản đóng gói (mã thoát 0 = ổn)
    PdfKySo.exe --activate                  mở màn hình kích hoạt / dùng thử (bộ cài gọi sau khi cài)
    PdfKySo.exe hop-dong.docx               Word/Excel/PowerPoint: chuyển sang PDF giữ nguyên khổ giấy rồi mở
    PdfKySo.exe --tray a.pdf b.xlsx         thêm vào khay ghép (menu chuột phải)

macOS: "PDF Ký Số.app" nhận file khi kéo thả lên biểu tượng Dock / "Mở bằng" trong Finder (sự kiện FileOpen),
các tham số dòng lệnh giống hệt Windows (Contents/MacOS/PdfKySo --selftest ...).
"""
import sys

OPEN_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")


class FileOpenCatcher:
    """Sự kiện FileOpen của macOS (Finder "Mở bằng", kéo file lên biểu tượng Dock).
    File đến trước khi cửa sổ chính sẵn sàng được giữ lại trong `pending`."""

    def __init__(self):
        self.pending: list[str] = []
        self.handler = None

    def handle(self, e) -> bool:
        from PySide6.QtCore import QEvent
        if e.type() != QEvent.Type.FileOpen:
            return False
        path = e.file() or e.url().toLocalFile()
        if path:
            if self.handler:
                self.handler([path])
            else:
                self.pending.append(path)
        return True

    def take_pending(self) -> list[str]:
        out, self.pending = self.pending, []
        return out


def make_app(argv):
    """QApplication chỉ bắt thêm FileOpen gửi tới chính nó (không lọc mọi sự kiện -> không tốn CPU)."""
    from PySide6.QtWidgets import QApplication

    class App(QApplication):
        def __init__(self, a):
            super().__init__(a)
            self.opener = FileOpenCatcher()

        def event(self, e):
            if self.opener.handle(e):
                return True
            return super().event(e)
    return App(argv)


def clean_args(argv):
    """Bỏ tham số hệ thống macOS thêm vào khi mở từ Finder (-psn_0_12345)."""
    return [a for a in argv if not a.startswith("-psn_")]


def main():
    if "--selftest" in sys.argv:
        from app.stability import selftest
        sys.exit(selftest())

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    sys.argv[:] = clean_args(sys.argv)
    from app.signing import quiet_windows_loader_errors
    quiet_windows_loader_errors()             # không để driver token hỏng bật hộp thoại "Bad Image" của Windows
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = make_app(sys.argv)
    opener = app.opener
    app.setStyle("Fusion")
    from app import i18n
    i18n.install(app)

    # bản cài đặt chỉ chạy khi đã cài bằng bộ cài (chép thư mục sang máy khác -> không chạy);
    # bản portable (có file PdfKySo.portable cạnh .exe) thì chạy luôn
    from app import install_check, portable
    if install_check.is_packaged(globals()) and not portable.is_portable():
        ok, msg = install_check.check()
        if not ok:
            from app import APP_NAME as _name
            QMessageBox.warning(None, _name, msg)
            sys.exit(2)

    from app import APP_NAME, __version__
    from app import stability
    if not install_check.is_packaged(globals()):      # chạy từ mã nguồn: báo ngay nếu thiếu thư viện
        from app import deps
        miss = deps.missing()
        if miss:
            QMessageBox.warning(None, APP_NAME, deps.missing_message(miss))
    log_path = stability.setup_logging()
    stability.log.info("Khởi động %s %s", APP_NAME, __version__)
    from app.office import OFFICE_EXT
    to_tray = "--tray" in sys.argv                # menu chuột phải "Thêm vào khay ghép"
    files = [("tray:" if to_tray else "") + a for a in sys.argv[1:]
             if not a.startswith("--") and a.lower().endswith((".pdf",) + OFFICE_EXT + OPEN_EXT)]

    single = stability.SingleInstance()
    if single.send_to_running(files):
        sys.exit(0)                      # đã có cửa sổ đang chạy, file được chuyển sang đó
    single.listen()

    from app.mainwindow import MainWindow
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    if sys.platform == "darwin":
        from app import macintegration
        macintegration.fix_shortcut_texts(w)      # "Ctrl+Z" -> "⌘Z" trên giao diện

    def show_error(msg):
        from app.deps import explain
        hint = explain(msg)
        if hint:
            msg = f"{msg}\n\n{hint}"
        QTimer.singleShot(0, lambda: QMessageBox.warning(
            w, APP_NAME, f"Đã xảy ra lỗi nhưng phần mềm vẫn chạy tiếp.\n\n{msg}\n\nChi tiết: {log_path}"))
    stability.install_excepthook(show_error)

    w.show()
    from app import license as L
    st = L.status()
    need_license = "--activate" in sys.argv or st.kind in (L.NEW, L.TRIAL_OVER, L.EXPIRED, L.INVALID, L.CLOCK)

    def startup_dialogs():
        # mỗi lần mở: bảng thông tin nhà phát triển; sau đó (nếu cần) màn hình bản quyền
        from app.ui_license import DeveloperDialog
        DeveloperDialog(w).exec()
        if need_license:
            # lần đầu chạy: chọn Dùng thử 15 ngày hoặc nhập mã kích hoạt; hết hạn: nhắc kích hoạt
            w.show_license("" if st.kind in (L.NEW, L.ACTIVE, L.TRIAL) else st.message)
        else:
            w.license_status()
            w._update_state()
    QTimer.singleShot(300, w, startup_dialogs)
    w.start_spool()                      # nhận file từ máy in ảo
    w.enable_recovery()                  # tự lưu bản khôi phục + hỏi khôi phục sau sự cố
    w.start_retention()                  # tự xóa lịch sử quá hạn theo thời hạn người dùng đặt
    w.start_autofolder()                 # thư mục tự xử lý (nếu người dùng đã bật)
    single.filesReceived.connect(lambda fs: (w.receive_files(fs), w.showNormal(), w.raise_(), w.activateWindow()))
    def from_finder(fs):
        w.receive_files(fs)
        w.showNormal()
        w.raise_()
        w.activateWindow()
    opener.handler = from_finder
    files += [f for f in opener.take_pending() if f not in files]
    if files:
        w.receive_files(files)
    code = app.exec()
    stability.log.info("Thoát bình thường (mã %s)", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
