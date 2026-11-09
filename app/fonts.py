"""Phông chữ cho hộp chữ, sửa chữ và chữ viết tay.

- Phông hệ thống (Times New Roman, Arial…) có sẵn trên Windows -> không đóng gói, phần mềm nhẹ.
- 5 phông viết tay miễn phí (OFL) đóng gói sẵn, đã rút gọn chỉ còn Latin + tiếng Việt (~270 KB).
- Khi nhúng vào PDF: chỉ nhúng các ký tự thực sự dùng (subset) -> mỗi hộp chữ chỉ thêm vài KB.
"""
from __future__ import annotations

import functools
import io
import os
import sys

HANDWRITING = {                     # tên hiển thị -> file trong assets/fonts
    "Chữ in tay (Patrick Hand)": "PatrickHand.ttf",
    "Chữ tròn (Pangolin)": "Pangolin.ttf",
    "Chữ học sinh (Mali)": "Mali.ttf",
    "Chữ nghiêng mềm (Charm)": "Charm.ttf",
    "Chữ viết liền (Dancing Script)": "DancingScript.ttf",
    "Chữ học trò Việt (Playwrite VN)": "PlaywriteVN.ttf",
    "Chữ bút bi (Itim)": "Itim.ttf",
    "Chữ bút dạ (Sriracha)": "Sriracha.ttf",
    "Chữ ký mềm (Comforter)": "Comforter.ttf",
    "Chữ ký bay (Moon Dance)": "MoonDance.ttf",
    "Chữ hoa mỹ (Great Vibes)": "GreatVibes.ttf",
}

# họ phông -> (thường, đậm, nghiêng, đậm nghiêng); thử lần lượt các tên file
SYSTEM = {
    "serif": [("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
              # macOS: /System/Library/Fonts/Supplemental
              ("Times New Roman.ttf", "Times New Roman Bold.ttf", "Times New Roman Italic.ttf",
               "Times New Roman Bold Italic.ttf"),
              ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf"),
              ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf",
               "LiberationSerif-BoldItalic.ttf")],
    "sans": [("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
             ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
             ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
             ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf",
              "LiberationSans-BoldItalic.ttf")],
    "calibri": [("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf")],
    "cambria": [("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf")],
    "tahoma": [("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
               ("Tahoma.ttf", "Tahoma Bold.ttf", "Tahoma.ttf", "Tahoma Bold.ttf")],
    "verdana": [("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
                ("Verdana.ttf", "Verdana Bold.ttf", "Verdana Italic.ttf", "Verdana Bold Italic.ttf")],
    "segoe": [("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf")],
    "mono": [("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
             ("Courier New.ttf", "Courier New Bold.ttf", "Courier New Italic.ttf", "Courier New Bold Italic.ttf"),
             ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf",
              "DejaVuSansMono-BoldOblique.ttf")],
}
FAMILY_LABEL = {"serif": "Times New Roman", "sans": "Arial", "calibri": "Calibri", "cambria": "Cambria",
                "tahoma": "Tahoma", "verdana": "Verdana", "segoe": "Segoe UI", "mono": "Courier New"}


def assets_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.dirname(here), here, os.path.dirname(sys.executable)):
        d = os.path.join(base, "assets")
        if os.path.isdir(d):
            return d
    return os.path.join(os.path.dirname(here), "assets")


def handwriting_path(name: str) -> str:
    return os.path.join(assets_dir(), "fonts", HANDWRITING.get(name, name))


@functools.lru_cache(maxsize=1)
def font_dirs() -> list[str]:
    out = []
    if sys.platform == "win32":
        out.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts"))
        la = os.environ.get("LOCALAPPDATA")
        if la:
            out.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        # Times New Roman, Arial... của macOS nằm trong thư mục con Supplemental
        out += ["/Library/Fonts", "/System/Library/Fonts/Supplemental", "/System/Library/Fonts",
                os.path.expanduser("~/Library/Fonts")]
    else:
        for root in ("/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")):
            for d, _, _ in os.walk(root):
                out.append(d)
    return [d for d in out if os.path.isdir(d)]


