"""Giai đoạn 6 – lõi: bảo vệ (quyền in, lớp in mờ), ký file được bảo vệ, luồng ký nhiều người, ký hàng loạt,
nén theo dung lượng, so sánh, dấu chữ, tạo hàng loạt từ Excel, lịch sử phiên bản, sao lưu, thư mục tự xử lý."""
import io
import os
import time
import zipfile

import pytest

from app import autofolder, protect, signing, tools
from app.document import PdfDocument, PasswordRequired

from .conftest import pymupdf
from .test_phase4 import _contract, _red_bbox, _red_png, _soft_signer
from .pki import CA


@pytest.fixture(scope="module")
def ca():
    return CA()


# ------------------------------------------------------------------ bảo vệ
@pytest.mark.parametrize("printing,low,high", [("none", False, False), ("low", True, False), ("high", True, True)])
def test_protect_permissions(printing, low, high):
    out, owner = protect.protect_pdf(_contract(2), protect.ProtectOptions(printing=printing))
    p = protect.permissions(out)
    assert p["encrypted"] and p["print_low"] == low and p["print_high"] == high
    assert not p["copy"] and not p["edit"]
    d = PdfDocument(data=out)                         # mở không cần mật khẩu, nhưng chỉ xem
    assert d.encrypted and not d.can_modify and d.can_print == low and d.can_print_high == high
    assert len(owner) >= 16


def test_open_password_and_owner():
    out, _ = protect.protect_pdf(_contract(1), protect.ProtectOptions(open_password="mo123", owner_password="chu456",
                                                                      allow_copy=True))
    with pytest.raises(PasswordRequired):
        PdfDocument(data=out)
    assert PdfDocument(data=out, password="mo123").can_copy
    assert PdfDocument(data=out, password="chu456").can_modify
    with pytest.raises(protect.ProtectError):
        protect.protect_pdf(_contract(1), protect.ProtectOptions(open_password="a", owner_password="a"))


def test_print_layer_view_sharp_print_blurry():
    import pypdfium2 as pdfium
    from PIL import ImageChops
    pdf = _contract(1)
    out, _ = protect.protect_pdf(pdf, protect.ProtectOptions(printing="low", lowres_dpi=72))
    a = pdfium.PdfDocument(pdf)[0].render(scale=2).to_pil().convert("L")
    view = pdfium.PdfDocument(out)[0].render(scale=2).to_pil().convert("L")
    prn = pdfium.PdfDocument(out)[0].render(scale=2, optimize_mode="print").to_pil().convert("L")
    assert ImageChops.difference(a, view).getbbox() is None      # xem trên máy: y hệt bản gốc
    assert ImageChops.difference(a, prn).getbbox() is not None   # khi in: dùng lớp ảnh mờ
    assert protect.permissions(out)["layers"]


def test_print_layer_size_reasonable():
    pdf = _contract(10)
    base, _ = protect.protect_pdf(pdf, protect.ProtectOptions(printing="low", lowres_layer=False))
    lay, _ = protect.protect_pdf(pdf, protect.ProtectOptions(printing="low", lowres_dpi=100, grayscale=True))
    assert (len(lay) - len(base)) / 10 < 40_000                  # < 40 KB/trang


def test_print_layer_rotated_pages():
    import pypdfium2 as pdfium
    out, _ = protect.protect_pdf(_contract(1, rotate=90), protect.ProtectOptions(printing="low", lowres_dpi=100))
    prn = pdfium.PdfDocument(out)[0].render(scale=1, optimize_mode="print").to_pil().convert("L")
    ref = pdfium.PdfDocument(_contract(1, rotate=90))[0].render(scale=1).to_pil().convert("L")
    assert prn.size == ref.size
    from PIL import ImageChops, ImageStat
    assert ImageStat.Stat(ImageChops.difference(prn, ref)).mean[0] < 8   # lớp in đúng hướng, khớp nội dung


