"""Đo hiệu năng: python tools/benchmark.py duong-dan-file.pdf"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def ms(t):
    return f"{(time.perf_counter() - t) * 1000:.0f} ms"


def main(path):
    import resource
    t = time.perf_counter()
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app.mainwindow import MainWindow
    w = MainWindow()
    w.show()
    app.processEvents()
    print("Khởi động tới khi hiện cửa sổ:", ms(t))
    t = time.perf_counter()
    w.open_files([path])
    v = w.current().view
    v.canvas.repaint()
    print("Mở file + hiện trang đầu:", ms(t), f"({w.current().doc.page_count} trang)")
    t = time.perf_counter()
    for z in range(100, 300, 10):
        v.set_zoom(z)
        v.canvas.repaint()
    print("Zoom 20 nấc (vẽ tạm):", ms(t))
    t = time.perf_counter()
    v._fast_pass = False
    v.canvas.repaint()
    print("Render nét ở 290%:", ms(t))
    t = time.perf_counter()
    sb = v.verticalScrollBar()
    for k in range(50):
        sb.setValue(sb.maximum() * k // 50)
        v.canvas.repaint()
    print("Cuộn 50 vị trí khắp file:", ms(t))
    d = w.current().doc
    t = time.perf_counter()
    out = path + ".opt.pdf"
    d.save(out)
    print("Lưu tối ưu:", ms(t), f"{os.path.getsize(path) / 1e6:.2f} MB -> {os.path.getsize(out) / 1e6:.2f} MB")
    os.remove(out)
    print("Bộ nhớ đỉnh:", f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
    d.modified = False


if __name__ == "__main__":
    main(sys.argv[1])
