"""Giai đoạn 6 – lưu có bảo vệ.

- Mã hóa AES-256 (chuẩn PDF 2.0) bằng pikepdf/qpdf: mật khẩu mở file (tùy chọn) + mật khẩu chủ sở hữu.
- Quyền: in (không / chất lượng thấp / đầy đủ), sao chép nội dung, sửa, ghi chú & điền form.
- "In mờ nhưng xem nét" (chỉ khi chọn in chất lượng thấp): mỗi trang có 2 lớp nội dung
  (Optional Content): lớp gốc chỉ để XEM (không in), lớp ảnh độ phân giải thấp chỉ để IN.
  Ảnh lớp in: JPEG, có thể thang xám -> tăng dung lượng ít nhất có thể (~15–40 KB/trang ở 100 dpi).
  Kèm quyền "chỉ in chất lượng thấp" cho các phần mềm không hỗ trợ lớp in.
"""
from __future__ import annotations

import io
import secrets
from dataclasses import asdict, dataclass

PRINT_NONE, PRINT_LOW, PRINT_HIGH = "none", "low", "high"


@dataclass
class ProtectOptions:
    open_password: str = ""
    owner_password: str = ""          # trống -> tạo ngẫu nhiên (không ai gỡ được bảo vệ)
    printing: str = PRINT_HIGH
    allow_copy: bool = False
    allow_edit: bool = False
    allow_annotate: bool = False      # ghi chú, điền form
    lowres_layer: bool = True         # chỉ có tác dụng khi printing == low
    lowres_dpi: int = 100
    grayscale: bool = False
    jpeg_quality: int = 60

    def to_dict(self, with_passwords: bool = False) -> dict:
        d = asdict(self)
        if not with_passwords:
            d["open_password"] = d["owner_password"] = ""
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProtectOptions":
        keys = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in keys})


PRESETS = [
    ("Chỉ xem – không in, không sao chép", ProtectOptions(printing=PRINT_NONE)),
    ("Cho in bản mờ – xem vẫn nét", ProtectOptions(printing=PRINT_LOW, lowres_dpi=100)),
    ("Cho in – cấm sửa, cấm sao chép", ProtectOptions(printing=PRINT_HIGH)),
    ("Cho in, cho sao chép – chỉ cấm sửa", ProtectOptions(printing=PRINT_HIGH, allow_copy=True)),
]


class ProtectError(Exception):
    pass


def is_signed(pdf_bytes: bytes) -> bool:
    return b"/ByteRange" in pdf_bytes and b"/Sig" in pdf_bytes


def _lowres_jpeg(page, dpi: int, gray: bool, quality: int, rotation: int) -> tuple[bytes, int, int]:
    bm = page.render(scale=dpi / 72, rotation=(360 - rotation) % 360, may_draw_forms=False,
                     grayscale=gray, rev_byteorder=True)
    try:
        img = bm.to_pil()
    finally:
        bm.close()
    img = img.convert("L" if gray else "RGB")
    b = io.BytesIO()
    img.save(b, "JPEG", quality=quality, optimize=True, progressive=False)
    return b.getvalue(), img.width, img.height


