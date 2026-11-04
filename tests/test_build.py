"""scripts/build.py（EPUB のビルド）のテスト。"""

from __future__ import annotations

import io
import json
import re
import stat
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

import build
from conftest import ROOT, make_image, run_script


# ---------------------------------------------------------------------------
# 設定の読み込み・正規化
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_missing_book_yaml(self, tmp_path):
        with pytest.raises(build.BuildError, match="book.yaml"):
            build.load_config(tmp_path)

    def test_empty_file_is_empty_dict(self, tmp_path):
        (tmp_path / "book.yaml").write_text("", encoding="utf-8")
        assert build.load_config(tmp_path) == {}

    def test_not_a_mapping(self, tmp_path):
        (tmp_path / "book.yaml").write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(build.BuildError, match="形式"):
            build.load_config(tmp_path)


@pytest.mark.parametrize("value, expected", [(None, []), ("a", ["a"]), (["a", "b"], ["a", "b"])])
def test_as_list(value, expected):
    assert build.as_list(value) == expected


class TestNormalizePeople:
    def test_string_and_dict(self):
        people = build.normalize_people(["山田 太郎", {"name": "鈴木", "kana": "スズキ", "role": "ill"}], "aut")
        assert people == [
            {"text": "山田 太郎", "role": "aut"},
            {"text": "鈴木", "role": "ill", "file-as": "スズキ"},
        ]

    def test_single_value_and_empty_names(self):
        assert build.normalize_people("著者", "aut") == [{"text": "著者", "role": "aut"}]
        assert build.normalize_people([{"name": ""}, {"kana": "ナシ"}], "ctb") == []
        assert build.normalize_people(None, "aut") == []


class TestNormalizeIsbn:
    @pytest.mark.parametrize("raw, expected", [
        ("978-4-00-000000-0", "9784000000000"),
        ("4-00-000000-x", "400000000X"),
        ("978 4 00 000000 0", "9784000000000"),
    ])
    def test_valid(self, raw, expected):
        assert build.normalize_isbn(raw) == expected

    @pytest.mark.parametrize("raw", ["123", "978-4-00-000000-00"])
    def test_invalid_length(self, raw):
        with pytest.raises(build.BuildError, match="ISBN"):
            build.normalize_isbn(raw)


# ---------------------------------------------------------------------------
# メタデータ
# ---------------------------------------------------------------------------

BASE_CFG = {"title": "本", "author": "著者", "uuid": "12345678-1234-5678-1234-567812345678"}


def meta_for(cfg: dict, tmp_path: Path, mode: str = "horizontal", warnings: list | None = None) -> dict:
    return build.build_metadata(cfg, tmp_path, mode, warnings if warnings is not None else [])


