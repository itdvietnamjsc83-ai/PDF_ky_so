"""Đợt 3 – chuyển trang PDF sang XÁM hoặc ĐEN TRẮNG mà vẫn giữ chữ thật, nét vector.

- Màu chữ / nét / nền (rg, RG, k, K, sc, scn...) đổi sang thang xám theo độ sáng (không render thành ảnh):
  chữ vẫn tìm kiếm, sao chép được, in sắc nét, file không phình to.
- Ảnh (logo, ảnh chụp, trang scan) đổi sang ảnh xám (JPEG xám nếu ảnh gốc là JPEG) hoặc ảnh 1-bit đen trắng
  (ngưỡng Otsu) -> trang scan nhỏ đi rất nhiều.
- Màu chuyển (gradient) của biểu đồ Word/Excel (/Shading hàm loại 2, 3) cũng được đổi.
- Chế độ ĐEN TRẮNG (tiết kiệm mực, như "In đen trắng" của Office): chữ và nét -> đen, nền tô -> xám rất nhạt.
- Chế độ CHỮ ĐEN: chỉ đổi màu CHỮ sang đen (chữ trắng trên nền đậm giữ trắng); ảnh, nền, đường kẻ giữ nguyên màu.
- Chế độ NHƯ MÁY IN ĐEN TRẮNG (1.0.22): chữ màu -> đen đậm; ô tô màu, hình, đường kẻ, ảnh -> xám theo độ đậm nhạt
  của màu gốc (xanh lơ, vàng -> xám nhạt; đỏ, xanh đậm -> xám đậm) – giống hệt bản in ra từ máy in đen trắng.

Chế độ: "color" (giữ nguyên) | "blacktext" (chữ đen) | "gray" (xám) | "print" (như máy in đen trắng) | "bw" (đen trắng).
"""
from __future__ import annotations

import io
import zlib

MODES = [("color", "Màu"), ("blacktext", "Chữ đen"), ("gray", "Xám"), ("print", "Như máy in đen trắng"),
         ("bw", "Đen trắng")]
MODE_LABEL = dict(MODES)
MODE_SHORT = {"color": "Màu", "blacktext": "Chữ đen", "gray": "Xám", "print": "In ĐT", "bw": "ĐT"}
CONVERT_MODES = ("blacktext", "gray", "print", "bw")
# khay ghép: "auto" = trang có màu thật giữ màu, trang không màu chuyển xám (máy in tính là trang đen trắng)
AUTO = "auto"
AUTO_LABEL = "Tự động: trang có màu giữ màu"
TRAY_MODES = MODES + [(AUTO, AUTO_LABEL)]
MODE_SHORT["auto"] = "Tự động"
MODE_LABEL["auto"] = AUTO_LABEL
MODE_TIP = {
    "auto": "Tự nhận trang có màu thật (logo, dấu đỏ, biểu đồ…) để giữ màu; trang chỉ có chữ đen chuyển xám",
    "color": "Giữ nguyên màu như file gốc",
    "blacktext": "Mọi chữ màu (đỏ, xanh…) thành chữ đen; ảnh, logo, nền, bảng màu giữ nguyên",
    "gray": "Toàn trang thang xám theo độ sáng của màu (chữ vẫn là chữ thật)",
    "print": "Giống bản in từ máy in đen trắng: chữ màu thành chữ đen đậm, ô tô màu / hình / ảnh thành xám "
             "đậm nhạt theo màu gốc",
    "bw": "Đen trắng tiết kiệm mực: chữ và nét đen, nền tô nhạt, ảnh 1-bit",
}


def _lum_rgb(r, g, b) -> float:
    return max(0.0, min(1.0, 0.299 * r + 0.587 * g + 0.114 * b))


def _lum_cmyk(c, m, y, k) -> float:
    return _lum_rgb((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))


def _bw_value(v: float, text_or_stroke: bool) -> float:
    if text_or_stroke:
        return 1.0 if v >= 0.95 else 0.0
    return 1.0 - (1.0 - v) * 0.3                   # nền tô: xám rất nhạt, chữ đen phía trên vẫn rõ