def test_protect_refuses_signed(ca):
    _, s = _soft_signer(ca)
    signed = signing.sign_pdf(_contract(1), s, signing.SignOptions())
    with pytest.raises(protect.ProtectError):
        protect.protect_pdf(signed, protect.ProtectOptions())


def test_remove_protection():
    out, _ = protect.protect_pdf(_contract(1), protect.ProtectOptions(owner_password="chu"))
    with pytest.raises(protect.ProtectError):
        protect.remove_protection(out, "sai")
    plain = protect.remove_protection(out, "chu")
    assert not PdfDocument(data=plain).encrypted


def test_sign_protected_file_needs_owner(ca):
    _, s = _soft_signer(ca)
    out, _ = protect.protect_pdf(_contract(1), protect.ProtectOptions(printing="low", owner_password="chu123"))
    assert signing.is_encrypted(out)
    with pytest.raises(signing.OwnerPasswordRequired):
        signing.sign_pdf(out, s, signing.SignOptions())
    with pytest.raises(signing.OwnerPasswordRequired):
        signing.sign_pdf(out, s, signing.SignOptions(owner_password="sai"))
    signed = signing.sign_pdf(out, s, signing.SignOptions(rect_pt=(300, 650, 500, 750), appearance_png=_red_png(),
                                                          owner_password="chu123"))
    r = signing.verify_pdf(signed, [ca.asn1()])[0]
    assert r.valid and r.trusted and protect.permissions(signed)["encrypted"]
    assert not protect.permissions(signed)["print_high"]         # quyền giữ nguyên sau khi ký


def test_presets_roundtrip():
    for name, o in protect.PRESETS:
        assert protect.ProtectOptions.from_dict(o.to_dict()) == o
    d = protect.ProtectOptions(open_password="x", owner_password="y").to_dict()
    assert d["open_password"] == "" and d["owner_password"] == ""   # mẫu không lưu mật khẩu


# ------------------------------------------------------------------ luồng ký, ký hàng loạt
def test_flow_fields_two_signers(ca):
    pre = signing.add_signature_fields(_contract(2), [("Bên A", 1, (60, 640, 260, 740)), ("Bên B", 1, (340, 640, 540, 740))])
    flds = signing.empty_fields(pre)
    assert [f.name for f in flds] == ["Bên A", "Bên B"] and flds[1].rect == pytest.approx((340, 640, 540, 740), abs=1)
    _, s = _soft_signer(ca)
    one = signing.sign_pdf(pre, s, signing.SignOptions(field_name="Bên B", appearance_png=_red_png()))
    assert [f.name for f in signing.empty_fields(one)] == ["Bên A"]
    x0, y0, x1, y1 = _red_bbox(one, 1)
    assert x0 >= 335 and x1 <= 545
    two = signing.sign_pdf(one, s, signing.SignOptions(field_name="Bên A", appearance_png=_red_png()))
    reps = signing.verify_pdf(two, [ca.asn1()])
    assert [r.field for r in reps] == ["Bên B", "Bên A"] and all(r.valid and r.trusted for r in reps)
    assert signing.empty_fields(two) == []


def test_sign_many(ca, tmp_path):
    _, s = _soft_signer(ca)
    items = []
    for k in range(4):
        p = tmp_path / f"hd{k}.pdf"
        p.write_bytes(_contract(1))
        items.append((str(p), signing.default_output(str(p)), signing.SignOptions()))
    items.insert(2, (str(tmp_path / "khong_co.pdf"), str(tmp_path / "x.pdf"), signing.SignOptions()))
    seen = []
    res = signing.sign_many(items, s, progress=lambda a, b: seen.append(a))
    assert [e is None for _, e in res] == [True, True, False, True, True] and seen[-1] == 5
    assert signing.verify_pdf((tmp_path / "hd3_da_ky.pdf").read_bytes(), [ca.asn1()])[0].valid


