"""Lõi xử lý tài liệu PDF - dựa trên PDFium (engine PDF của Google Chrome).

Thư viện: pypdfium2 (Apache-2.0 / BSD-3) + pikepdf (MPL-2.0) -> miễn phí kể cả khi bán
phần mềm, nhỏ gọn (~5 MB) và render rất nhanh.

Nguyên tắc tối ưu:
- Không phụ thuộc giao diện -> kiểm thử độc lập, khởi động nhanh.
- Chỉ render khi được yêu cầu; cache nằm ở tầng giao diện (tránh nhân đôi bộ nhớ).
- Nhận biết loại trang một lần rồi nhớ lại.
- Hoàn tác bằng ảnh chụp bytes của file, giới hạn cả số bước lẫn bộ nhớ.
- Lưu: file đã có chữ ký số -> lưu nối tiếp (giữ hiệu lực chữ ký, nhanh);
  còn lại -> lưu đầy đủ rồi tối ưu cấu trúc bằng pikepdf (file nhỏ nhất).
"""
from __future__ import annotations

import ctypes
import io
import math
import os
import re
from collections import Counter
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

PT_TO_MM = 25.4 / 72
PAPER_SIZES = {  # mm (rộng, cao) khổ dọc
    "A3": (297, 420), "A4": (210, 297), "A5": (148, 210),
    "Letter": (215.9, 279.4), "Legal": (215.9, 355.6),
}
A4_PT = (595.28, 841.89)

TEXT = "text"    # PDF từ Word/Excel - sửa được chữ
SCAN = "scan"    # PDF ảnh / máy scan - chỉ thao tác trên trang
BLANK = "blank"  # trang trắng

KIND_LABEL = {TEXT: "Văn bản", SCAN: "Ảnh/Scan", BLANK: "Trang trắng"}


def _blank_pdf_bytes(w: float = 595.28, h: float = 841.89) -> bytes:
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(w, h).close()
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def blank_document(count: int, size: tuple[float, float]) -> "PdfDocument":
    pdf = pdfium.PdfDocument.new()
    for _ in range(max(1, count)):
        pdf.new_page(*size).close()
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return PdfDocument(data=buf.getvalue())


NBSP = "\xa0"


def text_search(tp, text: str, match_case: bool = False) -> list[tuple[int, int]]:
    """Mọi chỗ có cụm chữ trên trang: [(chỉ số ký tự, số ký tự)].
    - Tự so khớp trên chữ của trang thay vì hàm tìm của PDFium: trên Windows PDFium chỉ phân biệt hoa/thường
      được với chữ không dấu ("điều" không tìm ra "Điều").
    - Khoảng trắng cứng U+00A0 (Word, phông Times New Roman...) coi như dấu cách."""
    if not text:
        return []
    try:
        n = tp.count_chars()
        page = tp.get_text_range(0, n) if n > 0 else ""
    except Exception:
        page, n = "", -1
    if n >= 0 and len(page) == n:
        hay = page.replace(NBSP, " ")
        needle = text.replace(NBSP, " ")
        if not match_case:
            low_h, low_n = hay.lower(), needle.lower()
            if len(low_h) == len(hay) and len(low_n) == len(needle):
                hay, needle = low_h, low_n
            else:                                     # ký tự đặc biệt đổi độ dài khi viết thường -> để PDFium tìm
                hay = None
        if hay is not None:
            out, k = [], hay.find(needle)
            while k >= 0:
                out.append((k, len(needle)))
                k = hay.find(needle, k + len(needle))
            return out
    variants = [text] + ([text.replace(" ", NBSP)] if " " in text else [])
    for v in variants:
        s = tp.search(v, match_case=match_case)
        out = []
        hit = s.get_next()
        while hit:
            out.append(tuple(hit))
            hit = s.get_next()
        s.close()
        if out:
            return out
    return []


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class PasswordRequired(Exception):
    pass


@dataclass
class PageInfo:
    width_mm: float
    height_mm: float
    paper: str
    landscape: bool
    kind: str

    @property
    def label(self) -> str:
        return f"{self.paper} · {'Ngang' if self.landscape else 'Dọc'}"


def paper_name(w_mm: float, h_mm: float, tol: float = 3.0) -> str:
    a, b = sorted((w_mm, h_mm))
    for name, (pw, ph) in PAPER_SIZES.items():
        if abs(a - pw) <= tol and abs(b - ph) <= tol:
            return name
    return f"{round(w_mm)}×{round(h_mm)} mm"


def parse_ranges(text: str, n: int) -> list[int]:
    """Dải trang kiểu máy in -> danh sách chỉ số (0-based), giữ thứ tự người nhập.
    Hỗ trợ: "1-3, 5, 8-", "-4", "all"/"" (tất cả), "lẻ", "chẵn", "3-1" (đảo ngược)."""
    t = (text or "").strip().lower().replace("–", "-").replace(";", ",")
    if t in ("", "all", "tất cả", "tat ca", "*"):
        return list(range(n))
    if t in ("lẻ", "le", "odd"):
        return list(range(0, n, 2))
    if t in ("chẵn", "chan", "even"):
        return list(range(1, n, 2))
    out: list[int] = []
    for part in filter(None, (x.strip() for x in t.split(","))):
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else n
            if not (1 <= a <= n and 1 <= b <= n):
                raise ValueError(f"Trang “{part}” vượt quá {n} trang")
            step = 1 if b >= a else -1
            out.extend(range(a - 1, b - 1 + step, step))
        elif part.isdigit():
            k = int(part)
            if not 1 <= k <= n:
                raise ValueError(f"Không có trang {k} (file có {n} trang)")
            out.append(k - 1)
        else:
            raise ValueError(f"Không hiểu “{part}”. Ví dụ đúng: 1-3, 5, 8-")
    return out


def format_ranges(pages: list[int]) -> str:
    """[0,1,2,4] -> "1-3, 5"."""
    out, i = [], 0
    ps = list(pages)
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[j] + 1:
            j += 1
        out.append(f"{ps[i] + 1}" if i == j else f"{ps[i] + 1}-{ps[j] + 1}")
        i = j + 1
    return ", ".join(out)


