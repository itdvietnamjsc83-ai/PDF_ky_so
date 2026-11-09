#!/bin/bash
# ===== Đóng gói PDF Ký Số cho macOS (chạy TRÊN MÁY MAC, macOS 12+ có Xcode Command Line Tools) =====
#
#   ./build_mac.sh                 build cho kiến trúc của máy đang chạy (Apple M -> arm64, Intel -> x86_64)
#   ARCH=x86_64 ./build_mac.sh     build riêng cho máy Intel (cần Python bản universal2 từ python.org)
#
# Kết quả trong thư mục dist/:
#   PDF Ký Số.app                              gói ứng dụng
#   PdfKySo-<phiên bản>-<kiến trúc>.dmg        bộ cài kéo-thả (khuyên dùng để gửi khách)
#   PdfKySo-<phiên bản>-<kiến trúc>.pkg        bộ cài kiểu trình hướng dẫn (tùy chọn, BUILD_PKG=1)
#
# Ký & công chứng (bắt buộc để khách mở được không bị macOS chặn) – cần tài khoản Apple Developer (99 USD/năm):
#   export MAC_SIGN_ID="Developer ID Application: Ten Cong Ty (TEAMID)"
#   export MAC_INSTALLER_ID="Developer ID Installer: Ten Cong Ty (TEAMID)"     # chỉ khi BUILD_PKG=1
#   xcrun notarytool store-credentials pdfkyso-notary --apple-id you@example.com --team-id TEAMID
#   export MAC_NOTARY_PROFILE=pdfkyso-notary
# Không đặt các biến trên -> bản ký tạm (ad-hoc), chỉ dùng để thử trên máy mình.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
ARCH=${ARCH:-$(uname -m)}
APP_NAME="PDF Ký Số"
BUNDLE_ID="vn.pdfkyso.app"
MAC_SIGN_ID=${MAC_SIGN_ID:-}
MAC_INSTALLER_ID=${MAC_INSTALLER_ID:-}
MAC_NOTARY_PROFILE=${MAC_NOTARY_PROFILE:-}
BUILD_PKG=${BUILD_PKG:-0}
fail() { echo "LỖI: $*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "Script này chỉ chạy trên máy Mac (bản Windows dùng build_windows.bat)."
xcode-select -p >/dev/null 2>&1 || fail "Thiếu Xcode Command Line Tools: chạy  xcode-select --install"

# 0) kiểm tra trình liên kết (ld) đọc được bộ SDK: Command Line Tools cập nhật dở (SDK mới hơn ld, vd. MacOSX27.sdk)
#    -> báo "tapi error: unknown architecture arm64e.x1". Khi đó tự chọn bộ SDK cũ hơn còn dùng được.
link_ok() { printf 'int main(void){return 0;}\n' | clang -x c - -o "${TMPDIR:-/tmp}/pdfkyso_ldtest" >/dev/null 2>&1; }
if ! link_ok; then
  echo "CẢNH BÁO: trình liên kết không dùng được bộ SDK mặc định ($(xcrun --show-sdk-path 2>/dev/null)) – thử bộ SDK khác..."
  FOUND=""
  for sdk in $(for p in /Library/Developer/CommandLineTools/SDKs/MacOSX[0-9]*.sdk /Applications/Xcode*.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX[0-9]*.sdk; do
                 [ -d "$p" ] && echo "$(basename "$p" .sdk | sed 's/^MacOSX//') $p"; done | sort -t ' ' -k1,1 -Vr | cut -d' ' -f2-); do
    if SDKROOT="$sdk" link_ok; then export SDKROOT="$sdk"; FOUND=1; echo "-> dùng SDK: $sdk"; break; fi
  done
  if [ -z "$FOUND" ]; then
    echo "Các bộ SDK hiện có:"; ls /Library/Developer/CommandLineTools/SDKs 2>/dev/null || true
    ld -v 2>&1 | head -n 2 || true
    fail "Xcode Command Line Tools bị lệch phiên bản (ld không đọc được SDK). Cài lại:
       sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install
   (hoặc cài Xcode đầy đủ từ App Store rồi: sudo xcode-select -s /Applications/Xcode.app) rồi chạy lại."
  fi
fi

# 1) môi trường ảo + đúng phiên bản thư viện đã kiểm thử
if [ ! -d .venv-mac ]; then "$PY" -m venv .venv-mac; fi
# shellcheck disable=SC1091
source .venv-mac/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements-dev.txt

# 2) toàn bộ kiểm thử (xóa bộ đệm .pyc chép từ máy Windows sang – trỏ đường dẫn D:\... cũ)
find . -name "__pycache__" -type d -prune -not -path "./.venv-mac/*" -exec rm -rf {} +
if [ "${SKIP_TESTS:-0}" = "1" ]; then
  echo "CẢNH BÁO: bỏ qua kiểm thử (SKIP_TESTS=1) – chỉ dùng khi đã chạy kiểm thử riêng."
else
  QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen} python -m pytest tests -q || fail "Kiểm thử không đạt – không đóng gói (xem lỗi phía trên)."
