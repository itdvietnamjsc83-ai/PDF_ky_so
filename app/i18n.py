"""Việt hóa các nút chuẩn của Qt (OK/Hủy/Có/Không...) mà không cần đóng gói file dịch của Qt."""
from PySide6.QtCore import QTranslator

VI = {
    "OK": "OK", "&OK": "&OK", "Cancel": "Hủy", "&Cancel": "&Hủy", "Close": "Đóng", "&Close": "Đó&ng",
    "Yes": "Có", "&Yes": "&Có", "No": "Không", "&No": "&Không", "Yes to &All": "Có tất cả",
    "N&o to All": "Không tất cả", "Save": "Lưu", "&Save": "&Lưu", "Save All": "Lưu tất cả",
    "Discard": "Không lưu", "Don't Save": "Không lưu", "Apply": "Áp dụng", "Reset": "Đặt lại",
    "Restore Defaults": "Mặc định", "Help": "Trợ giúp", "Open": "Mở", "&Open": "&Mở", "Abort": "Dừng",
    "Retry": "Thử lại", "Ignore": "Bỏ qua", "Show Details...": "Xem chi tiết…", "Hide Details...": "Ẩn chi tiết…",
    "&Undo": "&Hoàn tác", "&Redo": "&Làm lại", "Cu&t": "Cắ&t", "&Copy": "&Sao chép", "&Paste": "&Dán",
    "Delete": "Xóa", "Select All": "Chọn tất cả",
}


class ViTranslator(QTranslator):
    def translate(self, context, source, disambiguation=None, n=-1):
        return VI.get(source, "")


def install(app) -> ViTranslator:
    tr = ViTranslator(app)
    app.installTranslator(tr)
    return tr
