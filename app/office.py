"""Chuyển Word / Excel / PowerPoint sang PDF bằng CHÍNH phần mềm Office trên máy -> giữ nguyên khổ giấy.

Máy in ảo (driver Microsoft Print to PDF của Windows) chỉ hỗ trợ các khổ giấy chuẩn (A3, A4, A5, Letter…):
văn bản khổ tự đặt (vd. 210×330 mm, khổ biên lai, phong bì) bị đổi sang khổ gần nhất. Vì vậy phần mềm
còn nhận thẳng file .docx/.xlsx/.pptx: gọi Word/Excel/PowerPoint "Lưu thành PDF" (ExportAsFixedFormat) ->
đúng từng khổ trang, hướng trang, lề, bố cục như khi in từ Office, chữ vẫn là chữ thật.

Thứ tự thử: Microsoft Office -> WPS Office (hay dùng ở Việt Nam, cùng kiểu điều khiển) -> LibreOffice.
"""
from __future__ import annotations

import glob
import os
import shutil
import json
import subprocess
import sys
import tempfile

WORD_EXT = (".doc", ".docx", ".docm", ".rtf", ".odt", ".dot", ".dotx")
EXCEL_EXT = (".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".csv")
POWERPOINT_EXT = (".ppt", ".pptx", ".pptm", ".odp")
OFFICE_EXT = WORD_EXT + EXCEL_EXT + POWERPOINT_EXT
TIMEOUT = 240


class OfficeError(Exception):
    pass


def is_office_file(path: str) -> bool:
    return path.lower().endswith(OFFICE_EXT) and not os.path.basename(path).startswith("~$")


def _kind(path: str) -> str:
    p = path.lower()
    if p.endswith(WORD_EXT):
        return "word"
    if p.endswith(EXCEL_EXT):
        return "excel"
    return "powerpoint"


# PowerShell điều khiển Office qua COM (có sẵn trên Windows, không cần cài thêm thư viện).
# Word: wdExportFormatPDF=17, tối ưu để in, có bookmark theo đề mục.
# Excel: xlTypePDF=0, theo thiết lập trang in (Page Setup) của từng sheet, cả sổ làm việc.
# PowerPoint: ppSaveAsPDF=32.
_PS = r"""
param([string]$Src, [string]$Dst, [string]$Kind, [string]$Prog, [string]$Sheets = '', [string]$Fit = '',
      [string]$Orient = '')
$ErrorActionPreference = 'Stop'
$app = $null; $doc = $null
try {
  $app = New-Object -ComObject $Prog
  try { $app.DisplayAlerts = 0 } catch {}
  if ($Kind -eq 'word') {
    try { $app.Visible = $false } catch {}
    $doc = $app.Documents.Open($Src, $false, $true, $false)
    $doc.ExportAsFixedFormat($Dst, 17, $false, 0, 0, 0, 0, 0, $true, $true, 1, $true, $true, $false)
  } elseif ($Kind -eq 'excel') {
    try { $app.Visible = $false } catch {}
    $doc = $app.Workbooks.Open($Src, 0, $true)
    # tùy chọn xuất Excel: chỉ các sheet đã chọn (ẩn tạm sheet khác, không lưu vào file gốc), vừa trang, hướng
    $want = @()
    if ($Sheets -ne '') { $want = $Sheets -split '\|' }
    foreach ($ws in $doc.Worksheets) {
      if ($want.Count -gt 0 -and -not ($want -contains $ws.Name)) { try { $ws.Visible = 0 } catch {} ; continue }
      if ($Fit -ne '' -or $Orient -ne '') {
        try {
          $ps = $ws.PageSetup
          if ($Fit -eq 'page') { $ps.Zoom = $false; $ps.FitToPagesWide = 1; $ps.FitToPagesTall = 1 }
          elseif ($Fit -eq 'width') { $ps.Zoom = $false; $ps.FitToPagesWide = 1; $ps.FitToPagesTall = $false }
          if ($Orient -eq 'portrait') { $ps.Orientation = 1 } elseif ($Orient -eq 'landscape') { $ps.Orientation = 2 }
        } catch {}
      }
    }
    $doc.ExportAsFixedFormat(0, $Dst, 0, $true, $false)
  } else {
    $doc = $app.Presentations.Open($Src, $true, $false, $false)
    $doc.SaveAs($Dst, 32)
  }
  Write-Output 'OK'
} finally {
  if ($doc) { try { $doc.Close($false) } catch { try { $doc.Close() } catch {} } }
  if ($app) { try { $app.Quit() } catch {} ; [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) }
}
"""

PROGIDS = {
    "word": ["Word.Application", "KWPS.Application", "wps.Application"],
    "excel": ["Excel.Application", "KET.Application", "et.Application"],
    "powerpoint": ["PowerPoint.Application", "KWPP.Application", "wpp.Application"],
}


def _run(cmd, timeout=TIMEOUT, env=None) -> subprocess.CompletedProcess:
    flags = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW: không hiện cửa sổ đen
    # errors="replace": thông báo lỗi tiếng Việt của PowerShell/Office (bảng mã OEM) không làm hỏng việc đọc kết quả
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, creationflags=flags,
                          env=env)


