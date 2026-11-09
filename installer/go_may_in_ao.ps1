# Gỡ máy in ảo khi gỡ phần mềm.
foreach ($n in @("PDF Ky so", "PDF Khay ghep")) {
  if (Get-Printer -Name $n -ErrorAction SilentlyContinue) { Remove-Printer -Name $n }
}
Get-PrinterPort -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*PdfKySo*ban_in.pdf" } |
  ForEach-Object { try { Remove-PrinterPort -Name $_.Name } catch {} }
