# NGỮ CẢNH CHUYỂN GIAO – PDF Ký Số (bản 1.0.22, cập nhật 09/11/2026)

> Dán/đính kèm file này cho Claude ở tài khoản mới, kèm file zip mã nguồn, rồi nói: "Đọc NGU_CANH_CHUYEN_GIAO.md
> trước, rồi tiếp tục phát triển". Mọi trả lời bằng tiếng Việt.

## 1. Sản phẩm

- "PDF Ký Số": phần mềm desktop Windows + macOS để xem, sửa, ghép, đóng dấu và ký số PDF (USB token), bán thương mại.
- Chủ sở hữu: Công ty cổ phần Công nghệ ITD Việt Nam (dữ liệu thương hiệu thật chỉ nằm trên máy của chủ sở hữu).
- Mã nguồn: Python 3.12 + PySide6 6.11.2 (Essentials), pypdfium2 5.7.1, pikepdf, pyHanko + python-pkcs11, fontTools,
  Pillow, openpyxl 3.1.5. Đóng gói: Nuitka 4.2.x (Windows .exe + Inno Setup; macOS .app + .dmg). Kiểm thử: pytest.
- Không dùng PyMuPDF trong phần mềm (AGPL) – chỉ dùng trong bộ kiểm thử.
- Khoảng 24.000 dòng trong `app/`, 523 kiểm thử (Linux: 508 đạt, 15 bỏ qua; Mac: 507 đạt; Windows: đạt hết).

## 2. Quy tắc bắt buộc (không được phá)

- **Bản quyền**: cặp khóa Ed25519 sinh từ CỤM MẬT KHẨU của chủ sở hữu (`tools/keygen.py init`). Khóa bí mật không bao giờ
  nằm trong phần mềm/kho mã; chỉ có khóa công khai trong `app/license_key.py`.
- Gói zip này dùng **KHÓA MẪU** (`DEMO = True`). Máy chủ sở hữu có `app/license_key.py` thật (`DEMO = False`,
  PUBLIC_KEY bắt đầu `b5098984…`), `app/branding.py` thật và `installer/setup.iss` đã sửa
  → **khi gửi file cập nhật, KHÔNG BAO GIỜ ghi đè 3 file đó** trên máy chủ sở hữu.
- Bản bán phải build với `PDFKYSO_RELEASE=1` (script dừng nếu còn khóa mẫu).
- `tools/keygen.py`, `PdfKySo-KeyGen.exe`, `PdfKySo-KeyGen.app`, thư mục `DuLieuCapKey` (nhật ký + file .lic):
  chỉ của nhà phát triển, **không gửi khách, không đưa lên GitHub** (repo phải để riêng tư).
- `app/branding.py` trong zip là dữ liệu mẫu – chủ sở hữu tự điền.
- Trên máy người dùng: không xóa file (họ từng từ chối `rm -rf`); thay bằng `mv` sang thư mục cũ/_to_delete.
- Không sửa file `.bat` khi nó đang chạy. File `.bat` phải giữ xuống dòng CRLF.

## 3. Phân gói (app/editions.py)

- 1 = Tiêu chuẩn, 2 = Chuyên nghiệp, 3 = Doanh nghiệp. Dùng thử 15 ngày = Doanh nghiệp; đã kích hoạt = gói ghi trong mã;
  hết hạn/không mã = Tiêu chuẩn. Nâng cấp = cấp mã mới (bộ cấp mã có ô "Gói"), không cài lại.
- Tiêu chuẩn: mở/xem/in, Office→PDF, trang, ghi chú, hộp chữ, hình, bút, tẩy, **sửa chữ có sẵn, tìm & thay, sửa trang scan**.
- Chuyên nghiệp thêm: digisign, mergesign, spool (máy in ảo), tray/trayadd/traytabs/merge, colormode,
  protect/password/printperm/presets, compress, compare, hand, stamptext, notes_export.
- Doanh nghiệp thêm: verify, stamp, sigimg, seam, library, tray_advanced (bìa, mục lục, số trang, trang trắng in 2 mặt,
  mẫu khay), toc, autorotate, batchsign, flow, batchxl, autofolder, backup, history, usage_log.
- Muốn chuyển tính năng giữa các gói: chỉ sửa bảng `FEATURES`. Nút bị khóa có ổ khóa đỏ + tooltip; bấm vào hiện hộp
  thoại "Nhập mã nâng cấp…" (`MainWindow.edition_ok`, `apply_edition_ui`; `tray.apply_edition`).

## 4. Máy của chủ sở hữu