def _via_com(src: str, dst: str, kind: str, excel: dict | None = None) -> str | None:
    """Trả về tên phần mềm đã dùng, None nếu máy không có Office/WPS."""
    extra = []
    if kind == "excel" and excel:
        extra = ["-Sheets", "|".join(excel.get("sheets") or []), "-Fit", excel.get("fit") or "",
                 "-Orient", excel.get("orientation") or ""]
    fd, script = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    try:
        last = ""
        for prog in PROGIDS[kind]:
            try:
                r = _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                          "-Src", src, "-Dst", dst, "-Kind", kind, "-Prog", prog] + extra)
            except subprocess.TimeoutExpired:
                raise OfficeError("Office không phản hồi (quá thời gian). Hãy đóng các hộp thoại Word/Excel đang mở "
                                  "rồi thử lại.")
            if "OK" in r.stdout and os.path.exists(dst) and os.path.getsize(dst) > 0:
                return prog
            last = (r.stderr or r.stdout).strip()
            if "80040154" in last or "class not registered" in last.lower() or "Retrieving the COM class" in last:
                continue                                           # chưa cài phần mềm này -> thử phần mềm khác
            if last:
                raise OfficeError(f"{prog.split('.')[0]} báo lỗi khi chuyển sang PDF:\n{last[-600:]}")
        return None
    finally:
        try:
            os.remove(script)
        except OSError:
            pass


def find_libreoffice() -> str | None:
    p = shutil.which("soffice") or shutil.which("libreoffice")
    if p:
        return p
    if sys.platform == "darwin":
        from .macintegration import find_libreoffice as _mac_lo
        return _mac_lo()
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            for c in glob.glob(os.path.join(base, "LibreOffice*", "program", "soffice.exe")):
                return c
    return None


def _via_libreoffice(src: str, dst: str) -> bool:
    exe = find_libreoffice()
    if not exe:
        return False
    out_dir = tempfile.mkdtemp(prefix="pdfkyso-lo-")
    profile = tempfile.mkdtemp(prefix="pdfkyso-lo-profile-")
    try:
        prof_url = "file:///" + profile.replace("\\", "/").lstrip("/")
        env = os.environ.copy()
        env.setdefault("SAL_USE_VCLPLUGIN", "svp")
        r = _run([exe, f"-env:UserInstallation={prof_url}", "--headless", "--norestore", "--convert-to", "pdf",
                  "--outdir", out_dir, src], env=env)
        made = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
        if os.path.exists(made) and os.path.getsize(made) > 0:
            shutil.move(made, dst)
            return True
        raise OfficeError("LibreOffice không chuyển được file:\n" + (r.stderr or r.stdout)[-600:])
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def cache_dir() -> str:
    from .osutil import local_base
    d = os.path.join(local_base(), "PdfKySo", "tu_office")
    os.makedirs(d, exist_ok=True)
    return d


def excel_sheets(path: str) -> list[str]:
    """Tên các sheet (xlsx/xlsm: đọc trực tiếp; định dạng khác: [] = không liệt kê được, xuất cả sổ)."""
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return []
    try:
        import zipfile
        import re
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/workbook.xml").decode("utf-8", "ignore")
        import html
        return [html.unescape(m) for m in re.findall(r'<sheet\b[^>]*\bname="([^"]*)"', xml)]
    except Exception:
        return []


