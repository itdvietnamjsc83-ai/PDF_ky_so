@echo off
setlocal
REM ===== Dong goi PdfKySo.exe (chay tren Windows 10/11 64-bit, Python 3.12) =====
REM Quy trinh on dinh: 1) cai dung phien ban da khoa  2) chay toan bo kiem thu
REM                    3) bien dich bang Nuitka       4) chay --selftest tren chinh file .exe
python -m pip install -r requirements-dev.txt || goto :fail
if not exist dist mkdir dist
if "%SKIP_TESTS%"=="1" (
  echo CANH BAO: bo qua kiem thu ^(SKIP_TESTS=1^) - chi dung khi da chay kiem thu rieng.
) else (
  REM ket qua chi tiet tung kiem thu loi ghi vao dist\ketqua_kiemthu.xml ^(gui file nay khi can ho tro^)
  python -m pytest tests -q -rfE --tb=line -p no:cacheprovider --junitxml=dist\ketqua_kiemthu.xml || goto :failtest
)

REM Khoa ban quyen: ban ban cho khach PHAI dung khoa that (python tools\keygen.py init)
python -c "from app.license_key import DEMO; import sys; sys.exit(1 if DEMO else 0)"
if errorlevel 1 (
  echo CANH BAO: dang dung KHOA MAU. Chay "python tools\keygen.py init" truoc khi ban phan mem.
  if "%PDFKYSO_RELEASE%"=="1" goto :fail
)
for /f %%v in ('python -c "import app; print(app.__version__)"') do set PDFKYSO_VERSION=%%v

python -m nuitka main.py ^
  --standalone ^
  --enable-plugin=pyside6 ^
  --include-qt-plugins=platforms,styles,imageformats,iconengines,tls ^
  --noinclude-qt-translations ^
  --include-package=pypdfium2 --include-package=pypdfium2_raw --include-package-data=pypdfium2_raw ^
  --include-package=pikepdf --include-package-data=pikepdf ^
  --include-module=PIL.PngImagePlugin --include-module=PIL.JpegImagePlugin ^
  --include-package=pyhanko --include-package=pyhanko_certvalidator --include-package-data=pyhanko ^
  --include-package=pkcs11 --include-package=asn1crypto --include-package=tzdata ^
  --include-package-data=certifi ^
  --include-module=fontTools.subset --include-module=fontTools.ttLib --include-package=openpyxl ^
  --include-data-dir=assets/fonts=assets/fonts ^
  --include-module=app.license_key --include-module=app.install_check --include-module=app.retention --include-module=app.tray_preview --include-module=app.ui_pages --include-module=app.deps --include-module=app.items --include-module=app.notes --include-module=app.colormode --include-module=app.orient --include-module=app.ui_import --include-module=app.xlsxwrite --include-module=app.editions ^
  --nofollow-import-to=pymupdf,fitz,pytest,numpy,tkinter,PIL.ImageQt,uharfbuzz,qrcode,barcode,signxml,xsdata ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=assets\app.ico ^
  --company-name="Cong ty co phan Cong nghe ITD Viet Nam" --product-name="PDF Ky So" ^
  --file-version=%PDFKYSO_VERSION% --product-version=%PDFKYSO_VERSION% ^
  --output-dir=dist --output-filename=PdfKySo.exe ^
  --lto=yes --assume-yes-for-downloads || goto :fail

REM Tu kiem tra ban da dong goi: thieu thu vien nao se bao loi ngay tai day
dist\main.dist\PdfKySo.exe --selftest > dist\selftest.txt 2>&1
type dist\selftest.txt
findstr /C:"SELFTEST OK" dist\selftest.txt >nul || goto :fail

REM Ky code signing (neu co chung thu): set SIGN_PFX=duong\dan\cert.pfx  va  set SIGN_PASS=matkhau
if not "%SIGN_PFX%"=="" (
  signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f "%SIGN_PFX%" /p "%SIGN_PASS%" dist\main.dist\PdfKySo.exe || goto :fail
)

REM Ban portable (khong can cai): thu muc + file danh dau PdfKySo.portable, nen thanh .zip
set PORTDIR=dist\PdfKySo-Portable-%PDFKYSO_VERSION%
if exist "%PORTDIR%" rmdir /s /q "%PORTDIR%"
xcopy /e /i /q dist\main.dist "%PORTDIR%" >nul || goto :fail
echo PDF Ky So - ban portable> "%PORTDIR%\PdfKySo.portable"
copy /y installer\HUONG_DAN_PORTABLE.txt "%PORTDIR%\HUONG_DAN.txt" >nul
if exist "%PORTDIR%.zip" del /q "%PORTDIR%.zip"
powershell -NoProfile -Command "Compress-Archive -Path '%PORTDIR%' -DestinationPath '%PORTDIR%.zip' -Force" || goto :fail
echo ===== BAN PORTABLE: %PORTDIR%.zip =====

REM Bo cai (Inno Setup 6 mien phi). Khong co Inno Setup thi bo qua buoc nay.
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% /Q installer\setup.iss || goto :fail
  if not "%SIGN_PFX%"=="" (
    signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f "%SIGN_PFX%" /p "%SIGN_PASS%" dist\PdfKySo-Setup-%PDFKYSO_VERSION%.exe || goto :fail
  )
  echo ===== BO CAI: dist\PdfKySo-Setup-%PDFKYSO_VERSION%.exe =====
) else (
  echo (Chua cai Inno Setup 6 - bo qua buoc tao bo cai. Tai tai https://jrsoftware.org/isdl.php)
)
echo.
echo ===== XONG: dist\main.dist\PdfKySo.exe =====
exit /b 0
:failtest
echo.
echo ===== KIEM THU KHONG DAT: xem danh sach loi phia tren ^(short test summary info^) =====
echo ===== Gui file dist\ketqua_kiemthu.xml de duoc ho tro. =====
exit /b 1
:fail
echo.
echo ===== LOI: dung dong goi. Xem thong bao phia tren. =====
exit /b 1