- Windows: `D:\Setup\PDF ky so\pdfkyso-ban-hoan-chinh-1.0.19` (bản đang dùng, chứa khóa thật, đã build/cài 1.0.19–1.0.20).
  Build: chạy `dong_goi_ban.bat` (kích hoạt .venv, PDFKYSO_RELEASE=1, SKIP_TESTS=1). Kiểm thử: `kiemthu_windows.bat`
  → `ketqua_kiemthu.zip`.
- MacBook Air M (arm64): `~/Downloads/pdfkyso-ban-hoan-chinh-1.0.19` (đã là 1.0.21, khóa thật, `.venv-mac`).
  Thư mục cấp mã: `~/Downloads/Cấp key phần mềm` (có `DuLieuCapKey` với 2 key đã cấp, bản Windows KeyGen.exe).

## 5. Việc đang dở (tiếp tục từ đây)

1. **Build trên Mac chưa xong.** Kiểm thử Mac đã đạt hết (sau khi sửa 4 kiểm thử). Lần build trước hỏng ở bước liên kết:
   `ld: tapi error … MacOSX27.0.sdk … unknown architecture arm64e.x1` (Command Line Tools lệch phiên bản, SDK 27 mới hơn ld).
   `build_mac.sh` và `build_keygen_mac.sh` giờ tự thử SDK cũ hơn; nếu không có → báo cài lại:
   `sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install`.
   Người dùng chạy sai thư mục (đứng trong "Cấp key phần mềm"), chưa có kết quả. Lệnh đúng:
   ```
   cd ~/Downloads/pdfkyso-ban-hoan-chinh-1.0.19
   chmod +x build_keygen_mac.sh build_mac.sh
   KEYGEN_DEST="$HOME/Downloads/Cấp key phần mềm" ./build_keygen_mac.sh 2>&1 | tee build_keygen.log
   SKIP_TESTS=1 PDFKYSO_RELEASE=1 ./build_mac.sh 2>&1 | tee build_mac.log
   ```
   Kết quả mong đợi: `Cấp key phần mềm/PdfKySo-KeyGen.app` và `dist/PdfKySo-1.0.21-arm64.dmg` (ký tạm ad-hoc;
   muốn gửi khách cần Apple Developer ID + công chứng – biến MAC_SIGN_ID, MAC_NOTARY_PROFILE).
2. (xong ở 1.0.22) bỏ `--include-package-data=tzdata` thừa; hết cảnh báo Pillow `getdata` trong kiểm thử.
3. **Kho GitHub riêng tư:** `itdvietnamjsc83-ai/PDF_ky_so` (KHÔNG chứa tools/keygen.py, build_keygen*). Mỗi lần đẩy
   mã, GitHub Actions (windows.yml) kiểm thử + đóng gói bản Windows (tải ở tab Actions -> Artifacts).
   Khóa bản quyền / branding / setup.iss THẬT nạp từ Secrets `PDFKYSO_LICENSE_KEY_PY`, `PDFKYSO_BRANDING_PY`,
   `PDFKYSO_SETUP_ISS` (nội dung file mã hóa base64, xem `tools/ci_secrets.py`); chưa có secret -> bản khóa mẫu.
   Kiểm thử keygen tự bỏ qua khi không có keygen (`tests/_keygen_demo.py` thay thế phần khóa mẫu).
   ĐỪNG đẩy mã từ máy chủ sở hữu bằng `git add -A` khi app/license_key.py, app/branding.py đang là bản thật.
4. **Chữ viết tay (đang làm 1.0.22):** anh Dũng muốn giữ cách cắt từng chữ từ phiếu tự viết, nhưng phiếu bố trí lại
   cho dễ viết hơn và có bước XEM LẠI từng chữ đã cắt (chỉnh khung cắt, độ tách nền, bỏ chữ) trước khi lưu.

## 6. Kiến thức đã rút ra (tránh lặp lỗi)

- Windows: pdfium khóa file → nạp tài liệu từ bytes (`document._read_file`). Times New Roman sinh NBSP U+00A0 thay dấu
  cách → chuẩn hóa NBSP (`text_search`, `fonts.subset` bỏ cmap thừa). Tìm không phân biệt hoa/thường của pdfium hỏng với
  tiếng Việt → tự tìm (`document.text_search`). Kiểm thử mặc định cp1252 → luôn `encoding="utf-8"`. Hộp thoại
  "Bad Image" → `SetErrorMode` (`signing.quiet_windows_loader_errors`). QLocalSocket mất dữ liệu khi client ngắt trước →
  giao thức JSON+"\n", server ngắt (`stability.SingleInstance`). Ghi file đang mở trong tab gây access violation →
  đóng tab, `QTimer.singleShot(0, …)`, ghi, mở lại.
