"""scripts/paperback.py（KDP ペーパーバック用の本文 PDF）のテスト。"""

from __future__ import annotations

import io
import re
import zlib
from pathlib import Path

import pytest

import paperback as pb
from conftest import make_image


# ---------------------------------------------------------------------------
# 寸法
# ---------------------------------------------------------------------------

class TestToInch:
    @pytest.mark.parametrize("value, inches", [
        ("25.4mm", 1.0), ("2.54cm", 1.0), ("0.5in", 0.5), ("72pt", 1.0), ("4q", 1 / 25.4),
        (" 12.7 MM ", 0.5), ("25.4", 1.0), (25.4, 1.0), (0, 0.0), (".5in", 0.5),
    ])
    def test_units(self, value, inches):
        assert pb.to_inch(value, "x") == pytest.approx(inches)

    @pytest.mark.parametrize("value", ["abc", "10px", "-5mm", "", None, "1.2.3mm"])
    def test_invalid(self, value):
        with pytest.raises(pb.PaperbackError, match="paperback.margins.top"):
            pb.to_inch(value, "margins.top")


def test_fmt():
    assert pb.fmt_in(0.375) == "0.3750in"
    assert pb.fmt_mm(1.0) == "25.4mm"


class TestParseTrim:
    @pytest.mark.parametrize("value", ["6x9", "6X9", "6 x 9", "6×9", '6"x9"', "6inx9in", "6x9in"])
    def test_kdp_standard_spellings(self, value):
        warnings = []
        assert pb.parse_trim(value, warnings) == ('6"×9"', 6.0, 9.0)
        assert warnings == []

    def test_all_standard_sizes(self):
        for key, (w, h) in pb.KDP_TRIM_SIZES.items():
            warnings = []
            _, tw, th = pb.parse_trim(key, warnings)
            assert (tw, th) == (w, h)
            assert warnings == []

    @pytest.mark.parametrize("key, mm", [("a5", (148, 210)), ("B6", (128, 182))])
    def test_jis_sizes_are_custom(self, key, mm):
        warnings = []
        label, w, h = pb.parse_trim(key, warnings)
        assert (w * 25.4, h * 25.4) == pytest.approx(mm)
        assert label.startswith(key.upper())
        assert any("カスタムの判型" in x for x in warnings)

    def test_shinsho_is_recognized(self):
        """新書判（103×182mm = 約 4.06×7.17 インチ）は KDP のカスタム判型の範囲内。

        以前は判型名から "in" をすべて取り除いていたため "shinsho" が "shsho" になり、認識されなかった。
        """
        warnings = []
        label, w, h = pb.parse_trim("shinsho", warnings)
        assert (w * 25.4, h * 25.4) == pytest.approx((103, 182))
        assert label.startswith("SHINSHO")

    def test_bunko_is_out_of_range(self):
        # 文庫判は高さ 148mm（約 5.83 インチ）が KDP の最小 6 インチに足りない
        with pytest.raises(pb.PaperbackError, match="範囲外"):
            pb.parse_trim("bunko", [])

    def test_custom_dict(self):
        warnings = []
        label, w, h = pb.parse_trim({"width": "128mm", "height": "182mm"}, warnings)
        assert (w, h) == pytest.approx((128 / 25.4, 182 / 25.4))
        assert label == "128.0mm×182.0mm"
        assert warnings

    @pytest.mark.parametrize("size", [{"width": "3in", "height": "8in"}, {"width": "6in", "height": "12in"},
                                      {"width": "9in", "height": "9in"}])
    def test_custom_out_of_range(self, size):
        with pytest.raises(pb.PaperbackError, match="範囲外"):
            pb.parse_trim(size, [])

    def test_unknown(self):
        with pytest.raises(pb.PaperbackError, match="paperback.trim が分かりません"):
            pb.parse_trim("letter", [])


@pytest.mark.parametrize("pages, gutter", [
    (24, 0.375), (150, 0.375), (151, 0.5), (300, 0.5), (301, 0.625), (500, 0.625),
    (501, 0.75), (700, 0.75), (701, 0.875), (828, 0.875), (2000, 0.875),
])
def test_kdp_min_gutter(pages, gutter):
    assert pb.kdp_min_gutter(pages) == gutter