# ------------------------------------------------------------------ nén
def _scan_pdf(pages=3, dpi=300):
    from PIL import Image, ImageDraw
    d = pymupdf.open()
    for k in range(pages):
        img = Image.new("RGB", (int(8.27 * dpi), int(11.69 * dpi)), (245, 243, 238))
        dr = ImageDraw.Draw(img)
        for y in range(200, img.height - 200, 60):
            dr.rectangle((150, y, img.width - 150, y + 18), fill=(40, 40, 40))
        import random
        rnd = random.Random(k)
        px = img.load()
        for _ in range(60000):                       # nhiễu giấy như bản scan thật
            x, y = rnd.randrange(img.width), rnd.randrange(img.height)
            px[x, y] = (200, 200, 195)
        b = io.BytesIO()
        img.save(b, "JPEG", quality=92)
        p = d.new_page(width=595, height=842)
        p.insert_image(p.rect, stream=b.getvalue())
    return d.tobytes()


def test_compress_to_target():
    pdf = _scan_pdf()
    target = len(pdf) // 3
    out, desc = tools.compress_to_size(pdf, target)
    assert len(out) <= target and "dpi" in desc
    d = PdfDocument(data=out)
    assert d.page_count == 3 and d.page_kind(0) == "scan"


def test_compress_keeps_text_pdf():
    pdf = _contract(3)
    out, _ = tools.compress_to_size(pdf, 1000)
    assert PdfDocument(data=out).text(0) == PdfDocument(data=pdf).text(0)


def test_compress_gray_level():
    pdf = _scan_pdf(1)
    out, _ = tools.compress_to_size(pdf, level=3, gray=True)
    assert len(out) < len(pdf) / 2


# ------------------------------------------------------------------ so sánh
def test_compare_detects_changes():
    from app import editing
    a = PdfDocument(data=_contract(3))
    b = PdfDocument(data=_contract(3))
    run = editing.run_at(b, 1, 100, 95)
    editing.replace_run(b, 1, run, "HỢP ĐỒNG KINH TẾ – trang 2 (sửa đổi)")
    editing.add_shape(b, 2, "rect", (300, 700, 400, 760))
    diffs, summary = tools.compare_docs(a, b)
    assert [d.page for d in diffs] == [1, 2] and "2, 3" in summary
    assert any("sửa đổi" in t for t in diffs[0].added)
    assert diffs[1].boxes and not diffs[1].added
    x0, y0, x1, y1 = diffs[1].boxes[0]
    assert x0 <= 300 <= x1 and y0 <= 700 <= y1
    rep = tools.make_compare_report(a, b, diffs, summary)
    assert rep.page_count == 4 and "BÁO CÁO SO SÁNH" in rep.text(0)


def test_compare_identical():
    a, b = PdfDocument(data=_contract(2)), PdfDocument(data=_contract(2))
    diffs, summary = tools.compare_docs(a, b)
    assert diffs == [] and "giống nhau" in summary


# ------------------------------------------------------------------ dấu chữ
@pytest.mark.parametrize("style", ["watermark", "box"])
def test_text_stamp(style):
    d = PdfDocument(data=_contract(2))
    tools.text_stamp(d, [0, 1], "BẢN SAO", style, opacity=0.9)
    assert "BẢN SAO" in d.text(0) and "BẢN SAO" in d.text(1)
    box = _red_bbox(d.to_bytes(), 0)
    assert box
    if style == "box":
        assert box[0] > 595 / 2 and box[3] < 842 / 3            # góc trên phải
    else:
        assert box[0] < 200 and box[2] > 400                    # chéo giữa trang
    d.undo()
    assert "BẢN SAO" not in d.text(0)


# ------------------------------------------------------------------ tạo hàng loạt từ Excel
def _template():
    from .conftest import _FONT
    d = pymupdf.open()
    p = d.new_page()
    tw = pymupdf.TextWriter(p.rect)
    f = _FONT[0] if _FONT else None
    tw.append((72, 100), "GIẤY MỜI", font=f, fontsize=16)
    tw.append((72, 140), "Kính gửi: {{Họ tên}}", font=f, fontsize=12)
    tw.append((72, 160), "Đơn vị: {{Đơn vị}}", font=f, fontsize=12)
    tw.write_text(p)
    return d.tobytes()


