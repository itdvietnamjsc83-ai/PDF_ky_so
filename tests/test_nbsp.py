"""1.0.17 – file có "khoảng trắng cứng" U+00A0 thay cho dấu cách (Times New Roman trên Windows, Word gõ dấu cách
không ngắt dòng...): đọc chữ, tìm, tìm & thay vẫn khớp khi gõ dấu cách thường."""
import io

import pymupdf
import pytest
from fontTools.ttLib import TTFont

from app import editing, fonts
from app.document import PdfDocument


def _nbsp_pdf():
    f = TTFont(fonts.system_font("serif"))
    for t in f["cmap"].tables:
        if hasattr(t, "cmap") and 0x20 in t.cmap:
            t.cmap[0xA0] = t.cmap[0x20]
    b = io.BytesIO()
    f.save(b)
    font = pymupdf.Font(fontbuffer=b.getvalue())
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)
    tw = pymupdf.TextWriter(p.rect)
    tw.append((72, 100), "Hợp đồng mua bán số 12", font=font, fontsize=12)
    tw.write_text(p)
    return PdfDocument(data=doc.tobytes())


def test_nbsp_text_find_replace():
    d = _nbsp_pdf()
    raw = d.page(0).get_textpage().get_text_range()
    if " " not in raw:
        pytest.skip("PyMuPDF không ghi được khoảng trắng cứng với phông này")
    assert "Hợp đồng mua bán" in d.text(0)
    assert d.pages_with_text("đồng mua") == [0]
    hits = editing.find_hits(d, "Hợp đồng")
    assert len(hits) == 1 and hits[0].replaceable
    done, _ = editing.find_replace(d, "mua bán", "thuê")
    assert done == 1 and "Hợp đồng thuê" in d.text(0)


def test_subset_font_has_no_nbsp_alias():
    data = fonts.subset(fonts.system_font("serif"), "Hợp đồng")
    f = TTFont(io.BytesIO(data))
    cmap = f.getBestCmap()
    assert 0x20 in cmap and 0xA0 not in cmap
