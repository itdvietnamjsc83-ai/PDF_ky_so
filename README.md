# PDF Ký Số – mã nguồn Windows + macOS (giai đoạn 1–6, đủ để đóng gói bán)

Phần mềm desktop Windows chỉnh sửa, ghép và ký số PDF. Bản này gồm **giai đoạn 1** (nền tảng: giao diện,
xem, zoom, lưu, in) và **giai đoạn 2** (quản lý trang, chèn ảnh, khay ghép, máy in ảo) và **giai đoạn 3** (con dấu, chữ ký ảnh,
giáp lai, thư viện mã hóa) và **giai đoạn 4** (ký số bằng mọi USB token), kèm các cơ chế chạy ổn định khi đóng gói.

## Công nghệ (tất cả miễn phí, dùng được khi bán phần mềm)

| Thành phần | Thư viện | Giấy phép | Vì sao chọn |
| --- | --- | --- | --- |
| Giao diện | PySide6-Essentials (Qt 6) | LGPL-3 | Nhanh, giao diện desktop đẹp; bản Essentials nhẹ hơn bản đầy đủ |
| Đọc/render PDF | pypdfium2 (PDFium của Google Chrome) | Apache-2.0 / BSD-3 | Engine PDF mạnh và nhanh bậc nhất, chỉ ~5 MB |
| Tối ưu khi lưu, mã hóa | pikepdf (qpdf) | MPL-2.0 | Nén cấu trúc file, gộp ảnh trùng, mã hóa AES-256 |
| Ảnh con dấu | Pillow | MIT-CMU | Tách nền trắng nhanh (chạy bằng C), chỉ nạp khi dùng |
| Ký số | pyHanko + python-pkcs11 | MIT | Chuẩn PAdES, dấu thời gian, LTV; nói chuyện trực tiếp với driver của token |
| Biên dịch .exe | Nuitka | Apache-2.0 | Ra mã máy: chạy nhanh hơn, nhỏ hơn, khó dịch ngược |

> Không dùng PyMuPDF trong phần mềm (giấy phép AGPL bắt buộc mua license khi bán). PyMuPDF chỉ
> dùng trong bộ kiểm thử để tạo file PDF mẫu, không đóng gói vào bản phát hành.

## Chạy thử (máy Windows)

```bat
:: 1. Cài Python 3.12 64-bit từ python.org (tích "Add python.exe to PATH")
:: 2. Trong thư mục mã nguồn:
python -m pip install -r requirements.txt
python main.py
:: mở sẵn file:  python main.py "D:\Ho so\bao-gia.pdf"
```

## Kiểm thử

```bat
python -m pip install -r requirements-dev.txt
python -m pytest tests -q                       :: 318 kịch bản kiểm thử tự động
python tools\benchmark.py "D:\file-lon.pdf"      :: đo tốc độ, bộ nhớ trên file thật
```

## Biên dịch ra .exe

```bat
build_windows.bat
```

Kết quả ở `dist\main.dist\PdfKySo.exe`. Chỉ đóng gói các module Qt thật sự dùng. Có Inno Setup 6 thì tạo
luôn bộ cài `dist\PdfKySo-Setup-x.y.z.exe`.

## Đã có trong bản này

- Giao diện Windows 11 (Fluent): 7 nhóm công cụ, tab file, thumbnail, panel thuộc tính, thanh
  trạng thái; sáng/tối tự theo Windows, có nút đổi tay (lưu lại lựa chọn).
- Mở nhiều file (nút Mở, kéo thả, dòng lệnh), file có mật khẩu mở, báo lỗi file hỏng không treo.
- Nhận biết loại trang: **Văn bản** (từ Word/Excel), **Ảnh/Scan**, **Trang trắng**.
- Zoom 10%–6400%: giữ Ctrl + xoay chuột (zoom quanh con trỏ), Ctrl +/−, thanh trượt,
  Vừa trang (Ctrl+0), 100% (Ctrl+1), Vừa rộng (Ctrl+2).
- Thao tác trang: xoay, xóa (chặn xóa hết), chèn trang trắng cùng khổ/hướng trang trước,
  chèn trang từ file PDF khác; hoàn tác / làm lại (Ctrl+Z / Ctrl+Y).
- Lưu: file có chữ ký số -> lưu nối tiếp (giữ chữ ký); file thường -> tối ưu dung lượng.
  Cảnh báo khi sửa file đã ký. Hỏi lưu khi đóng tab chưa lưu.
- In (Ctrl+P), đi tới trang (Ctrl+G), toàn màn hình (F11).
- Các nút của giai đoạn sau đã có vị trí trên giao diện, bấm vào báo sẽ có ở giai đoạn nào.

## Giai đoạn 2 – đã có

- **Quản lý trang:** kéo thả thumbnail để sắp xếp, chuột phải để xoay trái/phải, xóa, chèn trang trắng,
  chèn trang từ file khác, trích/tách, đổi kích thước. Chọn nhiều trang bằng Ctrl/Shift.
- **Tự xoay đúng hướng:** trang có chữ bị nằm ngang/lộn ngược được xoay lại (trang scan cần nhận
  dạng chữ – làm ở giai đoạn sau).
- **Tách file:** mỗi N trang, theo dải ("1-3, 4-10, 11-"), mỗi trang một file, hoặc trích các trang
  đang chọn.
- **Đổi kích thước trang:** A3/A4/A5/Letter/Legal/tự nhập; co vừa / lấp đầy / giữ 100%; thêm lề.
  Nội dung giữ nguyên dạng vector (chữ vẫn nét, tìm kiếm được), file không phình.
- **Chèn ảnh** (dùng được cả trên file scan): kéo để di chuyển, kéo 4 góc để đổi cỡ (giữ tỉ lệ),
  phím mũi tên để nhích (Shift = 10 pt), Enter/nháy đúp để đặt, Esc để hủy. PNG trong suốt giữ
  nguyên nền trong suốt; ảnh chụp tự nén JPEG và giới hạn 300 dpi theo kích thước đặt.
- **Khay ghép PDF:** thêm file / tab đang mở, tích chọn file, "Cả file" hoặc "Chọn trang" (gõ dải
  hoặc tích trên ảnh thu nhỏ, nút Trang lẻ/chẵn), đổi thứ tự, in 2 mặt (tự chèn trang trắng để mỗi file
  bắt đầu ở trang lẻ), làm chẵn tổng số trang, tự xoay, bookmark theo tên file, đổi khổ khi ghép,
  lưu/mở mẫu khay (không lưu mật khẩu), khay tự nhớ khi tắt phần mềm. "Ghép + mở để ký" chuyển sang
  nhóm Ký & Đóng dấu.
- **Máy in ảo:** `installer\cai_may_in_ao.ps1` tạo 2 máy in "PDF Khay ghep" và "PDF Ky so" (dùng driver
  Microsoft Print to PDF có sẵn). In từ Word vào "PDF Khay ghep" -> file tự vào cuối khay; in vào
  "PDF Ky so" -> file tự mở ở chế độ ký. Chạy script bằng quyền Administrator (bộ cài sẽ tự gọi).

## Giai đoạn 3 – đã có

- **Thư viện dấu & chữ ký** (panel bên phải): nhập ảnh chụp/scan -> tách nền giấy trắng, làm đậm nét,
  đổi màu mực (đỏ/xanh/đen), tự cắt viền; xem trước trên nền ô cờ. Đoán loại theo tên file.
- **Đóng dấu:** bấm vào mẫu hoặc kéo thả mẫu vào đúng chỗ trên trang; chọn "Đóng lên" trang hiện tại /
  các trang đang chọn / tất cả trang (1 lần Ctrl+Z gỡ hết). Ảnh giới hạn 600 dpi theo cỡ đóng.
- **Giáp lai:** chia dấu thành N mảnh, mỗi trang một mảnh sát mép phải (hoặc trái), chọn vị trí dọc,
  đường kính, đảo thứ tự mảnh.
- **Bảo mật thư viện:** đặt mật khẩu -> file thư viện mã hóa AES-256 (không đọc được ảnh hay tên mẫu
  nếu không có mật khẩu), tự khóa sau 15 phút không dùng, nút Khóa lại.
- **Nhật ký dùng dấu:** mỗi lần đóng dấu ghi thời gian, người dùng máy, mẫu, tài liệu, trang vào
  `nhat_ky_dung_dau.csv` (mở bằng Excel).
- **File nhỏ:** cùng một con dấu đóng trên nhiều trang chỉ lưu 1 bản ảnh (thử 20 trang: 1,6 MB -> 80 KB).

## Giai đoạn 4 – ký số bằng mọi USB token

Phần mềm **không tự viết cách nói chuyện với từng loại token** mà dùng chính phần mềm (driver) của hãng
đã cài trên máy – vì vậy dùng được với mọi hãng: VNPT-CA, Viettel-CA, BKAV-CA, FPT-CA, MISA-CA, EasyCA,
Safe-CA, Newtel-CA, CA2, Nacencomm… và thẻ/token quốc tế (SafeNet, Feitian ePass, OpenSC…).