def analyze_page(page: pdfium.PdfPage) -> tuple[str, int | None]:
    """Một lượt duyệt đối tượng trang -> (loại trang, góc cần xoay để chữ đứng thẳng | None).

    Loại: chữ thật (TEXT), ảnh/scan (SCAN) hay trắng (BLANK). Góc lấy từ ma trận của các
    đối tượng chữ (nhanh hơn nhiều so với dựng textpage)."""
    visible = invisible = 0
    img_area = 0.0
    other = 0
    angles: Counter = Counter()
    inv_angles: Counter = Counter()      # lớp chữ OCR ẩn của bản scan: cho biết hướng trang chắc chắn hơn đoán từ ảnh
    w, h = page.get_size()
    area = max(w * h, 1)
    rot = page.get_rotation()
    if rot in (90, 270):
        w, h = h, w                      # toạ độ đối tượng là toạ độ chưa xoay
    for obj in page.get_objects(max_depth=2):
        t = obj.type
        if t == pdfium_c.FPDF_PAGEOBJ_TEXT:
            if pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
                invisible += 1
                if invisible <= 300:
                    m = obj.get_matrix()
                    inv_angles[int(round(math.degrees(math.atan2(m.b, m.a)) / 90.0)) % 4 * 90] += 1
            else:
                visible += 1
                if visible <= 300:       # lấy mẫu là đủ
                    m = obj.get_matrix()
                    angles[int(round(math.degrees(math.atan2(m.b, m.a)) / 90.0)) % 4 * 90] += 1
        elif t == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            try:
                l, b, r, tp = obj.get_bounds()
                img_area += max(0, min(r, w) - max(l, 0)) * max(0, min(tp, h) - max(b, 0))
            except Exception:
                img_area += area
        else:
            other += 1
    def dominant(cnt: Counter, need: int = 3):
        total = sum(cnt.values())
        if total >= need:
            a, c = cnt.most_common(1)[0]
            if c >= 0.6 * total:
                return a
        return None
    fix = dominant(angles)
    ocr_fix = dominant(inv_angles, 5)
    if visible:
        # ít chữ nhưng ảnh phủ kín trang -> bản scan có đóng thêm vài chữ
        if img_area / area > 0.6 and visible < 3:
            return SCAN, ocr_fix
        return TEXT, fix
    if img_area / area > 0.3 or invisible:
        return SCAN, ocr_fix
    if other or img_area:
        return TEXT, None    # có hình vẽ / ảnh nhỏ: vẫn là trang thường (không phải bản scan)
    return BLANK, None


def detect_kind(page: pdfium.PdfPage) -> str:
    return analyze_page(page)[0]


def dedupe_images(pk) -> int:
    """Gộp các ảnh giống hệt nhau (vd. cùng một con dấu đóng trên 20 trang) thành 1 bản dùng chung.
    Trả về số bản trùng đã bỏ."""
    import hashlib
    import pikepdf
    seen: dict[str, object] = {}
    removed = 0

    def key_of(obj):
        h = hashlib.sha1(obj.read_raw_bytes())
        for k in ("/Width", "/Height", "/BitsPerComponent", "/ColorSpace", "/Filter", "/Decode"):
            h.update(repr(obj.get(k)).encode())
        sm = obj.get("/SMask")
        if sm is not None:
            h.update(hashlib.sha1(sm.read_raw_bytes()).digest())
        return h.hexdigest()

    for page in pk.pages:
        res = page.obj.get("/Resources")
        xo = res.get("/XObject") if res is not None else None
        if xo is None:
            continue
        for name in list(xo.keys()):
            obj = xo[name]
            if not isinstance(obj, pikepdf.Stream) or obj.get("/Subtype") != "/Image":
                continue
            k = key_of(obj)
            first = seen.get(k)
            if first is None:
                seen[k] = obj
            elif first.objgen != obj.objgen:
                xo[name] = first
                removed += 1
    return removed


