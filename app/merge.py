"""Khay ghép PDF: danh sách file có thứ tự, chọn trang, ghép thành một file.

Tối ưu: chỉ mở file khi cần đếm trang/ghép; ghép bằng import_pages của PDFium (sao chép đối
tượng, không render lại -> giữ nguyên chất lượng và rất nhanh).
"""
from __future__ import annotations

import io
import json
import os
from dataclasses import asdict, dataclass, field

import pypdfium2 as pdfium

from .colormode import CONVERT_MODES
from .document import PdfDocument, format_ranges, parse_ranges

BLANK = -1   # đánh dấu trang trắng trong kế hoạch ghép
AUTO_CACHE: dict = {}   # (file, thời điểm sửa) + trang -> "color" | "gray" (tự nhận trang màu)


def color_stats(items, opts, progress=None) -> tuple[int, int]:
    """10f – (số trang màu, số trang đen trắng/xám) của file ghép (không tính bìa, mục lục, trang trắng)."""
    import pypdfium2 as pdfium
    from .colormode import resolve_auto
    n_color = n_mono = 0
    rows, _, _ = plan(items, opts)
    for k, row in enumerate(rows):
        eff = {p: row.item.mode_of(p, opts.color) for p in row.pages}
        autos = [p for p, m in eff.items() if m in ("auto", "color", "blacktext")]
        if autos:
            src = pdfium.PdfDocument(row.item.path, password=row.item.password)
            try:
                found = resolve_auto(src, autos, AUTO_CACHE, (row.item.path, os.path.getmtime(row.item.path)))
            finally:
                src.close()
            for p in autos:
                if eff[p] == "auto":
                    eff[p] = found[p]
                elif found[p] == "gray":              # "Màu" nhưng trang không có màu -> máy in tính đen trắng
                    eff[p] = "gray"
                elif eff[p] == "blacktext":
                    eff[p] = "color"                  # chữ đen nhưng còn ảnh/nền màu
        for m in eff.values():
            if m == "color":
                n_color += 1
            else:
                n_mono += 1
        if progress:
            progress(k + 1, len(rows))
    return n_color, n_mono


@dataclass
class TrayItem:
    path: str
    checked: bool = True
    whole: bool = True           # True: cả file; False: theo dải trang
    ranges: str = ""
    page_count: int = 0
    password: str | None = field(default=None, repr=False)
    color: str = ""              # đợt 3: "" = theo lựa chọn chung · "color" | "blacktext" | "gray" | "bw" cho riêng file này
    page_colors: dict = field(default_factory=dict)   # {"số trang (0-based)": "color"|"gray"|"bw"} – riêng từng trang
    # 1.0.22 – sửa trang ngay trong khay (không đụng file gốc): {"số trang (0-based)": ...}
    page_rot: dict = field(default_factory=dict)       # xoay thêm 90 / 180 / 270 độ
    page_blank: dict = field(default_factory=dict)     # số trang trắng chèn SAU trang này
    page_paper: dict = field(default_factory=dict)     # đổi khổ riêng trang này: "A4" | "A3" | "A5" | "Letter"…

    def extra_after(self, page: int) -> int:
        try:
            return max(0, int(self.page_blank.get(str(page), 0)))
        except (TypeError, ValueError):
            return 0

    def out_len(self) -> int:
        """Số trang đoạn này chiếm trong file ghép (trang được chọn + trang trắng chèn thêm)."""
        pages = self.pages()
        return len(pages) + sum(self.extra_after(p) for p in pages)

    def copy(self) -> "TrayItem":
        from dataclasses import replace
        return replace(self, page_colors=dict(self.page_colors), page_rot=dict(self.page_rot),
                       page_blank=dict(self.page_blank), page_paper=dict(self.page_paper))

    def mode_of(self, page: int, default: str = "color") -> str:
        """Chế độ màu của một trang: riêng trang > riêng file > lựa chọn chung."""
        return self.page_colors.get(str(page)) or self.color or default

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def pages(self) -> list[int]:
        if self.whole:
            return list(range(self.page_count))
        if not (self.ranges or "").strip():          # bỏ hết các trang -> file này không ghép trang nào
            return []
        return parse_ranges(self.ranges, self.page_count)

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("password", None)   # không lưu mật khẩu xuống đĩa
        return d