@functools.lru_cache(maxsize=256)
def _find_file(name: str) -> str | None:
    low = name.lower()
    for d in font_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
        try:
            for f in os.listdir(d):
                if f.lower() == low:
                    return os.path.join(d, f)
        except OSError:
            pass
    return None


def family_of(font_name: str) -> str:
    """Tên phông trong PDF (vd. 'ABCDEF+TimesNewRomanPS-BoldMT') -> họ phông tương đương có trên máy."""
    n = (font_name or "").lower()
    n = n.split("+", 1)[-1]
    for key, fam in (("calibri", "calibri"), ("cambria", "cambria"), ("tahoma", "tahoma"), ("verdana", "verdana"),
                     ("segoe", "segoe"), ("courier", "mono"), ("mono", "mono"), ("consola", "mono"),
                     ("arial", "sans"), ("helvet", "sans"), ("sans", "sans"), ("roboto", "sans"),
                     ("times", "serif"), ("roman", "serif"), ("serif", "serif"), ("georgia", "serif")):
        if key in n:
            return fam
    return "serif"


def system_font(family: str = "serif", bold: bool = False, italic: bool = False) -> str:
    idx = (1 if bold else 0) + (2 if italic else 0)
    for fam in (family, "serif" if family != "serif" else "sans", "sans"):
        for names in SYSTEM.get(fam, []):
            for k in (idx, idx & 1, 0):
                p = _find_file(names[k])
                if p:
                    return p
    # dự phòng cuối: phông giao diện Be Vietnam Pro đóng gói sẵn trong phần mềm (đủ dấu tiếng Việt)
    ui = os.path.join(assets_dir(), "fonts", "ui", "BeVietnamPro-Bold.ttf" if bold else "BeVietnamPro-Regular.ttf")
    if os.path.isfile(ui):
        return ui
    raise FileNotFoundError("Không tìm thấy phông chữ tiếng Việt trên máy")


def system_family_of_path(path: str) -> str | None:
    """Đường dẫn phông hệ thống -> họ phông trong SYSTEM ("serif", "sans"...) hoặc None (phông viết tay...)."""
    b = os.path.basename(path or "").lower()
    for fam, variants in SYSTEM.items():
        for names in variants:
            if b in (n.lower() for n in names):
                return fam
    return None


def styled_variant(path: str, bold: bool = False, italic: bool = False) -> str:
    """Bản đậm / nghiêng của một phông hệ thống (Times, Arial...). Phông không có biến thể: trả lại chính nó."""
    if not (bold or italic):
        return path
    fam = system_family_of_path(path)
    if fam is None:
        return path
    try:
        return system_font(fam, bold, italic)
    except FileNotFoundError:
        return path


def has_variants(path: str) -> bool:
    return system_family_of_path(path) is not None


@functools.lru_cache(maxsize=16)
def _load(path: str):
    from fontTools.ttLib import TTFont
    if path.lower().endswith(".ttc"):
        return TTFont(path, fontNumber=0, lazy=True)
    return TTFont(path, lazy=True)


def missing_chars(path: str, text: str) -> str:
    cmap = _load(path).getBestCmap()
    return "".join(sorted({c for c in text if c not in "\n\r\t" and ord(c) not in cmap}))


def measure(path: str, text: str, size: float) -> float:
    """Độ rộng dòng chữ (pt) – đủ chính xác để ngắt dòng hộp chữ."""
    f = _load(path)
    cmap = f.getBestCmap()
    hmtx = f["hmtx"]
    upm = f["head"].unitsPerEm
    w = 0
    for c in text:
        g = cmap.get(ord(c))
        w += hmtx[g][0] if g and g in hmtx.metrics else upm // 2
    return w * size / upm