| Đường ký | Cách hoạt động | Mã PIN |
| --- | --- | --- |
| **PKCS#11** (ưu tiên) | Tự dò file driver PKCS#11 của hãng trong `System32` và `Program Files`, nạp thử, giữ driver có token đang cắm. Có nút **Thêm driver…** nếu hãng để ở chỗ lạ | Phần mềm hỏi; token có bàn phím thì nhập trên token |
| **Kho chứng thư Windows** | Đọc chứng thư mà phần mềm token đã đăng ký vào Windows, ký qua KSP/CSP của hãng (CNG hoặc CryptoAPI đời cũ), RSA và ECDSA | Chính hộp thoại PIN của phần mềm token hiện ra |

- Cùng một chứng thư thấy qua cả 2 đường -> chỉ hiện 1 dòng, ưu tiên PKCS#11. Token chỉ có cơ chế ký "thô"
  (đời cũ) vẫn ký được: phần mềm tự băm SHA-256 rồi nhờ token ký.
- **Hộp thoại Ký số** (Ctrl+K): chọn chứng thư (báo hạn dùng, cảnh báo sắp hết hạn, chặn chứng thư hết hạn),
  kiểu hiển thị (dấu + chữ ký + thông tin / chỉ ảnh / chỉ thông tin / ký ẩn), chọn con dấu, chữ ký từ thư viện
  (chưa chọn thì tự lấy mẫu có sẵn), màu chữ, lý do, nơi ký, dấu thời gian TSA, LTV, khóa tài liệu sau khi ký.
  Nhớ lựa chọn cho lần sau.
- **Vị trí chỉ là gợi ý:** phần mềm tìm "ĐẠI DIỆN", "GIÁM ĐỐC", "(Ký, ghi rõ họ tên)"… ở các trang cuối và đặt
  khung ngay dưới; người dùng kéo đi chỗ khác, kéo góc đổi cỡ, Enter để ký, Esc để hủy.
- Sai PIN: báo và cho nhập lại, cảnh báo rõ khi chỉ còn 1 lần thử; PIN bị khóa, rút token giữa chừng, mất mạng
  khi lấy dấu thời gian -> thông báo tiếng Việt dễ hiểu, không mất file.
- Ký trong luồng nền (giao diện không đơ). Ký kiểu nối tiếp: file gốc giữ nguyên từng byte, chữ ký trước vẫn
  hợp lệ -> nhiều người ký lần lượt trên một file. Kết quả lưu thành `ten-file_da_ky.pdf` và mở ngay.
- In vào máy in ảo "PDF Ky so" hoặc "Ghép + ký" ở khay: tự mở hộp thoại ký.
- **Kiểm tra chữ ký:** người ký, nhà cung cấp, thời gian ký, dấu thời gian, còn nguyên vẹn hay đã bị sửa,
  có vi phạm khóa tài liệu không, chứng thư có tin cậy (dùng kho chứng thư gốc của Windows) không.