class TestGeometry:
    def test_without_bleed(self):
        g = pb.Geometry("6x9", 6.0, 9.0, False, 0.5, 0.5, 0.5, 0.4)
        assert (g.page_w, g.page_h) == (6.0, 9.0)
        assert g.gutter_for(100) == 0.4      # 指定のノドが KDP の最小値より広い
        assert g.gutter_for(400) == 0.625    # ページ数が多いと KDP の最小値
        assert g.text_width(0.5) == pytest.approx(5.0)

    def test_with_bleed(self):
        g = pb.Geometry("6x9", 6.0, 9.0, True, 0.5, 0.5, 0.5, 0.4)
        # ノド側には裁ち落としを付けない（幅 + 0.125、高さ + 0.25）
        assert (g.page_w, g.page_h) == (6.125, 9.25)


class TestReadSettings:
    def test_defaults_horizontal(self):
        s = pb.read_settings({}, "horizontal", [])
        g = s["geo"]
        assert g.trim_label.startswith("A5")
        assert not g.bleed
        assert (g.top, g.bottom, g.outside, g.inside) == pytest.approx((18 / 25.4, 20 / 25.4, 15 / 25.4, 18 / 25.4))
        assert s["paper"] == "white"
        assert s["font_size"] == "9.5pt"
        assert s["body_font"] == pb.FONT_STACKS["serif"]
        assert s["heading_font"] == pb.FONT_STACKS["sans"]
        assert s["page_numbers"] and s["running_heads"] and s["colophon"]

    def test_defaults_vertical(self):
        s = pb.read_settings({}, "vertical", [])
        assert s["paper"] == "cream"
        assert s["font_size"] == "9pt"
        assert s["geo"].outside == pytest.approx(16 / 25.4)

    def test_custom_values(self):
        cfg = {"paperback": {"trim": "6x9", "bleed": True, "paper": "color", "font": "My Font", "heading_font": "serif",
                             "margins": {"top": "0.5in", "outside": "12mm"}, "isbn": 9784000000000,
                             "colophon_notes": ["a", 1], "page_numbers": False, "css": ["x.css"]}}
        s = pb.read_settings(cfg, "horizontal", [])
        assert s["geo"].bleed and s["geo"].top == 0.5
        assert s["body_font"].startswith('"My Font", ')
        assert s["heading_font"] == pb.FONT_STACKS["serif"]
        assert s["isbn"] == "9784000000000"
        assert s["notes"] == ["a", "1"]
        assert s["page_numbers"] is False
        assert s["css"] == ["x.css"]

    def test_margin_below_kdp_minimum(self):
        with pytest.raises(pb.PaperbackError, match="margins.outside"):
            pb.read_settings({"paperback": {"margins": {"outside": "5mm"}}}, "horizontal", [])

    def test_bleed_requires_wider_margins(self):
        cfg = {"paperback": {"bleed": True, "margins": {"top": "8mm"}}}  # 0.315in < 0.375in
        with pytest.raises(pb.PaperbackError, match="裁ち落としあり"):
            pb.read_settings(cfg, "horizontal", [])
        # 裁ち落としなしなら 8mm（0.315in）は 0.25in 以上なので通る
        pb.read_settings({"paperback": {"margins": {"top": "8mm"}}}, "horizontal", [])

    def test_inside_margin_is_not_checked_against_outside_minimum(self):
        # ノドはページ数で決まる最小値と比べて広い方を使うので、ここではエラーにしない
        s = pb.read_settings({"paperback": {"margins": {"inside": "3mm"}}}, "horizontal", [])
        assert s["geo"].gutter_for(24) == 0.375

    def test_invalid_paper(self):
        with pytest.raises(pb.PaperbackError, match="paper"):
            pb.read_settings({"paperback": {"paper": "glossy"}}, "horizontal", [])

    def test_not_a_mapping(self):
        with pytest.raises(pb.PaperbackError, match="key: value"):
            pb.read_settings({"paperback": "a5"}, "horizontal", [])