- Nuitka: PySide6-Essentials không có plugin Qt `printsupport` → không khai báo. Chạy .bat bằng nháy đúp bỏ qua venv →
  dùng `dong_goi_ban.bat`.
- Chữ ký EC: chữ ký raw r||s có byte đầu 0x30 bị nhầm là DER (1/256) → `wincert._is_der_ecdsa`.
- macOS: phông ở `/System/Library/Fonts/Supplemental` tên có dấu cách ("Times New Roman.ttf"); ổ đĩa không phân biệt
  hoa/thường; cuối cùng dùng BeVietnamPro đóng kèm. Thư mục tạm `/var/folders` = `/private/var/folders` → so `realpath`
  (`MainWindow._is_temp`). `ru_maxrss` tính bằng byte (Linux: KB). QMessageBox không hiện tiêu đề. Xóa `__pycache__`
  chép từ Windows trước khi kiểm thử (build_mac.sh tự làm).
- Kiểm thử: conftest cô lập ProgramData + `PDFKYSO_REG_FILE` (thay Registry), ép khóa mẫu (`_demo_license_key`),
  giải phóng cửa sổ đã đóng, `_hang_guard` ghi `ketqua_treo.log` để bắt chỗ treo.

## 7. Lịch sử phiên bản gần đây

- 1.0.22: 16 góp ý (xem README mục "Bản 1.0.22"): xoay ảnh/dấu đã chèn, menu Bố cục + Ctrl+F2, nhiều cửa sổ,
  tự xoay scan viết lại (app/orient.py), khay ghép hỏi nơi lưu, màu "Như máy in đen trắng", sửa chữ giữ phông nhúng,
  hộp chữ gõ tại chỗ + thanh định dạng nổi (ui_edit.InlineFormatBar), 6 phông viết tay mới, bôi chọn & copy chữ,
  tìm kiếm tô vàng, cắt dấu từ scan (imaging: flatten/auto/keep=color/clean), giáp lai tự nhiên, giao diện tối.

- 1.0.16: hộp chữ không biến mất khi bấm bảng tùy chọn lúc đang sửa trực tiếp; cục tẩy nét vẽ/tẩy vùng lưu được.
- 1.0.17–1.0.18: loạt sửa đóng gói/kiểm thử Windows (khóa file, NBSP, tìm tiếng Việt, cp1252, Bad Image, printsupport,
  single-instance, EC 0x30), `dong_goi_ban.bat`, `kiemthu_windows.bat`.
- 1.0.19: bảng bên phải không còn bị cắt (WrapCheck, `fit_side_panel`).
- 1.0.20: phân 3 gói theo tài liệu "Gói phần mềm cung cấp" + hộp thoại "Các gói phần mềm…"; thêm openpyxl.
- 1.0.21: phông chữ macOS; sửa 4 kiểm thử trên Mac + lỗi thật `_is_temp` (/private/var); `build_mac.sh` tự chọn SDK,
  bỏ tzdata thừa; mới `build_keygen_mac.sh`; `tools/keygen.py` chạy được trên Mac (DuLieuCapKey cạnh gói .app,
  nút mở thư mục .lic).
  File đổi 1.0.20→1.0.21: app/__init__.py, app/fonts.py, app/mainwindow.py, tools/keygen.py, build_mac.sh,
  build_keygen_mac.sh, README.md, tests/test_fonts_mac.py, tests/test_gui.py, tests/test_signed_warnings.py.

## 8. Tài liệu đã có (giữ riêng, không trong zip)

- Huong_dan_su_dung_PDF_Ky_So (.docx/.pdf) – hướng dẫn khách, có mục 2.5 Các gói phần mềm và nâng cấp.
- Huong_dan_cai_thu_vien_va_tao_bo_cai (.docx/.pdf) – hướng dẫn nhà phát triển: cài thư viện, tạo bộ cài Win/Mac, cấp
  mã theo gói (mục 3.6). Cần bổ sung phần build_keygen_mac.sh và lỗi SDK của Mac khi cập nhật lần tới.

## 9. Cách chạy nhanh

```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python main.py                                           # chạy phần mềm
QT_QPA_PLATFORM=offscreen python -m pytest tests -q      # kiểm thử (Windows: kiemthu_windows.bat)
python tools/keygen.py                                   # giao diện cấp mã (cần cụm mật khẩu)
```
