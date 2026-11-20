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
# 1.0.25 – nhanh hơn:
#  - nhiều file cùng loại: MỘT lần khởi động PowerShell + Word cho cả lô (trước: mỗi file một lần, mất vài giây/file);
#  - Word không gắn thẻ cấu trúc (DocStructureTags) – bước này làm file lớn, nhiều trang xuất chậm gấp đôi, phần
#    mềm không dùng tới; tắt vẽ màn hình (ScreenUpdating) trong lúc xuất.
# Danh sách việc: file JSON [{"id", "src", "dst", "sheets", "fit", "orient"}]; kết quả từng dòng "OK<tab>id" hoặc
# "ERR<tab>id<tab>lỗi"; không tạo được ứng dụng: "NOAPP<tab>lỗi".
_PS = r"""
param([string]$Jobs, [string]$Kind, [string]$Prog)
$ErrorActionPreference = 'Stop'
$list = @(Get-Content -Raw -Encoding UTF8 -LiteralPath $Jobs | ConvertFrom-Json)
$app = $null
try {
  try { $app = New-Object -ComObject $Prog }
  catch { Write-Output ("NOAPP`t" + ($_.Exception.Message -replace "`r?`n", " ")); exit 0 }
  try { $app.DisplayAlerts = 0 } catch {}
  if ($Kind -ne 'powerpoint') { try { $app.Visible = $false } catch {} }
  try { $app.ScreenUpdating = $false } catch {}
  foreach ($j in $list) {
    $doc = $null
    try {
      if ($Kind -eq 'word') {
        $doc = $app.Documents.Open($j.src, $false, $true, $false)
        $doc.ExportAsFixedFormat($j.dst, 17, $false, 0, 0, 0, 0, 0, $true, $true, 1, $false, $true, $false)
      } elseif ($Kind -eq 'excel') {
        $doc = $app.Workbooks.Open($j.src, 0, $true)
        # tùy chọn xuất Excel: chỉ các sheet đã chọn (ẩn tạm sheet khác, không lưu vào file gốc), vừa trang, hướng
        $want = @()
        if ($j.sheets) { $want = $j.sheets -split '\|' }
        foreach ($ws in $doc.Worksheets) {
          if ($want.Count -gt 0 -and -not ($want -contains $ws.Name)) { try { $ws.Visible = 0 } catch {} ; continue }
          if ($j.fit -or $j.orient) {
            try {
              $ps = $ws.PageSetup
              if ($j.fit -eq 'page') { $ps.Zoom = $false; $ps.FitToPagesWide = 1; $ps.FitToPagesTall = 1 }
              elseif ($j.fit -eq 'width') { $ps.Zoom = $false; $ps.FitToPagesWide = 1; $ps.FitToPagesTall = $false }
              if ($j.orient -eq 'portrait') { $ps.Orientation = 1 } elseif ($j.orient -eq 'landscape') { $ps.Orientation = 2 }
            } catch {}
          }
        }
        $doc.ExportAsFixedFormat(0, $j.dst, 0, $true, $false)
      } else {
        $doc = $app.Presentations.Open($j.src, $true, $false, $false)
        $doc.SaveAs($j.dst, 32)
      }
      Write-Output ("OK`t" + $j.id)
    } catch {
      Write-Output ("ERR`t" + $j.id + "`t" + ($_.Exception.Message -replace "`r?`n", " "))
    } finally {
      if ($doc) { try { $doc.Close($false) } catch { try { $doc.Close() } catch {} } }
    }
  }
} finally {
  if ($app) {
    try { $app.ScreenUpdating = $true } catch {}
    try { $app.Quit() } catch {} ; [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
  }
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


def _not_installed(msg: str) -> bool:
    return "80040154" in msg or "class not registered" in msg.lower() or "Retrieving the COM class" in msg


def _via_com_batch(jobs: list[dict], kind: str) -> tuple[str | None, dict[int, str]]:
    """Chuyển cả lô file cùng loại trong MỘT phiên Office. jobs: [{"src", "dst", "excel"}].
    Trả về (phần mềm đã dùng hoặc None nếu máy không có Office/WPS, {chỉ số việc lỗi: thông báo lỗi})."""
    data = []
    for k, j in enumerate(jobs):
        x = j.get("excel") or {}
        data.append({"id": k, "src": j["src"], "dst": j["dst"], "sheets": "|".join(x.get("sheets") or []),
                     "fit": x.get("fit") or "", "orient": x.get("orientation") or ""})
    fd, script = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    fd, jobs_file = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    try:
        for prog in PROGIDS[kind]:
            try:
                r = _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                          "-Jobs", jobs_file, "-Kind", kind, "-Prog", prog], timeout=TIMEOUT * max(1, len(jobs)))
            except subprocess.TimeoutExpired:
                raise OfficeError("Office không phản hồi (quá thời gian). Hãy đóng các hộp thoại Word/Excel đang mở "
                                  "rồi thử lại.")
            out = r.stdout or ""
            noapp = [ln for ln in out.splitlines() if ln.startswith("NOAPP")]
            if noapp:
                if _not_installed(noapp[0]):
                    continue                                       # chưa cài phần mềm này -> thử phần mềm khác
                raise OfficeError(f"{prog.split('.')[0]} không khởi động được:\n{noapp[0][6:][-600:]}")
            errs = {}
            for k, j in enumerate(jobs):
                ok = any(ln.strip().split("\t")[:2] == ["OK", str(k)] or (len(jobs) == 1 and ln.strip() == "OK")
                         for ln in out.splitlines())
                if ok and os.path.exists(j["dst"]) and os.path.getsize(j["dst"]) > 0:
                    continue
                msg = next((ln.split("\t", 2)[2] for ln in out.splitlines()
                            if ln.startswith("ERR\t") and ln.split("\t")[1] == str(k) and ln.count("\t") >= 2), "")
                errs[k] = msg or (r.stderr or out).strip()
            if errs and len(errs) == len(jobs) and all(_not_installed(m) for m in errs.values()):
                continue
            return prog, errs
        return None, {}
    finally:
        for p in (script, jobs_file):
            try:
                os.remove(p)
            except OSError:
                pass


def _via_com(src: str, dst: str, kind: str, excel: dict | None = None) -> str | None:
    """Trả về tên phần mềm đã dùng, None nếu máy không có Office/WPS."""
    prog, errs = _via_com_batch([{"src": src, "dst": dst, "excel": excel}], kind)
    if prog and errs:
        raise OfficeError(f"{prog.split('.')[0]} báo lỗi khi chuyển sang PDF:\n{errs[0][-600:]}")
    return prog


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


def _cache_path(src: str, excel: dict | None = None) -> str:
    import hashlib
    if not any((excel or {}).values()):
        excel = None
    st = os.stat(src)
    opt = json.dumps(excel or {}, sort_keys=True, ensure_ascii=False) if excel else ""
    key = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{int(st.st_mtime)}|{opt}".encode("utf-8")).hexdigest()[:10]
    return os.path.join(cache_dir(), f"{os.path.splitext(os.path.basename(src))[0]}_{key}.pdf")


def cached_pdf(src: str, excel: dict | None = None) -> tuple[str, str]:
    """Chuyển và giữ bản PDF trong thư mục riêng (file phải còn tới lúc ghép; mở lại file Word chưa sửa thì có ngay).
    File Office không đổi thì dùng lại bản đã chuyển."""
    dst = _cache_path(src, excel)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst, "đã chuyển trước đó"
    return to_pdf(src, dst, excel) if excel else to_pdf(src, dst)


def prefetch(items: list[tuple[str, dict | None]]) -> dict[str, str]:
    """Chuyển trước nhiều file Office vào bộ nhớ đệm: trên Windows mỗi loại (Word / Excel / PowerPoint) chỉ khởi động
    Office MỘT lần cho cả lô. Sau đó cached_pdf() lấy ngay. Trả về {file: lỗi} (file lỗi để cached_pdf thử lại và báo)."""
    todo = []
    for src, excel in items:
        if not is_office_file(src) or not os.path.isfile(src):
            continue
        kind = _kind(src)
        if kind != "excel" or not any((excel or {}).values()):
            excel = None
        dst = _cache_path(src, excel)
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            todo.append({"src": os.path.abspath(src), "dst": dst, "excel": excel, "kind": kind})
    errors: dict[str, str] = {}
    if sys.platform != "win32" or len(todo) < 2:
        return errors                                   # 1 file / Mac: cached_pdf chuyển như thường
    for kind in ("word", "excel", "powerpoint"):
        jobs = [j for j in todo if j["kind"] == kind]
        if not jobs:
            continue
        try:
            prog, errs = _via_com_batch(jobs, kind)
        except OfficeError as e:
            errors.update({j["src"]: str(e) for j in jobs})
            continue
        errors.update({jobs[k]["src"]: m for k, m in errs.items()})
    return errors


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
        from .macintegration import find_libreoffice, office_to_pdf
        try:
            used = office_to_pdf(src, dst, kind, excel)
        except OfficeError:
            if not find_libreoffice():          # Office cho Mac lỗi: còn LibreOffice thì chuyển bằng LibreOffice
                raise
            used = None
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