def metrics(path: str) -> tuple[float, float]:
    """(ascent, descent) theo tỉ lệ cỡ chữ."""
    f = _load(path)
    upm = f["head"].unitsPerEm
    hh = f["hhea"]
    return hh.ascent / upm, -hh.descent / upm


def wrap(path: str, text: str, size: float, width: float) -> list[str]:
    lines = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = w if not cur else cur + " " + w
            if cur and measure(path, cand, size) > width:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        lines.append(cur)
    return lines


@functools.lru_cache(maxsize=64)
def subset(path: str, chars: str) -> bytes:
    """Rút gọn phông chỉ còn các ký tự dùng tới (giữ bảng cmap để PDFium dò ký tự)."""
    from fontTools import subset as fts
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=0) if path.lower().endswith(".ttc") else TTFont(path)
    opt = fts.Options()
    opt.layout_features = []            # PDF không dùng GSUB/GPOS -> bỏ cho nhẹ
    opt.hinting = False
    opt.name_IDs = [1, 2, 4, 6]
    opt.notdef_outline = True
    opt.glyph_names = False
    opt.drop_tables += ["DSIG", "FFTM", "GDEF", "GSUB", "GPOS", "kern", "vhea", "vmtx"]
    s = fts.Subsetter(opt)
    s.populate(text=chars + " ")
    s.subset(f)
    if "CFF " in f:                     # OTF dạng CFF: PDFium nạp TrueType ổn định hơn -> dùng phông khác
        raise ValueError("Phông CFF không hỗ trợ")
    # fontTools giữ mọi mã trỏ tới glyph còn giữ: Times New Roman / Arial dùng chung glyph cho dấu cách và
    # khoảng trắng cứng U+00A0 -> PDF ghi ngược thành U+00A0, chép chữ ra / tìm trong Adobe không khớp dấu cách.
    # Chỉ giữ đúng các ký tự đã dùng.
    wanted = {ord(c) for c in chars + " "}
    for table in f["cmap"].tables:
        if hasattr(table, "cmap") and isinstance(table.cmap, dict):
            for u in [u for u in table.cmap if u not in wanted]:
                del table.cmap[u]
    # đặt tên riêng cho bản rút gọn (kiểu "ABCDEF+TenPhong"): PDFium gộp các phông trùng tên trong cùng
    # tài liệu -> nếu giữ tên gốc, chữ mới có thể dùng nhầm phông cũ của file và hỏng khi lưu
    import hashlib
    h = hashlib.sha1((path + "|" + chars).encode("utf-8")).digest()
    tag = "".join(chr(65 + b % 26) for b in h[:6])
    name = f["name"]
    ps = (name.getDebugName(6) or "Font").replace(" ", "")
    for rec in list(name.names):
        if rec.nameID in (1, 3, 4, 6):
            try:
                val = tag + "+" + ps if rec.nameID in (3, 6) else tag + " " + (rec.toUnicode() or ps)
                rec.string = val
            except Exception:
                pass
    b = io.BytesIO()
    f.save(b)
    return b.getvalue()


# ------------------------------------------------------------------ 1.0.22: giữ đúng phông khi sửa chữ có sẵn
def _norm(s: str) -> str:
    """Chuẩn hóa tên phông để so: bỏ tiền tố bản rút gọn "ABCDEF+", chữ thường, bỏ dấu cách / gạch / "PS", "MT"."""
    import re
    s = (s or "").split("+", 1)[-1].lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    for suf in ("regular", "normal", "mt", "ps"):
        if s.endswith(suf) and len(s) > len(suf) + 3:
            s = s[: -len(suf)]
    return s.replace("ps", "") if s.startswith("timesnewromanps") else s


def _index_cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or \
        os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "PdfKySo", "font_index.json")