class TestPageCss:
    def css(self, cfg=None, mode="horizontal", gutter=0.5):
        return pb.page_css(pb.read_settings(cfg or {}, mode, []), gutter, mode)

    def test_page_size_and_margins(self):
        css = self.css({"paperback": {"trim": "6x9", "margins": {"top": "0.5in", "bottom": "0.6in", "outside": "0.4in"}}})
        assert "size: 6.0000in 9.0000in;" in css
        assert "marks: none;" in css
        assert "margin-top: 0.5000in;" in css
        assert "margin-bottom: 0.6000in;" in css
        right = re.search(r"@page :right \{(.*?)\n\}", css, re.S).group(1)
        left = re.search(r"@page :left \{(.*?)\n\}", css, re.S).group(1)
        # 右側のページはノドが左、左側のページはノドが右
        assert "margin-left: 0.5000in;" in right and "margin-right: 0.4000in;" in right
        assert "margin-left: 0.4000in;" in left and "margin-right: 0.5000in;" in left
        assert "--pb-text-width: 5.1000in;" in css
        assert "--pb-text-height: 7.9000in;" in css

    def test_bleed_extends_outer_margins_only(self):
        css = self.css({"paperback": {"trim": "6x9", "bleed": True,
                                      "margins": {"top": "0.5in", "bottom": "0.5in", "outside": "0.5in"}}})
        assert "size: 6.1250in 9.2500in;" in css
        assert "margin-top: 0.6250in;" in css
        right = re.search(r"@page :right \{(.*?)\n\}", css, re.S).group(1)
        assert "margin-left: 0.5000in;" in right      # ノドはそのまま
        assert "margin-right: 0.6250in;" in right     # 小口は裁ち落とし分だけ広げる

    def test_page_numbers_and_running_heads(self):
        on = self.css()
        assert "content: counter(page);" in on
        assert "content: string(chapter, first-except);" in on
        off = self.css({"paperback": {"page_numbers": False, "running_heads": False}})
        assert "counter(page)" not in off and "string(chapter" not in off

    def test_vertical_uses_horizontal_margin_boxes(self):
        assert "writing-mode: horizontal-tb;" in self.css(mode="vertical")


# ---------------------------------------------------------------------------
# PDF の簡易解析
# ---------------------------------------------------------------------------

def pillow_pdf(path: Path, pages: int, size_in=(6.0, 9.0)) -> Path:
    from PIL import Image
    dpi = 10
    imgs = [Image.new("RGB", (int(size_in[0] * dpi), int(size_in[1] * dpi)), "white") for _ in range(pages)]
    imgs[0].save(path, "PDF", resolution=dpi, save_all=True, append_images=imgs[1:])
    return path


def handmade_pdf(path: Path, objects: list[bytes], objstm: list[bytes] | None = None) -> Path:
    """ページやフォントの辞書を直接書いた（xref の無い）PDF もどき。inspect_pdf は正規表現で読むので十分。"""
    body = b"%PDF-1.7\n"
    for i, obj in enumerate(objects, 1):
        body += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    if objstm:
        data = zlib.compress(b"\n".join(objstm))
        body += b"99 0 obj\n<< /Type /ObjStm /N %d /First 0 /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (
            len(objstm), len(data), data)
    path.write_bytes(body + b"%%EOF\n")
    return path


class TestInspectPdf:
    def test_pages_and_sizes(self, tmp_path):
        info = pb.inspect_pdf(pillow_pdf(tmp_path / "a.pdf", 3))
        assert info["pages"] == 3
        assert info["sizes"] == {(6.0, 9.0)}
        assert not info["unembedded"]

    def test_fonts_embedded(self, tmp_path):
        p = handmade_pdf(tmp_path / "f.pdf", [
            b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>",
            b"<< /Type /Page /MediaBox [0 0 432 648] >>",
            b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /ABCDEF+NotoSerifCJKjp-Regular >>",
            b"<< /Type /FontDescriptor /FontName /ABCDEF+NotoSerifCJKjp-Regular /FontFile3 9 0 R >>",
        ])
        info = pb.inspect_pdf(p)
        assert info["pages"] == 1
        assert info["sizes"] == {(6.0, 9.0)}
        assert info["fonts"] == ["ABCDEF+NotoSerifCJKjp-Regular"]
        assert info["embedded"] == 1 and not info["unembedded"]

    def test_fonts_not_embedded(self, tmp_path):
        p = handmade_pdf(tmp_path / "f.pdf", [
            b"<< /Type /Page /MediaBox [0 0 432 648] >>",
            b"<< /Type /Font /Subtype /TrueType /BaseFont /Arial >>",
        ])
        assert pb.inspect_pdf(p)["unembedded"]

    def test_object_streams_are_expanded(self, tmp_path):
        p = handmade_pdf(tmp_path / "s.pdf", [b"<< /Type /Catalog >>"], objstm=[
            b"<< /Type /Page /MediaBox [0 0 419.53 595.28] >>",
            b"<< /Type /Page /MediaBox [0 0 419.53 595.28] >>",
            b"<< /Type /FontDescriptor /FontName /XYZ+Font /FontFile2 5 0 R >>",
        ])
        info = pb.inspect_pdf(p)
        assert info["pages"] == 2
        assert info["sizes"] == {(5.827, 8.268)}
        assert info["embedded"] == 1