class TestBuildMetadata:
    def test_requires_title_and_author(self, tmp_path):
        with pytest.raises(build.BuildError, match="title"):
            meta_for({"author": "a"}, tmp_path)
        with pytest.raises(build.BuildError, match="author"):
            meta_for({"title": "t"}, tmp_path)

    def test_basic_fields(self, tmp_path):
        cfg = {**BASE_CFG, "title_kana": "ホン", "subtitle": "副題", "publisher": " 出版社 ",
               "date": "2026-11-01", "keywords": ["a", 1], "contributors": [{"name": "協力", "role": "edt"}]}
        meta = meta_for(cfg, tmp_path)
        assert meta["title"] == [{"type": "main", "text": "本", "file-as": "ホン"},
                                 {"type": "subtitle", "text": "副題"}]
        assert meta["creator"] == [{"text": "著者", "role": "aut"}, {"text": "協力", "role": "edt"}]
        assert meta["identifier"] == [{"scheme": "UUID", "text": "urn:uuid:12345678-1234-5678-1234-567812345678"}]
        assert meta["publisher"] == "出版社"
        assert meta["date"] == "2026-11-01"
        assert meta["subject"] == ["a", "1"]
        assert meta["lang"] == "ja"
        assert meta["toc-title"] == "目次"
        # 扉ページで重複しないよう、pandoc の author / subtitle は設定しない
        assert "author" not in meta and "subtitle" not in meta

    @pytest.mark.parametrize("mode, direction", [("vertical", "rtl"), ("horizontal", "ltr")])
    def test_page_progression(self, tmp_path, mode, direction):
        meta = meta_for(BASE_CFG, tmp_path, mode)
        assert meta["page-progression-direction"] == direction
        assert meta["kbt"]["writing_mode"] == mode

    def test_isbn_identifier(self, tmp_path):
        meta = meta_for({**BASE_CFG, "isbn": "978-4-00-000000-0"}, tmp_path)
        assert meta["identifier"] == [{"scheme": "ISBN-13", "text": "urn:isbn:9784000000000"}]
        meta = meta_for({**BASE_CFG, "isbn": "4-00-000000-X"}, tmp_path)
        assert meta["identifier"][0]["scheme"] == "ISBN-10"

    def test_missing_uuid_is_deterministic_and_warns(self, tmp_path):
        cfg = {"title": "本", "author": "著者"}
        w1, w2 = [], []
        m1, m2 = meta_for(cfg, tmp_path, warnings=w1), meta_for(cfg, tmp_path, warnings=w2)
        assert m1["identifier"] == m2["identifier"]
        expected = uuid.uuid5(uuid.NAMESPACE_URL, "kindle-book-template:本/著者")
        assert m1["identifier"][0]["text"] == f"urn:uuid:{expected}"
        assert any("uuid" in w for w in w1)
        # タイトルが違えば別の UUID
        other = meta_for({"title": "別の本", "author": "著者"}, tmp_path)
        assert other["identifier"] != m1["identifier"]

    def test_uuid_is_normalized(self, tmp_path):
        meta = meta_for({**BASE_CFG, "uuid": "{12345678123456781234567812345678}"}, tmp_path)
        assert meta["identifier"][0]["text"] == "urn:uuid:12345678-1234-5678-1234-567812345678"

    def test_invalid_uuid(self, tmp_path):
        with pytest.raises(build.BuildError, match="uuid"):
            meta_for({**BASE_CFG, "uuid": "not-a-uuid"}, tmp_path)

    def test_layout_options_passed_to_filters(self, tmp_path):
        cfg = {**BASE_CFG, "layout": {"number_chapters": False, "chapter_label": "Chapter {n}", "toc_title": "Contents",
                                      "vertical": {"code_blocks": "horizontal", "tables": "vertical", "tcy_digits": 3}}}
        meta = meta_for(cfg, tmp_path, "vertical")
        kbt = meta["kbt"]
        assert kbt["number_chapters"] is False
        assert kbt["chapter_label"] == "Chapter {n}"
        assert kbt["vertical_code"] == "horizontal"
        assert kbt["vertical_table"] == "vertical"
        assert kbt["tcy_digits"] == "3"
        assert meta["toc-title"] == "Contents"

    @pytest.mark.parametrize("key", ["code_blocks", "tables"])
    def test_invalid_vertical_mode(self, tmp_path, key):
        with pytest.raises(build.BuildError, match=key):
            meta_for({**BASE_CFG, "layout": {"vertical": {key: "rotated"}}}, tmp_path)

    def test_cover(self, tmp_path):
        warnings = []
        meta_for(BASE_CFG, tmp_path, warnings=warnings)
        assert any("cover が未設定" in w for w in warnings)

        with pytest.raises(build.BuildError, match="表紙画像が見つかりません"):
            meta_for({**BASE_CFG, "cover": "images/none.jpg"}, tmp_path)

        make_image(tmp_path / "images" / "cover.jpg", (1600, 2560))
        warnings = []
        meta = meta_for({**BASE_CFG, "cover": "images/cover.jpg"}, tmp_path, warnings=warnings)
        assert meta["cover-image"] == str((tmp_path / "images" / "cover.jpg").resolve())
        assert warnings == []


class TestCheckCover:
    def test_good_cover(self, tmp_path):
        warnings = []
        build.check_cover(make_image(tmp_path / "c.jpg", (1600, 2560)), warnings)
        assert warnings == []

    def test_too_small(self, tmp_path):
        warnings = []
        build.check_cover(make_image(tmp_path / "c.jpg", (500, 800)), warnings)
        assert any("小さすぎます" in w for w in warnings)

    def test_wrong_ratio(self, tmp_path):
        warnings = []
        build.check_cover(make_image(tmp_path / "c.jpg", (1600, 1600)), warnings)
        assert any("縦横比" in w for w in warnings)

    def test_format_and_mode(self, tmp_path):
        warnings = []
        build.check_cover(make_image(tmp_path / "c.gif", (1600, 2560), fmt="GIF"), warnings)
        assert any("JPEG を推奨" in w for w in warnings)
        assert any("カラーモード" in w for w in warnings)  # GIF はパレット（P）