def _xlsx(path, rows):
    """Tạo .xlsx tối thiểu (chuẩn OOXML) để kiểm thử bộ đọc."""
    shared = []

    def si(v):
        if v not in shared:
            shared.append(v)
        return shared.index(v)
    sheet_rows = []
    for r, row in enumerate(rows, 1):
        cells = "".join(f'<c r="{chr(65 + c)}{r}" t="s"><v>{si(v)}</v></c>' for c, v in enumerate(row))
        sheet_rows.append(f'<row r="{r}">{cells}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                      '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(sheet_rows)}</sheetData></worksheet>")
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{v}</t></si>" for v in shared) + "</sst>")


def test_read_table_xlsx_and_csv(tmp_path):
    _xlsx(tmp_path / "ds.xlsx", [["Họ tên", "Đơn vị"], ["Nguyễn Văn A", "Phòng Kế toán"], ["Trần Thị Bé", "Ban Giám đốc"]])
    head, rows = tools.read_table(str(tmp_path / "ds.xlsx"))
    assert head == ["Họ tên", "Đơn vị"] and rows[1] == ["Trần Thị Bé", "Ban Giám đốc"]
    (tmp_path / "ds.csv").write_text("Họ tên;Đơn vị\nLê C;Kho\n", encoding="utf-8-sig")
    head, rows = tools.read_table(str(tmp_path / "ds.csv"))
    assert head == ["Họ tên", "Đơn vị"] and rows == [["Lê C", "Kho"]]


def test_batch_from_table(tmp_path):
    tpl = _template()
    assert tools.placeholders(PdfDocument(data=tpl)) == ["Họ tên", "Đơn vị"]
    head = ["Họ tên", "Đơn vị"]
    rows = [["Nguyễn Văn A", "Phòng Kế toán"], ["Trần Thị Bé", "Ban Giám đốc"], ["Nguyễn Văn A", "Kho"]]
    made, warns = tools.batch_from_table(tpl, head, rows, str(tmp_path / "out"), "Họ tên")
    assert len(made) == 3 and not warns
    assert os.path.basename(made[2]) == "Nguyễn Văn A (2).pdf"
    t = PdfDocument(made[1]).text(0)
    assert "Kính gửi: Trần Thị Bé" in t and "{{" not in t


# ------------------------------------------------------------------ lịch sử, sao lưu
def test_history_versions(tmp_path):
    p = tmp_path / "hs.pdf"
    for k in range(3):
        p.write_bytes(_contract(1) + b"%" + str(k).encode())
        tools.keep_version(str(p))
        time.sleep(0.01)
    vers = tools.versions(str(p))
    assert len(vers) == 3 and vers[0]["time"] >= vers[-1]["time"]
    assert tools.keep_version(str(tmp_path / "khong_co.pdf")) is None


def test_history_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "MAX_VERSIONS", 3)
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4 x")
    for _ in range(6):
        tools.keep_version(str(p))
        time.sleep(0.002)
    assert len(tools.versions(str(p))) == 3


def test_backup_restore(tmp_path):
    from app.library import STAMP, Library, data_dir
    lib = Library(os.path.join(data_dir(), "library.pdf"))
    lib.add("Dấu sao lưu", _red_png(), STAMP)
    z = tmp_path / "bk.zip"
    names = tools.backup(str(z), {"theme": "dark", "sign/reason": "Duyệt"})
    assert "library.pdf" in names
    os.remove(lib.path)
    st = tools.restore(str(z))
    assert st["theme"] == "dark" and os.path.exists(lib.path)
    assert Library(lib.path).items[-1].name == "Dấu sao lưu"