- Kiểm thử: token giả lập SoftHSM2 (chuẩn PKCS#11 như token thật, RSA và ECDSA), sai PIN, rút token, 2 chữ ký,
  ký chứng nhận rồi sửa, sửa 1 byte, trang xoay 90/180/270, dấu thời gian, file 300 trang. Trên GitHub Actions
  Windows còn tạo chứng thư trong kho Windows (KSP RSA, KSP ECDSA, CSP đời cũ) để kiểm thử đường ký qua Windows.

## Giai đoạn 5 – chỉnh sửa nội dung

Mọi thứ thêm vào trang là đối tượng PDF thật (chữ thật, nét vector), không phải ảnh chụp: phóng to, in vẫn
sắc nét, file tăng rất ít (phông chữ chỉ nhúng các ký tự dùng tới, mỗi hộp chữ vài KB).

- **Sửa chữ** (PDF từ Word/Excel): bấm vào dòng chữ, sửa, chữ mới giữ đúng vị trí, cỡ, màu; phông cùng kiểu
  (Times/Arial/Calibri… đậm/nghiêng) lấy từ Windows. Trang scan: phần mềm hướng dẫn dùng Tẩy vùng + Hộp chữ.
- **Tìm & thay** trên toàn tài liệu, 1 lần Ctrl+Z hoàn tác hết; chỗ nào cụm chữ bị tách đoạn thì báo rõ.
- **Hộp chữ** tự ngắt dòng theo khung, chọn phông/cỡ/màu; **Ghi chú** dạng sticky note (mở được ở mọi phần mềm PDF).
- **Ký hiệu** ✓ ✗ ● ○ ☐ ☑, **Hình vẽ** (chữ nhật, elip, đường thẳng, mũi tên, bút dạ quang), **Vẽ tay** (nét mượt,
  tự rút gọn điểm), **Tẩy vùng** (gỡ hẳn chữ trong vùng + phủ trắng). Dùng được cả trên trang scan.
- **Chữ viết tay:** 5 nét chữ viết tay miễn phí có đủ dấu tiếng Việt, hoặc **nét chữ của chính bạn**: in phiếu mẫu
  (1 trang A4), viết tay, scan/chụp -> phần mềm tự nắn thẳng, cắt từng chữ, tự đặt dấu thanh khi gõ. Lưu trong
  thư viện (được mã hóa nếu đặt mật khẩu). **Vẽ tay** chữ ký/chữ viết bằng chuột hoặc bút cảm ứng.
- **Sửa/xóa ảnh, con dấu đã chèn:** bấm vào ảnh -> kéo để di chuyển, kéo góc để đổi cỡ, Delete để xóa, Esc giữ
  nguyên. Dữ liệu ảnh gốc giữ nguyên (không nén lại).
- **Ảnh scan đúng kích thước thật:** đọc độ phân giải máy scan (vd. 600 dpi) trong file; không có thì suy ra từ khổ
  giấy (scan nguyên trang A4). Con dấu nhập từ bản scan có chiều rộng thật (vd. 40 mm) -> đóng lên trang đúng cỡ,
  không bị to quá. Cắt sát con dấu trên ảnh gốc trước khi thu nhỏ -> dấu vẫn nét.
- **Ô số trang ở thanh dưới:** bấm vào, gõ số trang, Enter là tới (Ctrl+G); lăn chuột trên ô để sang trang.

## Giai đoạn 6 – bảo vệ, ký hàng loạt, công cụ

- **Lưu có bảo vệ** (AES-256): mật khẩu mở file (tùy chọn), mật khẩu chủ sở hữu; quyền in (không / chất lượng thấp /
  đầy đủ), sao chép, sửa, ghi chú. **In mờ – xem nét:** mỗi trang có lớp xem (bản gốc, không in) và lớp in (ảnh
  72/100/150 dpi, có thể thang xám) – chỉ thêm khi chọn "in chất lượng thấp", báo trước dung lượng tăng
  (~12–45 KB/trang). **Mẫu bảo vệ** có sẵn + tự lưu mẫu riêng (không lưu mật khẩu).
- File được bảo vệ mở bằng phần mềm này: tôn trọng quyền của người gửi (chỉ xem, in theo quyền, in mờ đúng lớp in).
  **Gỡ bảo vệ** bằng mật khẩu chủ sở hữu. **Ký số file đã bảo vệ**: nhập mật khẩu chủ sở hữu, quyền giữ nguyên.
- **Ký hàng loạt:** chọn nhiều file / cả thư mục, một chứng thư, nhập PIN một lần; tự tìm chỗ ký từng file, hoặc
  ký vào ô chuẩn bị sẵn, hoặc ký ẩn; file lỗi không làm dừng file khác, báo cáo cuối.
- **Luồng ký:** chuẩn bị ô ký cho từng người (Người lập → Kế toán → Giám đốc…); mỗi người mở file, bấm Ký số,
  chọn đúng ô của mình. Các chữ ký trước vẫn hợp lệ.
- **Nén theo dung lượng** (vd. dưới 2/5/10 MB cho cổng dịch vụ công): chỉ nén lại ảnh scan lớn, chữ/dấu giữ nguyên.
- **So sánh 2 bản:** chỉ ra trang khác, đoạn chữ bị bỏ/thêm, khung đỏ vùng khác (cả dấu, chữ ký, hình); tạo bản
  báo cáo so sánh.
- **Dấu chữ:** ĐÃ DUYỆT, BẢN SAO, MẬT, NHÁP… kiểu khung dấu ở góc hoặc chữ chéo mờ giữa trang.
- **Tạo hàng loạt từ Excel:** mẫu (Word in ra PDF) có chỗ {{Họ tên}}, {{Số tiền}}… + file Excel/CSV -> mỗi dòng một
  file PDF, đặt tên theo cột (không cần cài Excel).
- **Lịch sử phiên bản:** mỗi lần lưu đè tự cất bản trước (20 bản gần nhất); mở xem hoặc khôi phục.
- **Sao lưu & chuyển máy:** thư viện dấu (vẫn mã hóa), nhật ký, mẫu, cài đặt vào 1 file .zip; khôi phục trên máy mới.
- **Thư mục tự xử lý:** thả file vào thư mục -> tự đóng dấu chữ / nén / bảo vệ, kết quả ở thư mục con "da_xu_ly".
- **Gửi email:** mở thư mới của Outlook/Thunderbird đã đính kèm file; máy không có phần mềm email thì mở thư mục chứa
  file để kéo vào Gmail/Zalo.
- Chưa làm (cần máy chủ/dịch vụ ngoài hoặc để bản sau): ký từ xa qua điện thoại, nhận dạng chữ (OCR).

## Giai đoạn 6c – bìa & mục lục khi ghép

Khay ghép có thêm: **trang bìa** (đơn vị, tiêu đề, dòng phụ, ngày), **mục lục** (tên từng tài liệu + số trang, bấm để
nhảy tới), **đánh số trang** "Trang x / y" (trừ trang bìa). In 2 mặt: tự đệm trang trắng để nội dung vẫn bắt đầu ở
trang lẻ; bookmark có thêm "Trang bìa", "Mục lục".

## Giai đoạn 6b – bản quyền, bộ cài, thông tin nhà phát triển

### Trước khi bán – làm 3 việc (một lần)

1. **Thông tin nhà phát triển:** sửa `app/branding.py` (tên, điện thoại/Zalo, email, website) và dòng
   `AppPublisher` trong `installer/setup.iss`, `--company-name` trong `build_windows.bat`.
2. **Tạo cặp khóa bản quyền:** `python tools\keygen.py init` -> nhập **cụm mật khẩu nhà phát triển** (dài, dễ nhớ,
   ví dụ "mua thu ha noi 2026 cay bang"). Phần mềm chỉ chứa khóa công khai. Khóa bí mật **không lưu ở đâu cả**:
   lúc nào cần cấp key, gõ lại cụm mật khẩu là tạo lại đúng khóa đó -> không sợ mất file khóa, không phải đóng gói
   lại. Ghi cụm mật khẩu ra giấy cất kỹ; quên cụm mật khẩu thì không cấp key được cho các bản đã bán.
   (Mã nguồn đang dùng **khóa mẫu**; `build_windows.bat` sẽ cảnh báo, và dừng hẳn nếu đặt `PDFKYSO_RELEASE=1`.)
3. **Đóng gói:** `build_windows.bat` -> `dist\PdfKySo-Setup-x.y.z.exe` (cần Inno Setup 6 miễn phí). Có chứng thư
   code signing thì đặt `SIGN_PFX`, `SIGN_PASS` trước khi chạy -> tự ký cả .exe và bộ cài (Windows không cảnh báo
   "không rõ nhà phát hành").

### Bộ tạo mã dạng .exe (không cần Python)

`build_keygen.bat` -> `dist_keygen\PdfKySo-KeyGen.exe` (1 file, bấm đúp là mở). Chạy sau khi đã `keygen.py init`.
Cửa sổ có: ô cụm mật khẩu + nút **Mở khóa** (báo ngay nếu sai), kiểm tra mã máy khi gõ (đủ 16 ký tự), chọn hạn
dùng (số ngày / đến ngày / vĩnh viễn) kèm dòng xem trước ngày hết hạn, nút **Tạo mã** (tự sao chép), **Sao chép mã**,
**Mở thư mục file .lic**, thẻ **Đã cấp** để tra cứu và sao chép lại mã cũ. Nhật ký và file .lic nằm trong
`DuLieuCapKey` cạnh file .exe. File .exe không chứa cụm mật khẩu -> lộ file cũng không ai cấp được mã.
Không gửi file này cho khách.

### Bán hàng – cấp key

- Khách cài xong, phần mềm hiện màn hình **Bản quyền**: chọn **Dùng thử 15 ngày** hoặc **nhập mã kích hoạt**; màn hình
  hiện **mã máy** (XXXX-XXXX-XXXX-XXXX) + nút Sao chép + thông tin liên hệ của bạn.
- Khách gửi mã máy -> bạn chạy `python tools\keygen.py` (giao diện) hoặc
  `python tools\keygen.py issue --machine ABCD-... --days 365 --customer "Công ty A"` (`--until 2027-12-31`,
  `--forever`, `--edition 1|2|3`) -> ra mã kích hoạt + file `.lic`; mọi lần cấp ghi vào `tools\nhat_ky_cap_key.csv`.
- Khách dán mã (hoặc mở file .lic) -> kích hoạt ngay, **không cần Internet**. Key chỉ chạy trên đúng máy đó, có hạn
  dùng; đổi máy / cài lại Windows thì gửi mã máy mới để cấp lại.
- Key là chữ ký số Ed25519: không ai tự tạo được key, kể cả khi dịch ngược phần mềm.
- Hết hạn dùng thử / hết hạn key: vẫn mở xem, in, kiểm tra chữ ký; lưu, ký, ghép, chỉnh sửa thì yêu cầu kích hoạt.
- Chống gian lận offline: ngày dùng thử lưu 3 nơi (AppData, Registry, ProgramData) có mã chống sửa; phát hiện chỉnh
  lùi đồng hồ máy. (Offline thì không chặn tuyệt đối được – đủ để ngăn người dùng thông thường.)

### Bộ cài (`installer/setup.iss`)

**Bắt buộc cài đặt:** bản .exe chỉ chạy khi đã cài bằng bộ cài. Chép thư mục phần mềm sang máy khác (hoặc sang chỗ
khác trên cùng máy) rồi bấm PdfKySo.exe -> phần mềm báo "chưa được cài đặt" và thoát. Phần mềm đối chiếu khóa gỡ cài
đặt mà bộ cài ghi vào Registry (AppId trong `setup.iss` = `APP_ID` trong `app/install_check.py`) với chính thư mục
đang chạy và file `unins000.exe`. Chạy từ mã nguồn (`python main.py`) thì không kiểm tra.

### Bản portable (không cần cài)

`build_windows.bat` tạo thêm `dist\PdfKySo-Portable-x.y.z.zip`: giải nén là chạy (kể cả trên USB). Nhận biết bằng
file `PdfKySo.portable` cạnh `PdfKySo.exe` (xóa file này thì phần mềm đòi cài đặt). Thư viện dấu, cài đặt, bản quyền
lưu trong thư mục `Data` bên cạnh. Mã kích hoạt vẫn theo từng máy; mang sang máy khác thì dùng thử/kích hoạt theo mã
máy mới (không bị coi là gian lận). Không có máy in ảo và mục "Mở bằng".

Tiếng Việt; cài vào Program Files; biểu tượng Desktop; thêm "Mở bằng PDF Ký Số" (tùy chọn đặt làm mặc định); tự tạo
2 máy in ảo (thư mục chung `C:\ProgramData\PdfKySo\spool`, đúng cho mọi tài khoản); cài xong mở màn hình kích
hoạt. Gỡ cài đặt: gỡ máy in ảo, **giữ** thư viện dấu và bản quyền (cài lại không mất).

### Giới thiệu

Nhóm Công cụ có **Bản quyền** và **Giới thiệu** (phiên bản, trạng thái bản quyền, mã máy, thông tin nhà phát triển,
danh sách thành phần mã nguồn mở và giấy phép – Qt dùng LGPL dạng thư viện động nên được phép dùng trong phần mềm bán).

## Giao diện "Ấn triện" (1.0.6)

- Màu mực xanh đêm, đỏ son con dấu, nền giấy; phông **Be Vietnam Pro** (SIL OFL, đi kèm trong `assets/fonts/ui`,
  đã rút gọn còn Latin + tiếng Việt) – máy khách không cần cài phông. Có chế độ tối (nút mặt trăng ở thanh trái).
- **Thanh điều hướng trái**: 7 nhóm (Trang chủ, Chỉnh sửa, Trang, Ký & Dấu, Bảo vệ, Khay ghép, Công cụ).
- **Dải công cụ** dạng ô biểu tượng có màu theo loại việc; nút chính (Ký số, Lưu có bảo vệ, Ghép + ký) to, màu đỏ.
- **Ẩn/hiện thanh công cụ chính**: nút mũi tên ở góc phải trên cùng hoặc **Ctrl+F1**; khi đang ẩn, bấm một nhóm ở
  thanh trái thì dải công cụ hiện lại. Phần mềm nhớ lựa chọn cho lần mở sau.
- **Màn hình bắt đầu**: khung kéo thả, 6 ô bắt đầu nhanh, danh sách **mở gần đây** (12 file, bấm để mở lại; file
  tạm/bản in từ máy in ảo không lưu vào danh sách), thẻ bản quyền.
- **Thẻ chứng thư số** (bảng bên phải): chứng thư dùng gần nhất, hạn dùng, nút **Dò USB token** và **Ký số**.
- **Bảng thông tin nhà phát triển** hiện mỗi lần mở phần mềm (trước màn hình bản quyền) và khi bấm nút ⓘ ở thanh
  trái. Nội dung lấy từ `app/branding.py` – nhớ sửa tên, điện thoại/Zalo, email, website trước khi đóng gói.

## Lịch sử & dữ liệu – thời hạn tự xóa (1.0.8)

- **Công cụ → Xóa lịch sử** (hoặc “Xóa lịch sử…” ở màn hình bắt đầu) mở bảng **Lịch sử & dữ liệu lưu trên máy**: mỗi mục có
  ô tích, cho biết đang lưu bao nhiêu, và **thời hạn tự xóa**: Không lưu / 7 ngày / 30 ngày / 6 tháng / 1 năm / Vĩnh viễn.
  Có **Chọn tất cả**, **Xóa mục đã chọn**, **Xóa tất cả…** (xóa toàn bộ, hỏi lại một lần), **Lưu thời hạn**.
- Các mục: danh sách mở gần đây · lịch sử phiên bản · nhật ký dùng dấu (xóa theo từng dòng quá hạn) · PDF tạm từ Office
  (cả thư mục tạm trong %TEMP%) · bản in từ máy in ảo · bản khôi phục sự cố còn sót · nhật ký hoạt động (log, crash.log)
  · khay ghép đã nhớ · dấu vết khác (thư mục gần nhất, chứng thư gần nhất, driver đã dò) · mẫu & cấu hình (mẫu bảo vệ,
  mẫu khay – cả file .khay.json đã lưu, thư mục tự xử lý, tùy chọn ký/chữ/ảnh) · thư viện dấu, chữ ký, chữ viết tay.
  Ba mục cuối chỉ xóa khi người dùng chọn (không tự xóa theo thời gian); thư viện và mẫu hỏi lại trước khi xóa.
- Mặc định: phiên bản 6 tháng; PDF tạm từ Office, bản in máy in ảo 7 ngày; bản khôi phục, nhật ký hoạt động 30 ngày;
  còn lại vĩnh viễn. Tự xóa chạy khi mở phần mềm và mỗi 6 giờ. “Không lưu” = không ghi mục đó nữa (không cất phiên bản,
  không nhớ file gần đây, không ghi nhật ký dùng dấu, không nhớ khay).
- Danh sách gần đây: chuột phải → xóa khỏi danh sách (Delete), mở thư mục chứa file, xóa file không còn, xóa toàn bộ.
  Hộp thoại Lịch sử phiên bản: Xóa bản này / Xóa toàn bộ lịch sử file này.
- Không xóa được bằng phần mềm: các bản trước nằm bên trong file PDF đã ký số (xóa là mất hiệu lực chữ ký).

## Tùy chọn ảnh khi chèn (1.0.8)

Khi đặt ảnh, con dấu, chữ ký ảnh, nét chữ tay của mình lên trang, bảng **Tùy chọn ảnh** hiện ở bên phải:
- **Lớp:** *Nổi trên chữ* (như trước) · *Hòa trộn như mực thật* (blend Multiply – chữ đen hiện xuyên qua mực, giống dấu
  đóng thật; dùng được cả trang scan) · *Chìm dưới chữ* (ảnh nằm dưới chữ, hình, ô bảng; trang scan hoặc file đã ký số
  tự dùng Hòa trộn vì cả trang là ảnh / để không phải viết lại file).
- **Độ đậm** 10–100 %, **Xoay** tự do ±180° (nút ⟲90° ⟳90°, **Nghiêng** ngẫu nhiên 3–9° như dấu đóng tay, 0°) – xoay bằng
  ma trận nên ảnh JPEG không bị nén lại.
- **Xóa nền trắng** (ảnh chụp/scan dấu, chữ ký) và **Đóng lên**: trang hiện tại / các trang đang chọn / tất cả các trang.
- Xem trước trực tiếp khi đổi tùy chọn. Phần mềm nhớ lớp và độ đậm cho lần sau.
- **Ảnh đã chèn:** bấm vào ảnh → đổi lớp, độ đậm, vị trí, cỡ (hoặc Delete); phần mềm nhớ lớp của từng ảnh nó chèn.

## File đối tác đã ký số / đã khóa / được bảo vệ – cảnh báo (1.0.9)

- Mở file đã có chữ ký số: **dải cảnh báo** trên đầu tài liệu cho biết ai đã ký, ngày ký và điều cần tránh; nút
  *Kiểm tra chữ ký*, *Ký số tiếp…*. Màu vàng: có chữ ký, còn hợp lệ. Màu đỏ: file đã **KHÓA** (ký chứng nhận không cho
  thay đổi), chữ ký **KHÔNG HỢP LỆ** (file bị sửa sau khi ký), hoặc bạn đã sửa nội dung trong phiên này. File được bảo vệ:
  dải cảnh báo + nút *Gỡ bảo vệ…*. Thiếu chứng thư gốc: ghi chú “chưa xác minh nhà cung cấp – nội dung vẫn nguyên vẹn”.
- **Mọi thao tác sửa** trên file đã ký (đóng dấu, chữ ký ảnh, chèn ảnh, chữ, hình, ghi chú, tẩy, tìm & thay, dấu chữ,
  giáp lai, xoay/xóa/chèn/sắp xếp/đổi cỡ trang, sửa ảnh đã chèn) đều hỏi trước: *Hủy – giữ nguyên chữ ký* (mặc định) ·
  *Ký số (giữ chữ ký của đối tác)…* · *Vẫn sửa (chữ ký sẽ mất hiệu lực)*, có ô “Không hỏi lại với file này trong lần mở
  này”. Không hỏi với: hoàn tác, Luồng ký (thêm ô ký trống vẫn giữ chữ ký cũ).
- **Trước khi ký:** file đã khóa -> không cho ký, giải thích rõ; chữ ký có sẵn không hợp lệ -> hỏi; bình thường -> báo
  “chữ ký của bạn được thêm nối tiếp, chữ ký cũ vẫn giữ hiệu lực”, ký xong kiểm tra lại và báo chữ ký cũ vẫn hợp lệ.
  Lỗi khóa tài liệu từ thư viện ký được dịch sang tiếng Việt (cả khi ký hàng loạt).
- Lưu / Lưu thành sau khi sửa file đã ký, nén, tách trang, gỡ bảo vệ, ghép trong khay (lúc thêm file và lúc ghép) đều
  cảnh báo chữ ký sẽ mất / không đi theo file mới. Thư mục tự xử lý bỏ qua file đã ký (báo lỗi, file giữ nguyên).

## Khay ghép – xem trước file (1.0.10)

- Bấm một file trong khay: bảng **Xem trước** bên phải hiện ảnh tất cả các trang dạng lưới, **cuộn** được, dưới mỗi ảnh có
  **số trang** và vị trí trong file ghép (“Trang 3 → 7”). Thanh **Cỡ** phóng to/thu nhỏ ảnh trang.
- **Giữ / bỏ trang:** tích / bỏ tích từng trang (trang bỏ bị mờ, gạch chéo đỏ, chữ BỎ); nút Tất cả · Lẻ · Chẵn · Đảo ·
  Bỏ hết; chọn nhiều trang rồi **Space** để đổi; chuột phải: giữ / bỏ / chỉ giữ các trang đang chọn. Cột “Trang chọn” và
  tổng số trang của khay cập nhật ngay. Bỏ hết -> file đó không ghép trang nào.
- **Xem lớn:** nháy đúp (hoặc Enter) một trang -> cửa sổ xem từng trang: ◀ ▶ / ← → / PgUp PgDn / Home End, cuộn chuột hết
  trang thì sang trang kế, Ctrl+lăn chuột hoặc − + Vừa khung để phóng to, ô **Giữ trang này khi ghép** (Space).

## Đợt 1 – chọn trang ký, khay ghép, thao tác trang (1.0.11)

- **Ký ở trang** (hộp thoại Ký số): Gợi ý tự động / Trang đang xem / Trang đầu / Trang cuối / Trang số… (nhớ lựa chọn).
  Khi đặt khung ký có dòng hướng dẫn “Bấm vào trang khác để chuyển sang trang đó”.
- **Khay ghép:** kéo thả file PDF/Word/Excel/PowerPoint vào khay; ô **Lưu vào** + **Tên file** (mặc định thư mục file
  đầu tiên / lần trước, tên theo tiêu đề bìa hoặc file đầu + ngày); **Ghép lưu luôn**, báo đường dẫn, nút **Mở thư mục
  chứa file**, trùng tên hỏi ghi đè / thêm số; **Ghép + ký** không hỏi lưu nữa.
- **Xem trước khay:** nút **Vừa khung** (giãn hết bề ngang ô, vẽ lại nét theo cỡ và tỉ lệ màn hình), thanh Cỡ tới 1600 px
  kèm %, Ctrl + lăn chuột, các trang chia đều bề ngang (không dồn góc trái).
- **Trang trắng:** trước/sau trang hiện tại, đầu/cuối file, sau trang N, số lượng.
- **Xóa trang:** hiện tại / đang chọn / nhập dải / lẻ / chẵn / trang trắng / trang trùng lặp, xem trước ảnh trang sẽ xóa,
  không cho xóa hết; phím **Delete** trên ảnh thu nhỏ.
- **Tự xoay:** hộp xem trước trước → sau, bỏ tích từng trang; xoay nhanh trang ngang → dọc, trang lẻ/chẵn 180°; báo rõ
  trang scan chưa nhận biết được hướng. Nút **⟲ ⟳** trên ảnh thu nhỏ khi di chuột qua.
- Hộp Kiểm tra chữ ký: “nội dung trang đã bị thay đổi sau khi ký” (thay câu dễ hiểu nhầm “vi phạm khóa”).

## Đợt 2 – ghi chú, chọn lại để sửa, hình vẽ, bút, tẩy vùng, chèn trang (1.0.12)

- **Đọc ghi chú:** bấm vào biểu tượng ghi chú để mở ra đọc – kể cả ghi chú tạo từ Acrobat, Foxit, Word… (ghi chú dán,
  tô sáng, gạch chân/ngang, hộp chữ, hình có lời bình), luồng trả lời /IRT, và cả file đã ký số / bị khóa sửa (chỉ đọc).
- **Ghi chú (12a, 12d):** bấm để mở/sửa nội dung, người ghi; kéo để dời; Delete để xóa; màu, biểu tượng (ghi chú, ?, !, ✓,
  tờ giấy), độ đậm; đánh dấu **Đã xử lý** (huy hiệu ✓ xanh); trả lời ngay trong hộp sửa.
- **Danh sách ghi chú (12b):** nút **DS ghi chú** (tab Chỉnh sửa) – lọc theo người ghi, theo ngày, ẩn ghi chú đã xử lý;
  bấm để tới đúng trang; Trả lời / Đã xử lý / Mở–sửa / Xóa.
- **Chọn lại nội dung đã thêm (13a–13e):** nút **Chọn**; bấm vào hộp chữ, hình vẽ, ký hiệu, nét vẽ tay để kéo di chuyển,
  kéo góc đổi cỡ, kéo núm tròn để xoay (Shift: bước 15°), Delete để xóa, Esc bỏ thay đổi. **Nháy đúp hộp chữ** để gõ sửa
  ngay trên trang. Con trỏ đổi theo ngữ cảnh (4 mũi tên trên đối tượng, chữ I trên chữ sửa được, mũi tên chéo ở góc).
  **Bảng thuộc tính** bên phải: màu, nét, kiểu nét, tô màu, độ đậm, bóng đổ, bo góc, góc xoay, **Lên trên cùng /
  Xuống dưới cùng**. Nháy đúp dòng chữ có sẵn (PDF từ Word/Excel) để sửa chữ.
  Nội dung vẫn là vector/chữ thật; thông tin để sửa lại được lưu ngay trong file (đóng, mở lại vẫn sửa được).
- **Thư viện hình (14a):** đường (thẳng, mũi tên, hai đầu, cong, mũi tên cong, gấp khúc, tự do), hình cơ bản (chữ nhật, bo
  góc, elip, tam giác, thoi, bình hành, thang, ngũ/lục/bát giác, đa giác tự do, sao, trái tim, đám mây, dấu cộng), mũi tên
  khối, lưu đồ, chú thích (callout), khung, ✓ ✗, bút dạ quang vùng.
- **Kiểu hình (14b, 14c):** màu viền (bảng màu + Màu khác…), độ dày, liền/đứt/chấm/gạch chấm, đầu mũi tên, màu tô + độ
  đậm, bóng đổ, bo góc; giữ **Shift** để vẽ hình vuông/tròn/đường 45°; **Bắt lưới** (mm), hiện lưới, tự gióng thẳng hàng
  với cạnh/tâm nội dung khác và trang khi kéo.
- **Vẽ tay (15a, 15b):** bút bi, **bút ký** (nét to nhỏ theo tốc độ / lực nhấn bút cảm ứng), bút dạ, bút chì, bút lông,
  bút dạ quang; bảng màu + màu tùy ý, độ dày có xem trước nét, độ đậm.
- **Tẩy vùng (16a–16d):** hình tẩy chữ nhật / elip / khoanh tự do / cục tẩy (cọ chỉnh cỡ); phủ trắng / lấy màu nền giấy
  / không phủ; chỉ gỡ chữ / ảnh / hình vẽ / tất cả – chỉ gỡ đối tượng nằm trọn trong vùng, phủ đúng hình vùng (không lem);
  vùng sẽ tẩy hiện **đỏ mờ**, kéo/chỉnh khung rồi Enter mới tẩy; kính lúp 3× khi khoanh vùng.
- **Chèn trang (17a–17d):** nguồn: file PDF / Word / Excel / PowerPoint / ảnh, trang trắng, tab đang mở, file trong khay
  ghép; trang nguồn: tất cả / dải / một trang / lẻ / chẵn / tích trên ảnh thu nhỏ; vị trí: trước/sau trang hiện tại, đầu,
  cuối, sau trang N; **xen kẽ** mặt trước/mặt sau (có đảo thứ tự), **lặp** sau mỗi N trang; khổ: giữ nguyên hoặc đưa về
  khổ trang hiện tại (co vừa, vẫn là vector). Cả lần chèn là 1 bước hoàn tác.

## Đợt 3 – Màu / Chữ đen / Xám / Đen trắng, bảng tùy chọn mở file, tự xoay trang scan (1.0.13)

- **4 chế độ màu** (chữ luôn là chữ thật – tìm, sao chép được; không render thành ảnh):
  **Màu** (giữ nguyên) · **Chữ đen** (mọi chữ màu → đen; ảnh, logo, nền, bảng màu giữ nguyên; chữ trắng trên nền đậm
  giữ trắng) · **Xám** (cả trang, kể cả ảnh và dải màu biểu đồ) · **Đen trắng** (tiết kiệm mực: chữ và nét đen, nền tô
  nhạt, ảnh 1-bit – trang scan màu nhỏ đi hàng chục lần).
- **Mở / kéo thả vào phần mềm** (9a–9h): PDF, Word, Excel, PowerPoint, ảnh (PNG, JPG, TIFF nhiều trang…). Kéo nhiều file
  hoặc Word/Excel/ảnh → **bảng tích chọn**: chọn file, chế độ màu từng file (hoặc áp dụng cho tất cả), **mở từng tab**
  hoặc **gộp thành một file**; ô **Không hỏi lại**. Bấm nút Mở cũng hiện bảng này. **Công cụ → Tùy chọn mở file** để
  bật lại / đổi mặc định. File đang mở: **Trang → Màu / đen trắng** (tất cả / trang hiện tại / trang chọn / dải).
  Chuyển màu là 1 bước Ctrl+Z.
- **Khay ghép** (8a, 8b, 8e, 10a–10c, 10e): thêm Word/Excel vào khay → hỏi chế độ màu (nhớ lựa chọn, có "Không hỏi lại");
  **Màu khi ghép** chung cho cả khay; cột **Màu** cho từng file ("Theo chung" / riêng; dấu * = có trang đặt riêng);
  ô xem trước: chọn trang rồi bấm **Màu / Chữ đen / Xám / Đen trắng** (hoặc chuột phải) – ảnh trang hiện đúng kết quả
  sau khi chuyển, có nhãn Xám / ĐT / Chữ đen.
- **Tự xoay trang scan** (20a): nhận biết hướng trang scan (ngang, lộn ngược) từ ảnh, không cần OCR – dùng trong Trang →
  Tự xoay và khi ghép (Tự xoay đúng hướng). Trang ít chữ không chắc chắn thì báo để xoay tay.

## Đợt 4 – sửa chữ tại chỗ, chọn nhiều, khay ghép nâng cao (1.0.14)

- **Sửa chữ (11a–11f):** bấm vào chữ là gõ sửa ngay trên trang (ô nhập đúng chỗ, đúng cỡ); phạm vi **mảnh chữ / cả dòng /
  cả đoạn** (tự nhận các dòng cùng đoạn, tự xuống dòng lại); đổi phông, **đậm**, *nghiêng*, cỡ, màu; chữ dài hơn tự co cho
  vừa chỗ cũ (có cảnh báo tràn); **trang scan**: kéo khung quanh chữ → phủ màu nền giấy → gõ chữ mới cùng cỡ;
  **Tìm & thay** liệt kê từng chỗ kèm ngữ cảnh, tích chọn chỗ cần thay, bấm để tới trang.
- **Ghi chú (12c, 12e):** xuất tổng hợp ghi chú ra **Excel / PDF** (theo bộ lọc); ẩn/hiện biểu tượng ghi chú khi xem
  (file không đổi); tùy chọn **in kèm ghi chú** (mặc định không in).
- **Chọn nhiều (13d):** kéo khung từ chỗ trống hoặc Ctrl + bấm; dời / co giãn cả nhóm; **Ctrl+C / X / V / D**
  (dán được sang trang, file khác); Delete xóa cả nhóm.
- **Hình (14d, 14e):** nháy đúp để gõ **chữ trong hình / khung chú thích**; **kiểu hình đã lưu** (+ để lưu, bấm để áp).
- **Vẽ tay (15c–15e):** cục tẩy nét vẽ tay (chỉ gỡ nét bị chạm); giữ Shift kẻ thẳng (Alt: 45°); 4 mức làm mượt;
  **tự nắn hình** (tròn, chữ nhật, tam giác, thoi, đường thẳng, mũi tên).
- **Trang (16e, 17e, 18b, 19c):** tẩy cùng vùng trên mọi trang / trang lẻ / chẵn / trang chọn; kéo file vào cột ảnh thu nhỏ
  để chèn đúng chỗ; chèn trang trắng sau mỗi N trang, chọn khổ; xóa trang có chứa cụm chữ, trang gần trắng (ngưỡng mực).
- **Ký (4c, 4d):** đặt khung ký theo cụm chữ tự nhập (nhớ các cụm đã dùng); đóng ảnh chữ ký/dấu lên **mọi trang trừ trang
  cuối** (ký nháy), trang lẻ, trang chẵn.
- **Khay ghép (5b, 5c, 6b, 8c, 8d, 10d, 10f–10h):** kéo thả sắp thứ tự, thả file vào đúng vị trí; kéo cả thư mục (sắp tên tự
  nhiên); **Xem trước file ghép**; Excel: chọn sheet, vừa trang, hướng giấy (file gốc không đổi); màu **Tự động** (trang có
  màu thật giữ màu); **Đếm trang màu**; lựa chọn màu lưu trong mẫu khay; **Lưu thêm bản đen trắng**.
- **Mở ảnh (9c, 9f):** khổ giấy, lề, co/phóng vừa khổ, chất lượng (200 / 150 / 100 dpi) để file nhẹ.

## Bản 1.0.22 (16 góp ý của anh Dũng)

- **Xoay ảnh / dấu / chữ ký đã chèn:** núm xoay tròn trên khung, ô "Xoay" ở bảng bên phải; bấm lại ảnh đã chèn vẫn xoay
  tiếp được (giữ nguyên cỡ, không méo).
- **Bố cục thu gọn (nút "Bố cục"):** ẩn/hiện cột ảnh thu nhỏ, thanh công cụ trái, thanh lệnh, bảng phải (chứng thư số,
  thư viện dấu). **Ctrl+F2**: chỉ xem văn bản. Cửa sổ thu hẹp được còn ~760 px (chia đôi màn hình, zoom 125–150%);
  bảng phải không còn bị cắt mất một phần.
- **Nhiều cửa sổ:** chuột phải tên tab -> "Mở tab này ở cửa sổ riêng"; "Mở file ở cửa sổ mới…"; các cửa sổ tự xếp cạnh nhau.
- **Tự xoay đúng hướng trang scan:** viết lại thuật toán (bỏ đường kẻ bảng, nắn nghiêng, chấm từng dòng); không còn xoay
  sai với trang có bảng, không chắc thì giữ nguyên. Trang scan có lớp chữ OCR: theo hướng lớp chữ.
- **Khay ghép:** bấm Ghép -> hỏi nơi lưu và tên file (tắt được), có thanh tiến độ.
- **Màu "Như máy in đen trắng":** chữ không đen -> đen, vùng màu -> xám theo độ sáng gốc. Có ở mọi chỗ đổi màu văn bản
  (mở file, khay ghép, xem trước, ghép file).
- **Sửa chữ có sẵn:** dùng đúng phông nhúng trong file (kể cả phông rút gọn CID), không có thì phông cùng tên trên máy;
  con trỏ nhấp nháy đúng chỗ bấm; thanh định dạng nổi ngay trên dòng chữ.
- **Hộp chữ gõ ngay trên trang như Word:** thanh định dạng nổi (phông – có xem trước kiểu chữ, cỡ, **đậm**, *nghiêng*,
  màu, canh trái/giữa/phải, ✓ xong, ✕ hủy; Ctrl+B / Ctrl+I). Thêm 6 phông viết tay: Playwrite VN (chữ học trò Việt),
  Itim (bút bi), Sriracha (bút dạ), Comforter, Moon Dance (chữ ký), Great Vibes (hoa mỹ) – giấy phép OFL.
- **Chọn & sao chép chữ như Foxit/Adobe:** kéo chuột trên chữ để bôi xanh, nháy đúp chọn một từ, Shift+bấm nối vùng
  chọn, Ctrl+A cả trang, **Ctrl+C** sao chép, chuột phải: Sao chép / Chọn hết / Tìm đoạn đã chọn / Sửa chữ tại đây.
  Bấm lên chữ KHÔNG còn mở sửa chữ (không đổi định dạng). Dùng được cả lớp chữ OCR của trang scan.
- **Tìm kiếm tô vàng:** mọi chỗ tìm thấy tô vàng, chỗ đang xem tô cam; Enter/F3 tiếp, Shift+Enter/Shift+F3 lùi, Esc bỏ.
- **Cắt con dấu từ bản scan:** làm phẳng nền (bóng tay, giấy ngả vàng, ảnh chụp điện thoại), tự tìm ngưỡng tách nền,
  "Chỉ giữ màu mực của dấu" (bỏ chữ đen in sẵn, đường kẻ đè lên dấu – tự lấp chỗ bị cắt ngang), lọc chấm nhiễu,
  màu "Màu chủ đạo – đều màu" cho dấu mờ loang.
- **Giáp lai như đóng thật:** kiểu "Tự nhiên" (mảnh rộng hẹp không đều như xếp giấy so le, lệch nhẹ, mực đậm nhạt),
  nghiêng dấu, **mỗi dấu qua tối đa N trang** (tập dày tự gợi ý 8), cách mép giấy, hình minh họa trước khi đóng.
- **Bộ chữ tay của chính mình:** phiếu mẫu mới 2 trang, ô to 21 x 28 mm, nhãn in rõ phía trên ô, đường kẻ chân chữ +
  đường chấm chiều cao chữ như vở ô ly; trang 1 (chữ thường, số, dấu thanh) bắt buộc, trang 2 (chữ hoa, dấu câu) nên có.
  Nạp 1 file PDF hoặc ảnh từng trang -> **bảng xem lại** từng chữ đã cắt: kéo lại khung cắt, chỉnh độ tách nền (từng chữ
  hoặc tất cả), bỏ chữ, **viết lại bằng chuột / bút cảm ứng**. Phiếu cũ (v1) vẫn đọc được. Chữ viết tay bằng phông
  giờ thành hộp chữ, nháy đúp sửa ngay trên trang.
- **Giao diện tối:** bảng hình vẽ, bút vẽ tay, ghi chú, so sánh/ký hàng loạt, bảng kiểm tra chữ ký đổi màu theo nền tối.
- Bỏ `--include-package-data=tzdata` thừa trong `build_windows.bat`; kiểm thử hết cảnh báo Pillow `getdata`.

## Sửa lỗi 1.0.21 (chạy thật trên MacBook)

- **macOS báo "Không tìm thấy phông chữ tiếng Việt trên máy":** Times New Roman, Arial… của macOS nằm ở
  `/System/Library/Fonts/Supplemental` với tên có dấu cách ("Times New Roman.ttf"). Nay tìm đúng chỗ, đúng tên; nếu
  máy vẫn không có thì dùng phông Be Vietnam Pro đóng gói sẵn (đủ dấu tiếng Việt) thay vì báo lỗi.
- `build_mac.sh` xóa bộ đệm `__pycache__` chép từ máy Windows trước khi kiểm thử.

## Gói Tiêu chuẩn / Chuyên nghiệp / Doanh nghiệp (1.0.20)

Theo tài liệu "Gói phần mềm cung cấp" (có bổ sung: gói Tiêu chuẩn có cả Sửa chữ có sẵn, Tìm & thay, Sửa trang
scan). Bảng chia nằm ở `app/editions.py` (FEATURES) – muốn chuyển tính năng sang gói khác chỉ sửa một dòng.

- **Gói ghi trong mã kích hoạt:** bộ tạo mã (KeyGen / `keygen.py issue --edition 1|2|3`) có ô "Gói".
  Nâng cấp = cấp mã mới cho đúng mã máy, khách nhập là dùng ngay, không cài lại.
- **Dùng thử 15 ngày:** đủ tính năng gói Doanh nghiệp. Hết hạn / chưa kích hoạt: như gói thấp nhất (chỉ xem, in).
- **Tính năng ngoài gói:** nút vẫn hiện nhưng có ổ khóa đỏ nhỏ và ghi chú "Thuộc gói …"; bấm vào báo gói cần có
  + nút "Nhập mã nâng cấp…". Khay ghép gói Chuyên nghiệp: tùy chọn bìa, mục lục, số trang, trang trắng in 2 mặt,
  làm chẵn trang, mẫu khay bị khóa.
- Màn hình Bản quyền có nút **Các gói phần mềm…** – bảng so sánh, đánh dấu gói đang dùng.
- Cảnh báo chữ ký hỏng / đã khóa khi mở file vẫn hiện ở mọi gói (bảo vệ người dùng); lệnh "Kiểm tra chữ ký"
  (báo cáo chi tiết) thuộc gói Doanh nghiệp.
- **Mã cấp trước bản 1.0.20** mặc định ghi gói Tiêu chuẩn -> khách cũ cần cấp lại mã đúng gói đã bán.
- Sửa lỗi ký bằng token EC qua kho chứng thư Windows: khoảng 1/256 lần ký chữ ký báo KHÔNG HỢP LỆ (nhận nhầm
  dạng chữ ký thô là DER).

## Sửa lỗi 1.0.19

- **Bảng bên phải bị cắt** (Tẩy vùng, Bút, Hình, Sửa chữ, bảng thuộc tính nội dung): chữ dài, ô chọn rộng làm bảng
  rộng hơn khung (Windows dùng phông / độ phóng to khác) -> mất một phần bên phải. Nay ô tích có chữ dài tự xuống
  dòng, ô chọn / ô số co lại được, dòng dài tách 2 dòng; kiểm thử tự động bảo đảm mọi bảng vừa khung.

## Sửa lỗi 1.0.18 (chạy kiểm thử trên Windows 11 thật)

- **Khoảng trắng cứng (U+00A0):** file dùng Times New Roman / Arial trên Windows, hoặc Word có dấu cách không
  ngắt dòng, lưu dấu cách là U+00A0 -> trước đây Tìm, Tìm & thay, Tẩy theo chữ, Sửa chữ, tạo hàng loạt từ mẫu
  {{…}} không khớp khi gõ dấu cách thường. Nay đọc chữ coi U+00A0 là dấu cách và tìm cả hai kiểu.
- **Chữ phần mềm chèn vào PDF** (hộp chữ, số trang, bìa, mục lục…) không còn bị ghi dấu cách thành U+00A0
  (phông rút gọn chỉ giữ đúng ký tự dùng) -> chép chữ ra / tìm trong Adobe Reader khớp.
- **Mở file khi phần mềm đang chạy (Windows):** file gửi sang phiên đang mở đôi khi bị mất (đường ống đóng trước
  khi đọc). Nay bên nhận đọc xong mới ngắt.
- **Dò driver USB token:** không nạp file không phải thư viện; tắt hộp thoại "Bad Image" của Windows khi gặp DLL
  hỏng / sai loại (trước đây hộp thoại này chặn cả phần mềm).
- Thêm openpyxl (tùy chọn sheet / vừa trang Excel khi chuyển bằng LibreOffice).
- Kiểm thử: không ghi trạng thái bản quyền vào Registry / ProgramData thật; dùng khóa mẫu kể cả khi máy đã chạy
  `keygen.py init`; `kiemthu_windows.bat` gom kết quả vào `ketqua_kiemthu.zip`.

## Sửa lỗi 1.0.17 (đóng gói trên Windows thật)

- **Chuẩn bị ô ký cho nhiều người (Luồng ký):** trên Windows phần mềm thoát đột ngột ("access violation") khi ghi
  ô ký vào file đang mở. Nay đóng tab trước, ghi file, rồi mở lại.
- **Không còn khóa file đang mở trên Windows:** tài liệu được đọc vào bộ nhớ khi mở, nên lưu đè, ghi ô ký, hay phần
  mềm khác ghi vào file đó đều không bị "file đang được dùng".
- Xuất tổng hợp ghi chú ra PDF trên Windows không còn lỗi "Phông chữ không có ký tự" (Times New Roman thiếu một số
  ký hiệu; ký tự phông không có được bỏ qua thay vì báo lỗi).
- Đọc thông báo của PowerShell / Office tiếng Việt không còn lỗi bảng mã.
- `build_windows.bat`: kiểm thử lỗi thì in danh sách ở cuối và ghi `dist\ketqua_kiemthu.xml` để gửi hỗ trợ;
  thêm `SKIP_TESTS=1`. Kiểm thử dùng đúng phông của máy (Times New Roman trên Windows).

## Sửa lỗi 1.0.16

- **Sửa chữ tại chỗ + bảng bên phải:** đang gõ sửa (nháy đúp hộp chữ, hoặc công cụ Sửa chữ) mà bấm vào cỡ chữ,
  đậm, nghiêng, màu, phông, độ đậm… thì ô sửa không còn biến mất; thay đổi hiện ngay trên ô đang gõ và được áp
  dụng khi xong. Chỉ đổi kiểu (không đổi chữ) vẫn áp dụng. Đổi cỡ / đậm không còn làm chữ bị tô màu đỏ.
- **Tẩy:** vùng đỏ xem trước giờ được **tẩy khi bấm ra ngoài / bấm Lưu / đổi công cụ** (trước đây bị bỏ, người dùng
  tưởng tẩy không lưu); Esc mới là bỏ. Hình tẩy **cục tẩy (cọ)** tẩy ngay khi thả chuột và gỡ luôn nét vẽ tay
  chạm vào (1 bước Ctrl+Z).

## Bản macOS – bộ cài .dmg / .pkg (1.0.15)

Cùng một mã nguồn cho Windows và Mac; phần riêng của Mac nằm ở `app/osutil.py`, `app/macintegration.py`,
`build_mac.sh`, `installer/mac/`.

**Đóng gói (phải làm trên máy Mac, macOS 12+).** Không có máy Mac: đẩy mã lên GitHub rồi chạy workflow
**macos-build** (`.github/workflows/macos.yml`, tab Actions → Run workflow) – GitHub build trên máy Mac thật cả
2 bản arm64 và x86_64, tải .dmg/.pkg ở mục Artifacts. Chứng thư ký mã đặt trong Secrets (xem đầu file workflow).

1. Cài Python 3.12 bản *universal2* từ python.org và Xcode Command Line Tools (`xcode-select --install`).
2. Chép **đúng thư mục mã nguồn đã chạy `python tools/keygen.py init`** (file `app/license_key.py` chứa khóa công
   khai thật) sang Mac. Khóa bí mật vẫn chỉ nằm trong cụm mật khẩu của bạn, không đóng gói vào phần mềm.
3. `./build_mac.sh` → `dist/PdfKySo-1.0.15-arm64.dmg` (máy Apple M). Máy Intel: `ARCH=x86_64 ./build_mac.sh`
   → `…-x86_64.dmg`. Thêm `BUILD_PKG=1` để có thêm bộ cài `.pkg` kiểu trình hướng dẫn.
   Script tự chạy toàn bộ kiểm thử, biên dịch bằng Nuitka (mã máy, khó dịch ngược như bản .exe),
   ghép Info.plist, chạy `--selftest` trên chính gói .app, ký mã và tạo bộ cài.
4. **Ký & công chứng (bắt buộc khi gửi khách)** – cần tài khoản Apple Developer (99 USD/năm):
   ```
   export MAC_SIGN_ID="Developer ID Application: Ten Cong Ty (TEAMID)"
   export MAC_INSTALLER_ID="Developer ID Installer: Ten Cong Ty (TEAMID)"   # chỉ khi BUILD_PKG=1
   xcrun notarytool store-credentials pdfkyso-notary --apple-id you@example.com --team-id TEAMID
   export MAC_NOTARY_PROFILE=pdfkyso-notary
   PDFKYSO_RELEASE=1 ./build_mac.sh
   ```
   Không ký thì macOS trên máy khách chặn với thông báo "không xác minh được nhà phát triển" (khách vẫn mở được
   qua Cài đặt hệ thống → Quyền riêng tư & Bảo mật → "Vẫn mở", nhưng không chuyên nghiệp).

**Khác biệt so với Windows:**

| Windows | macOS |
|---|---|
| Máy in ảo "PDF Ky so" / "PDF Khay ghep" | Nút **PDF ▾** trong hộp thoại In của mọi ứng dụng → "Mở bằng PDF Ký Số" / "Thêm vào Khay ghép PDF Ký Số" (tự tạo ở `~/Library/PDF Services` khi mở phần mềm) |
| Word/Excel/PowerPoint qua COM | Microsoft Office cho Mac qua AppleScript (hỏi quyền "Tự động hóa" lần đầu), dự phòng LibreOffice |
| Gửi email qua MAPI | Thư mới trong Mail (hoặc Outlook nếu là ứng dụng email mặc định) |
| Mã máy: MachineGuid | UUID phần cứng + số sê-ri máy (không đổi khi cài lại macOS) |
| Trạng thái dùng thử: Registry | `~/Library/Preferences/.vn.pdfkyso.state` |
| Dữ liệu `%APPDATA%\PdfKySo` | `~/Library/Application Support/PdfKySo`, nhật ký `~/Library/Logs/PdfKySo` |
| Ctrl+… | ⌘… (chữ hướng dẫn trên giao diện tự đổi) |
| Driver token `.dll` | Driver token `.dylib` (tự tìm trong /usr/local/lib, /Library, /Applications/<hãng>.app) |

Mở file: Finder → chuột phải → Mở bằng → PDF Ký Số, hoặc kéo file lên biểu tượng trên Dock (PDF, Word, Excel,
PowerPoint, ảnh). Phần mềm không giành quyền mở PDF mặc định của Xem trước (Preview).
Chạy thẳng từ cửa sổ .dmg (chưa kéo vào Applications) → phần mềm nhắc cài trước.

## Giữ nguyên khổ giấy của Word / Excel

Máy in ảo dùng driver "Microsoft Print to PDF" của Windows: giữ đúng các khổ chuẩn (A3, A4, A5, B4, B5, Letter, Legal,
dọc/ngang, nhiều khổ trong một văn bản), nhưng **không hỗ trợ khổ tự đặt** (210×330, biên lai, phong bì…). Vì vậy
phần mềm còn nhận thẳng file **Word, Excel, PowerPoint**: gọi chính Office trên máy "Lưu thành PDF" -> đúng từng khổ
trang, hướng, lề, bố cục như khi in, chữ vẫn là chữ thật. Thứ tự dùng: Microsoft Office -> WPS Office -> LibreOffice.

- Mở / kéo thả file .docx .xlsx .pptx… vào phần mềm, hoặc chuột phải file -> **"Mở bằng PDF Ký Số (giữ nguyên khổ
  giấy)"** / **"Thêm vào khay ghép PDF Ký Số"** (bộ cài thêm menu này; cũng có cho file .pdf).
