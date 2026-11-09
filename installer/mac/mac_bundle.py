"""Công cụ đóng gói macOS (chạy bằng python trên máy Mac, build_mac.sh gọi tự động).

    python3 installer/mac/mac_bundle.py icns  assets/app.png  build/app.icns
    python3 installer/mac/mac_bundle.py plist "dist/PDF Ký Số.app/Contents/Info.plist" 1.0.15
    python3 installer/mac/mac_bundle.py entitlements build/entitlements.plist

Chỉ dùng thư viện chuẩn + Pillow nên kiểm thử được cả trên Windows / Linux.
"""
from __future__ import annotations

import plistlib
import sys

APP_NAME = "PDF Ký Số"
BUNDLE_ID = "vn.pdfkyso.app"
EXECUTABLE = "PdfKySo"
MIN_MACOS = "11.0"            # Big Sur trở lên (máy Intel 2013+ và mọi máy Apple M)

# Loại file PDF Ký Số mở được. LSHandlerRank "Alternate": có trong menu "Mở bằng" nhưng
# KHÔNG giành quyền mặc định của Xem trước (Preview) / Word / Excel – khách tự chọn nếu muốn.
DOCUMENT_TYPES = [
    ("Tài liệu PDF", ["com.adobe.pdf"], ["pdf"], "Alternate"),
    ("Tài liệu Word", ["org.openxmlformats.wordprocessingml.document", "com.microsoft.word.doc",
                       "org.openxmlformats.wordprocessingml.template", "public.rtf",
                       "org.oasis-open.opendocument.text"], ["docx", "doc", "docm", "dotx", "dot", "rtf", "odt"],
     "Alternate"),
    ("Bảng tính Excel", ["org.openxmlformats.spreadsheetml.sheet", "com.microsoft.excel.xls",
                         "com.microsoft.excel.sheet.binary.macroenabled", "public.comma-separated-values-text",
                         "org.oasis-open.opendocument.spreadsheet"], ["xlsx", "xls", "xlsm", "xlsb", "csv", "ods"],
     "Alternate"),
    ("Bản trình chiếu PowerPoint", ["org.openxmlformats.presentationml.presentation",
                                    "com.microsoft.powerpoint.ppt", "org.oasis-open.opendocument.presentation"],
     ["pptx", "ppt", "pptm", "odp"], "Alternate"),
    ("Ảnh", ["public.png", "public.jpeg", "public.tiff", "com.microsoft.bmp", "com.compuserve.gif",
             "org.webmproject.webp"], ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"], "Alternate"),
]

APPLE_EVENTS_TEXT = ("PDF Ký Số điều khiển Microsoft Word, Excel, PowerPoint để chuyển tài liệu sang PDF giữ nguyên "
                     "khổ giấy, và ứng dụng Mail / Outlook để tạo thư đã đính kèm file.")


def info_plist(version: str, base: dict | None = None) -> dict:
    """Info.plist đầy đủ cho gói .app (giữ các khóa Nuitka / PyInstaller đã tạo, ghi đè khóa của mình)."""
    d = dict(base or {})
    d.update({
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": d.get("CFBundleExecutable") or EXECUTABLE,
        "CFBundleIconFile": "app.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleDevelopmentRegion": "vi",
        "CFBundleLocalizations": ["vi"],
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSAppleEventsUsageDescription": APPLE_EVENTS_TEXT,
        "NSHumanReadableCopyright": "© PDF Ký Số",
        "CFBundleDocumentTypes": [
            {"CFBundleTypeName": name, "CFBundleTypeRole": "Editor" if "com.adobe.pdf" in utis else "Viewer",
             "LSItemContentTypes": utis, "CFBundleTypeExtensions": exts, "LSHandlerRank": rank,
             "CFBundleTypeIconFile": "app.icns"}
            for name, utis, exts, rank in DOCUMENT_TYPES],
    })
    return d


def patch_info_plist(path: str, version: str) -> dict:
    with open(path, "rb") as f:
        base = plistlib.load(f)
    d = info_plist(version, base)
    with open(path, "wb") as f:
        plistlib.dump(d, f)
    return d


# Hardened Runtime (bắt buộc để công chứng – notarize):
#  - disable-library-validation: nạp được driver PKCS#11 (.dylib) của hãng USB token (VNPT, Viettel, BKAV...)
#    vốn do hãng khác ký -> nếu thiếu, ký số bằng token sẽ báo "không nạp được thư viện".
#  - automation.apple-events: điều khiển Word / Excel / PowerPoint / Mail.
#  - network.client: dấu thời gian (TSA), kiểm tra thu hồi chứng thư (OCSP/CRL).
ENTITLEMENTS = {
    "com.apple.security.cs.disable-library-validation": True,
    "com.apple.security.cs.allow-unsigned-executable-memory": True,
    "com.apple.security.automation.apple-events": True,
    "com.apple.security.network.client": True,
}


def write_entitlements(path: str):
    with open(path, "wb") as f:
        plistlib.dump(ENTITLEMENTS, f)


ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def make_icns(src_png: str, out: str):
    """app.icns từ ảnh PNG vuông (Pillow ghi được .icns trên mọi hệ điều hành)."""
    from PIL import Image
    im = Image.open(src_png).convert("RGBA")
    side = max(im.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    big = sq.resize((1024, 1024), Image.LANCZOS)
    big.save(out, format="ICNS", append_images=[sq.resize((s, s), Image.LANCZOS) for s in ICNS_SIZES[:-1]])
    return out


def main(argv):
    if len(argv) >= 3 and argv[0] == "icns":
        make_icns(argv[1], argv[2])
    elif len(argv) >= 3 and argv[0] == "plist":
        patch_info_plist(argv[1], argv[2])
    elif len(argv) >= 2 and argv[0] == "entitlements":
        write_entitlements(argv[1])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