@functools.lru_cache(maxsize=1)
def font_index() -> dict:
    """Danh mục phông đã cài: {tên chuẩn hóa: [đường dẫn, đậm?, nghiêng?]} – đọc bảng tên của từng phông
    (một lần, lưu đệm theo thời điểm sửa thư mục phông để các lần sau mở ngay)."""
    import json
    dirs = font_dirs()
    stamp = [[d, os.path.getmtime(d)] for d in dirs if os.path.isdir(d)]
    cache = _index_cache_path()
    try:
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("stamp") == stamp and data.get("v") == 1:
            return data["index"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    from fontTools.ttLib import TTFont
    index: dict = {}
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for fn in names:
            if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
                continue
            path = os.path.join(d, fn)
            try:
                f = TTFont(path, fontNumber=0, lazy=True) if fn.lower().endswith(".ttc") else TTFont(path, lazy=True)
                nm = f["name"]
                fam = nm.getDebugName(16) or nm.getDebugName(1) or ""
                sub = (nm.getDebugName(17) or nm.getDebugName(2) or "").lower()
                full = nm.getDebugName(4) or ""
                ps = nm.getDebugName(6) or ""
                cff = "CFF " in f
                f.close()
            except Exception:
                continue
            if cff:                                  # PDFium nạp phông TrueType ổn định hơn
                continue
            bold = any(k in sub for k in ("bold", "black", "heavy", "semibold", "demi"))
            italic = "italic" in sub or "oblique" in sub
            rec = [path, bold, italic]
            for key in {_norm(ps), _norm(full), _norm(fam + sub.replace("regular", "")), }:
                if key and key not in index:
                    index[key] = rec
            fk = "fam:" + _norm(fam) + (":b" if bold else "") + (":i" if italic else "")
            index.setdefault(fk, rec)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "stamp": stamp, "index": index}, f)
    except OSError:
        pass
    return index


def match_installed(pdf_font_name: str, bold: bool = False, italic: bool = False) -> str | None:
    """Phông ĐÃ CÀI trùng tên với phông trong PDF (vd. 'ABCDEF+Roboto-Bold' -> Roboto Bold trên máy)."""
    if not pdf_font_name:
        return None
    try:
        idx = font_index()
    except Exception:
        return None
    raw = pdf_font_name.split("+", 1)[-1]
    hit = idx.get(_norm(raw))
    if hit and os.path.isfile(hit[0]):
        return hit[0]
    fam = raw.replace(",", "-").split("-", 1)[0]
    for b, it in ((bold, italic), (bold, False), (False, False)):
        hit = idx.get("fam:" + _norm(fam) + (":b" if b else "") + (":i" if it else ""))
        if hit and os.path.isfile(hit[0]):
            return hit[0]
    return None


def embedded_font_file(data: bytes) -> str | None:
    """Lưu chương trình phông nhúng trong PDF ra thư mục tạm (dùng lại đúng phông gốc khi sửa chữ).
    Chỉ nhận phông TrueType đọc được và có bảng mã Unicode; trả về đường dẫn hoặc None."""
    import hashlib
    import tempfile
    if not data or len(data) < 100:
        return None
    h = hashlib.sha1(data).hexdigest()[:20]
    d = os.path.join(tempfile.gettempdir(), "pdfkyso-fonts")
    path = os.path.join(d, h + ".ttf")
    if os.path.isfile(path):
        return path if _usable_embedded(path) else None
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(io.BytesIO(data), lazy=False)
        if "CFF " in f or "glyf" not in f or "cmap" not in f:
            return None
        cmap = f.getBestCmap() or {}
        if not any(0x20 < u < 0xF000 for u in cmap):        # phông ký hiệu (mã riêng) -> không dùng lại được
            return None
        os.makedirs(d, exist_ok=True)
        with open(path, "wb") as out:
            out.write(data)
    except Exception:
        return None
    return path if _usable_embedded(path) else None


@functools.lru_cache(maxsize=64)
def _usable_embedded(path: str) -> bool:
    try:
        f = _load(path)
        return "hmtx" in f and "head" in f and "hhea" in f and bool(f.getBestCmap())
    except Exception:
        return False