- Excel: xuất theo thiết lập trang in (Page Setup, vùng in) của từng sheet – giống hệt khi in.
- File PDF có sẵn: mở thẳng hoặc chuột phải -> "Thêm vào khay ghép" (giữ nguyên 100%), không cần in qua máy in ảo.
- Máy in ảo đặt sẵn khổ A4; bản in có trang Letter thì phần mềm cảnh báo.

## Chạy ổn định khi đóng gói

| Cơ chế | Tác dụng |
| --- | --- |
| Khóa cứng phiên bản thư viện (`requirements.txt`) | Bản .exe luôn dùng đúng bộ thư viện đã kiểm thử |
| `build_windows.bat` chạy kiểm thử trước, `--selftest` sau khi đóng gói | Thiếu thư viện/DLL trong bản .exe bị phát hiện ngay, không lọt tới người dùng |
| GitHub Actions (`.github/workflows/windows.yml`) | Mỗi lần sửa mã: tự kiểm thử + đóng gói trên máy Windows thật |
| Bắt mọi lỗi chưa xử lý + nhật ký `%LOCALAPPDATA%\PdfKySo\logs` | Gặp lỗi phần mềm báo nhẹ và chạy tiếp, không tắt đột ngột; có log để sửa |
| `crash.log` (faulthandler) | Ghi vết cả sự cố nặng trong thư viện C |
| Tự lưu bản khôi phục 2 phút/lần | Mất điện, treo máy: mở lại hỏi khôi phục tài liệu chưa lưu |
| Chạy một phiên duy nhất | Mở file khi phần mềm đang chạy -> vào cửa sổ đang mở, không tranh file |
| Lưu an toàn (ghi file tạm rồi đổi tên) + bản `.bak` thư viện | Lưu lỗi giữa chừng không làm hỏng file gốc; thư viện hỏng tự phục hồi |
| Việt hóa nút chuẩn (Có/Không/Hủy/Lưu) không cần file dịch Qt | Nhẹ hơn, giao diện thuần Việt |
| Kiểm thử đường dẫn tiếng Việt có dấu, file đang bị khóa, file hỏng | Tránh lỗi hay gặp trên máy người dùng |