TEXT_SHOW = {"Tj", "TJ", "'", '"'}
FILL_PAINT = {"f", "F", "f*", "B", "B*", "b", "b*"}


def _num(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


class _Converter:
    def __init__(self, pdf, mode: str):
        import pikepdf
        self.pk = pikepdf
        self.pdf = pdf
        self.mode = mode
        self.done: set = set()
        self.stats = {"ops": 0, "images": 0, "shadings": 0}

    # ---------- không gian màu ----------
    def _ncomp(self, cs, resources):
        """Số thành phần của không gian màu; None nếu không đổi được (Pattern, Separation, Indexed...)."""
        pk = self.pk
        name = cs
        if isinstance(cs, pk.Name):
            s = str(cs)
            if s in ("/DeviceRGB", "/RGB", "/CalRGB"):
                return 3
            if s in ("/DeviceCMYK", "/CMYK"):
                return 4
            if s in ("/DeviceGray", "/G", "/CalGray"):
                return 1
            try:
                name = resources.ColorSpace[s]
            except Exception:
                return None
        return self._ncomp_obj(name)

    def _ncomp_obj(self, obj):
        pk = self.pk
        if isinstance(obj, pk.Name):
            return {"/DeviceRGB": 3, "/DeviceCMYK": 4, "/DeviceGray": 1}.get(str(obj))
        if isinstance(obj, pk.Array) and len(obj):
            kind = str(obj[0])
            if kind == "/ICCBased":
                try:
                    return int(obj[1].get("/N", 3))
                except Exception:
                    return 3
            if kind in ("/CalRGB", "/Lab"):
                return 3
            if kind == "/CalGray":
                return 1
        return None

    def _gray_from(self, vals, n):
        if n == 3:
            return _lum_rgb(*vals[:3])
        if n == 4:
            return _lum_cmyk(*vals[:4])
        return vals[0] if vals else 0.0

    # ---------- chữ đen ----------
    def _blacktext(self, instrs, resources):
        """Chữ màu -> đen. Mỗi khối chữ BT…ET được bọc q…Q để màu đen không lan sang hình vẽ phía sau."""
        pk = self.pk
        out = []
        fill_lum = 0.0                                 # độ sáng màu tô hiện tại (ngoài khối chữ)
        fill_n = 1
        stack = []
        changed = False
        in_text = False
        k = 0
        n = len(instrs)
        while k < n:
            ins = instrs[k]
            k += 1
            if isinstance(ins, pk.ContentStreamInlineImage):
                out.append(ins)
                continue
            ops, op = list(ins.operands), str(ins.operator)
            if op == "q":
                stack.append((fill_lum, fill_n))
            elif op == "Q" and stack:
                fill_lum, fill_n = stack.pop()
            if op == "BT":
                # khối chữ có chế độ cắt (Tr 4–7) thì không bọc q…Q (giữ vùng cắt cho phần sau)
                j = k
                clip = False
                while j < n and not (not isinstance(instrs[j], pk.ContentStreamInlineImage)
                                     and str(instrs[j].operator) == "ET"):
                    x = instrs[j]
                    if not isinstance(x, pk.ContentStreamInlineImage) and str(x.operator) == "Tr" and \
                            x.operands and int(_num(x.operands[0])) >= 4:
                        clip = True
                    j += 1
                wrap = not clip
                if wrap:
                    out.append(pk.ContentStreamInstruction([], pk.Operator("q")))
                out.append(ins)
                if fill_lum < 0.95:
                    out.append(pk.ContentStreamInstruction([0], pk.Operator("g")))
                in_text = wrap or True
                self._bt_wrap = wrap
                changed = True
                continue
            if op == "ET":
                out.append(ins)
                if getattr(self, "_bt_wrap", False):
                    out.append(pk.ContentStreamInstruction([], pk.Operator("Q")))
                in_text = False
                continue
            lum = None
            if op in ("rg", "k", "g") and len(ops) in (1, 3, 4):
                vals = list(map(_num, ops))
                lum = vals[0] if op == "g" else (_lum_rgb(*vals) if op == "rg" else _lum_cmyk(*vals))
            elif op == "cs" and len(ops) == 1:
                fill_n = self._ncomp(ops[0], resources)
                if not in_text:
                    fill_lum = 0.0
            elif op in ("sc", "scn") and fill_n in (1, 3, 4):
                nums = [o for o in ops if not isinstance(o, pk.Name)]
                if len(nums) == len(ops) == fill_n:
                    lum = self._gray_from(list(map(_num, nums)), fill_n)
            if lum is not None:
                if in_text:
                    if lum < 0.95:                     # chữ màu -> đen; chữ trắng giữ nguyên
                        out.append(pk.ContentStreamInstruction([0], pk.Operator("g")))
                        continue
                else:
                    fill_lum = lum
            elif in_text and op in ("cs", "sc", "scn"):
                out.append(pk.ContentStreamInstruction([0], pk.Operator("g")))   # màu đặc biệt trong chữ -> đen
                continue
            out.append(ins)
        return out, changed

    # ---------- luồng nội dung ----------
    def convert_stream_owner(self, owner, resources):
        """owner: trang (pikepdf.Page) hoặc Form XObject."""
        pk = self.pk
        key = owner.obj.objgen if isinstance(owner, pk.Page) else owner.objgen
        if key != (0, 0) and key in self.done:
            return
        self.done.add(key)
        try:
            instrs = pk.parse_content_stream(owner)
        except Exception:
            return
        if self.mode == "blacktext":
            out, changed = self._blacktext(instrs, resources)
            if changed:
                data = pk.unparse_content_stream(out)
                if isinstance(owner, pk.Page):
                    owner.obj.Contents = pk.Stream(self.pdf, data)
                else:
                    owner.write(data)
            self.convert_resources(resources)
            return
        out = []
        fill_n = stroke_n = 1                          # mặc định DeviceGray
        in_text = False
        changed = False
        bw = self.mode in ("bw", "print")          # màu tô quyết định lúc vẽ (chữ khác ô tô màu)
        ink_save = self.mode == "bw"               # đen trắng tiết kiệm mực: nét đen, nền tô xám rất nhạt
        # đen trắng: màu tô được quyết định lúc VẼ (chữ -> đen, nền tô -> xám nhạt), vì phần mềm thường đặt màu
        # trước BT. cur = độ xám mong muốn; emitted = giá trị đã ghi ra luồng; lưu/khôi phục theo q/Q
        cur_fill, emitted = 0.0, None
        stack = []

        def emit_fill(text: bool):
            nonlocal emitted
            if cur_fill is None:
                return
            if ink_save:
                v = 0.0 if text else _bw_value(cur_fill, False)
            else:                                  # như máy in: chữ màu -> đen, chữ trắng giữ; ô tô -> xám theo màu
                v = (0.0 if cur_fill < 0.95 else cur_fill) if text else cur_fill
            if emitted != v:
                out.append(pk.ContentStreamInstruction([v], pk.Operator("g")))
                emitted = v
        for ins in instrs:
            if isinstance(ins, pk.ContentStreamInlineImage):
                out.append(ins)
                continue
            ops, op = list(ins.operands), str(ins.operator)
            if op == "BT":
                in_text = True
            elif op == "ET":
                in_text = False
            if bw:
                if op == "q":
                    stack.append((cur_fill, emitted, fill_n))
                elif op == "Q" and stack:
                    cur_fill, emitted, fill_n = stack.pop()
                if op in TEXT_SHOW:
                    emit_fill(True)
                elif op in FILL_PAINT:
                    emit_fill(False)
                elif op == "Do":
                    emit_fill(True)                    # ảnh mặt nạ (stencil) lấy màu tô -> đen
            fill_set = None
            if op in ("rg", "k") and len(ops) in (3, 4):
                fill_set = _lum_rgb(*map(_num, ops)) if op == "rg" else _lum_cmyk(*map(_num, ops))
            elif op == "g" and len(ops) == 1:
                fill_set = _num(ops[0])
            elif op in ("sc", "scn") and fill_n in (1, 3, 4):
                nums = [o for o in ops if not isinstance(o, pk.Name)]
                if len(nums) == len(ops) == fill_n:
                    fill_set = self._gray_from(list(map(_num, nums)), fill_n)
            if op == "cs" and len(ops) == 1:
                fill_n = self._ncomp(ops[0], resources)
                if fill_n in (3, 4):
                    out.append(pk.ContentStreamInstruction([pk.Name("/DeviceGray")], pk.Operator("cs")))
                    changed = True
                    if bw:
                        emitted = 0.0                  # cs đặt màu về 0
                    continue
                if bw:
                    cur_fill = 0.0 if fill_n == 1 else None
                    emitted = 0.0 if fill_n == 1 else None
                out.append(ins)
                continue
            if fill_set is not None:
                changed = changed or op != "g" or bw
                if bw:
                    cur_fill = fill_set                # ghi ra khi vẽ
                    continue
                out.append(pk.ContentStreamInstruction([fill_set], pk.Operator("g" if op in ("rg", "k", "g")
                                                                                  else op)))
                continue
            if op in ("sc", "scn") and bw:
                cur_fill, emitted = None, None         # mẫu tô (pattern) / màu đặc biệt: giữ nguyên
            # ---- nét viền ----
            if op in ("RG", "K") and len(ops) in (3, 4):
                v = _lum_rgb(*map(_num, ops)) if op == "RG" else _lum_cmyk(*map(_num, ops))
                if ink_save:
                    v = _bw_value(v, True)
                out.append(pk.ContentStreamInstruction([v], pk.Operator("G")))
                changed = True
                continue
            if op == "G" and len(ops) == 1 and ink_save:
                out.append(pk.ContentStreamInstruction([_bw_value(_num(ops[0]), True)], pk.Operator("G")))
                changed = True
                continue
            if op == "CS" and len(ops) == 1:
                stroke_n = self._ncomp(ops[0], resources)
                if stroke_n in (3, 4):
                    out.append(pk.ContentStreamInstruction([pk.Name("/DeviceGray")], pk.Operator("CS")))
                    changed = True
                    continue
            if op in ("SC", "SCN"):
                nums = [o for o in ops if not isinstance(o, pk.Name)]
                if stroke_n in (1, 3, 4) and len(nums) == len(ops) == stroke_n and (stroke_n != 1 or ink_save):
                    v = self._gray_from(list(map(_num, nums)), stroke_n)
                    if ink_save:
                        v = _bw_value(v, True)
                    out.append(pk.ContentStreamInstruction([v], pk.Operator(op)))
                    changed = True
                    continue
            out.append(ins)
        if changed:
            data = pk.unparse_content_stream(out)
            if isinstance(owner, pk.Page):
                owner.obj.Contents = pk.Stream(self.pdf, data)
            else:
                owner.write(data)
            self.stats["ops"] += 1
        self.convert_resources(resources)

    def convert_resources(self, resources):
        pk = self.pk
        if resources is None:
            return
        try:
            xobjs = resources.get("/XObject")
        except Exception:
            xobjs = None
        if xobjs:
            for name in list(xobjs.keys()):
                x = xobjs[name]
                try:
                    st = x.get("/Subtype")
                except Exception:
                    continue
                if st == "/Image":
                    if self.mode != "blacktext":
                        self.convert_image(x)
                elif st == "/Form":
                    self.convert_stream_owner(x, x.get("/Resources") or resources)
        for key in (("/Shading", "/Pattern") if self.mode != "blacktext" else ()):
            try:
                d = resources.get(key)
            except Exception:
                d = None
            if d:
                for name in list(d.keys()):
                    obj = d[name]
                    if key == "/Pattern":
                        if obj.get("/PatternType") == 2 and "/Shading" in obj:
                            self.convert_shading(obj.Shading)
                        elif obj.get("/PatternType") == 1:
                            self.convert_stream_owner(obj, obj.get("/Resources") or resources)
                    else:
                        self.convert_shading(obj)

    # ---------- màu chuyển ----------
    def _conv_function(self, fn, n):
        pk = self.pk
        t = int(fn.get("/FunctionType", -1))
        if t == 2:
            for k in ("/C0", "/C1"):
                c = fn.get(k)
                vals = [_num(v) for v in c] if c is not None else ([0.0] * n if k == "/C0" else [1.0] * n)
                if len(vals) != n:
                    return False
                v = self._gray_from(vals, n)
                if self.mode == "bw":
                    v = _bw_value(v, False)
                fn[k] = pk.Array([v])
            return True
        if t == 3:
            fns = fn.get("/Functions")
            return bool(fns) and all(self._conv_function(f, n) for f in fns)
        return False

    def convert_shading(self, sh):
        pk = self.pk
        key = sh.objgen
        if key != (0, 0) and key in self.done:
            return
        self.done.add(key)
        n = self._ncomp_obj(sh.get("/ColorSpace"))
        if n not in (3, 4) or "/Function" not in sh:
            return
        fn = sh.Function
        fns = list(fn) if isinstance(fn, pk.Array) else [fn]
        if len(fns) == 1 and self._conv_function(fns[0], n):
            sh.ColorSpace = pk.Name("/DeviceGray")
            if "/Background" in sh:
                del sh["/Background"]
            self.stats["shadings"] += 1

    # ---------- ảnh ----------
    def convert_image(self, img):
        pk = self.pk
        key = img.objgen
        if key != (0, 0) and key in self.done:
            return
        self.done.add(key)
        if img.get("/ImageMask", False):
            return
        try:
            pim = pk.PdfImage(img)
            bpc = int(img.get("/BitsPerComponent", 8))
            cs = img.get("/ColorSpace")
            if self.mode in ("gray", "print") and cs == "/DeviceGray" and bpc == 8:
                return
            if cs == "/DeviceGray" and bpc == 1:
                return                                  # đã là ảnh đen trắng
            pil = pim.as_pil_image()
        except Exception:
            return
        from PIL import Image
        g = pil.convert("L")
        was_jpeg = "/DCTDecode" in str(img.get("/Filter", ""))
        for k in ("/Decode", "/DecodeParms", "/Intent"):
            if k in img:
                del img[k]
        if self.mode == "bw":
            t = _otsu(g)
            bw = g.point(lambda v, t=t: 255 if v > t else 0).convert("1")
            raw = bw.tobytes()                            # 1 bit/điểm, hàng đệm tới byte
            img.write(zlib.compress(raw, 9), filter=pk.Name("/FlateDecode"))
            img.BitsPerComponent = 1
        elif was_jpeg:
            buf = io.BytesIO()
            g.save(buf, "JPEG", quality=88, optimize=True)
            img.write(buf.getvalue(), filter=pk.Name("/DCTDecode"))
            img.BitsPerComponent = 8
        else:
            img.write(zlib.compress(g.tobytes(), 6), filter=pk.Name("/FlateDecode"))
            img.BitsPerComponent = 8
        img.ColorSpace = pk.Name("/DeviceGray")
        img.Width, img.Height = g.width, g.height
        self.stats["images"] += 1
        del Image


def _otsu(g) -> int:
    hist = g.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best, thr = -1.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        between = wb * wf * (mb - mf) ** 2
        if between > best:
            best, thr = between, t
    return min(245, max(60, thr))


def page_has_color(page, threshold: float = 0.0004) -> bool:
    """Trang pdfium (PdfPage) có màu thật không: vẽ nhỏ rồi đếm điểm ảnh có độ bão hòa rõ."""
    w, h = page.get_size()
    scale = min(0.5, 400 / max(w, h, 1))
    bm = page.render(scale=scale)
    try:
        im = bm.to_pil().convert("RGB")
    finally:
        bm.close()
    hsv = im.convert("HSV")
    _, sat, val = hsv.split()
    # điểm màu = bão hòa > 70 và không quá tối (chữ đen khử răng cưa cũng có chút màu)
    mask = sat.point(lambda v: 255 if v > 70 else 0)
    bright = val.point(lambda v: 255 if v > 60 else 0)
    from PIL import ImageChops
    n = ImageChops.multiply(mask, bright).histogram()[255]
    return n > threshold * im.width * im.height


def resolve_auto(src_doc, pages, cache: dict | None = None, key=None) -> dict[int, str]:
    """{trang: "color" | "gray"} theo màu thật của từng trang (src_doc: pypdfium2.PdfDocument)."""
    out = {}
    for p in pages:
        ck = (key, p)
        if cache is not None and ck in cache:
            out[p] = cache[ck]
            continue
        pg = src_doc[p]
        try:
            m = "color" if page_has_color(pg) else "gray"
        finally:
            pg.close()
        out[p] = m
        if cache is not None:
            cache[ck] = m
    return out


def convert_bytes(data: bytes, page_modes: dict[int, str]) -> bytes:
    """page_modes: {chỉ số trang: "blacktext" | "gray" | "print" | "bw"} (trang không có trong dict giữ nguyên màu)."""
    import pikepdf
    todo = {i: m for i, m in page_modes.items() if m in CONVERT_MODES}
    if not todo:
        return data
    with pikepdf.open(io.BytesIO(data)) as pdf:
        convs = {m: _Converter(pdf, m) for m in set(todo.values())}
        # trang đen trắng làm trước: tài nguyên dùng chung giữa trang xám và trang đen trắng -> theo trang đầu tiên
        for i in sorted(todo, key=lambda i: ({"bw": 0, "print": 1, "gray": 2}.get(todo[i], 3), i)):
            if i >= len(pdf.pages):
                continue
            page = pdf.pages[i]
            cv = convs[todo[i]]
            res = page.obj.get("/Resources")
            cv.convert_stream_owner(page, res)
            for a in page.obj.get("/Annots", []) or []:      # hình hiển thị của chú thích (con dấu, hình vẽ...)
                try:
                    ap = a.get("/AP")
                    n = ap.get("/N") if ap is not None else None
                    if n is not None and isinstance(n, pikepdf.Stream):
                        cv.convert_stream_owner(n, n.get("/Resources") or res)
                except Exception:
                    continue
        out = io.BytesIO()
        pdf.save(out)
    return out.getvalue()


def convert_document(doc, pages, mode: str, snapshot: bool = True):
    """Chuyển các trang của PdfDocument đang mở (1 bước hoàn tác)."""
    if mode not in CONVERT_MODES or not pages:
        return
    if snapshot:
        doc._snapshot()
    data = convert_bytes(doc.to_bytes(), {i: mode for i in pages})
    doc._load_bytes(data)
    if snapshot:
        doc._changed()


def preview_png(path: str, page: int, mode: str, width: int, password: str | None = None) -> bytes:
    """Ảnh xem trước một trang sau khi chuyển (dùng cho khay ghép)."""
    import pypdfium2 as pdfium
    src = pdfium.PdfDocument(path, password=password)
    try:
        one = pdfium.PdfDocument.new()
        one.import_pages(src, [page])
        buf = io.BytesIO()
        one.save(buf)
        one.close()
    finally:
        src.close()
    data = convert_bytes(buf.getvalue(), {0: mode})
    pdf = pdfium.PdfDocument(data)
    try:
        pg = pdf[0]
        w, _ = pg.get_size()
        bm = pg.render(scale=width / max(1, w))
        im = bm.to_pil()
        bm.close()
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()
    finally:
        pdf.close()


__all__ = ["MODES", "MODE_LABEL", "convert_bytes", "convert_document", "preview_png"]