fi

# 3) khóa bản quyền: bản bán cho khách PHẢI dùng khóa thật (python tools/keygen.py init)
if python -c "from app.license_key import DEMO; import sys; sys.exit(1 if DEMO else 0)"; then :; else
  echo "CẢNH BÁO: đang dùng KHÓA MẪU. Chạy \"python tools/keygen.py init\" trước khi bán phần mềm."
  [ "${PDFKYSO_RELEASE:-0}" = "1" ] && fail "PDFKYSO_RELEASE=1 nhưng vẫn là khóa mẫu."
fi
VERSION=$(python -c "import app; print(app.__version__)")
echo "===== PDF Ký Số $VERSION – macOS $ARCH ====="

mkdir -p build dist
python installer/mac/mac_bundle.py icns assets/app.png build/app.icns
python installer/mac/mac_bundle.py entitlements build/entitlements.plist

# 4) biên dịch bằng Nuitka (mã máy, khó dịch ngược – giống bản Windows)
python -m nuitka main.py \
  --standalone \
  --macos-create-app-bundle \
  --macos-target-arch="$ARCH" \
  --macos-app-name="$APP_NAME" \
  --macos-signed-app-name="$BUNDLE_ID" \
  --macos-app-version="$VERSION" \
  --macos-app-mode=gui \
  --macos-app-icon=build/app.icns \
  --macos-app-protected-resource="NSAppleEventsUsageDescription:PDF Ký Số điều khiển Word, Excel, PowerPoint, Mail để chuyển tài liệu sang PDF và gửi email." \
  --enable-plugin=pyside6 \
  --include-qt-plugins=platforms,styles,imageformats,iconengines,tls \
  --noinclude-qt-translations \
  --include-package=pypdfium2 --include-package=pypdfium2_raw --include-package-data=pypdfium2_raw \
  --include-package=pikepdf --include-package-data=pikepdf \
  --include-module=PIL.PngImagePlugin --include-module=PIL.JpegImagePlugin --include-module=PIL.IcnsImagePlugin \
  --include-package=pyhanko --include-package=pyhanko_certvalidator --include-package-data=pyhanko \
  --include-package=pkcs11 --include-package=asn1crypto --include-package=tzdata \
  --include-package-data=certifi \
  --include-module=fontTools.subset --include-module=fontTools.ttLib --include-package=openpyxl \
  --include-data-dir=assets/fonts=assets/fonts \
  --include-data-files=assets/app.png=assets/app.png \
  --include-module=app.license_key --include-module=app.install_check --include-module=app.retention \
  --include-module=app.tray_preview --include-module=app.ui_pages --include-module=app.deps \
  --include-module=app.items --include-module=app.notes --include-module=app.colormode --include-module=app.orient \
  --include-module=app.ui_import --include-module=app.xlsxwrite --include-module=app.osutil \
  --include-module=app.macintegration --include-module=app.editions \
  --nofollow-import-to=pymupdf,fitz,pytest,numpy,tkinter,PIL.ImageQt,uharfbuzz,qrcode,barcode,signxml,xsdata \
  --output-dir=build/nuitka --output-filename=PdfKySo \
  --lto=yes --assume-yes-for-downloads

APP="dist/$APP_NAME.app"
[ -e "$APP" ] && mv "$APP" "build/old-$(date +%s).app"
BUILT=$(find build/nuitka -maxdepth 1 -name "*.app" -type d | head -n 1)
[ -n "$BUILT" ] || fail "Nuitka không tạo ra gói .app (xem thông báo phía trên)."
mv "$BUILT" "$APP"
cp build/app.icns "$APP/Contents/Resources/app.icns"
python installer/mac/mac_bundle.py plist "$APP/Contents/Info.plist" "$VERSION"
plutil -lint "$APP/Contents/Info.plist"

# 5) tự kiểm tra bản đã đóng gói
"$APP/Contents/MacOS/PdfKySo" --selftest > build/selftest.txt 2>&1 || true
cat build/selftest.txt
grep -q "SELFTEST OK" build/selftest.txt || fail "Bản đóng gói thiếu thư viện (xem build/selftest.txt)."

