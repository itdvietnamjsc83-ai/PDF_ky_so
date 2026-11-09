"""Lịch sử & dữ liệu phần mềm lưu trên máy: xem, xóa từng mục / xóa tất cả, đặt thời hạn tự xóa.

Mỗi mục có thời hạn lưu: Không lưu, 7 ngày, 30 ngày, 6 tháng, 1 năm, Vĩnh viễn. Phần mềm tự xóa phần quá hạn
khi khởi động và định kỳ khi đang chạy. File gốc của người dùng không bao giờ bị đụng tới.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import tempfile
import time

DAY = 86400
# (số ngày, nhãn); None = vĩnh viễn, 0 = không lưu
RETENTION_CHOICES = [(0, "Không lưu"), (7, "7 ngày"), (30, "30 ngày"), (182, "6 tháng"), (365, "1 năm"),
                     (None, "Vĩnh viễn")]

# (mã, nhãn, có thời hạn tự xóa?, thời hạn mặc định, tích sẵn khi mở hộp thoại?)
PARTS = [
    ("recent", "Danh sách file mở gần đây", True, None, True),
    ("versions", "Lịch sử phiên bản (bản cũ mỗi lần lưu đè)", True, 182, True),
    ("usage", "Nhật ký dùng dấu & chữ ký (file nào, trang nào)", True, None, True),
    ("office", "Bản PDF tạm chuyển từ Word / Excel / PowerPoint", True, 7, True),
    ("spool", "Bản in nhận từ máy in ảo", True, 7, True),
    ("recovery", "Bản khôi phục sự cố còn sót lại", True, 30, True),
    ("logs", "Nhật ký hoạt động của phần mềm (tên file đã mở, lưu, ký; báo lỗi)", True, 30, True),
    ("tray", "Khay ghép đã nhớ (danh sách file trong khay)", True, None, True),
    ("traces", "Dấu vết khác: thư mục mở gần nhất, chứng thư dùng gần nhất, driver token đã dò", False, None, False),
    ("templates", "Mẫu & cấu hình đã lưu: mẫu bảo vệ, mẫu khay, thư mục tự xử lý, tùy chọn ký và chữ", False, None,
     False),
    ("library", "Thư viện dấu, chữ ký, chữ viết tay (toàn bộ mẫu)", False, None, False),
]
LABELS = {k: lab for k, lab, *_ in PARTS}
TIMED = [k for k, _, timed, *_ in PARTS if timed]
DANGEROUS = ("templates", "library")            # xóa là mất công chuẩn bị -> hỏi lại
# tương thích bản 1.0.7
HISTORY_PARTS = [(k, LABELS[k]) for k in ("recent", "versions", "usage", "office", "logs")]
log = logging.getLogger(__name__)


# ------------------------------------------------------------------ thời hạn
def retention_days(settings, part: str):
    default = next(d for k, _, _, d, _ in PARTS if k == part)
    if settings is None:
        return default
    v = settings.value(f"retention/{part}", "default")
    if v in ("default", None):
        return default
    if v in ("forever", "None", ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def set_retention(settings, part: str, days):
    settings.setValue(f"retention/{part}", "forever" if days is None else int(days))


def keeps(settings, part: str) -> bool:
    """Có lưu mục này không (thời hạn khác 'Không lưu')."""
    return retention_days(settings, part) != 0


def label_of(days) -> str:
    return dict(RETENTION_CHOICES).get(days, f"{days} ngày")


# ------------------------------------------------------------------ vị trí dữ liệu
def _data_dir():
    from .library import data_dir
    return data_dir()


def _local(*parts):
    from .stability import local_dir
    return local_dir(*parts)


def versions_root() -> str:
    return os.path.join(_data_dir(), "lich_su")


def usage_path() -> str:
    return os.path.join(_data_dir(), "nhat_ky_dung_dau.csv")


def spool_inbox() -> str:
    from .spool import spool_root
    return os.path.join(spool_root(), "inbox")


def office_dirs() -> list[str]:
    """Thư mục cache chuyển Office + các thư mục tạm của lần chuyển (trong %TEMP%)."""
    from .office import cache_dir
    out = [cache_dir()]
    tmp = tempfile.gettempdir()
    try:
        out += [os.path.join(tmp, n) for n in os.listdir(tmp)
                if n.startswith(("pdfkyso-office-", "pdfkyso-lo-")) and os.path.isdir(os.path.join(tmp, n))]
    except OSError:
        pass
    return out


def log_files() -> list[str]:
    d = _local("logs")
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith(("app.log", "crash.log"))]


def recovery_dir() -> str:
    return _local("recovery")


def library_files(library_path: str | None = None) -> list[str]:
    p = library_path or os.path.join(_data_dir(), "library.pdf")
    return [x for x in (p, p + ".bak", p + ".tmp") if os.path.exists(x)]


# ------------------------------------------------------------------ danh sách gần đây (có thời gian)
def recent_list(settings) -> list[str]:
    v = settings.value("recent", []) if settings is not None else []
    if isinstance(v, str):
        v = [v] if v else []
    return [p for p in (v or []) if isinstance(p, str) and p]


def recent_times(settings) -> dict:
    try:
        d = json.loads(settings.value("recent_t", "") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def touch_recent(settings, path: str):
    t = recent_times(settings)
    t[os.path.normcase(os.path.abspath(path))] = time.time()
    keep = {os.path.normcase(os.path.abspath(p)) for p in recent_list(settings)}
    settings.setValue("recent_t", json.dumps({k: v for k, v in t.items() if k in keep}))


# ------------------------------------------------------------------ đếm / mô tả
def _files(root: str, exts=None):
    if not os.path.isdir(root):
        return
    for dp, _, fs in os.walk(root):
        for f in fs:
            if exts is None or f.lower().endswith(exts):
                yield os.path.join(dp, f)


def _stats(paths) -> tuple[int, int]:
    n = size = 0
    for p in paths:
        try:
            size += os.path.getsize(p)
            n += 1
        except OSError:
            pass
    return n, size


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(n, 1) / 1024:.0f} KB"


TRACE_KEYS = ("last_dir", "img_dir", "sign/last_cert", "sign/known_libs", "sign/cert")
TEMPLATE_KEYS = ("protect/presets", "protect/last", "auto/config", "tray/template_files", "hand/style", "hand/color",
                 "text/font", "text/color", "note/author", "tool/color", "tool/width", "tool/size", "img/layer",
                 "img/opacity", "img/angle")
TEMPLATE_PREFIX = ("sign/",)


def _usage_rows() -> list[list[str]]:
    p = usage_path()
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
        return list(csv.reader(f))


def _has(settings, key) -> bool:
    if settings is None:
        return False
    v = settings.value(key, None)
    return v not in (None, "", [], "[]", "{}", "null")


def _settings_keys(settings) -> list[str]:
    try:
        return list(settings.allKeys())
    except AttributeError:                       # dict giả lập khi kiểm thử
        return list(settings.keys())


def summary(settings=None, library_path: str | None = None) -> dict:
    """{mã: (số lượng, mô tả)} cho từng mục."""
    out = {}
    n = len(recent_list(settings))
    out["recent"] = (n, f"{n} file" if n else "trống")
    n, size = _stats(_files(versions_root(), (".pdf",)))
    out["versions"] = (n, f"{n} bản · {_mb(size)}" if n else "trống")
    rows = max(len(_usage_rows()) - 1, 0)
    out["usage"] = (rows, f"{rows} dòng" if rows else "trống")
    n, size = _stats(p for d in office_dirs() for p in _files(d))
    out["office"] = (n, f"{n} file · {_mb(size)}" if n else "trống")
    try:
        n, size = _stats(_files(spool_inbox(), (".pdf",)))
    except OSError:
        n = size = 0
    out["spool"] = (n, f"{n} file · {_mb(size)}" if n else "trống")
    n, size = _stats(_files(recovery_dir(), (".pdf",)))
    out["recovery"] = (n, f"{n} bản · {_mb(size)}" if n else "trống")
    lf = [p for p in log_files() if os.path.getsize(p) > 0]
    n, size = _stats(lf)
    out["logs"] = (size, _mb(size) if size else "trống")
    items = 0
    if _has(settings, "tray"):
        try:
            items = len(json.loads(settings.value("tray")).get("items", []))
        except (TypeError, ValueError, AttributeError):
            items = 0
    out["tray"] = (items, f"{items} file" if items else "trống")
    n = sum(1 for k in TRACE_KEYS if _has(settings, k))
    out["traces"] = (n, f"{n} mục" if n else "trống")
    n = sum(1 for k in TEMPLATE_KEYS if _has(settings, k))
    if settings is not None:
        n += sum(1 for k in _settings_keys(settings) if k.startswith(TEMPLATE_PREFIX) and k not in TRACE_KEYS
                 and _has(settings, k))
    out["templates"] = (n, f"{n} mục" if n else "trống")
    n, size = _stats(library_files(library_path))
    out["library"] = (n, _mb(size) if n else "trống")
    return out


# ------------------------------------------------------------------ xóa
def _rm(p: str):
    try:
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)
        return True
    except OSError:
        return False


def _truncate_logs(older_than: float | None = None):
    open_files = set()
    ours = {os.path.normcase(os.path.abspath(p)) for p in log_files()}
    for h in logging.getLogger().handlers:              # file đang ghi: làm rỗng tại chỗ (Windows không cho xóa)
        name = os.path.normcase(os.path.abspath(getattr(h, "baseFilename", "") or "."))
        if isinstance(h, logging.FileHandler) and h.stream and name in ours:
            open_files.add(name)
            try:
                if older_than is not None and os.path.getmtime(name) >= older_than:
                    continue
            except OSError:
                continue
            h.acquire()
            try:
                h.stream.flush()
                h.stream.seek(0)
                h.stream.truncate()
            except (OSError, ValueError):
                pass
            finally:
                h.release()
    for p in log_files():
        name = os.path.normcase(os.path.abspath(p))
        if name in open_files:
            continue
        try:
            if older_than is not None and os.path.getmtime(p) >= older_than:
                continue
        except OSError:
            continue
        if not _rm(p):
            try:                                 # crash.log đang mở để ghi vết sự cố -> làm rỗng
                open(p, "w").close()
            except OSError:
                pass


def _prune_usage(cutoff: float | None):
    rows = _usage_rows()
    if not rows:
        return 0
    if cutoff is None:
        _rm(usage_path())
        return len(rows) - 1
    head, body = rows[0], rows[1:]
    keep = []
    for r in body:
        try:
            t = time.mktime(time.strptime(r[0], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, IndexError):
            t = time.time()
        if t >= cutoff:
            keep.append(r)
    if len(keep) == len(body):
        return 0
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    w.writerows(keep)
    with open(usage_path(), "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    return len(body) - len(keep)


def _old(p: str, cutoff: float | None) -> bool:
    if cutoff is None:
        return True
    try:
        return os.path.getmtime(p) < cutoff
    except OSError:
        return False


def _clean(part: str, settings, cutoff: float | None, library_path=None, active_recovery=()) -> int:
    """Xóa mục `part`: cutoff=None -> xóa hết; cutoff=t -> chỉ phần cũ hơn thời điểm t. Trả về số đã xóa."""
    n = 0
    if part == "recent" and settings is not None:
        lst = recent_list(settings)
        if cutoff is None:
            keep = []
        else:
            t = recent_times(settings)
            now = time.time()
            for p in lst:                        # mục cũ (chưa có thời gian): bắt đầu tính từ bây giờ
                t.setdefault(os.path.normcase(os.path.abspath(p)), now)
            keep = [p for p in lst if t[os.path.normcase(os.path.abspath(p))] >= cutoff]
            settings.setValue("recent_t", json.dumps(t))
        n = len(lst) - len(keep)
        if n or cutoff is None:
            settings.setValue("recent", keep)
        if cutoff is None:
            settings.setValue("recent_t", "{}")
    elif part == "versions":
        root = versions_root()
        for p in list(_files(root, (".pdf",))):
            if _old(p, cutoff) and _rm(p):
                n += 1
        if os.path.isdir(root):
            for d in os.listdir(root):
                dp = os.path.join(root, d)
                if os.path.isdir(dp) and not any(f.endswith(".pdf") for f in os.listdir(dp)):
                    _rm(dp)
    elif part == "usage":
        n = _prune_usage(cutoff)
    elif part == "office":
        for d in office_dirs():
            for p in list(_files(d)):
                if _old(p, cutoff) and _rm(p):
                    n += 1
            if os.path.basename(d).startswith(("pdfkyso-office-", "pdfkyso-lo-")) and not any(_files(d)):
                _rm(d)
    elif part == "spool":
        try:
            inbox = spool_inbox()
        except OSError:
            inbox = ""
        for p in list(_files(inbox)):
            if _old(p, cutoff) and _rm(p):
                n += 1
    elif part == "recovery":
        d = recovery_dir()
        for p in list(_files(d)):
            key = os.path.splitext(os.path.basename(p))[0]
            if key in active_recovery:
                continue                          # tài liệu đang mở: giữ bản tự lưu
            if _old(p, cutoff) and _rm(p):
                n += p.endswith(".pdf")
    elif part == "logs":
        before = sum(os.path.getsize(p) for p in log_files())
        _truncate_logs(cutoff)
        n = int(before > sum(os.path.getsize(p) for p in log_files()))
    elif part == "tray" and settings is not None:
        t = float(settings.value("tray_t", 0) or 0)
        if _has(settings, "tray") and (cutoff is None or (t and t < cutoff)):
            settings.setValue("tray", "")
            n = 1
    elif part == "traces" and settings is not None:
        for k in TRACE_KEYS:
            if _has(settings, k):
                settings.setValue(k, "")
                n += 1
    elif part == "templates" and settings is not None:
        try:
            files = json.loads(settings.value("tray/template_files", "") or "[]")
        except (TypeError, ValueError):
            files = []
        for p in files if isinstance(files, list) else []:
            if isinstance(p, str) and os.path.isfile(p) and p.lower().endswith(".json") and _rm(p):
                n += 1
        keys = set(TEMPLATE_KEYS) | {k for k in _settings_keys(settings) if k.startswith(TEMPLATE_PREFIX)
                                     and k not in TRACE_KEYS}
        for k in keys:
            if _has(settings, k):
                settings.setValue(k, "")
                n += 1
    elif part == "library":
        for p in library_files(library_path):
            if _rm(p):
                n += 1
    return n


def clear(parts, settings=None, library_path: str | None = None, active_recovery=()) -> list[str]:
    """Xóa hẳn các mục đã chọn. Trả về nhãn các mục đã xóa."""
    done = []
    for part in parts:
        if part not in LABELS:
            continue
        _clean(part, settings, None, library_path, active_recovery)
        done.append(LABELS[part])
    return done


def apply_retention(settings, now: float | None = None, active_recovery=()) -> dict:
    """Tự xóa phần quá hạn của từng mục theo thời hạn đã đặt. Trả về {mã: số đã xóa}."""
    now = now or time.time()
    out = {}
    for part in TIMED:
        days = retention_days(settings, part)
        if days is None:
            continue
        try:
            n = _clean(part, settings, now - days * DAY if days else now + 1, active_recovery=active_recovery)
        except Exception:
            log.exception("Tự xóa lịch sử quá hạn lỗi (%s)", part)
            continue
        if n:
            out[part] = n
    if out:
        log.info("Tự xóa lịch sử quá hạn: %s", out)
    return out


# ------------------------------------------------------------------ tương thích bản 1.0.7 (tools.*)
def history_summary(settings=None) -> dict:
    return summary(settings)


def clear_history(parts, settings=None) -> list[str]:
    return clear(parts, settings)