def _prepare_excel_copy(src: str, excel: dict) -> str | None:
    """LibreOffice: tạo bản sao tạm của sổ xlsx đã ẩn sheet không chọn + đặt vừa trang / hướng (bằng openpyxl)."""
    if not src.lower().endswith((".xlsx", ".xlsm")):
        return None
    try:
        import openpyxl
    except ImportError:
        return None
    wb = openpyxl.load_workbook(src, keep_vba=src.lower().endswith(".xlsm"))
    want = set(excel.get("sheets") or [])
    for ws in wb.worksheets:
        if want and ws.title not in want:
            ws.sheet_state = "hidden"
            continue
        fit = excel.get("fit")
        if fit in ("page", "width"):
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 1 if fit == "page" else 0
        o = excel.get("orientation")
        if o in ("portrait", "landscape"):
            ws.page_setup.orientation = o
        if not ws.page_setup.paperSize:
            ws.page_setup.paperSize = ws.PAPERSIZE_A4
    d = tempfile.mkdtemp(prefix="pdfkyso-xl-")
    out = os.path.join(d, os.path.basename(src))
    wb.save(out)
    return out


def cached_pdf(src: str, excel: dict | None = None) -> tuple[str, str]:
    """Chuyển và giữ bản PDF trong thư mục riêng (dùng cho khay ghép: file phải còn tới lúc ghép).
    File Office không đổi thì dùng lại bản đã chuyển."""
    import hashlib
    st = os.stat(src)
    opt = json.dumps(excel or {}, sort_keys=True, ensure_ascii=False) if excel else ""
    key = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{int(st.st_mtime)}|{opt}".encode("utf-8")).hexdigest()[:10]
    dst = os.path.join(cache_dir(), f"{os.path.splitext(os.path.basename(src))[0]}_{key}.pdf")
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst, "đã chuyển trước đó"
    return to_pdf(src, dst, excel) if excel else to_pdf(src, dst)


def to_pdf(src: str, dst: str | None = None, excel: dict | None = None) -> tuple[str, str]:
    """Chuyển file Office -> PDF. Trả về (đường dẫn PDF, phần mềm đã dùng).
    excel: {"sheets": [tên sheet] (trống = tất cả), "fit": "" | "width" | "page", "orientation": "" | "portrait" |
    "landscape"} – chỉ dùng cho Excel."""
    if not os.path.isfile(src):
        raise OfficeError(f"Không thấy file: {src}")
    src = os.path.abspath(src)
    if dst is None:
        d = tempfile.mkdtemp(prefix="pdfkyso-office-")
        dst = os.path.join(d, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    dst = os.path.abspath(dst)
    if os.path.exists(dst):
        os.remove(dst)
    kind = _kind(src)
    if kind != "excel" or not any((excel or {}).values()):
        excel = None
    if sys.platform == "darwin":                      # Office cho Mac qua AppleScript
        from .macintegration import office_to_pdf
        used = office_to_pdf(src, dst, kind, excel)
        if used:
            return dst, used
    if sys.platform == "win32":
        used = _via_com(src, dst, kind, excel)
        if used:
            return dst, {"Word": "Microsoft Word", "Excel": "Microsoft Excel", "PowerPoint": "Microsoft PowerPoint"}.get(
                used.split(".")[0], "WPS Office")
    lo_src = _prepare_excel_copy(src, excel) if excel else None
    try:
        if _via_libreoffice(lo_src or src, dst):
            return dst, "LibreOffice"
    finally:
        if lo_src:
            shutil.rmtree(os.path.dirname(lo_src), ignore_errors=True)
    raise OfficeError("Máy chưa có phần mềm Office để chuyển file sang PDF.\n"
                      + ("Cần Microsoft Office cho Mac hoặc LibreOffice (miễn phí, tải tại libreoffice.org)."
                         if sys.platform == "darwin" else
                         "Cần một trong các phần mềm: Microsoft Office, WPS Office hoặc LibreOffice (miễn phí)."))