class TestVerifyPdf:
    geo = pb.Geometry("6x9", 6.0, 9.0, False, 0.5, 0.5, 0.5, 0.5)

    def info(self, **kw):
        return {"pages": 24, "sizes": {(6.0, 9.0)}, "fonts": ["AB+Font"], "embedded": 1, "unembedded": False, **kw}

    def test_ok(self, tmp_path):
        warnings = []
        pb.verify_pdf(tmp_path / "x.pdf", self.info(), self.geo, 0.5, warnings)
        assert warnings == []

    def test_no_pages(self, tmp_path):
        with pytest.raises(pb.PaperbackError, match="ページ数"):
            pb.verify_pdf(tmp_path / "x.pdf", self.info(pages=0), self.geo, 0.5, [])

    def test_wrong_size(self, tmp_path):
        with pytest.raises(pb.PaperbackError, match="ページサイズ"):
            pb.verify_pdf(tmp_path / "x.pdf", self.info(sizes={(6.0, 9.0), (8.5, 11.0)}), self.geo, 0.5, [])

    def test_unembedded_fonts(self, tmp_path):
        with pytest.raises(pb.PaperbackError, match="埋め込まれていません"):
            pb.verify_pdf(tmp_path / "x.pdf", self.info(unembedded=True), self.geo, 0.5, [])

    @pytest.mark.parametrize("pages, word", [(10, "24 ページ以上"), (25, "奇数"), (900, "上限")])
    def test_page_count_warnings(self, tmp_path, pages, word):
        warnings = []
        pb.verify_pdf(tmp_path / "x.pdf", self.info(pages=pages), self.geo, 0.5, warnings)
        assert any(word in w for w in warnings)


@pytest.mark.parametrize("value, text", [
    ("2026-11-01", "2026年11月1日"), ("2026-1-5", "2026年1月5日"), ("2026年秋", "2026年秋"), ("", ""),
])
def test_format_date(value, text):
    assert pb.format_date(value) == text


def test_report_cover(capsys):
    geo = pb.Geometry("6x9", 6.0, 9.0, False, 0.5, 0.5, 0.5, 0.5)
    pb.report_cover(101, geo, "white")
    err = capsys.readouterr().err
    # 102 ページ（偶数に切り上げ）× 0.002252 = 0.2297 インチ、幅 = 0.125 + 6 + 0.2297 + 6 + 0.125
    assert "102 ページ" in err
    assert "背幅 0.230 インチ" in err
    assert "幅 12.480 × 高さ 9.250 インチ" in err
    assert "背表紙に文字は入れられません" not in err
    pb.report_cover(40, geo, "cream")
    assert "背表紙に文字は入れられません" in capsys.readouterr().err


def test_collect_images(tmp_path):
    book = tmp_path / "book"
    make_image(book / "images" / "a.png", (10, 10))
    make_image(book / "images" / "sub" / "b.jpg", (10, 10))
    make_image(book / "dist" / "c.png", (10, 10))
    make_image(book / ".cache" / "d.png", (10, 10))
    (book / "images" / "notes.txt").write_text("x", encoding="utf-8")
    work = tmp_path / "work"
    mapping = pb.collect_images(book, work)
    assert mapping == {"images/a.png": "assets/images/a.png", "images/sub/b.jpg": "assets/images/sub/b.jpg"}
    assert (work / "assets" / "images" / "a.png").exists()


