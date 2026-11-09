@echo off
REM ===== Dong goi ban ban cho khach bang 1 cu bam dup =====
REM Dung moi truong ao .venv trong thu muc nay (khong dung Python chung cua may).
REM Bo qua kiem thu (da chay rieng bang kiemthu_windows.bat); dung han neu con khoa mau.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Chua co moi truong ao .venv. Chay truoc:
  echo    py -3.12 -m venv .venv
  echo    .venv\Scripts\activate
  echo    python -m pip install -r requirements-dev.txt
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
set PDFKYSO_RELEASE=1
set SKIP_TESTS=1
call build_windows.bat
echo.
pause
