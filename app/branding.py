"""Thông tin nhà phát triển – SỬA các dòng dưới đây trước khi đóng gói bản bán.
Hiện ở: màn hình Giới thiệu, màn hình kích hoạt (để khách liên hệ mua key), thuộc tính file .exe."""

PRODUCT = "PDF Ký Số"
DEVELOPER = "Công ty cổ phần Công nghệ ITD Việt Nam"
PHONE = "0988095867"
EMAIL = "vanthu.itdvn@gmail.com"
WEBSITE = "itdvietnam.com.vn"
ADDRESS = "Số 1 Ngõ 30 đường Lý Sơn, Hà Nội"
PRICE_NOTE = "Liên hệ để được cấp mã kích hoạt theo mã máy (1 năm / vĩnh viễn)."
COPYRIGHT = "© 2026 " + DEVELOPER


def contact_lines() -> list[str]:
    out = [DEVELOPER]
    if PHONE:
        out.append(f"Điện thoại/Zalo: {PHONE}")
    if EMAIL:
        out.append(f"Email: {EMAIL}")
    if WEBSITE:
        out.append(f"Website: {WEBSITE}")
    if ADDRESS:
        out.append(ADDRESS)
    return out