# ---------------------------------------------------------------------------
# pandoc のバージョン判定
# ---------------------------------------------------------------------------

def fake_pandoc(tmp_path: Path, version_line: str) -> str:
    script = tmp_path / "fake-pandoc"
    script.write_text(f"#!{sys.executable}\nprint({version_line!r})\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.skipif(sys.platform == "win32", reason="シェバン付きのスクリプトを使う")
class TestPandocVersion:
    def test_parses_version(self, tmp_path):
        assert build.pandoc_version(fake_pandoc(tmp_path, "pandoc 3.9")) == (3, 9)
        assert build.pandoc_version(fake_pandoc(tmp_path, "pandoc.exe 3.1.13")) == (3, 1, 13)

    def test_too_old(self, tmp_path):
        with pytest.raises(build.BuildError, match="以上が必要"):
            build.pandoc_version(fake_pandoc(tmp_path, "pandoc 2.19.2"))

    def test_unparsable(self, tmp_path):
        with pytest.raises(build.BuildError, match="判定できません"):
            build.pandoc_version(fake_pandoc(tmp_path, "something else"))

    def test_missing(self, tmp_path):
        with pytest.raises(build.BuildError, match="見つかりません"):
            build.pandoc_version(str(tmp_path / "no-such-pandoc"))


def test_pandoc_common_args_highlight_flag(tmp_path):
    new = build.pandoc_common_args("pandoc", (3, 8), tmp_path, {})
    old = build.pandoc_common_args("pandoc", (3, 1, 3), tmp_path, {"toc_depth": 3})
    assert any(a.startswith("--syntax-highlighting=") for a in new)
    assert any(a.startswith("--highlight-style=") for a in old)
    assert old[old.index("--toc-depth") + 1] == "3"
    # 既定の配色は styles/kindle.theme
    assert f"--syntax-highlighting={build.STYLES / 'kindle.theme'}" in new
    # 本のディレクトリにある .theme を優先する
    (tmp_path / "my.theme").write_text("{}", encoding="utf-8")
    args = build.pandoc_common_args("pandoc", (3, 9), tmp_path, {"highlight_style": "my.theme"})
    assert f"--syntax-highlighting={tmp_path / 'my.theme'}" in args
    # 名前（tango など）はそのまま
    args = build.pandoc_common_args("pandoc", (3, 9), tmp_path, {"highlight_style": "tango"})
    assert "--syntax-highlighting=tango" in args


# ---------------------------------------------------------------------------
# EPUB の後処理
# ---------------------------------------------------------------------------

NAV = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
<nav epub:type="toc" id="toc">
  <ol>
    <li><a href="text/ch001.xhtml#sec">第1章</a></li>
    <li><a href="text/ch002.xhtml">第2章</a></li>
  </ol>
</nav>
<nav epub:type="landmarks" id="landmarks" hidden="hidden">
  <ol>
    <li>
      <a href="text/title_page.xhtml" epub:type="titlepage">Title Page</a>
    </li>
  </ol>
</nav>
</body>
</html>
"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>本</dc:title>
  </metadata>
</package>
"""


class TestBodymatterLandmark:
    def test_adds_first_chapter(self):
        out = build.add_bodymatter_landmark(NAV)
        assert out.count('epub:type="bodymatter"') == 1
        m = re.search(r'<a href="([^"]+)" epub:type="bodymatter">', out)
        assert m and m.group(1) == "text/ch001.xhtml"
        # 既存の landmarks の項目より前に入る
        assert out.index("bodymatter") < out.index("titlepage")

    def test_idempotent(self):
        once = build.add_bodymatter_landmark(NAV)
        assert build.add_bodymatter_landmark(once) == once

    def test_without_toc_or_landmarks(self):
        assert build.add_bodymatter_landmark("<html></html>") == "<html></html>"
        no_landmarks = NAV.split('<nav epub:type="landmarks"')[0]
        assert "bodymatter" not in build.add_bodymatter_landmark(no_landmarks)


def make_fake_epub(path: Path, mimetype_first: bool = False) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if mimetype_first:
            z.writestr("mimetype", "application/epub+zip")
        z.writestr("EPUB/content.opf", OPF)
        z.writestr("EPUB/nav.xhtml", NAV)
        z.writestr("EPUB/text/ch001.xhtml", "<html/>")
        if not mimetype_first:
            z.writestr("mimetype", "application/epub+zip")
    return path


class TestPostprocess:
    @pytest.mark.parametrize("mode, pwm", [("vertical", "vertical-rl"), ("horizontal", "horizontal-lr")])
    def test_postprocess(self, tmp_path, mode, pwm):
        epub = make_fake_epub(tmp_path / "book.epub")
        build.postprocess(epub, mode)
        with zipfile.ZipFile(epub) as z:
            infos = z.infolist()
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            assert z.read("mimetype") == b"application/epub+zip"
            assert sorted(z.namelist()) == sorted(["mimetype", "EPUB/content.opf", "EPUB/nav.xhtml", "EPUB/text/ch001.xhtml"])
            opf = z.read("EPUB/content.opf").decode()
            assert f'<meta name="primary-writing-mode" content="{pwm}" />' in opf
            assert 'epub:type="bodymatter"' in z.read("EPUB/nav.xhtml").decode()
        assert not epub.with_suffix(".tmp").exists()

    def test_postprocess_twice_does_not_duplicate(self, tmp_path):
        epub = make_fake_epub(tmp_path / "book.epub", mimetype_first=True)
        build.postprocess(epub, "vertical")
        build.postprocess(epub, "vertical")
        with zipfile.ZipFile(epub) as z:
            assert z.read("EPUB/content.opf").decode().count("primary-writing-mode") == 1
            assert z.read("EPUB/nav.xhtml").decode().count("bodymatter") == 1


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def test_main_without_books_prints_help(capsys):
    assert build.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_main_reports_errors_and_continues(tmp_path, make_book, capsys):
    bad = tmp_path / "no-book"
    bad.mkdir()
    assert build.main(["-o", str(tmp_path / "dist"), str(bad)]) == 1
    assert "book.yaml がありません" in capsys.readouterr().err


class TestBuildBookErrors:
    def test_no_chapters(self, make_book, build_args):
        book = make_book(chapters={})
        with pytest.raises(build.BuildError, match="原稿"):
            build.build_book(book, build_args())

    def test_missing_chapter(self, make_book, build_args):
        book = make_book({"chapters": ["chapters/01-intro.md", "chapters/99-none.md"]})
        with pytest.raises(build.BuildError, match="99-none.md"):
            build.build_book(book, build_args())

    def test_invalid_writing_mode(self, make_book, build_args):
        book = make_book({"layout": {"writing_mode": "diagonal"}})
        with pytest.raises(build.BuildError, match="writing_mode"):
            build.build_book(book, build_args())

    def test_missing_css(self, make_book, build_args, require_pandoc):
        book = make_book({"css": ["custom.css"]})
        with pytest.raises(build.BuildError, match="CSS が見つかりません"):
            build.build_book(book, build_args())


# ---------------------------------------------------------------------------
# 実際に pandoc でビルドする
# ---------------------------------------------------------------------------

def read_epub(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        assert z.infolist()[0].filename == "mimetype"
        assert z.infolist()[0].compress_type == zipfile.ZIP_STORED
        return {n: z.read(n) for n in z.namelist()}


def opf_of(files: dict[str, bytes]) -> str:
    return next(v.decode() for k, v in files.items() if k.endswith(".opf"))


def xhtml_text(files: dict[str, bytes]) -> str:
    return "\n".join(v.decode() for k, v in files.items() if k.endswith(".xhtml"))


@pytest.mark.usefixtures("require_pandoc")
class TestBuildWithPandoc:
    def test_horizontal_book(self, make_book, build_args, tmp_path):
        book = make_book({"cover": "images/cover.jpg"},
                         images={"images/figure.png": (800, 400), "images/cover.jpg": (1600, 2560)})
        out = build.build_book(book, build_args())
        assert out == (tmp_path / "dist" / f"{book.name}.epub").resolve()
        files = read_epub(out)
        opf = opf_of(files)
        assert "<dc:title" in opf and "テストの本" in opf
        assert 'content="horizontal-lr"' in opf
        assert "urn:uuid:12345678-1234-5678-1234-567812345678" in opf
        assert 'properties="cover-image"' in opf
        assert 'page-progression-direction="ltr"' in opf
        nav = next(v.decode() for k, v in files.items() if k.endswith("nav.xhtml"))
        assert 'epub:type="bodymatter"' in nav
        body = xhtml_text(files)
        # crossref.lua: 章番号と図番号、相互参照
        assert "第1章" in body and "図1.1" in body
        # 画像は最適化された版が入る（キャッシュに manifest ができる）
        assert (tmp_path / "dist" / ".image-cache" / book.name / "manifest.json").exists()
        assert any(k.endswith(".png") for k in files)

    def test_vertical_override_changes_name_and_direction(self, make_book, build_args, tmp_path):
        book = make_book()
        out = build.build_book(book, build_args(writing_mode="vertical"))
        assert out.name == f"{book.name}-vertical.epub"
        opf = opf_of(read_epub(out))
        assert 'content="vertical-rl"' in opf
        assert 'page-progression-direction="rtl"' in opf

    def test_output_name_from_config(self, make_book, build_args, tmp_path):
        book = make_book({"output": "custom-name.epub"})
        out = build.build_book(book, build_args(writing_mode="vertical"))
        assert out.name == "custom-name.epub"

    def test_chapters_default_to_sorted_glob(self, make_book, build_args):
        book = make_book(chapters={"chapters/b.md": "# 後の章\n\n本文。\n", "chapters/a.md": "# 先の章\n\n本文。\n"},
                         images={})
        files = read_epub(build.build_book(book, build_args()))
        body = xhtml_text(files)
        assert body.index("先の章") < body.index("後の章")

    def test_no_optimize_images(self, make_book, build_args, tmp_path):
        book = make_book()
        build.build_book(book, build_args(no_optimize_images=True))
        assert not (tmp_path / "dist" / ".image-cache").exists()

    def test_images_optimize_false_in_config(self, make_book, build_args, tmp_path):
        book = make_book({"images": {"optimize": False}})
        build.build_book(book, build_args())
        assert not (tmp_path / "dist" / ".image-cache").exists()

    def test_extra_css_is_included(self, make_book, build_args):
        book = make_book({"css": ["custom.css"]})
        (book / "custom.css").write_text("/* custom-marker */\n", encoding="utf-8")
        files = read_epub(build.build_book(book, build_args()))
        assert any(b"custom-marker" in v for k, v in files.items() if k.endswith(".css"))

    def test_cover_design_generates_cover(self, make_book, build_args, tmp_path, require_japanese_font):
        book = make_book({"cover_design": {"colors": ["#123456"]}})
        out = build.build_book(book, build_args())
        cover = out.with_name(out.stem + "-cover.jpg")
        assert cover.exists()
        from PIL import Image
        with Image.open(cover) as im:
            assert im.size == (1600, 2560)
        assert 'properties="cover-image"' in opf_of(read_epub(out))

    def test_cli_all_samples(self, tmp_path):
        """リポジトリのサンプル（books/*）が CLI からビルドできる。"""
        result = run_script("build.py", "--all", "-o", str(tmp_path / "dist"))
        assert result.returncode == 0, result.stderr
        for sample in sorted((ROOT / "books").glob("*/book.yaml")):
            assert (tmp_path / "dist" / f"{sample.parent.name}.epub").exists()


@pytest.mark.usefixtures("require_pandoc", "require_epubcheck")
def test_build_and_epubcheck(make_book, build_args, tmp_path):
    """ビルドした EPUB が EPUBCheck を警告なしで通る（--check）。"""
    book = make_book({"cover": "images/cover.jpg"},
                     images={"images/figure.png": (800, 400), "images/cover.jpg": (1600, 2560)})
    report_dir = tmp_path / "reports"
    out = build.build_book(book, build_args(check=True, report_dir=str(report_dir)))
    report = json.loads((report_dir / f"{out.stem}.epubcheck.json").read_text(encoding="utf-8"))
    bad = [m for m in report["messages"] if m["severity"] in ("FATAL", "ERROR", "WARNING")]
    assert bad == []
