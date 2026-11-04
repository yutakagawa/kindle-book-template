"""scripts/cover.py（表紙の自動生成）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageStat

import cover
from conftest import make_image, run_script


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

class TestDesignConfig:
    @pytest.mark.parametrize("cfg, enabled", [
        ({}, False), ({"cover_design": None}, True), ({"cover_design": {}}, True),
        ({"cover_design": True}, True), ({"cover_design": False}, False), ({"cover_design": {"style": "vertical"}}, True),
    ])
    def test_design_enabled(self, cfg, enabled):
        assert cover.design_enabled(cfg) is enabled

    def test_design_of(self):
        assert cover.design_of({}) == {}
        assert cover.design_of({"cover_design": True}) == {}
        d = {"style": "vertical"}
        got = cover.design_of({"cover_design": d})
        assert got == d and got is not d  # 呼び出し側が書き換えても元の設定は変わらない
        with pytest.raises(cover.CoverError, match="形式"):
            cover.design_of({"cover_design": "vertical"})

    @pytest.mark.parametrize("cfg, mode, override, style", [
        ({}, None, None, "horizontal"),
        ({"layout": {"writing_mode": "vertical"}}, None, None, "vertical"),
        ({"layout": {"writing_mode": "vertical"}}, "horizontal", None, "horizontal"),
        ({"cover_design": {"style": "vertical"}}, "horizontal", None, "vertical"),
        ({"cover_design": {"style": "auto"}}, "vertical", None, "vertical"),
        ({"cover_design": {"style": "vertical"}}, None, "horizontal", "horizontal"),
    ])
    def test_resolve_style(self, cfg, mode, override, style):
        assert cover.resolve_style(cfg, mode, override) == style

    def test_texts_from_config(self):
        cfg = {"title": "題名", "subtitle": "副題", "author": [{"name": "甲"}, "乙", {"kana": "ナシ"}]}
        t = cover.texts_from_config(cfg, {})
        assert (t.title, t.subtitle, t.author) == ("題名", "副題", "甲・乙")
        t = cover.texts_from_config(cfg, {"title": "表紙用\n題名", "subtitle": "", "author": "丙", "author_suffix": " 著"})
        assert (t.title, t.subtitle, t.author) == ("表紙用\n題名", "", "丙 著")
        t = cover.texts_from_config({"title": 2026, "author": {"name": "単独"}}, {})
        assert (t.title, t.author) == ("2026", "単独")
        # 著者がいなければ接尾辞も付けない
        assert cover.texts_from_config({"title": "t"}, {"author_suffix": " 著"}).author == ""
        with pytest.raises(cover.CoverError, match="title"):
            cover.texts_from_config({}, {})

    def test_default_output(self, tmp_path):
        assert cover.default_output(Path("books/abc"), {}, tmp_path) == tmp_path / "abc-cover.jpg"
        assert cover.default_output(Path("books/abc"), {"output": "my.epub"}, tmp_path) == tmp_path / "my-cover.jpg"

    def test_load_config(self, tmp_path):
        with pytest.raises(cover.CoverError, match="book.yaml"):
            cover.load_config(tmp_path)
        (tmp_path / "book.yaml").write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(cover.CoverError, match="形式"):
            cover.load_config(tmp_path)


@pytest.mark.parametrize("value, rgb", [
    ("#1d3557", (0x1d, 0x35, 0x57)), ("1d3557", (0x1d, 0x35, 0x57)), ("#fff", (255, 255, 255)),
    ([1, 2, 3], (1, 2, 3)), ((10, 20, 30), (10, 20, 30)),
])
def test_parse_color(value, rgb):
    assert cover.parse_color(value, "colors") == rgb


@pytest.mark.parametrize("value", ["red", "#12345", "#ggg", [1, 2], None])
def test_parse_color_invalid(value):
    with pytest.raises(cover.CoverError, match="accent_color"):
        cover.parse_color(value, "accent_color")


@pytest.mark.parametrize("style, weight", [
    ("Bold", 700), ("Regular", 400), ("W6", 600), ("ExtraLight", 200), ("Semi Bold", 600), ("Black", 900),
    ("Medium", 500), ("Light", 300), ("Oblique", 400), ("Demi-Bold", 600),
])
def test_style_weight(style, weight):
    assert cover.style_weight(style) == weight


# ---------------------------------------------------------------------------
# 禁則処理つきの分割
# ---------------------------------------------------------------------------

def atom_texts(text: str) -> list[str]:
    return [a.text for a in cover.make_atoms(text)]


class TestMakeAtoms:
    def test_cjk_split_per_character(self):
        assert atom_texts("本の題") == ["本", "の", "題"]

    def test_latin_words_are_not_split(self):
        assert atom_texts("Python入門") == ["Python", "入", "門"]
        assert atom_texts("Hello World") == ["Hello", " ", "World"]

    def test_no_start_characters_glue_to_previous(self):
        # 句読点・閉じ括弧・小書き・長音は行頭に来ない
        assert atom_texts("です。") == ["で", "す。"]
        assert atom_texts("コーヒー") == ["コー", "ヒー"]
        assert atom_texts("きょう") == ["きょ", "う"]
        assert atom_texts("「本」") == ["「本」"]

    def test_no_end_characters_glue_to_next(self):
        assert atom_texts("と（注）") == ["と", "（注）"]
        assert atom_texts("『題』の") == ["『題』", "の"]

    def test_newlines(self):
        atoms = cover.make_atoms("上の行\n\n\n下の行\n")
        kinds = [a.kind for a in atoms]
        assert kinds.count("nl") == 1  # 連続する改行・前後の空白はまとめる
        assert atoms[3].kind == "nl"

    def test_tokenize_kinds(self):
        kinds = [(t.text, t.kind) for t in cover.tokenize("ab 字\n　")]
        assert kinds == [("ab", "latin"), (" ", "space"), ("字", "cjk"), ("\n", "nl"), ("　", "space")]


@pytest.mark.parametrize("ch, cls", [
    ("a", "latin"), ("1", "latin"), ("-", "punct"), ("あ", "hira"), ("ア", "kata"), ("ｱ", "kata"),
    ("漢", "kanji"), ("々", "kanji"), ("Ａ", "latin"), ("。", "punct"),
])
def test_char_class(ch, cls):
    assert cover.char_class(ch) == cls


class TestBreakPenalty:
    def pen(self, a: str, b: str) -> float:
        return cover.break_penalty(cover.Atom([cover.Token(a, "cjk")]), cover.Atom([cover.Token(b, "cjk")]))

    def test_order_of_naturalness(self):
        after_particle = self.pen("の", "本")       # 「〜の|本」は自然
        okurigana = self.pen("作", "る")             # 「作|る」は送り仮名の途中
        same_kind = self.pen("自", "動")             # 単語の途中
        assert after_particle < okurigana < same_kind

    def test_punctuation_and_space_are_free(self):
        assert self.pen("本。", "次") == 0.0
        space = cover.Atom([cover.Token(" ", "space")])
        assert cover.break_penalty(space, cover.Atom([cover.Token("字", "cjk")])) == 0.0


@pytest.mark.parametrize("text, tcy", [("12", True), ("1", True), ("123", False), ("!?", True), ("A", True),
                                       ("AB", False), ("", False)])
def test_is_tcy(text, tcy):
    assert cover.is_tcy(text) is tcy


def test_trim():
    sp = cover.Atom([cover.Token(" ", "space")])
    w = cover.Atom([cover.Token("字", "cjk")])
    assert cover.trim([sp, w, sp, w, sp]) == [w, sp, w]
    assert cover.trim([sp, sp]) == []


# ---------------------------------------------------------------------------
# 背景
# ---------------------------------------------------------------------------

class TestGradient:
    def test_single_color(self):
        im = cover.gradient((100, 160), [(10, 20, 30)], "vertical")
        assert im.size == (100, 160)
        assert im.getextrema() == ((10, 10), (20, 20), (30, 30))

    @pytest.mark.parametrize("direction, a, b", [
        ("vertical", (50, 2), (50, 157)),
        ("horizontal", (2, 80), (97, 80)),
        ("diagonal", (2, 2), (97, 157)),
    ])
    def test_two_colors(self, direction, a, b):
        im = cover.gradient((100, 160), [(0, 0, 0), (255, 255, 255)], direction)
        assert im.getpixel(a)[0] < 40 and im.getpixel(b)[0] > 215

    def test_radial_center_is_first_color(self):
        im = cover.gradient((100, 160), [(0, 0, 0), (255, 255, 255)], "radial")
        assert im.getpixel((50, 64))[0] < im.getpixel((0, 159))[0]


def test_load_background_fits_and_warns_when_upscaled(tmp_path):
    src = make_image(tmp_path / "bg.png", (400, 400))
    warnings = []
    im = cover.load_background(src, (160, 256), (0.5, 0.5), warnings)
    assert im.size == (160, 256) and im.mode == "RGB"
    assert warnings == []
    cover.load_background(src, (1600, 2560), (0.5, 0.5), warnings)
    assert any("拡大" in w for w in warnings)


def test_load_background_transparent_on_white(tmp_path):
    src = tmp_path / "bg.png"
    Image.new("RGBA", (200, 320), (0, 0, 0, 0)).save(src)
    im = cover.load_background(src, (200, 320), (0.5, 0.5), [])
    assert im.getpixel((10, 10)) == (255, 255, 255)


def test_load_background_unreadable(tmp_path):
    src = tmp_path / "bg.jpg"
    src.write_bytes(b"not an image")
    with pytest.raises(cover.CoverError, match="背景画像を開けません"):
        cover.load_background(src, (100, 160), (0.5, 0.5), [])


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

class TestSaveCover:
    def test_jpeg(self, tmp_path):
        out = cover.save_cover(Image.new("RGB", (160, 256), "navy"), tmp_path / "sub" / "c.jpg")
        with Image.open(out) as im:
            assert im.format == "JPEG" and im.mode == "RGB"
            assert round(im.info["dpi"][0]) == cover.COVER_DPI
            assert im.info.get("icc_profile")  # sRGB プロファイル

    def test_tiff(self, tmp_path):
        out = cover.save_cover(Image.new("RGB", (160, 256), "navy"), tmp_path / "c.tif")
        with Image.open(out) as im:
            assert im.format == "TIFF"

    def test_other_extension(self, tmp_path):
        with pytest.raises(cover.CoverError, match="JPEG"):
            cover.save_cover(Image.new("RGB", (16, 16)), tmp_path / "c.png")


# ---------------------------------------------------------------------------
# フォント
# ---------------------------------------------------------------------------

class TestResolveFont:
    def test_file_path_relative_to_book(self, tmp_path):
        font = tmp_path / "fonts" / "my.otf"
        font.parent.mkdir()
        font.write_bytes(b"")
        spec = cover.resolve_font("fonts/my.otf", 700, tmp_path, [])
        assert spec == cover.FontSpec(str(font), 0)
        spec = cover.resolve_font({"path": "fonts/my.otf", "index": 2}, 700, tmp_path, [])
        assert spec.index == 2 and spec.label() == "my.otf#2"

    def test_missing_file(self, tmp_path):
        with pytest.raises(cover.CoverError, match="フォントが見つかりません"):
            cover.resolve_font("fonts/none.otf", 700, tmp_path, [])

    def test_no_japanese_font_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cover, "find_font", lambda kind, weight: None)
        with pytest.raises(cover.CoverError, match="日本語フォントが見つかりません"):
            cover.resolve_font("serif", 700, tmp_path, [])

    def test_falls_back_to_other_kind(self, tmp_path, monkeypatch):
        spec = cover.FontSpec("/fonts/gothic.ttc")
        monkeypatch.setattr(cover, "find_font", lambda kind, weight: spec if kind == "sans" else None)
        warnings = []
        assert cover.resolve_font("mincho", 700, tmp_path, warnings) == spec
        assert any("明朝体" in w for w in warnings)

    def test_find_font_prefers_family_order_and_weight(self, monkeypatch):
        monkeypatch.setattr(cover, "_FC_CACHE", [
            ("/f/ipa.ttf", 0, ["IPAexMincho"], "Regular"),
            ("/f/noto.ttc", 0, ["Noto Serif CJK JP"], "Regular"),
            ("/f/noto.ttc", 4, ["Noto Serif CJK JP"], "Bold"),
            ("/f/noto.ttc", 6, ["Noto Serif CJK JP", "Noto Serif CJK JP Black"], "Black"),
        ])
        assert cover.find_font("serif", 700) == cover.FontSpec("/f/noto.ttc", 4)
        assert cover.find_font("serif", 400) == cover.FontSpec("/f/noto.ttc", 0)
        monkeypatch.setattr(cover, "FONT_PATHS", {"serif": [], "sans": []})
        assert cover.find_font("sans", 400) is None


# ---------------------------------------------------------------------------
# 表紙の生成（日本語フォントが必要）
# ---------------------------------------------------------------------------

CFG = {"title": "テストの本", "subtitle": "副題もあります", "author": [{"name": "試験 太郎"}]}


@pytest.mark.usefixtures("require_japanese_font")
class TestRenderCover:
    @pytest.mark.parametrize("style", ["horizontal", "vertical"])
    def test_kdp_size_and_text_drawn(self, tmp_path, style):
        warnings = []
        im = cover.render_cover(CFG, tmp_path, style, warnings, {"colors": ["#336699"]})
        assert im.size == (cover.COVER_WIDTH, cover.COVER_HEIGHT) and im.mode == "RGB"
        # 単色の背景の上に文字が描かれている（背景色以外の画素がある）
        assert len(im.getcolors(1 << 24)) > 10

    def test_auto_text_color(self, tmp_path):
        dark = cover.render_cover(CFG, tmp_path, "horizontal", [], {"colors": ["#000000"], "decoration": False})
        light = cover.render_cover(CFG, tmp_path, "horizontal", [], {"colors": ["#ffffff"], "decoration": False})
        # 暗い背景には白い文字、明るい背景には黒い文字
        assert dark.convert("L").getextrema()[1] > 200
        assert light.convert("L").getextrema()[0] < 60

    def test_explicit_text_color(self, tmp_path):
        im = cover.render_cover(CFG, tmp_path, "horizontal", [],
                                {"colors": ["#000000"], "text_color": "#ff0000", "decoration": False})
        r, g, b = im.split()
        assert r.getextrema()[1] > 200 and g.getextrema()[1] < 60

    def test_custom_size_and_ratio_warning(self, tmp_path):
        warnings = []
        im = cover.render_cover(CFG, tmp_path, "horizontal", warnings, {"width": 1000, "height": 1500})
        assert im.size == (1000, 1500)
        assert any("1.6:1" in w for w in warnings)

    @pytest.mark.parametrize("size", [{"width": 500, "height": 800}, {"width": 1600, "height": 12000}])
    def test_invalid_size(self, tmp_path, size):
        with pytest.raises(cover.CoverError, match="表紙のサイズ"):
            cover.render_cover(CFG, tmp_path, "horizontal", [], size)

    def test_invalid_options(self, tmp_path):
        with pytest.raises(cover.CoverError, match="style"):
            cover.render_cover(CFG, tmp_path, "diagonal", [], {})
        with pytest.raises(cover.CoverError, match="gradient"):
            cover.render_cover(CFG, tmp_path, "horizontal", [], {"gradient": "spiral"})
        with pytest.raises(cover.CoverError, match="colors"):
            cover.render_cover(CFG, tmp_path, "horizontal", [], {"colors": []})
        with pytest.raises(cover.CoverError, match="背景画像が見つかりません"):
            cover.render_cover(CFG, tmp_path, "horizontal", [], {"background": "none.jpg"})

    def test_background_image_with_overlay(self, tmp_path):
        make_image(tmp_path / "bg.jpg", (1600, 2560), color=(250, 250, 250))
        im = cover.render_cover(CFG, tmp_path, "vertical", [], {"background": "bg.jpg", "overlay": 0.5,
                                                                "decoration": False})
        # 白い背景に 50% の黒を重ねるので、隅は灰色になる
        corner = im.getpixel((5, 5))
        assert 100 < corner[0] < 160

    def test_long_title_shrinks_or_warns(self, tmp_path):
        warnings = []
        cfg = {**CFG, "title": "長い題名の本" * 10}
        im = cover.render_cover(cfg, tmp_path, "horizontal", warnings, {})
        assert im.size == (1600, 2560)
        assert any("小さくしました" in w for w in warnings)

    def test_too_long_title(self, tmp_path):
        fonts = cover.Fonts(cover.resolve_font("sans", 700, tmp_path, []))
        el = cover.Element("長" * 30, fonts, False, 100, 50, 1, 1.3)
        with pytest.raises(cover.CoverError, match="タイトルが長すぎて"):
            cover.fit(el, 100, 50, "タイトル", [])

    def test_fit_respects_box_and_explicit_newlines(self, tmp_path):
        fonts = cover.Fonts(cover.resolve_font("sans", 700, tmp_path, []))
        el = cover.Element("Markdownで作る\nKindle技術書", fonts, False, 190, 96, 4, 1.28)
        lay = cover.fit(el, 1300, 900, "タイトル", [])
        assert lay.count == 2
        assert ["".join(a.text for a in line) for line in lay.lines] == ["Markdownで作る", "Kindle技術書"]
        assert max(lay.widths) <= 1300
        assert lay.size * (1 + (lay.count - 1) * el.pitch) <= 900
        assert cover.fit(cover.Element("  ", fonts, False, 100, 50, 2, 1.3), 1000, 500, "副題", []) is None

    def test_fit_avoids_breaking_inside_latin_words(self, tmp_path):
        fonts = cover.Fonts(cover.resolve_font("sans", 700, tmp_path, []))
        el = cover.Element("はじめてのPythonプログラミング", fonts, False, 190, 96, 3, 1.28)
        lay = cover.fit(el, 1300, 900, "タイトル", [])
        for line in lay.lines:
            text = "".join(a.text for a in line)
            assert not text.startswith(("ython", "thon")) and not text.endswith(("Pyt", "Py"))

    def test_generate_book_cover_prefers_design_over_cover(self, tmp_path):
        warnings = []
        cfg = {**CFG, "cover": "images/cover.jpg", "cover_design": {"style": "vertical"}}
        out = cover.generate_book_cover(tmp_path, cfg, tmp_path / "out.jpg", "horizontal", warnings)
        assert out.exists()
        assert any("cover_design があるため" in w for w in warnings)
        with Image.open(out) as im:
            assert im.size == (1600, 2560)
            # 縦書きの既定デザインは明るい背景
            assert ImageStat.Stat(im.convert("L")).mean[0] > 150

    def test_cli(self, make_book, tmp_path):
        book = make_book({"cover_design": {}}, name="cli-book")
        r = run_script("cover.py", str(book), "--output-dir", str(tmp_path / "out"), "--style", "vertical")
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "out" / "cli-book-cover.jpg").exists()
        r = run_script("cover.py", str(book), "-o", str(tmp_path / "x.tif"))
        assert r.returncode == 0, r.stderr
        with Image.open(tmp_path / "x.tif") as im:
            assert im.format == "TIFF" and im.size == (1600, 2560)


def test_cli_errors(tmp_path):
    assert run_script("cover.py").returncode == 2
    r = run_script("cover.py", str(tmp_path / "nothing"))
    assert r.returncode == 1 and "book.yaml がありません" in r.stderr
    r = run_script("cover.py", "--all", "-o", str(tmp_path / "x.jpg"))
    assert r.returncode == 2 and "-o" in r.stderr