# 6) ký mã: từng thư viện bên trong trước, gói .app sau (Hardened Runtime để công chứng được)
sign() {
  if [ -n "$MAC_SIGN_ID" ]; then
    codesign --force --timestamp --options runtime --entitlements build/entitlements.plist -s "$MAC_SIGN_ID" "$@"
  else
    codesign --force -s - "$@"          # ký tạm (ad-hoc): chạy được trên máy build, KHÔNG gửi khách
  fi
}
find "$APP/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 | while IFS= read -r -d '' f; do sign "$f"; done
find "$APP/Contents" -type d -name "*.framework" -prune -print0 | while IFS= read -r -d '' f; do sign "$f"; done
sign "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

notarize() {   # $1 = file .zip / .dmg / .pkg
  [ -n "$MAC_NOTARY_PROFILE" ] || return 0
  xcrun notarytool submit "$1" --keychain-profile "$MAC_NOTARY_PROFILE" --wait || fail "Công chứng thất bại: $1 (xem: xcrun notarytool log <id> --keychain-profile $MAC_NOTARY_PROFILE)"
}
if [ -n "$MAC_SIGN_ID" ] && [ -n "$MAC_NOTARY_PROFILE" ]; then
  ditto -c -k --keepParent "$APP" build/app-notarize.zip
  notarize build/app-notarize.zip
  xcrun stapler staple "$APP"
fi

# 7) bộ cài DMG: cửa sổ có biểu tượng ứng dụng + lối tắt thư mục Applications (kéo-thả để cài)
BASE="PdfKySo-$VERSION-$ARCH"
STAGE="build/dmg"
[ -e "$STAGE" ] && mv "$STAGE" "build/dmg-old-$(date +%s)"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
cp installer/mac/HUONG_DAN_CAI_MAC.txt "$STAGE/Hướng dẫn cài đặt.txt"
DMG="dist/$BASE.dmg"
[ -e "$DMG" ] && mv "$DMG" "build/$(basename "$DMG").old-$(date +%s)"
hdiutil create -volname "$APP_NAME $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=9 "$DMG"
if [ -n "$MAC_SIGN_ID" ]; then
  codesign --force --timestamp -s "$MAC_SIGN_ID" "$DMG"
  notarize "$DMG"
  [ -n "$MAC_NOTARY_PROFILE" ] && xcrun stapler staple "$DMG"
fi
echo "===== BỘ CÀI DMG: $DMG ====="

# 8) (tùy chọn) bộ cài PKG kiểu trình hướng dẫn: cài vào /Applications, mở màn hình kích hoạt khi xong
if [ "$BUILD_PKG" = "1" ]; then
  PKGROOT="build/pkgroot"
  [ -e "$PKGROOT" ] && mv "$PKGROOT" "build/pkgroot-old-$(date +%s)"
  mkdir -p "$PKGROOT"
  # pkgbuild (mkbom) lỗi với tên thư mục có dấu ("parent directory ... does not exist"):
  # đóng gói dưới tên không dấu PdfKySo.app, postinstall đổi lại thành "PDF Ký Số.app".
  ditto "$APP" "$PKGROOT/PdfKySo.app"
  chmod +x installer/mac/pkg/scripts/postinstall
  pkgbuild --analyze --root "$PKGROOT" build/component.plist
  plutil -replace 0.BundleIsRelocatable -bool NO build/component.plist
  plutil -replace 0.BundleOverwriteAction -string upgrade build/component.plist
  pkgbuild --root "$PKGROOT" --component-plist build/component.plist --install-location /Applications \
    --identifier "$BUNDLE_ID.pkg" --version "$VERSION" --scripts installer/mac/pkg/scripts build/component.pkg
  sed "s/@VERSION@/$VERSION/g; s/@ARCH@/$ARCH/g" installer/mac/pkg/distribution.xml > build/distribution.xml
  PKG="dist/$BASE.pkg"
  [ -e "$PKG" ] && mv "$PKG" "build/$(basename "$PKG").old-$(date +%s)"
  if [ -n "$MAC_INSTALLER_ID" ]; then
    productbuild --distribution build/distribution.xml --resources installer/mac/pkg/resources \
      --package-path build --sign "$MAC_INSTALLER_ID" "$PKG"
    notarize "$PKG"
    [ -n "$MAC_NOTARY_PROFILE" ] && xcrun stapler staple "$PKG"
  else
    productbuild --distribution build/distribution.xml --resources installer/mac/pkg/resources \
      --package-path build "$PKG"
  fi
  echo "===== BỘ CÀI PKG: $PKG ====="
fi

if [ -z "$MAC_SIGN_ID" ]; then
  echo "LƯU Ý: bản này CHƯA ký Developer ID -> máy khách sẽ báo \"không thể mở vì không xác minh được nhà phát triển\"."
  echo "       Đặt MAC_SIGN_ID và MAC_NOTARY_PROFILE rồi build lại trước khi gửi khách."
fi
