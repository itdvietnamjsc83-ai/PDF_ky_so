# Tạo 3 máy in ảo cho phần mềm (chạy bằng quyền Administrator; bộ cài gọi tự động).
#   "PDF Ky so"     -> in xong tự mở phần mềm ở chế độ ký số
#   "PDF Ky so - Mo file" -> in xong chỉ mở thành file PDF trong phần mềm (không ký)
#   "PDF Khay ghep" -> in xong tự xếp vào cuối khay ghép
# Dùng driver "Microsoft Print to PDF" có sẵn trên Windows 10/11. Cổng máy in là file trong thư mục chung
# C:\ProgramData\PdfKySo\spool (cấp quyền sửa cho nhóm Users) -> đúng cho mọi tài khoản trên máy.
param([string]$Root = (Join-Path $env:ProgramData "PdfKySo\spool"))
$ErrorActionPreference = "Stop"
$printers = @(
  @{ Name = "PDF Ky so";     Dir = "sign" },
  @{ Name = "PDF Ky so - Mo file"; Dir = "open" },
  @{ Name = "PDF Khay ghep"; Dir = "tray" }
)
New-Item -ItemType Directory -Force -Path (Join-Path $Root "inbox") | Out-Null
# nhóm Users (SID S-1-5-32-545): được đọc/sửa/xóa file trong thư mục spool
& icacls $Root /grant "*S-1-5-32-545:(OI)(CI)M" /T /Q | Out-Null
if (-not (Get-PrinterDriver -Name "Microsoft Print to PDF" -ErrorAction SilentlyContinue)) {
  try { Enable-WindowsOptionalFeature -Online -FeatureName "Printing-PrintToPDFServices-Features" -NoRestart | Out-Null }
  catch { Write-Warning "Khong bat duoc Microsoft Print to PDF: $_" }
}
foreach ($p in $printers) {
  $dir = Join-Path $Root $p.Dir
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $port = Join-Path $dir "ban_in.pdf"
  if (-not (Get-PrinterPort -Name $port -ErrorAction SilentlyContinue)) {
    Add-PrinterPort -Name $port
  }
  if (Get-Printer -Name $p.Name -ErrorAction SilentlyContinue) { Remove-Printer -Name $p.Name }
  Add-Printer -Name $p.Name -DriverName "Microsoft Print to PDF" -PortName $port
  # khổ giấy mặc định A4 (máy mới cài Windows bản tiếng Anh hay để Letter -> văn bản A4 bị in sai khổ)
  try { Set-PrintConfiguration -PrinterName $p.Name -PaperSize A4 } catch { Write-Warning "Khong dat duoc kho A4: $_" }
  Write-Host "Da tao may in: $($p.Name) -> $dir"
}
