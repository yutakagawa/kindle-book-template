"""scripts/build.py のテスト（EPUB を実際にビルドして中身を確かめる。pandoc 3.1 以上が必要）。

- docs/review-2026-11.md の 1: 拡張子だけ違う画像が EPUB の中で同じ画像になる
- docs/review-2026-11.md の 5: EPUB に HTML の表紙ページ（cover.xhtml）が本文として入る
- docs/review-2026-11.md の 6: 画像の最適化を無効にしたとき、GPS 付きの写真が黙って入る
- docs/review-2026-11.md の 7: アクセシビリティのメタデータが無い
"""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from helpers import gps_exif, have_pandoc, have_pillow, solid_image, write_book

import build

OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}

BOOK_YAML = """\
title: テストの本
author: テスト 著者
uuid: 3d5c1c0e-6c43-4d38-9a2e-2a3f6f2f4b11
language: ja
{extra}
"""

CHAPTER = """\
# はじめに

{{漢字|かんじ}}を含む本文です。

![赤い図](images/diagram.png)

![青い図](images/diagram.tiff)
"""


class EpubBuildCase(unittest.TestCase):
    """一時ディレクトリに本を作ってビルドする。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.book = self.root / "book"
        self.dist = self.root / "dist"

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, extra_yaml: str = "", chapter: str = CHAPTER, cover: bool = True, args=()):
        if cover:
            solid_image(self.book / "images" / "cover.jpg", (40, 90, 160), size=(1600, 2560))
            extra_yaml = "cover: images/cover.jpg\n" + extra_yaml
        solid_image(self.book / "images" / "diagram.png", (220, 30, 30))
        solid_image(self.book / "images" / "diagram.tiff", (30, 30, 220))
        write_book(self.book, BOOK_YAML.format(extra=extra_yaml), {"01.md": chapter})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = build.main([str(self.book), "-o", str(self.dist), *args])
        self.log = err.getvalue()
        self.assertEqual(code, 0, self.log)
        self.epub = zipfile.ZipFile(self.dist / "book.epub")
        self.addCleanup(self.epub.close)
        self.opf_text = self.epub.read("EPUB/content.opf").decode("utf-8")
        self.opf = ET.fromstring(self.opf_text)  # 整形式の XML であること
        return self.epub

    def metas(self, prop: str) -> list[str]:
        return [m.text for m in self.opf.iterfind("opf:metadata/opf:meta", OPF_NS) if m.get("property") == prop]


@unittest.skipUnless(have_pandoc() and have_pillow(), "pandoc 3.1 以上と Pillow が必要です")
class CoverPageTest(EpubBuildCase):
    def test_html_cover_page_is_removed_by_default(self):
        epub = self.build()
        names = epub.namelist()
        self.assertFalse([n for n in names if n.endswith("cover.xhtml")], "cover.xhtml が残っています")

        spine = [i.get("idref") for i in self.opf.iterfind("opf:spine/opf:itemref", OPF_NS)]
        self.assertNotIn("cover_xhtml", spine)
        self.assertFalse(spine[0].startswith("cover"), spine)
        manifest = {i.get("id"): i for i in self.opf.iterfind("opf:manifest/opf:item", OPF_NS)}
        self.assertNotIn("cover_xhtml", manifest)
        for ref in self.opf.iterfind("opf:guide/opf:reference", OPF_NS):
            self.assertNotEqual(ref.get("type"), "cover")

        # 表紙画像そのものは残す（Kindle やほかのリーダーの表紙・サムネイル）
        covers = [i for i in manifest.values() if "cover-image" in (i.get("properties") or "")]
        self.assertEqual(len(covers), 1)
        self.assertIn("EPUB/" + covers[0].get("href"), names)

        nav = epub.read("EPUB/nav.xhtml").decode("utf-8")
        self.assertNotIn('epub:type="cover"', nav)
        self.assertNotIn("cover.xhtml", nav)
        self.assertIn('epub:type="bodymatter"', nav)
        # ほかのファイルからも表紙ページへのリンクが無いこと
        for n in names:
            if n.endswith((".xhtml", ".ncx", ".opf")):
                self.assertNotIn("cover.xhtml", epub.read(n).decode("utf-8"), n)

    def test_cover_page_can_be_kept(self):
        epub = self.build("layout:\n  cover_page: true\n")
        self.assertTrue([n for n in epub.namelist() if n.endswith("cover.xhtml")])
        spine = [i.get("idref") for i in self.opf.iterfind("opf:spine/opf:itemref", OPF_NS)]
        self.assertIn("cover_xhtml", spine)
        # 表紙ページの画像は本文の画像として数えない
        self.build("layout:\n  cover_page: true\n", chapter="# 章\n\n本文だけです。\n")
        self.assertEqual(self.metas("schema:accessMode"), ["textual"])

    def test_invalid_cover_page_value(self):
        write_book(self.book, BOOK_YAML.format(extra="layout:\n  cover_page: yes please\n"), {"01.md": "# a\n"})
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(build.main([str(self.book), "-o", str(self.dist)]), 1)
        self.assertIn("cover_page", err.getvalue())

    def test_book_without_cover(self):
        self.build(cover=False)
        self.assertNotIn("cover_xhtml", self.opf_text)


@unittest.skipUnless(have_pandoc() and have_pillow(), "pandoc 3.1 以上と Pillow が必要です")
class AccessibilityMetadataTest(EpubBuildCase):
    def test_default_metadata(self):
        self.build()
        self.assertEqual(self.metas("schema:accessMode"), ["textual", "visual"])
        self.assertEqual(self.metas("schema:accessModeSufficient"), ["textual"])
        features = self.metas("schema:accessibilityFeature")
        for f in ("structuralNavigation", "tableOfContents", "readingOrder", "alternativeText", "rubyAnnotations"):
            self.assertIn(f, features)
        self.assertEqual(self.metas("schema:accessibilityHazard"), ["none"])
        summary = self.metas("schema:accessibilitySummary")
        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0].strip())
        # 適合は自動では宣言しない
        self.assertEqual(self.metas("dcterms:conformsTo"), [])

    def test_image_without_alt_text(self):
        self.build(chapter="# 章\n\n本文です。\n\n![](images/diagram.png)\n")
        self.assertNotIn("alternativeText", self.metas("schema:accessibilityFeature"))
        self.assertNotIn("rubyAnnotations", self.metas("schema:accessibilityFeature"))
        self.assertEqual(self.metas("schema:accessModeSufficient"), ["textual,visual"])
        self.assertIn("代替テキスト", self.log)

    def test_text_only_book(self):
        self.build(chapter="# 章\n\n本文だけです。\n", cover=True)
        # 表紙画像は本文の画像として数えない
        self.assertEqual(self.metas("schema:accessMode"), ["textual"])
        self.assertNotIn("alternativeText", self.metas("schema:accessibilityFeature"))

    def test_override_from_book_yaml(self):
        self.build(
            "accessibility:\n"
            "  summary: 読み上げに対応した <テスト> 用の本です & 確認済み\n"
            "  conforms_to: EPUB Accessibility 1.1 - WCAG 2.2 Level AA\n"
            "  certified_by: テスト出版\n"
            "  hazards: [noFlashingHazard, noMotionSimulationHazard, noSoundHazard]\n"
        )
        self.assertEqual(self.metas("schema:accessibilitySummary"), ["読み上げに対応した <テスト> 用の本です & 確認済み"])
        self.assertEqual(self.metas("dcterms:conformsTo"), ["EPUB Accessibility 1.1 - WCAG 2.2 Level AA"])
        self.assertEqual(self.metas("a11y:certifiedBy"), ["テスト出版"])
        self.assertEqual(self.metas("schema:accessibilityHazard"),
                         ["noFlashingHazard", "noMotionSimulationHazard", "noSoundHazard"])

    def test_unknown_accessibility_key(self):
        solid_image(self.book / "images" / "diagram.png", (220, 30, 30))
        write_book(self.book, BOOK_YAML.format(extra="accessibility:\n  sumary: typo\n"), {"01.md": "# a\n"})
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(build.main([str(self.book), "-o", str(self.dist)]), 1)
        self.assertIn("sumary", err.getvalue())

    def test_existing_metadata_is_not_duplicated(self):
        opf = '<package><metadata>\n    <meta property="schema:accessMode">textual</meta>\n  </metadata></package>'
        self.assertEqual(build.add_accessibility_metadata(opf, [], {}, []), opf)


@unittest.skipUnless(have_pandoc() and have_pillow(), "pandoc 3.1 以上と Pillow が必要です")
class EpubImagesTest(EpubBuildCase):
    def test_same_stem_images_are_both_in_epub(self):
        from PIL import Image

        epub = self.build()
        chapter = next(n for n in epub.namelist() if re.search(r"ch\d+\.xhtml$", n))
        srcs = re.findall(r'<img src="\.\./([^"]+)"', epub.read(chapter).decode("utf-8"))
        self.assertEqual(len(srcs), 2)
        self.assertEqual(len(set(srcs)), 2, f"2 つの図が同じ画像になっています: {srcs}")
        colors = []
        for s in srcs:
            with Image.open(io.BytesIO(epub.read("EPUB/" + s))) as im:
                colors.append(im.convert("RGB").getpixel((10, 10)))
        self.assertGreater(colors[0][0], 150, "1 つ目は赤い図")
        self.assertGreater(colors[1][2], 150, "2 つ目は青い図")

    def test_gps_removed_from_epub(self):
        import images

        solid_image(self.book / "images" / "photo.jpg", (200, 200, 200), exif=gps_exif().tobytes())
        epub = self.build(chapter="# 章\n\n![写真](images/photo.jpg)\n")
        jpgs = [n for n in epub.namelist() if n.startswith("EPUB/media/") and n.endswith(".jpg")
                and "cover" not in n]
        self.assertEqual(len(jpgs), 1)
        data = epub.read(jpgs[0])
        self.assertFalse(images.jpeg_has_gps(data))
        self.assertNotIn(b"TestPhone", data)

    def test_warns_about_gps_when_optimization_is_disabled(self):
        solid_image(self.book / "images" / "photo.jpg", (200, 200, 200), exif=gps_exif().tobytes())
        self.build(chapter="# 章\n\n![写真](images/photo.jpg)\n", args=["--no-optimize-images"])
        self.assertIn("images/photo.jpg に撮影場所（GPS 位置情報）が入っています", self.log)


if __name__ == "__main__":
    unittest.main()