# ------------------------------------------------------------------ thư mục tự xử lý
def test_autofolder(tmp_path):
    cfg = autofolder.AutoConfig(folder=str(tmp_path), enabled=True, stamp_text="ĐÃ DUYỆT",
                                protect=protect.PRESETS[2][1].to_dict(), owner_password="chu")
    w = autofolder.Watcher(cfg)
    (tmp_path / "a.pdf").write_bytes(_contract(1))
    old = time.time() - 5
    os.utime(tmp_path / "a.pdf", (old, old))
    assert w.scan() == []                                  # lượt đầu: ghi nhận kích thước (chờ ghi xong)
    out = w.scan()
    assert len(out) == 1 and out[0].endswith(os.path.join("da_xu_ly", "a.pdf"))
    assert protect.permissions(open(out[0], "rb").read())["encrypted"]
    assert "ĐÃ DUYỆT" in PdfDocument(out[0]).text(0)
    assert w.scan() == []                                  # không xử lý lại
    w2 = autofolder.Watcher(cfg)                           # mở lại phần mềm: nhớ file đã xử lý
    assert w2.scan() == [] and w2.scan() == []


def test_autofolder_config_json():
    c = autofolder.AutoConfig(folder="D:/x", enabled=True, compress_mb=5)
    c2 = autofolder.AutoConfig.from_json(c.to_json())
    assert c2 == c and "nén ≤ 5 MB" in c2.summary()
    assert autofolder.AutoConfig.from_json("hỏng") == autofolder.AutoConfig()


# ------------------------------------------------------------------ 6c: bìa, mục lục, số trang
def _tray(tmp_path, sizes=(3, 2, 1)):
    from app import merge
    items = []
    for k, n in enumerate(sizes):
        p = tmp_path / f"Tài liệu {k + 1}.pdf"
        p.write_bytes(_contract(n))
        items.append(merge.TrayItem(str(p), page_count=n))
    return items


def test_cover_toc_numbers(tmp_path):
    import pikepdf
    from app import merge
    items = _tray(tmp_path)
    o = merge.MergeOptions(cover=True, cover_title="HỒ SƠ DỰ THẦU", cover_org="CÔNG TY ABC", toc=True,
                           page_numbers=True, bookmarks=True)
    rows, total, blanks = merge.plan(items, o)
    assert [r.start for r in rows] == [3, 7, 9] and total == 9
    d = merge.merge(items, o)
    assert d.page_count == 9
    assert "HỒ SƠ DỰ THẦU" in d.text(0) and "CÔNG TY ABC" in d.text(0) and "Trang" not in d.text(0)
    toc = d.text(1)
    assert "MỤC LỤC" in toc and "Tài liệu 2" in toc and "7" in toc
    assert "Trang 3 / 9" in d.text(2) and "HỢP ĐỒNG" in d.text(2)
    p = str(tmp_path / "g.pdf")
    d.save(p)
    with pikepdf.open(p) as pk:
        annots = pk.pages[1].Annots
        assert len(annots) == 3
        dest = annots[1].Dest[0]
        assert dest.objgen == pk.pages[6].obj.objgen                 # dòng 2 -> trang 7
        titles = [x.title for x in pk.open_outline().root]
        assert titles[:2] == ["Trang bìa", "Mục lục"] and len(titles) == 5


def test_front_padding_duplex(tmp_path):
    from app import merge
    items = _tray(tmp_path, (2, 2))
    o = merge.MergeOptions(cover=True, toc=False, duplex=True)
    rows, total, _ = merge.plan(items, o)
    assert rows[0].start == 3                                         # bìa + trang trắng -> nội dung trang lẻ
    assert merge.merge(items, o).page_count == total
    o2 = merge.MergeOptions(cover=True, duplex=False)
    assert merge.plan(items, o2)[0][0].start == 2


def test_long_toc_multiple_pages(tmp_path):
    from app import merge
    items = _tray(tmp_path, [1] * 30)
    o = merge.MergeOptions(toc=True, duplex=False)
    d = merge.merge(items, o)
    assert d.page_count == 32 and "30." in d.text(1)