class PdfDocument:
    MAX_UNDO = 30
    MAX_UNDO_BYTES = 300 * 1024 * 1024

    def __init__(self, path: str | None = None, data: bytes | None = None,
                 password: str | None = None):
        self.path = path
        self._data = None
        try:
            if data is not None:
                self._data = data
                self.pdf = pdfium.PdfDocument(data, password=password)
            elif path:
                # đọc cả file vào bộ nhớ: Windows không khóa file đang mở -> lưu đè, ghi ô ký, phần mềm khác ghi
                # vào file này đều được (PDFium mở theo đường dẫn giữ file suốt thời gian xem)
                self._data = _read_file(path)
                self.pdf = pdfium.PdfDocument(self._data, password=password)
            else:
                self.pdf = pdfium.PdfDocument.new()
        except pdfium.PdfiumError as e:
            if "password" in str(e).lower():
                raise PasswordRequired(str(e)) from e
            raise
        self._init()
        self._kinds: dict[int, tuple] = {}
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self.modified = False
        self.version = 0          # tăng khi nội dung đổi -> giao diện bỏ cache
        self.from_bytes = data is not None

    def _init(self):
        try:
            self.pdf.init_forms()  # để hiện ô form, khung chữ ký số
        except Exception:
            pass
        self._pages: dict[int, pdfium.PdfPage] = {}

    # ---------- truy cập trang (giữ trang đã mở để khỏi nạp lại) ----------
    def page(self, i: int) -> pdfium.PdfPage:
        p = self._pages.get(i)
        if p is None:
            p = self._pages[i] = self.pdf[i]
            if len(self._pages) > 64:  # giải phóng bớt trang ít dùng
                k = next(iter(self._pages))
                if k != i:
                    self._pages.pop(k).close()
        return p

    def _drop_pages(self):
        for p in self._pages.values():
            try:
                p.close()
            except Exception:
                pass
        self._pages.clear()

    # ---------- thông tin ----------
    @property
    def page_count(self) -> int:
        return len(self.pdf)

    @property
    def name(self) -> str:
        return os.path.basename(self.path) if self.path else "Tài liệu mới.pdf"

    def page_size_pt(self, i: int) -> tuple[float, float]:
        return self.pdf.get_page_size(i)  # đã tính cả xoay trang

    def _analyze(self, i: int) -> tuple[str, int | None]:
        r = self._kinds.get(i)
        if r is None:
            r = self._kinds[i] = analyze_page(self.page(i))
        return r

    def page_kind(self, i: int) -> str:
        return self._analyze(i)[0]

    def page_info(self, i: int) -> PageInfo:
        w, h = self.page_size_pt(i)
        wm, hm = w * PT_TO_MM, h * PT_TO_MM
        return PageInfo(wm, hm, paper_name(wm, hm), w > h, self.page_kind(i))

    # ---------- quyền (file được bảo vệ) ----------
    @property
    def encrypted(self) -> bool:
        return pdfium_c.FPDF_GetSecurityHandlerRevision(self.pdf.raw) >= 0

    @property
    def perm_bits(self) -> int:
        return pdfium_c.FPDF_GetDocPermissions(self.pdf.raw) & 0xFFFFFFFF

    @property
    def can_print(self) -> bool:
        return not self.encrypted or bool(self.perm_bits & (1 << 2))

    @property
    def can_print_high(self) -> bool:
        return not self.encrypted or (self.can_print and bool(self.perm_bits & (1 << 11)))

    @property
    def can_modify(self) -> bool:
        """File được bảo vệ mở bằng mật khẩu thường: chỉ xem (phần mềm tôn trọng quyền của người gửi)."""
        return not self.encrypted or bool(self.perm_bits & (1 << 3))

    @property
    def can_copy(self) -> bool:
        return not self.encrypted or bool(self.perm_bits & (1 << 4))

    def signature_count(self) -> int:
        return max(0, pdfium_c.FPDF_GetSignatureCount(self.pdf.raw))

    def text(self, i: int) -> str:
        tp = self.page(i).get_textpage()
        try:
            return tp.get_text_range().replace(NBSP, " ")     # khoảng trắng cứng -> dấu cách thường
        finally:
            tp.close()

    # ---------- render ----------
    hide_notes = False          # 12e: ẩn biểu tượng ghi chú khi xem (không đổi file)

    def _note_annots(self, i: int) -> list:
        page = self.page(i)
        out = []
        for k in range(pdfium_c.FPDFPage_GetAnnotCount(page.raw)):
            a = pdfium_c.FPDFPage_GetAnnot(page.raw, k)
            if pdfium_c.FPDFAnnot_GetSubtype(a) in (pdfium_c.FPDF_ANNOT_TEXT, pdfium_c.FPDF_ANNOT_POPUP):
                out.append(a)
            else:
                pdfium_c.FPDFPage_CloseAnnot(a)
        return out

    def render(self, i: int, scale: float, crop=(0, 0, 0, 0), for_print: bool = False, notes: bool | None = None):
        """Trả về PdfBitmap RGB. scale = pixel/point; crop = (trái, dưới, phải, trên) tính bằng pt
        đã loại bỏ theo hướng hiển thị. for_print: dùng lớp nội dung dành cho in (file bảo vệ in mờ).
        notes=False (hoặc hide_notes): không vẽ biểu tượng ghi chú – chỉ ẩn tạm lúc vẽ, file không đổi."""
        show = (not self.hide_notes) if notes is None else notes
        if not show:
            anns = self._note_annots(i)
            if anns:
                H = getattr(pdfium_c, "FPDF_ANNOT_FLAG_HIDDEN", 2)
                old = [pdfium_c.FPDFAnnot_GetFlags(a) for a in anns]
                try:
                    for a, f in zip(anns, old):
                        pdfium_c.FPDFAnnot_SetFlags(a, f | H)
                    return self.render(i, scale, crop, for_print, True)
                finally:
                    for a, f in zip(anns, old):
                        pdfium_c.FPDFAnnot_SetFlags(a, f)
                        pdfium_c.FPDFPage_CloseAnnot(a)
        if for_print:
            return self.page(i).render(scale=scale, crop=crop, rev_byteorder=True, may_draw_forms=True,
                                       optimize_mode="print")
        return self.page(i).render(scale=scale, crop=crop, rev_byteorder=True,
                                   may_draw_forms=True)

    # ---------- hoàn tác ----------
    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.pdf.save(buf)
        return buf.getvalue()

    def _snapshot(self):
        self._undo.append(self.to_bytes())
        while len(self._undo) > 1 and (len(self._undo) > self.MAX_UNDO or
                                       sum(map(len, self._undo)) > self.MAX_UNDO_BYTES):
            self._undo.pop(0)
        self._redo.clear()

    def _changed(self):
        self.modified = True
        self.version += 1
        self._kinds.clear()

    def _load_bytes(self, data: bytes):
        self._drop_pages()
        self.pdf.close()
        self._data = data
        self.pdf = pdfium.PdfDocument(data)
        self.from_bytes = True
        self._init()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.to_bytes())
        self._load_bytes(self._undo.pop())
        self._changed()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.to_bytes())
        self._load_bytes(self._redo.pop())
        self._changed()
        return True

    # ---------- thao tác trang ----------
    def rotate_pages(self, pages: list[int], angle: int = 90):
        self._snapshot()
        for i in pages:
            p = self.page(i)
            p.set_rotation((p.get_rotation() + angle) % 360)
        self._changed()

    def delete_pages(self, pages: list[int]):
        pages = sorted(set(pages), reverse=True)
        if len(pages) >= self.page_count:
            raise ValueError("Không thể xóa hết tất cả các trang")
        self._snapshot()
        self._drop_pages()
        for i in pages:
            self.pdf.del_page(i)
        self._changed()

    def insert_blank(self, after: int, count: int = 1, size: tuple[float, float] | None = None):
        """Chèn trang trắng cùng khổ, cùng hướng với trang đứng trước (after=-1: lên đầu). size: khổ riêng (pt)."""
        self._snapshot()
        if size:
            w, h = size
        elif self.page_count:
            ref = max(0, min(after, self.page_count - 1))
            w, h = self.page_size_pt(ref)
        else:
            w, h = A4_PT
        self._drop_pages()
        for k in range(count):
            self.pdf.new_page(w, h, index=after + 1 + k).close()
        self._changed()

    def insert_blank_every(self, every: int = 1, count: int = 1, size: tuple[float, float] | None = None,
                           skip_last: bool = True) -> int:
        """18b – chèn `count` trang trắng sau mỗi `every` trang (every=1: xen sau mọi trang – bản in 2 mặt để trống
        mặt sau). Trang trắng cùng khổ, cùng hướng với trang liền trước (hoặc khổ `size`). Trả về số trang đã chèn."""
        n = self.page_count
        every = max(1, int(every))
        after = [k for k in range(every - 1, n, every) if not (skip_last and k == n - 1)]
        if not after:
            return 0
        self._snapshot()
        sizes = {k: size or self.page_size_pt(k) for k in after}
        self._drop_pages()
        for k in reversed(after):                      # chèn từ cuối lên -> chỉ số không lệch
            w, h = sizes[k]
            if size and (self.page_size_pt(k)[0] > self.page_size_pt(k)[1]) != (w > h):
                w, h = h, w                            # cùng hướng với trang trước
            for j in range(count):
                self.pdf.new_page(w, h, index=k + 1).close()
            self._drop_pages()
        self._changed()
        return len(after) * count

    def ink_ratio(self, i: int) -> float:
        """Tỉ lệ điểm ảnh có mực (tối) của trang – để nhận trang gần trắng (scan có bụi, vết bẩn)."""
        w, h = self.page_size_pt(i)
        bm = self.render(i, min(0.6, 500 / max(w, h, 1)))
        try:
            g = bm.to_pil().convert("L")
        finally:
            bm.close()
        hist = g.histogram()
        return sum(hist[:170]) / max(1, g.width * g.height)

    def pages_with_text(self, needle: str, match_case: bool = False) -> list[int]:
        """19c – các trang có chứa cụm chữ (trang chữ thật hoặc scan đã có lớp chữ)."""
        needle = (needle or "").strip()
        if not needle:
            return []
        out = []
        for i in range(self.page_count):
            t = self.text(i)
            if (needle in t) if match_case else (needle.lower() in t.lower()):
                out.append(i)
        return out

    def move_pages(self, pages: list[int], dest: int):
        """Chuyển các trang (theo thứ tự) tới vị trí dest (tính sau khi đã lấy ra)."""
        self._snapshot()
        self._drop_pages()
        arr = (ctypes.c_int * len(pages))(*pages)
        if not pdfium_c.FPDF_MovePages(self.pdf.raw, arr, len(pages), dest):
            raise ValueError("Không chuyển được trang")
        self._changed()

    def import_pages(self, other: "PdfDocument", pages: list[int] | None = None, index: int | None = None):
        self._snapshot()
        self._drop_pages()
        self.pdf.import_pages(other.pdf, pages, index)
        self._changed()

    def text_rotation_fix(self, i: int) -> int | None:
        """Góc /Rotate cần đặt để chữ đứng thẳng (chỉ trang có chữ thật). None = không xác định."""
        return self._analyze(i)[1]

    def auto_rotate(self, pages: list[int] | None = None) -> list[int]:
        """Tự xoay các trang có chữ bị nằm ngang/lộn ngược. Trả về danh sách trang đã xoay."""
        pages = range(self.page_count) if pages is None else pages
        todo = []
        for i in pages:
            kind, fix = self._analyze(i)
            if kind == SCAN and fix is None:          # có lớp chữ OCR thì tin lớp chữ, không thì đoán từ ảnh
                fix = self.scan_rotation_fix(i)
            elif kind not in (TEXT, SCAN):
                continue
            if fix is not None and fix != self.page(i).get_rotation():
                todo.append((i, fix))
        if todo:
            self._snapshot()
            for i, rot in todo:
                self.page(i).set_rotation(rot)
            self._changed()
        return [i for i, _ in todo]

    def scan_rotation_fix(self, i: int) -> int | None:
        """Trang scan: góc /Rotate để chữ đứng thẳng, nhận biết từ ảnh (không cần OCR). None = không chắc."""
        key = ("scanrot", i, self.version)
        cache = self.__dict__.setdefault("_scanrot", {})
        if key not in cache:
            from .orient import page_fix
            try:
                cache[key] = page_fix(self, i)
            except Exception:
                cache[key] = None
        return cache[key]

    def rotation_candidates(self, pages: list[int] | None = None) -> tuple[dict, list[int]]:
        """Phân tích hướng trang: ({trang: góc cần đặt} cho trang chữ bị xoay, [các trang scan chưa biết hướng])."""
        pages = range(self.page_count) if pages is None else pages
        fix_map, unknown = {}, []
        for i in pages:
            kind, fix = self._analyze(i)
            if kind == SCAN:
                if fix is None:
                    fix = self.scan_rotation_fix(i)
                if fix is None:
                    unknown.append(i)
                elif fix != self.page(i).get_rotation():
                    fix_map[i] = fix
            elif kind == TEXT and fix is not None and fix != self.page(i).get_rotation():
                fix_map[i] = fix
        return fix_map, unknown

    def set_rotations(self, rot: dict):
        """Đặt góc xoay (0/90/180/270) cho nhiều trang – một bước hoàn tác."""
        if not rot:
            return
        self._snapshot()
        for i, r in rot.items():
            self.page(i).set_rotation(int(r) % 360)
        self._changed()

    def page_signature(self, i: int) -> str:
        """Dấu vân tay nội dung trang (ảnh thu nhỏ + chữ) – để tìm trang trùng lặp."""
        import hashlib
        w, _ = self.page_size_pt(i)
        bm = self.render(i, 48 / max(w, 1))
        img = bm.to_pil().convert("L")
        data = bytes(v // 16 for v in img.tobytes())
        try:
            tp = self.page(i).get_textpage()
            txt = tp.get_text_range()
            tp.close()
        except Exception:
            txt = ""
        return hashlib.sha1(data + txt.encode("utf-8", "ignore")).hexdigest()

    def extract(self, pages: list[int]) -> bytes:
        """Tạo file PDF mới chỉ gồm các trang đã chọn (theo thứ tự) -> bytes."""
        new = pdfium.PdfDocument.new()
        new.import_pages(self.pdf, list(pages))
        buf = io.BytesIO()
        new.save(buf)
        new.close()
        return buf.getvalue()

    def resize_pages(self, pages: list[int], paper: str = "A4", orientation: str = "keep",
                     mode: str = "fit", margin_mm: float = 0.0, custom_mm=None, snapshot: bool = True):
        """Đổi khổ giấy, giữ nội dung dạng vector.
        orientation: keep | portrait | landscape | auto ; mode: fit (co vừa) | fill (lấp đầy) | none (giữ 100%)."""
        pw_mm, ph_mm = custom_mm or PAPER_SIZES[paper]
        import pikepdf   # nạp khi cần
        if snapshot:
            self._snapshot()
        with pikepdf.open(io.BytesIO(self.to_bytes())) as pk:
            for i in sorted(set(pages)):
                pg = pk.pages[i]
                box = [float(v) for v in (pg.obj.get("/CropBox") or pg.mediabox)]
                l, b, r, t = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
                uw, uh = r - l, t - b
                rot = int(pg.obj.get("/Rotate", 0)) % 360
                sw, sh = (uh, uw) if rot in (90, 270) else (uw, uh)
                land = {"portrait": False, "landscape": True}.get(orientation, sw > sh)
                tw, th = pw_mm / PT_TO_MM, ph_mm / PT_TO_MM
                if land:
                    tw, th = th, tw
                m = margin_mm / PT_TO_MM
                aw, ah = max(tw - 2 * m, 1), max(th - 2 * m, 1)
                k = {"fit": min(aw / sw, ah / sh), "fill": max(aw / sw, ah / sh)}.get(mode, 1.0)
                # ma trận đưa nội dung về đúng hướng hiển thị (bỏ /Rotate), gốc (0, 0)
                ma, mb, mc, md, me, mf = {
                    0: (1, 0, 0, 1, -l, -b),
                    90: (0, -1, 1, 0, -b, uw + l),
                    180: (-1, 0, 0, -1, uw + l, uh + b),
                    270: (0, 1, -1, 0, uh + b, -l),
                }[rot]
                tx, ty = (tw - sw * k) / 2, (th - sh * k) / 2
                cm = (ma * k, mb * k, mc * k, md * k, me * k + tx, mf * k + ty)
                pg.contents_add(pikepdf.Stream(pk, ("q %s cm\n" % " ".join(f"{v:.6f}" for v in cm)).encode()),
                                prepend=True)
                pg.contents_add(pikepdf.Stream(pk, b"\nQ\n"))
                pg.obj.MediaBox = pikepdf.Array([0, 0, tw, th])
                for key in ("/CropBox", "/TrimBox", "/BleedBox", "/ArtBox"):
                    if key in pg.obj:
                        del pg.obj[key]
                pg.obj.Rotate = 0
                for annot in pg.obj.get("/Annots", []) or []:   # dời cả link/ghi chú theo nội dung
                    if "/Rect" in annot:
                        x0, y0, x1, y1 = [float(v) for v in annot.Rect]
                        pts = [(cm[0] * x + cm[2] * y + cm[4], cm[1] * x + cm[3] * y + cm[5])
                               for x, y in ((x0, y0), (x1, y1))]
                        annot.Rect = pikepdf.Array([min(p[0] for p in pts), min(p[1] for p in pts),
                                                    max(p[0] for p in pts), max(p[1] for p in pts)])
            buf = io.BytesIO()
            pk.save(buf)
        self._load_bytes(buf.getvalue())
        if snapshot:
            self._changed()

    def insert_pages(self, other: "PdfDocument", src_pages: list[int] | None = None, index: int | None = None,
                     mode: str = "block", every: int = 1, reverse: bool = False, fit_to: int | None = None) -> list[int]:
        """Chèn trang từ tài liệu khác (1 bước hoàn tác).
        mode: "block" – chèn liền một khối tại index (None = cuối file)
              "interleave" – xen kẽ: trang 1 gốc, trang 1 nguồn, trang 2 gốc, trang 2 nguồn... (ghép mặt trước/mặt sau)
              "repeat" – chèn lặp cả khối sau mỗi `every` trang của file hiện tại
        reverse: đảo thứ tự trang nguồn (mặt sau scan ngược từ cuối lên).
        fit_to: đưa các trang chèn về khổ của trang này (None = giữ nguyên khổ gốc).
        Trả về vị trí các trang mới."""
        src = list(range(other.page_count)) if src_pages is None else list(src_pages)
        if not src:
            return []
        if reverse:
            src = src[::-1]
        ref_size = self.page_size_pt(fit_to) if fit_to is not None and self.page_count else None
        n = self.page_count
        self._snapshot()
        self._drop_pages()
        if mode == "block" or n == 0:
            at = n if index is None else max(0, min(index, n))
            self.pdf.import_pages(other.pdf, src, at)
            new = list(range(at, at + len(src)))
        else:
            if mode == "interleave":
                self.pdf.import_pages(other.pdf, src, n)
                m = len(src)
                order = []
                for k in range(max(n, m)):
                    if k < n:
                        order.append(k)
                    if k < m:
                        order.append(n + k)
            else:                                   # repeat
                every = max(1, int(every))
                reps = n // every
                if reps == 0:
                    reps = 1
                for r in range(reps):
                    self.pdf.import_pages(other.pdf, src, n + r * len(src))
                order = []
                blk = 0
                for k in range(n):
                    order.append(k)
                    if (k + 1) % every == 0 and blk < reps:
                        order += list(range(n + blk * len(src), n + (blk + 1) * len(src)))
                        blk += 1
                while blk < reps:
                    order += list(range(n + blk * len(src), n + (blk + 1) * len(src)))
                    blk += 1
            arr = (ctypes.c_int * len(order))(*order)
            if not pdfium_c.FPDF_MovePages(self.pdf.raw, arr, len(order), 0):
                raise ValueError("Không sắp xếp được trang")
            new = [pos for pos, v in enumerate(order) if v >= n]
        if ref_size and new:
            w, h = ref_size
            need = [k for k in new if abs(self.page_size_pt(k)[0] - w) > 1 or abs(self.page_size_pt(k)[1] - h) > 1]
            if need:
                mm = (min(w, h) * PT_TO_MM, max(w, h) * PT_TO_MM)
                self.resize_pages(need, orientation="landscape" if w > h else "portrait", mode="fit",
                                  custom_mm=mm, snapshot=False)
        self._changed()
        return new

    @staticmethod
    def from_images(paths: list[str], page_size: tuple[float, float] | None = None, dpi: float = 150,
                    margin_pt: float = 0.0, max_dpi: float | None = None, quality: int | None = None,
                    fit: str = "fit") -> "PdfDocument":
        """Tạo tài liệu từ ảnh: mỗi ảnh (mỗi khung TIFF) một trang.
        page_size=None: trang đúng cỡ ảnh (theo DPI của ảnh); có khổ: ảnh nằm giữa, trừ lề margin_pt, tự xoay khổ
        theo hướng ảnh. fit: "fit" (co vừa, không phóng to ảnh nhỏ) | "fill" (phóng to vừa khung).
        max_dpi: giảm độ phân giải ảnh quá nét (file nhẹ); quality: nén JPEG (vd. 75) – None giữ nguyên ảnh gốc."""
        from PIL import Image
        doc = PdfDocument(data=_blank_pdf_bytes())
        doc._drop_pages()
        doc.pdf.del_page(0)
        frames = []
        for p in paths:
            with Image.open(p) as src:
                n = getattr(src, "n_frames", 1) if p.lower().endswith((".tif", ".tiff")) else 1
                for k in range(n):                         # TIFF nhiều trang (scan nhiều trang) -> nhiều trang
                    src.seek(k)
                    fr = src.copy()
                    fr.info = dict(src.info)
                    frames.append((p if n == 1 else None, fr))
        for p, im in frames:
            d = im.info.get("dpi", (dpi, dpi))[0] or dpi
            d = d if 30 <= d <= 1200 else dpi
            w_pt, h_pt = im.width * 72 / d, im.height * 72 / d
            if page_size:
                pw, ph = page_size
                if (w_pt > h_pt) != (pw > ph):
                    pw, ph = ph, pw
                aw, ah = max(1.0, pw - 2 * margin_pt), max(1.0, ph - 2 * margin_pt)
                k = min(aw / w_pt, ah / h_pt)
                if fit != "fill" and w_pt <= aw and h_pt <= ah:
                    k = 1.0
            else:
                pw, ph = w_pt + 2 * margin_pt, h_pt + 2 * margin_pt
                k = 1.0
            ww, hh = w_pt * k, h_pt * k
            # giảm độ phân giải theo cỡ in thật
            recode = False
            if max_dpi:
                eff_dpi = im.width / max(ww / 72, 1e-6)
                if eff_dpi > max_dpi * 1.05:
                    f = max_dpi / eff_dpi
                    im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
                    recode = True
            idx = doc.page_count
            doc.pdf.new_page(pw, ph, index=idx).close()
            doc._drop_pages()
            x0, y0 = (pw - ww) / 2, (ph - hh) / 2
            rect = (x0, y0, x0 + ww, y0 + hh)
            if quality and im.mode not in ("RGBA", "LA", "P") or (quality and im.mode == "P" and
                                                                   "transparency" not in im.info):
                import io as _io
                b = _io.BytesIO()
                im.convert("L" if im.mode in ("L", "1") else "RGB").save(b, "JPEG", quality=int(quality), optimize=True)
                j = Image.open(_io.BytesIO(b.getvalue()))
                doc.insert_image(idx, rect, b"", j.width, j.height, jpeg=b.getvalue(), snapshot=False)
            elif not recode and p and p.lower().endswith((".jpg", ".jpeg")) and im.mode in ("RGB", "L", "CMYK"):
                with open(p, "rb") as f:
                    doc.insert_image(idx, rect, b"", im.width, im.height, jpeg=f.read(), snapshot=False)
            else:
                rgba = im.convert("RGBA")
                doc.insert_image(idx, rect, rgba.tobytes(), im.width, im.height, snapshot=False)
        doc.modified = False
        doc._undo.clear()
        return doc

    def display_to_user(self, i: int, x: float, y: float) -> tuple[float, float]:
        """Toạ độ hiển thị (gốc trên-trái, đơn vị pt) -> toạ độ PDF của trang (gốc dưới-trái, chưa xoay)."""
        pg = self.page(i)
        l, b, r, t = pg.get_cropbox()
        uw, uh = r - l, t - b
        rot = pg.get_rotation()
        if rot == 0:
            ux, uy = x, uh - y
        elif rot == 90:
            ux, uy = y, x
        elif rot == 180:
            ux, uy = uw - x, y
        else:
            ux, uy = uw - y, uh - x
        return ux + l, uy + b

    def user_to_display(self, i: int, ux: float, uy: float) -> tuple[float, float]:
        """Ngược lại display_to_user."""
        pg = self.page(i)
        l, b, r, t = pg.get_cropbox()
        uw, uh = r - l, t - b
        ux, uy = ux - l, uy - b
        rot = pg.get_rotation()
        if rot == 0:
            return ux, uh - uy
        if rot == 90:
            return uy, ux
        if rot == 180:
            return uw - ux, uy
        return uh - uy, uw - ux

    def text_rects(self, i: int, tp, index: int, count: int) -> list[tuple[float, float, float, float]]:
        """Khung hiển thị (x0, y0, x1, y1 pt, gốc trên-trái) của một đoạn chữ trên trang (mỗi dòng một khung)."""
        out = []
        try:
            n = tp.count_rects(index, count)
        except Exception:
            return out
        for k in range(n):
            l, b, r, t = tp.get_rect(k)
            pts = [self.user_to_display(i, x, y) for x, y in ((l, b), (r, t))]
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            out.append((min(xs), min(ys), max(xs), max(ys)))
        return out

    def search_hits(self, text: str, match_case: bool = False) -> list[tuple[int, list]]:
        """Mọi chỗ tìm thấy trong tài liệu: [(trang, [khung hiển thị của chỗ đó...])] theo thứ tự đọc."""
        hits = []
        if not text:
            return hits
        for i in range(self.page_count):
            tp = self.page(i).get_textpage()
            try:
                for idx, cnt in text_search(tp, text, match_case):
                    rects = self.text_rects(i, tp, idx, cnt)
                    if rects:
                        hits.append((i, rects))
            finally:
                tp.close()
        return hits

    SIGN_KEYWORDS = ("ĐẠI DIỆN", "GIÁM ĐỐC", "THỦ TRƯỞNG", "CHỦ TỊCH", "TỔNG GIÁM ĐỐC", "TM.", "KT.",
                     "NGƯỜI ĐẠI DIỆN", "NGƯỜI KÝ", "NGƯỜI LẬP", "BÊN A", "BÊN B", "(Ký, ghi rõ", "(Ký tên",
                     "Ký tên", "(ký, ghi rõ", "Ký và ghi rõ")

    def find_sign_spot(self, keywords=None, max_pages: int = 3, page: int | None = None):
        """Gợi ý chỗ ký: tìm các cụm như "GIÁM ĐỐC", "(Ký, ghi rõ họ tên)" ở các trang cuối (hoặc chỉ trên `page`).
        Trả về (trang, x, y) – tâm khung ký, toạ độ hiển thị; khung đặt ngay dưới cụm chữ tìm được.
        Không thấy: góc dưới bên phải trang đó / trang cuối. Chỉ là gợi ý, người dùng kéo lại được."""
        keywords = keywords or self.SIGN_KEYWORDS
        last = self.page_count - 1 if page is None else max(0, min(page, self.page_count - 1))
        scan = [last] if page is not None else range(last, max(-1, last - max_pages), -1)
        for i in scan:
            if self.page_kind(i) != "text":
                continue
            tp = self.page(i).get_textpage()
            try:
                best = None
                for kw in keywords:
                    for idx, n in text_search(tp, kw, match_case=kw.isupper()):
                        boxes = [tp.get_charbox(k) for k in range(idx, idx + n)]
                        l = min(b[0] for b in boxes)
                        r = max(b[2] for b in boxes)
                        bot = min(b[1] for b in boxes)
                        # lấy cụm thấp nhất trên trang (khối ký thường ở cuối)
                        if best is None or bot < best[2]:
                            best = ((l + r) / 2, bot, bot)
            finally:
                tp.close()
            if best:
                x, y = self.user_to_display(i, best[0], best[1])
                pw, ph = self.page_size_pt(i)
                return i, min(max(x, 100), pw - 100), min(y + 50, ph - 45)
        pw, ph = self.page_size_pt(last)
        return last, pw * 0.7, ph * 0.78

    def find_text_spot(self, text: str):
        """4c – chỗ ký ngay dưới cụm chữ `text` (tìm từ trang cuối lên, cả trang scan đã có lớp chữ).
        Trả về (trang, x, y, tìm_thấy)."""
        text = (text or "").strip()
        for i in range(self.page_count - 1, -1, -1):
            tp = self.page(i).get_textpage()
            try:
                best = None
                for idx, n in text_search(tp, text, match_case=False):
                    boxes = [tp.get_charbox(k) for k in range(idx, idx + n)]
                    l, r = min(b[0] for b in boxes), max(b[2] for b in boxes)
                    bot = min(b[1] for b in boxes)
                    if best is None or bot < best[1]:
                        best = ((l + r) / 2, bot)
            finally:
                tp.close()
            if best:
                x, y = self.user_to_display(i, best[0], best[1])
                pw, ph = self.page_size_pt(i)
                return i, min(max(x, 100), pw - 100), min(y + 50, ph - 45), True
        last = self.page_count - 1
        pw, ph = self.page_size_pt(last)
        return last, pw * 0.7, ph * 0.78, False

    LAYERS = ("top", "multiply", "behind")

    def layer_for(self, i: int, layer: str) -> str:
        """Lớp dùng được thực tế: trang scan (cả trang là một ảnh) hoặc file đã ký số không đặt "chìm dưới chữ"
        được -> dùng "hòa trộn" (chữ vẫn hiện xuyên qua mực, nhìn giống hệt)."""
        if layer == "behind" and (self.page_info(i).kind == "scan" or self.signature_count()):
            return "multiply"
        return layer if layer in self.LAYERS else "top"

    @staticmethod
    def rotated_corners(rect_pt, px_w: int, px_h: int, angle: float):
        """Ảnh px_w×px_h xoay `angle` độ (chiều kim đồng hồ) nằm vừa khung hiển thị rect_pt (khung bao).
        Trả về 3 góc hiển thị của ảnh: dưới-trái, dưới-phải, trên-trái."""
        import math
        x0, y0, x1, y1 = rect_pt
        if not angle:
            return (x0, y1), (x1, y1), (x0, y0)
        a = math.radians(angle)
        c, s = math.cos(a), math.sin(a)
        bw = px_w * abs(c) + px_h * abs(s)
        k = (x1 - x0) / bw if bw else 1.0
        hw, hh = px_w * k / 2, px_h * k / 2
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        def rot(x, y):
            return cx + x * c - y * s, cy + x * s + y * c
        return rot(-hw, hh), rot(hw, hh), rot(-hw, -hh)

    def _stream_to_back(self, i: int):
        """Đưa luồng nội dung vừa thêm (cuối trang) lên đầu -> ảnh nằm dưới chữ, hình, bảng có sẵn."""
        import pikepdf
        data = self.to_bytes()
        with pikepdf.open(io.BytesIO(data)) as pk:
            pg = pk.pages[i].obj
            c = pg.get("/Contents")
            if isinstance(c, pikepdf.Array) and len(c) > 1:
                items = [c[len(c) - 1]] + [c[k] for k in range(len(c) - 1)]
                pg.Contents = pikepdf.Array(items)
            out = io.BytesIO()
            pk.save(out)
        self._load_bytes(out.getvalue())

    def insert_image(self, i: int, rect_pt: tuple[float, float, float, float],
                     rgba: bytes, px_w: int, px_h: int, stride: int | None = None,
                     jpeg: bytes | None = None, order: str = "rgba", snapshot: bool = True,
                     angle: float = 0.0, layer: str = "top"):
        """Chèn ảnh vào trang i tại rect hiển thị (x0, y0, x1, y1) pt, gốc trên-trái.
        Ảnh truyền dạng RGBA/BGRA (giữ nền trong suốt) hoặc JPEG gốc (nhỏ gọn, không nén lại).
        order="bgra": dữ liệu đã đúng thứ tự PDFium cần (QImage ARGB32) -> không phải đảo kênh.
        angle: xoay (độ, chiều kim đồng hồ) – rect là khung bao ảnh đã xoay.
        layer: "top" nổi trên chữ · "multiply" hòa trộn như mực dấu thật · "behind" chìm dưới chữ."""
        if snapshot:
            self._snapshot()
        layer = self.layer_for(i, layer)
        if layer == "behind":
            self._load_bytes(self.to_bytes())      # mọi đối tượng cũ về luồng nội dung sẵn có
        page = self.page(i)
        img = pdfium.PdfImage.new(self.pdf)
        if jpeg is not None:
            img.load_jpeg(io.BytesIO(jpeg), pages=[page], inline=False)
        else:
            bm = pdfium.PdfBitmap.new_native(px_w, px_h, pdfium_c.FPDFBitmap_BGRA, rev_byteorder=False)
            src = memoryview(rgba)
            st = stride or px_w * 4
            dst = bm.buffer
            n = px_w * 4
            if order == "bgra" and st == bm.stride:
                dst[: st * px_h] = src[: st * px_h]
            else:
                for yy in range(px_h):
                    row = bytearray(src[yy * st: yy * st + n])
                    if order != "bgra":                 # RGBA -> BGRA
                        row[0::4], row[2::4] = row[2::4], row[0::4]
                    dst[yy * bm.stride: yy * bm.stride + n] = row
            img.set_bitmap(bm, pages=[page])
            bm.close()
        if jpeg is not None:
            iw, ih = img.get_px_size() if angle else (1, 1)
        else:
            iw, ih = px_w, px_h
        # ảnh đứng thẳng khi hiển thị dù trang có /Rotate: tính ma trận từ 3 góc hiển thị
        bl, br, tl = self.rotated_corners(rect_pt, iw, ih, angle)
        p00 = self.display_to_user(i, *bl)      # góc dưới-trái của ảnh
        p10 = self.display_to_user(i, *br)      # góc dưới-phải
        p01 = self.display_to_user(i, *tl)      # góc trên-trái
        m = pdfium.PdfMatrix(p10[0] - p00[0], p10[1] - p00[1], p01[0] - p00[0], p01[1] - p00[1],
                             p00[0], p00[1])
        img.set_matrix(m)
        page.insert_obj(img)
        if layer == "multiply":
            pdfium_c.FPDFPageObj_SetBlendMode(img.raw, b"Multiply")
        try:                                       # ghi nhớ lớp (để khi sửa ảnh đã chèn biết đang ở lớp nào)
            pdfium_c.FPDFPageObj_AddMark(img.raw, f"PdfKySo_{layer}".encode())
        except Exception:
            pass
        page.gen_content()
        if layer == "behind":
            self._stream_to_back(i)
        if snapshot:
            self._changed()

    def stamp_pages(self, pages: list[int], rect_pt, bgra: bytes, px_w: int, px_h: int, stride: int,
                    angle: float = 0.0, layer: str = "top"):
        """Đóng cùng một ảnh (dấu/chữ ký) tại cùng vị trí lên nhiều trang - 1 bước hoàn tác.
        Trang khác khổ: vị trí tính theo tỉ lệ so với trang gốc của khung."""
        self._snapshot()
        ref_w, ref_h = self.page_size_pt(pages[0])
        x0, y0, x1, y1 = rect_pt
        for i in pages:
            w, h = self.page_size_pt(i)
            kx, ky = w / ref_w, h / ref_h
            # giữ nguyên kích thước ảnh, chỉ dời vị trí theo tỉ lệ trang
            nx0, ny0 = x0 * kx, y0 * ky
            r = (nx0, ny0, nx0 + (x1 - x0), ny0 + (y1 - y0))
            self.insert_image(i, r, bgra, px_w, px_h, stride, order="bgra", snapshot=False, angle=angle,
                              layer=layer)
        self._changed()

    def seam_stamp(self, pages: list[int], bgra: bytes, px_w: int, px_h: int, stride: int,
                   diameter_pt: float, center_y: float = 0.5, edge: str = "right", reverse: bool = False,
                   natural: bool = False, group_size: int = 0, margin_pt: float = 0.0, seed: int | None = None):
        """Đóng dấu giáp lai: chia ảnh dấu thành N mảnh dọc, mỗi trang một mảnh sát mép.
        center_y: vị trí tâm dấu theo chiều cao trang (0 = đỉnh, 1 = đáy).
        1.0.22 – như đóng dấu thật:
          natural    : mảnh rộng hẹp không đều (xếp giấy so le bằng tay), lệch lên xuống chút ít, mực đậm nhạt khác nhau
          group_size : nhiều trang -> mỗi nhóm tối đa N trang một con dấu (mảnh không bị quá mỏng)
          margin_pt  : chừa khoảng cách với mép giấy (0 = sát mép)."""
        import random
        n_all = len(pages)
        if n_all < 2:
            raise ValueError("Đóng giáp lai cần ít nhất 2 trang")
        if group_size and group_size >= 2 and n_all > group_size:
            k = -(-n_all // group_size)                    # số nhóm, chia đều cho các nhóm (mỗi nhóm >= 2 trang)
            base, extra = divmod(n_all, k)
            groups, pos = [], 0
            for g in range(k):
                cnt = base + (1 if g < extra else 0)
                groups.append(pages[pos:pos + cnt])
                pos += cnt
        else:
            groups = [pages]
        rnd = random.Random(seed if seed is not None else (n_all * 7919 + px_w))
        self._snapshot()
        h_pt = diameter_pt * px_h / px_w
        mv = memoryview(bgra)
        for grp in groups:
            n = len(grp)
            cuts = [k / n for k in range(n + 1)]
            if natural:                                # ranh giới các mảnh lệch +-22% (tay xếp giấy không đều)
                for k in range(1, n):
                    cuts[k] += rnd.uniform(-0.22, 0.22) / n
            order = list(range(n))[::-1] if reverse else list(range(n))
            # các trang lệch nhau theo chiều dọc như khi xếp tập giấy (một chiều, nhỏ dần)
            drift = rnd.uniform(-1.0, 1.0) * diameter_pt * 0.03 if natural else 0.0
            for k, i in enumerate(grp):
                part = order[k]
                sx0 = int(round(cuts[part] * px_w))
                sx1 = int(round(cuts[part + 1] * px_w))
                sw = max(1, sx1 - sx0)
                buf = bytearray(sw * 4 * px_h)
                for yy in range(px_h):
                    buf[yy * sw * 4:(yy + 1) * sw * 4] = mv[yy * stride + sx0 * 4: yy * stride + sx0 * 4 + sw * 4]
                if natural:                            # mực ăn giấy không đều giữa các trang
                    buf = _scale_alpha(bytes(buf), sw, px_h, rnd.uniform(0.82, 1.0))
                slice_pt = diameter_pt * sw / px_w
                w, h = self.page_size_pt(i)
                dy = (drift * (k - (n - 1) / 2) + (rnd.uniform(-0.6, 0.6) if natural else 0.0))
                y0 = max(0.0, min(h - h_pt, center_y * h - h_pt / 2 + dy))
                x0 = w - slice_pt - margin_pt if edge == "right" else margin_pt
                self.insert_image(i, (x0, y0, x0 + slice_pt, y0 + h_pt), bytes(buf), sw, px_h, sw * 4,
                                  order="bgra", snapshot=False)
        self._changed()

    # ---------- lưu ----------
    def save(self, path: str | None = None, optimize: bool = True) -> str:
        target = path or self.path
        if not target:
            raise ValueError("Chưa có đường dẫn lưu")
        tmp = target + ".tmp"
        signed = self.signature_count() > 0
        if signed and not self.from_bytes:
            # lưu nối tiếp: giữ nguyên phần đã ký, chữ ký số còn hiệu lực
            self.pdf.save(tmp, flags=pdfium_c.FPDF_INCREMENTAL)
        elif optimize:
            data = self.to_bytes()
            import pikepdf  # nạp khi cần -> khởi động nhanh hơn
            with pikepdf.open(io.BytesIO(data)) as pk:
                dedupe_images(pk)
                pk.remove_unreferenced_resources()
                pk.save(tmp, compress_streams=True,
                        object_stream_mode=pikepdf.ObjectStreamMode.generate)
        else:
            self.pdf.save(tmp)
        same = self.path and os.path.abspath(target) == os.path.abspath(self.path)
        if same and not self.from_bytes:
            self._drop_pages()
            self.pdf.close()     # Windows khóa file đang mở
        os.replace(tmp, target)
        if same and not self.from_bytes:
            self._data = _read_file(target)
            self.pdf = pdfium.PdfDocument(self._data)
            self._init()
        self.path = target
        self.modified = False
        return target

    def close(self):
        self._drop_pages()
        self.pdf.close()


def _scale_alpha(bgra: bytes, w: int, h: int, k: float) -> bytes:
    """Nhân độ phủ (kênh alpha) của ảnh BGRA với k (0..1) – mực nhạt hơn một chút."""
    from PIL import Image
    im = Image.frombytes("RGBA", (w, h), bgra)          # thứ tự byte giữ nguyên, chỉ đụng kênh thứ 4
    r, g, b, a = im.split()
    a = a.point([int(v * k) for v in range(256)])
    return Image.merge("RGBA", (r, g, b, a)).tobytes()