@dataclass
class MergeOptions:
    duplex: bool = True          # in 2 mặt: mỗi file bắt đầu ở trang lẻ
    auto_rotate: bool = True
    bookmarks: bool = False
    resize: str | None = None    # None = giữ nguyên; "A4"...
    resize_mode: str = "fit"
    even_total: bool = False     # làm chẵn tổng số trang
    cover: bool = False          # giai đoạn 6c: trang bìa
    cover_title: str = "HỒ SƠ"
    cover_subtitle: str = ""
    cover_org: str = ""
    cover_date: str = ""         # trống = ngày ghép
    toc: bool = False            # mục lục (tên file + số trang, bấm để nhảy tới)
    page_numbers: bool = False   # đánh số "Trang x / y" chân trang (trừ trang bìa)
    color: str = "color"         # đợt 3: màu chung khi ghép: "color" | "gray" | "bw"


@dataclass
class PlanRow:
    item: TrayItem
    pages: list[int]
    start: int                   # trang bắt đầu trong file ghép (1-based)
    blanks_after: int


def count_pages(path: str, password: str | None = None) -> int:
    pdf = pdfium.PdfDocument(path, password=password)
    try:
        return len(pdf)
    finally:
        pdf.close()


TOC_PER_PAGE = 26


def front_pages(opts: MergeOptions, n_files: int) -> tuple[int, int, int]:
    """(số trang bìa, số trang mục lục, trang trắng đệm) đặt trước nội dung."""
    cover = 1 if opts.cover else 0
    toc = -(-n_files // TOC_PER_PAGE) if opts.toc and n_files else 0
    pad = 1 if opts.duplex and (cover + toc) % 2 == 1 else 0     # in 2 mặt: nội dung bắt đầu trang lẻ
    return cover, toc, pad


def plan(items: list[TrayItem], opts: MergeOptions) -> tuple[list[PlanRow], int, int]:
    """Tính vị trí từng file trong file ghép + số trang trắng cần chèn.
    Trả về (các dòng, tổng số trang, số trang trắng)."""
    rows: list[PlanRow] = []
    active = [it for it in items if it.checked]
    cover, toc, pad = front_pages(opts, len([it for it in active if it.pages()]))
    pos = cover + toc + pad
    blanks = pad
    for k, it in enumerate(active):
        pages = it.pages()
        if not pages:
            continue
        start = pos + 1
        pos += len(pages) + sum(it.extra_after(p) for p in pages)
        need = 0
        is_last = k == len(active) - 1
        if opts.duplex and not is_last and pos % 2 == 1:
            need = 1
        pos += need
        blanks += need
        rows.append(PlanRow(it, pages, start, need))
    if opts.even_total and pos % 2 == 1:
        if rows:
            rows[-1].blanks_after += 1
        pos += 1
        blanks += 1
    return rows, pos, blanks


def check_plan(items: list[TrayItem], opts: MergeOptions) -> list[str]:
    """1.0.22 – các điều nên xem lại trước khi ghép: trang dùng trùng, file đã ký số, trang khác khổ."""
    from .document import paper_name
    out = []
    rows, _, _ = plan(items, opts)
    used: dict = {}
    for row in rows:
        for p in row.pages:
            used.setdefault((os.path.normcase(os.path.abspath(row.item.path)), p), []).append(row)
    dup: dict = {}
    for (path, p), rs in used.items():
        if len(rs) > 1:
            dup.setdefault(rs[0].item.name, []).append(p + 1)
    for name, pgs in dup.items():
        pgs.sort()
        out.append(f"Trang dùng lặp lại: {name} – trang {format_ranges([x - 1 for x in pgs])} có ở nhiều đoạn.")
    signed = []
    for row in rows:
        try:
            from .tray import _has_signature
            if _has_signature(row.item.path) and row.item.name not in signed:
                signed.append(row.item.name)
        except Exception:
            pass
    if signed:
        out.append("File đã có chữ ký số (file ghép sẽ không còn chữ ký của chúng): " + ", ".join(signed[:6]) +
                   (" …" if len(signed) > 6 else ""))
    if not opts.resize:
        sizes: dict = {}
        for row in rows:
            pdf = pdfium.PdfDocument(row.item.path, password=row.item.password)
            try:
                for p in row.pages:
                    w, h = pdf.get_page_size(p)
                    lab = row.item.page_paper.get(str(p)) or paper_name(w * 25.4 / 72, h * 25.4 / 72)
                    sizes[lab] = sizes.get(lab, 0) + 1
            finally:
                pdf.close()
        if len(sizes) > 1:
            out.append("Các trang khác khổ: " + ", ".join(f"{k} ({v} trang)" for k, v in
                                                           sorted(sizes.items(), key=lambda kv: -kv[1])) +
                       ". Có thể chọn “Kích thước trang” để đưa về một khổ.")
    return out


def sheets(total_pages: int, duplex: bool) -> int:
    return (total_pages + 1) // 2 if duplex else total_pages


def merge(items: list[TrayItem], opts: MergeOptions, progress=None) -> PdfDocument:
    """Ghép theo kế hoạch -> PdfDocument mới (chưa lưu)."""
    rows, total, _ = plan(items, opts)
    if not rows:
        raise ValueError("Khay chưa có file nào được chọn để ghép")
    out = pdfium.PdfDocument.new()
    outline = []   # (tên, trang bắt đầu 0-based)
    modes = {}     # trang trong file ghép -> "gray" | "bw"
    user_rot = set()   # trang người dùng đã tự xoay trong khay -> không tự xoay lại
    papers = {}        # khổ -> [trang trong file ghép] đổi khổ riêng
    for n, row in enumerate(rows):
        src = pdfium.PdfDocument(row.item.path, password=row.item.password)
        it = row.item
        try:
            at = len(out)
            out.import_pages(src, row.pages)
            # trang trắng chèn sau từng trang (chèn từ cuối lên để chỉ số không lệch)
            for k in reversed(range(len(row.pages))):
                extra = it.extra_after(row.pages[k])
                if extra:
                    w, h = out.get_page_size(at + k)
                    for _ in range(extra):
                        out.new_page(w, h, index=at + k + 1).close()
            idx, off = [], 0
            for k, p in enumerate(row.pages):
                idx.append(at + k + off)
                off += it.extra_after(p)
            eff = {p: it.mode_of(p, opts.color) for p in row.pages}
            autos = [p for p, m in eff.items() if m == "auto"]
            if autos:                                   # tự nhận trang có màu thật
                from .colormode import resolve_auto
                eff.update(resolve_auto(src, autos, AUTO_CACHE, (it.path, os.path.getmtime(it.path))))
            for k, p in enumerate(row.pages):
                m = eff[p]
                if m in CONVERT_MODES:
                    modes[idx[k]] = m
                deg = int(it.page_rot.get(str(p), 0) or 0) % 360
                if deg:
                    pg = out[idx[k]]
                    pg.set_rotation((pg.get_rotation() + deg) % 360)
                    pg.close()
                    user_rot.add(idx[k])
                paper = it.page_paper.get(str(p))
                if paper:
                    papers.setdefault(paper, []).append(idx[k])
            outline.append((os.path.splitext(it.name)[0], at))
            if row.blanks_after:
                w, h = out.get_page_size(len(out) - 1)   # trang trắng cùng khổ trang trước
                for _ in range(row.blanks_after):
                    out.new_page(w, h).close()
        finally:
            src.close()
        if progress:
            progress(n + 1, len(rows))
    cover, toc, pad = front_pages(opts, len(rows))
    nfront = cover + toc + pad
    buf = io.BytesIO()
    out.save(buf)
    out.close()
    data = buf.getvalue()
    if modes:
        from .colormode import convert_bytes
        data = convert_bytes(data, modes)
    doc = PdfDocument(data=data)
    doc.path = None
    if opts.auto_rotate:
        doc.auto_rotate([i for i in range(doc.page_count) if i not in user_rot])
    if opts.resize:
        # chỉ đổi khổ trang nội dung, trang trắng đổi theo luôn cho đồng bộ
        doc.resize_pages(list(range(doc.page_count)), opts.resize, "keep", opts.resize_mode)
    for paper, pgs in papers.items():                 # khổ riêng từng trang (đặt trong khay) – ưu tiên hơn khổ chung
        doc.resize_pages(pgs, paper, "keep", opts.resize_mode)
    links = []
    if nfront:
        front, links = build_front(opts, rows, doc.page_size_pt(0), cover, toc, pad)
        doc.pdf.import_pages(front.pdf, index=0)
        doc._drop_pages()
        front.close()
    if opts.page_numbers:
        from .editing import add_page_numbers
        add_page_numbers(doc, list(range(cover, doc.page_count)), snapshot=False)
    data = doc.to_bytes()
    doc.close()
    if links:
        data = add_links(data, links)
    if opts.bookmarks and outline:
        extra = ([("Trang bìa", 0)] if cover else []) + ([("Mục lục", cover)] if toc else [])
        data = add_bookmarks(data, extra + [(t, p + nfront) for t, p in outline])
    doc = PdfDocument(data=data)
    doc.path = None
    doc._undo.clear()
    doc._redo.clear()
    doc.modified = True
    return doc


def build_front(opts: MergeOptions, rows: list[PlanRow], size, cover: int, toc: int, pad: int):
    """Trang bìa + mục lục (chữ thật, dùng phông hệ thống). Trả về (tài liệu, [(trang mục lục, khung, trang đích)])."""
    import time as _t
    from . import editing, fonts
    w, h = size
    if w > h:                                   # bìa/mục lục luôn khổ dọc
        w, h = h, w
    d = PdfDocument()
    d.pdf.new_page(w, h).close()
    for _ in range(cover + toc + pad - 1):
        d.pdf.new_page(w, h).close()
    serif = fonts.system_font("serif")
    bold = fonts.system_font("serif", bold=True)
    links = []
    if cover:
        title = opts.cover_title or "HỒ SƠ"
        tsize = 28
        while fonts.measure(bold, title, tsize) > w - 120 and tsize > 12:
            tsize -= 1
        items_b = [((w - fonts.measure(bold, title, tsize)) / 2, h * 0.36, title, tsize, "#0b2e6b")]
        items = []
        if opts.cover_org:
            items.append(((w - fonts.measure(serif, opts.cover_org, 14)) / 2, 90, opts.cover_org, 14, "#333333"))
        if opts.cover_subtitle:
            items.append(((w - fonts.measure(serif, opts.cover_subtitle, 15)) / 2, h * 0.36 + tsize * 1.8,
                          opts.cover_subtitle, 15, "#333333"))
        date = opts.cover_date or _t.strftime("Ngày %d tháng %m năm %Y")
        items.append(((w - fonts.measure(serif, date, 12)) / 2, h - 110, date, 12, "#555555"))
        count = f"Gồm {len(rows)} tài liệu"
        items.append(((w - fonts.measure(serif, count, 11)) / 2, h * 0.36 + tsize * 1.8 + 30, count, 11, "#777777"))
        editing.add_shapes(d, 0, [("rect", (40, 40, w - 40, h - 40), "#0b2e6b", 2.2, None),
                                  ("rect", (46, 46, w - 46, h - 46), "#0b2e6b", 0.6, None),
                                  ("line", (w * 0.3, h * 0.36 - 18, w * 0.7, h * 0.36 - 18), "#0b2e6b", 1, None)],
                           snapshot=False)
        editing.add_texts(d, 0, items_b, bold, snapshot=False)
        editing.add_texts(d, 0, items, serif, snapshot=False)
    for k in range(toc):
        pg = cover + k
        texts = []
        if k == 0:
            texts.append(((w - fonts.measure(bold, "MỤC LỤC", 18)) / 2, 70, "MỤC LỤC", 18, "#0b2e6b"))
        y = 115
        for n, row in enumerate(rows[k * TOC_PER_PAGE:(k + 1) * TOC_PER_PAGE], k * TOC_PER_PAGE + 1):
            name = f"{n}. {os.path.splitext(row.item.name)[0]}"
            num = str(row.start)
            left, right = 70, w - 70
            avail = right - left - fonts.measure(serif, num, 11) - 30
            while fonts.measure(serif, name, 11) > avail and len(name) > 8:
                name = name[:-2]
                name = name.rstrip() + "…" if not name.endswith("…") else name[:-1] + "…"
            nw = fonts.measure(serif, name, 11)
            dots_w = right - left - nw - fonts.measure(serif, num, 11) - 12
            dots = "." * max(3, int(dots_w / max(1, fonts.measure(serif, ".", 11))))
            texts.append((left, y, name, 11, "#1b1b1b"))
            texts.append((left + nw + 6, y, dots, 11, "#9a9a9a"))
            texts.append((right - fonts.measure(serif, num, 11), y, num, 11, "#1b1b1b"))
            links.append((pg, (left, y - 2, right, y + 14), row.start - 1))
            y += 26
        chars = "".join(sorted({c for t in texts for c in t[2]}))
        miss = fonts.missing_chars(serif, chars)
        if miss:
            texts = [(x, yy, "".join(c for c in t if c not in miss), sz, col) for x, yy, t, sz, col in texts]
        editing.add_texts(d, pg, [t for t in texts if t[2] != "MỤC LỤC"], serif, snapshot=False)
        if k == 0:
            editing.add_texts(d, pg, [t for t in texts if t[2] == "MỤC LỤC"], bold, snapshot=False)
    return d, links


def add_links(data: bytes, links) -> bytes:
    """Dòng mục lục bấm được: nhảy tới trang đầu của từng tài liệu."""
    import pikepdf
    from pikepdf import Array, Dictionary, Name
    with pikepdf.open(io.BytesIO(data)) as pk:
        for pg, (x0, y0, x1, y1), dest in links:
            page = pk.pages[pg]
            h = float(page.mediabox[3])
            annot = pk.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Border=Array([0, 0, 0]),
                                                Rect=Array([x0, h - y1, x1, h - y0]),
                                                Dest=Array([pk.pages[dest].obj, Name.Fit])))
            if "/Annots" not in page.obj:
                page.obj.Annots = Array()
            page.obj.Annots.append(annot)
        buf = io.BytesIO()
        pk.save(buf)
        return buf.getvalue()


def add_bookmarks(data: bytes, outline: list[tuple[str, int]]) -> bytes:
    import pikepdf
    with pikepdf.open(io.BytesIO(data)) as pk:
        with pk.open_outline() as ol:
            ol.root.extend(pikepdf.OutlineItem(title, page) for title, page in outline)
        buf = io.BytesIO()
        pk.save(buf)
        return buf.getvalue()


# ---------- lưu / mở mẫu khay ----------
def save_template(path: str, items: list[TrayItem], opts: MergeOptions):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"items": [it.to_json() for it in items], "options": asdict(opts)}, f,
                  ensure_ascii=False, indent=1)


def load_template(path: str) -> tuple[list[TrayItem], MergeOptions]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = [TrayItem(**it) for it in data.get("items", [])]
    opts = MergeOptions(**data.get("options", {}))
    return items, opts


__all__ = ["TrayItem", "MergeOptions", "PlanRow", "plan", "merge", "sheets", "count_pages",
           "save_template", "load_template", "format_ranges", "BLANK"]
