"""Phân gói bản quyền: Tiêu chuẩn (1) / Chuyên nghiệp (2) / Doanh nghiệp (3) – theo "Gói phần mềm cung cấp".

Muốn chuyển một tính năng sang gói khác: chỉ sửa bảng FEATURES bên dưới (1, 2 hoặc 3).
- Dùng thử 15 ngày: mở đủ gói Doanh nghiệp để khách dùng thử hết.
- Mã kích hoạt ghi sẵn gói (bộ tạo mã có ô "Gói"); nâng cấp = cấp mã mới, không cần cài lại.
"""
from __future__ import annotations

STANDARD, PRO, ENTERPRISE = 1, 2, 3
NAMES = {STANDARD: "Tiêu chuẩn", PRO: "Chuyên nghiệp", ENTERPRISE: "Doanh nghiệp"}

# mã lệnh / tính năng -> gói thấp nhất được dùng. Không có trong bảng = mọi gói (kể cả Tiêu chuẩn):
# mở/xem/in, trang, ghi chú, hộp chữ, hình, bút, tẩy, SỬA CHỮ CÓ SẴN, TÌM & THAY, SỬA TRANG SCAN.
FEATURES: dict[str, int] = {
    # --- Chuyên nghiệp ---
    "digisign": PRO,            # Ký số bằng USB token (từng file)
    "mergesign": PRO,           # Ghép + ký
    "spool": PRO,               # Máy in ảo "PDF Ky so" / "PDF Khay ghep"
    "tray": PRO, "trayadd": PRO, "traytabs": PRO, "merge": PRO,       # Khay ghép
    "colormode": PRO,           # Chữ đen / Xám / Đen trắng
    "protect": PRO, "password": PRO, "printperm": PRO, "presets": PRO,  # Bảo vệ file
    "compress": PRO, "compare": PRO,
    "hand": PRO,                # Chữ viết tay theo mẫu
    "stamptext": PRO,           # Dấu chữ / watermark
    "notes_export": PRO,        # Xuất tổng hợp ghi chú ra Excel/PDF
    # --- Doanh nghiệp ---
    "verify": ENTERPRISE,       # Kiểm tra chữ ký
    "stamp": ENTERPRISE, "sigimg": ENTERPRISE, "seam": ENTERPRISE,   # Con dấu, chữ ký ảnh, giáp lai
    "library": ENTERPRISE,      # Thư viện dấu & chữ ký
    "tray_advanced": ENTERPRISE,  # Bìa, mục lục, đánh số trang, trang trắng in 2 mặt, mẫu khay
    "toc": ENTERPRISE,
    "autorotate": ENTERPRISE,   # Tự xoay trang scan
    "batchsign": ENTERPRISE,    # Ký hàng loạt
    "flow": ENTERPRISE,         # Luồng ký nhiều người
    "batchxl": ENTERPRISE,      # Tạo hàng loạt từ mẫu + Excel
    "autofolder": ENTERPRISE,   # Thư mục tự xử lý
    "backup": ENTERPRISE, "history": ENTERPRISE, "usage_log": ENTERPRISE,
}

LABELS = {
    "spool": "Máy in ảo PDF Ký Số", "scanedit": "Sửa trang scan", "notes_export": "Xuất tổng hợp ghi chú",
    "library": "Thư viện dấu & chữ ký", "tray_advanced": "Khay ghép nâng cao (bìa, mục lục, số trang, in 2 mặt, mẫu)",
    "usage_log": "Nhật ký dùng dấu",
}


def required(feature: str) -> int:
    return FEATURES.get(feature, STANDARD)


def current(status=None) -> int:
    """Gói đang dùng: dùng thử -> Doanh nghiệp; đã kích hoạt -> gói ghi trong mã; còn lại -> Tiêu chuẩn."""
    from . import license as L
    st = status if status is not None else L.status()
    if st.kind == L.TRIAL:
        return ENTERPRISE
    if st.kind == L.ACTIVE and st.license is not None:
        return max(STANDARD, min(ENTERPRISE, int(st.license.edition or STANDARD)))
    return STANDARD


def allowed(feature: str, level: int) -> bool:
    return level >= required(feature)


def locked_message(feature: str, label: str | None, level: int) -> str:
    need = required(feature)
    name = label or LABELS.get(feature, feature)
    return (f"Tính năng “{name}” thuộc gói {NAMES[need]}.\n"
            f"Gói đang dùng: {NAMES.get(level, NAMES[STANDARD])}.\n\n"
            "Liên hệ nhà cung cấp để nâng cấp – chỉ cần nhập mã kích hoạt mới, không phải cài lại phần mềm.")


# bảng so sánh hiện cho khách (màn hình Bản quyền → "Các gói phần mềm") – theo tài liệu "Gói phần mềm cung cấp"
COMPARE = [
    ("Mở, xem, in; mở Word/Excel/PowerPoint, ảnh", STANDARD),
    ("Thêm/xóa/xoay/tách trang, ghép file cơ bản", STANDARD),
    ("Ghi chú, hộp chữ, hình vẽ, bút, tẩy", STANDARD),
    ("Sửa chữ có sẵn, tìm & thay, sửa trang scan", STANDARD),
    ("Ký số bằng USB token (từng file)", PRO),
    ("Máy in ảo \"PDF Ky so\" / \"PDF Khay ghep\"", PRO),
    ("Khay ghép", PRO),
    ("Chuyển Chữ đen / Xám / Như máy in đen trắng / Đen trắng", PRO),
    ("Bảo vệ file (mật khẩu, cấm in/sửa, in bản mờ), nén PDF, so sánh 2 bản", PRO),
    ("Chữ viết tay theo mẫu, dấu chữ / watermark", PRO),
    ("Xuất tổng hợp ghi chú ra Excel/PDF", PRO),
    ("Kiểm tra chữ ký", ENTERPRISE),
    ("Đóng dấu, chữ ký tay, thư viện dấu (không giới hạn)", ENTERPRISE),
    ("Khay ghép nâng cao (bìa, mục lục, đánh số trang, trang trắng in 2 mặt, mẫu khay)", ENTERPRISE),
    ("Tự xoay trang scan", ENTERPRISE),
    ("Ký hàng loạt nhiều file một lần", ENTERPRISE),
    ("Luồng ký nhiều người (chuẩn bị ô ký sẵn cho từng người)", ENTERPRISE),
    ("Tạo hàng loạt từ mẫu + Excel (thư mời, hợp đồng…)", ENTERPRISE),
    ("Thư mục tự xử lý (thả file vào là tự đóng dấu/ký/ghép)", ENTERPRISE),
    ("Sao lưu/khôi phục thư viện dấu, lịch sử phiên bản, nhật ký dùng dấu", ENTERPRISE),
]


def compare_html(level: int | None = None) -> str:
    head = "".join(f"<th style='padding:4px 10px'>{NAMES[k]}{' (đang dùng)' if k == level else ''}</th>"
                   for k in (STANDARD, PRO, ENTERPRISE))
    rows = "".join(f"<tr><td style='padding:3px 8px'>{name}</td>" +
                   "".join(f"<td align='center'>{'✓' if k >= need else ''}</td>" for k in (STANDARD, PRO, ENTERPRISE))
                   + "</tr>" for name, need in COMPARE)
    return (f"<table border='1' cellspacing='0' style='border-collapse:collapse'><tr><th>Nhóm tính năng</th>{head}"
            f"</tr>{rows}</table>")


__all__ = ["STANDARD", "PRO", "ENTERPRISE", "NAMES", "FEATURES", "required", "current", "allowed", "locked_message"]