def test_check_image_resolution(tmp_path):
    make_image(tmp_path / "assets" / "low.png", (600, 100))
    make_image(tmp_path / "assets" / "high.png", (2000, 100))
    html = ('<img src="assets/low.png"><img src="assets/high.png"><img src="assets/low.png">'
            '<img src="https://example.com/x.png"><img src="assets/missing.png">')
    warnings = []
    pb.check_image_resolution(html, tmp_path, 5.0, warnings)
    assert len(warnings) == 1
    assert "low.png" in warnings[0] and "約 120dpi" in warnings[0] and "幅 1500px 以上" in warnings[0]


class TestFindVivliostyle:
    def test_env(self, monkeypatch):
        monkeypatch.setenv("VIVLIOSTYLE", "/opt/viv")
        assert pb.find_vivliostyle() == ["/opt/viv"]

    def test_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VIVLIOSTYLE", raising=False)
        monkeypatch.setattr(pb, "ROOT", tmp_path)
        monkeypatch.setattr(pb.shutil, "which", lambda name: None)
        with pytest.raises(pb.PaperbackError, match="npm install"):
            pb.find_vivliostyle()


def test_browser_args(monkeypatch):
    class A:
        browser = None
    monkeypatch.delenv("VIVLIOSTYLE_BROWSER", raising=False)
    assert pb.browser_args(A()) == []
    monkeypatch.setenv("VIVLIOSTYLE_BROWSER", "/usr/bin/chrome")
    assert pb.browser_args(A()) == ["--executable-browser", "/usr/bin/chrome"]
    A.browser = "/x/chromium"
    assert pb.browser_args(A()) == ["--executable-browser", "/x/chromium"]


# ---------------------------------------------------------------------------
# build.py --paperback（エラー処理と実際の組版）
# ---------------------------------------------------------------------------

def test_paperback_invalid_trim_is_build_error(make_book, build_args, require_pandoc):
    import build
    book = make_book({"paperback": {"trim": "postcard"}})
    with pytest.raises(build.BuildError, match="paperback.trim"):
        build.build_book(book, build_args(paperback=True))


def test_paperback_missing_css(make_book, build_args, require_pandoc):
    import build
    book = make_book({"paperback": {"css": ["print-extra.css"]}})
    with pytest.raises(build.BuildError, match="CSS が見つかりません"):
        build.build_book(book, build_args(paperback=True))


@pytest.mark.slow
@pytest.mark.usefixtures("require_vivliostyle", "require_japanese_font")
class TestPaperbackBuild:
    @pytest.mark.parametrize("mode", ["horizontal", "vertical"])
    def test_builds_kdp_compliant_pdf(self, make_book, build_args, tmp_path, mode):
        import build
        book = make_book({"paperback": {"trim": "6x9", "isbn": "978-4-00-000000-0"}, "publisher": "テスト出版",
                          "date": "2026-11-01"})
        out = build.build_book(book, build_args(paperback=True, writing_mode=mode, keep_html=True))
        assert out.name == f"{book.name}-{mode}-paperback.pdf"
        info = pb.inspect_pdf(out)
        assert info["pages"] >= 3
        assert info["sizes"] == {(6.0, 9.0)}
        assert info["embedded"] > 0 and not info["unembedded"]
        work = out.parent / ".paperback" / out.stem
        html = (work / "index.html").read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>|\s", "", html)  # 縦書きでは数字が縦中横の span で囲まれる
        assert "テストの本" in text and "テスト出版" in text and "2026年11月1日" in text
        assert ("tcy" in html) is (mode == "vertical")
        assert "assets/images/figure.png" in html
        css = (work / "page.css").read_text(encoding="utf-8")
        assert "size: 6.0000in 9.0000in;" in css

    def test_bleed_page_size_and_cleanup(self, make_book, build_args, tmp_path):
        import build
        book = make_book({"paperback": {"trim": "6x9", "bleed": True, "output": "custom.pdf"}})
        out = build.build_book(book, build_args(paperback=True))
        assert out.name == "custom.pdf"
        assert pb.inspect_pdf(out)["sizes"] == {(6.125, 9.25)}
        assert not (out.parent / ".paperback" / out.stem).exists()  # --keep-html なしなら作業用 HTML は消す
