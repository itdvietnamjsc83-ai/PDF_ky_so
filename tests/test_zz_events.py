"""Chạy cuối cùng: xử lý mọi sự kiện Qt còn tồn đọng – bắt lỗi đối tượng bị hủy sớm (gây văng phần mềm)."""
def test_pending_events_do_not_crash():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    for _ in range(20):
        app.processEvents()