def add_print_layer(pdf_bytes: bytes, dpi: int = 100, gray: bool = False, quality: int = 60, progress=None) -> bytes:
    """Thêm lớp in độ phân giải thấp: xem thấy bản gốc sắc nét, in ra bản ảnh mờ."""
    import pikepdf
    import pypdfium2 as pdfium
    from pikepdf import Array, Dictionary, Name, Stream
    src = pdfium.PdfDocument(pdf_bytes)
    pk = pikepdf.open(io.BytesIO(pdf_bytes))
    try:
        view = pk.make_indirect(Dictionary(Type=Name.OCG, Name="Bản xem (không in)",
                                           Usage=Dictionary(Print=Dictionary(PrintState=Name.OFF),
                                                            View=Dictionary(ViewState=Name.ON))))
        prn = pk.make_indirect(Dictionary(Type=Name.OCG, Name="Bản in độ phân giải thấp",
                                          Usage=Dictionary(Print=Dictionary(PrintState=Name.ON),
                                                           View=Dictionary(ViewState=Name.OFF))))
        pk.Root.OCProperties = Dictionary(
            OCGs=Array([view, prn]),
            D=Dictionary(Name="Mặc định", Order=Array([view, prn]), ON=Array([view]), OFF=Array([prn]),
                         Locked=Array([view, prn]),
                         AS=Array([Dictionary(Event=Name.Print, OCGs=Array([view, prn]), Category=Array([Name.Print])),
                                   Dictionary(Event=Name.View, OCGs=Array([view, prn]), Category=Array([Name.View]))])))
        n = len(pk.pages)
        for i, page in enumerate(pk.pages):
            sp = src[i]
            try:
                rot = int(page.obj.get("/Rotate", 0)) % 360
                jpg, w, h = _lowres_jpeg(sp, dpi, gray, quality, rot)
            finally:
                sp.close()
            img = Stream(pk, jpg)
            img.Type, img.Subtype = Name.XObject, Name.Image
            img.Width, img.Height = w, h
            img.ColorSpace = Name.DeviceGray if gray else Name.DeviceRGB
            img.BitsPerComponent = 8
            img.Filter = Name.DCTDecode
            box = [float(v) for v in (page.obj.get("/CropBox") or page.mediabox)]
            x0, y0, x1, y1 = box
            res = page.obj.get("/Resources")
            if res is None:
                page.obj.Resources = res = Dictionary()
            if "/XObject" not in res:
                res.XObject = Dictionary()
            if "/Properties" not in res:
                res.Properties = Dictionary()
            res.XObject.PdfKySoPrint = img
            res.Properties.PdfKySoView = view
            res.Properties.PdfKySoPrn = prn
            pre = Stream(pk, b"/OC /PdfKySoView BDC q\n")
            post = Stream(pk, (f"\nQ EMC /OC /PdfKySoPrn BDC q {x1 - x0:.3f} 0 0 {y1 - y0:.3f} {x0:.3f} {y0:.3f} cm "
                               f"/PdfKySoPrint Do Q EMC\n").encode())
            contents = page.obj.get("/Contents")
            items = list(contents) if isinstance(contents, pikepdf.Array) else ([contents] if contents is not None else [])
            page.obj.Contents = Array([pre] + items + [post])
            if progress:
                progress(i + 1, n)
        out = io.BytesIO()
        pk.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return out.getvalue()
    finally:
        pk.close()
        src.close()


def protect_pdf(pdf_bytes: bytes, opts: ProtectOptions, progress=None) -> tuple[bytes, str]:
    """Trả về (bytes đã bảo vệ, mật khẩu chủ sở hữu thực dùng)."""
    import pikepdf
    if is_signed(pdf_bytes):
        raise ProtectError("File đã có chữ ký số: thêm bảo vệ sẽ làm chữ ký mất hiệu lực.\n"
                           "Hãy bảo vệ file trước, rồi mới ký số (phần mềm sẽ hỏi mật khẩu chủ sở hữu khi ký).")
    data = pdf_bytes
    if opts.printing == PRINT_LOW and opts.lowres_layer:
        data = add_print_layer(data, opts.lowres_dpi, opts.grayscale, opts.jpeg_quality, progress)
    owner = opts.owner_password or secrets.token_urlsafe(18)
    if opts.open_password and owner == opts.open_password:
        raise ProtectError("Mật khẩu chủ sở hữu phải khác mật khẩu mở file.")
    allow = pikepdf.Permissions(
        accessibility=True, extract=opts.allow_copy, modify_annotation=opts.allow_annotate,
        modify_assembly=opts.allow_edit, modify_form=opts.allow_annotate or opts.allow_edit,
        modify_other=opts.allow_edit, print_lowres=opts.printing in (PRINT_LOW, PRINT_HIGH),
        print_highres=opts.printing == PRINT_HIGH)
    with pikepdf.open(io.BytesIO(data)) as pk:
        out = io.BytesIO()
        pk.save(out, encryption=pikepdf.Encryption(owner=owner, user=opts.open_password or "", R=6, allow=allow),
                compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return out.getvalue(), owner


def permissions(pdf_bytes: bytes, password: str = "") -> dict:
    """Đọc lại quyền của file (để kiểm thử và hiển thị)."""
    import pikepdf
    with pikepdf.open(io.BytesIO(pdf_bytes), password=password) as pk:
        a = pk.allow
        enc = pk.is_encrypted
        return {"encrypted": enc, "print_low": a.print_lowres, "print_high": a.print_highres,
                "copy": a.extract, "edit": a.modify_other, "annotate": a.modify_annotation,
                "layers": "/OCProperties" in pk.Root}


def remove_protection(pdf_bytes: bytes, owner_password: str) -> bytes:
    import pikepdf
    try:
        pk = pikepdf.open(io.BytesIO(pdf_bytes), password=owner_password)
    except pikepdf.PasswordError as e:
        raise ProtectError("Sai mật khẩu.") from e
    with pk:
        out = io.BytesIO()
        pk.save(out, encryption=False)
        return out.getvalue()