## Tối ưu tốc độ và dung lượng

- Chỉ render trang đang nhìn thấy; zoom lớn chia trang thành ô 1024 px, chỉ render ô đang thấy.
- Zoom: vẽ tạm ngay từ ảnh cũ, 60 ms sau mới render nét -> zoom mượt.
- Cache ảnh giới hạn ~150 MB; hoàn tác giới hạn 30 bước và 300 MB.
- Thumbnail render dần khi rảnh, không làm đơ khi mở file hàng trăm trang.
- Module nặng (in ấn, pikepdf) chỉ nạp khi dùng -> khởi động nhanh.

## Cấu trúc

```
main.py              điểm khởi động
app/theme.py         màu và stylesheet Windows 11 sáng/tối
app/icons.py         bộ icon SVG nội tuyến (không cần file ảnh)
app/document.py      lõi PDF (không phụ thuộc giao diện)
app/viewer.py        vùng xem trang: render, zoom, cache
app/thumbnails.py    cột ảnh thu nhỏ
app/mainwindow.py    cửa sổ chính, lệnh, phím tắt
app/printing.py      in ấn
app/merge.py         lõi khay ghép (kế hoạch trang trắng, ghép, bookmark, mẫu khay)
app/tray.py          cửa sổ Khay ghép
app/pagetools.py     tách file, đổi kích thước trang
app/spool.py         nhận file từ máy in ảo
app/imaging.py       tách nền ảnh con dấu/chữ ký
app/library.py       thư viện dấu mã hóa, nhật ký dùng dấu
app/ui_library.py    panel thư viện, nhập ảnh, quản lý, giáp lai
app/stability.py     nhật ký lỗi, bắt lỗi, một phiên, bản khôi phục, --selftest
app/i18n.py          Việt hóa nút chuẩn của Qt
app/signing.py       ký số: dò token PKCS#11, ký PAdES, kiểm tra chữ ký
app/wincert.py       ký qua kho chứng thư Windows (driver KSP/CSP của hãng token)
app/ui_sign.py       hộp thoại ký, hình hiển thị chữ ký, PIN, kiểm tra chữ ký
app/fonts.py         phông chữ hệ thống + viết tay, rút gọn phông khi nhúng
app/editing.py       chữ, hình, vẽ tay, ghi chú, sửa chữ, tìm & thay, tẩy vùng, sửa/xóa ảnh
app/items.py         nội dung đã thêm chọn lại được: thư viện hình, bút, dựng lại / sửa / xoay
app/notes.py         ghi chú: đọc (cả file ngoài), sửa, dời, trả lời, đã xử lý
app/colormode.py     chuyển trang sang Chữ đen / Xám / Đen trắng (giữ chữ thật)
app/orient.py        nhận biết hướng trang scan (không cần OCR)
app/ui_import.py     bảng tùy chọn mở / thêm file, chuyển màu, tùy chọn mở file, Excel, ảnh
app/xlsxwrite.py     ghi file Excel đơn giản (xuất tổng hợp ghi chú) – không cần thư viện ngoài
app/ui_pages.py      hộp thoại trang trắng, xóa trang, tự xoay, chèn trang
app/handwriting.py   phiếu mẫu chữ tay, đọc bản scan, ghép chữ viết tay
app/ui_edit.py       công cụ vẽ, hộp chữ, sửa chữ, tìm & thay, chữ viết tay, bảng vẽ tay
assets/fonts/        5 phông viết tay miễn phí (SIL OFL) đã rút gọn; assets/fonts/ui: phông giao diện Be Vietnam Pro
app/theme.py         bảng màu "Ấn triện" sáng/tối, stylesheet, nạp phông giao diện
app/protect.py       lưu có bảo vệ, lớp in mờ, quyền, gỡ bảo vệ
app/tools.py         nén, so sánh, dấu chữ, Excel, lịch sử phiên bản, sao lưu, email
app/autofolder.py    thư mục tự xử lý
app/ui_tools.py      hộp thoại giai đoạn 6
app/license.py       mã máy, kiểm tra mã kích hoạt, dùng thử 15 ngày
app/license_key.py   khóa công khai (tạo bằng tools/keygen.py init)
app/branding.py      thông tin nhà phát triển
app/install_check.py bắt buộc cài bằng bộ cài
app/portable.py      chế độ portable (không cần cài)
app/office.py        Word/Excel/PowerPoint -> PDF bằng Office trên máy (giữ khổ giấy)
app/ui_license.py    màn hình Bản quyền, Giới thiệu
tools/keygen.py      BỘ TẠO KEY – chỉ nhà phát triển giữ, không đóng gói vào phần mềm
build_keygen.bat     đóng gói bộ tạo key thành PdfKySo-KeyGen.exe
installer/setup.iss  bộ cài Inno Setup (tiếng Việt)
installer/           script tạo/gỡ máy in ảo
app/osutil.py        thư mục dữ liệu, mở file, phím tắt theo hệ điều hành (Windows / macOS)
app/macintegration.py macOS: Office cho Mac (AppleScript), Mail, mục PDF ▾ trong hộp thoại In
build_mac.sh         đóng gói bản macOS: .app + .dmg (+ .pkg), ký mã, công chứng
installer/mac/       Info.plist, entitlements, biểu tượng .icns, bộ cài .pkg, hướng dẫn cài cho khách
tests/               kiểm thử tự động (lõi + giao diện + hiệu năng)
tools/benchmark.py   đo hiệu năng trên file thật
```
