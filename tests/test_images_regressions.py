"""scripts/images.py のテスト。

- docs/review-2026-11.md の 1: 拡張子だけ違う画像（a.tiff と a.png）が同じ出力になり、片方が消える
- docs/review-2026-11.md の 6: 変更不要と判定された JPEG に EXIF（GPS 位置情報など）が残る
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from helpers import gps_exif, have_pillow, solid_image

import images

RED = (220, 30, 30)
BLUE = (30, 30, 220)


def center_color(path: Path):
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        return im.getpixel((im.width // 2, im.height // 2))


def close(a, b, tol=12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@unittest.skipUnless(have_pillow(), "Pillow が必要です")
class OutputNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "book"
        self.cache = Path(self.tmp.name) / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def optimize(self):
        return images.optimize_book_images(self.book, {}, self.cache, None)

    def test_png_and_tiff_with_same_stem_stay_separate(self):
        solid_image(self.book / "images" / "diagram.png", RED)
        solid_image(self.book / "images" / "diagram.tiff", BLUE)
        report = self.optimize()

        png_out = Path(report.mapping["images/diagram.png"])
        tiff_out = Path(report.mapping["images/diagram.tiff"])
        self.assertNotEqual(png_out, tiff_out)
        self.assertTrue(close(center_color(png_out), RED), "diagram.png の最適化版が赤のままであること")
        self.assertTrue(close(center_color(tiff_out), BLUE), "diagram.tiff の最適化版が青のままであること")
        self.assertEqual(tiff_out.name, "diagram.tiff.png")

    def test_jpg_and_webp_with_same_stem_stay_separate(self):
        from PIL import Image

        solid_image(self.book / "images" / "photo.jpg", RED)
        # 色数の多い WebP は JPEG に変換される
        im = Image.effect_noise((800, 600), 80).convert("RGB")
        im.save(self.book / "images" / "photo.webp", "WEBP")
        report = self.optimize()

        outs = {Path(report.mapping["images/photo.jpg"]), Path(report.mapping["images/photo.webp"])}
        self.assertEqual(len(outs), 2)
        self.assertTrue(close(center_color(Path(report.mapping["images/photo.jpg"])), RED))

    def test_unchanged_extension_keeps_name(self):
        solid_image(self.book / "images" / "a.png", RED)
        solid_image(self.book / "images" / "b.jpeg", BLUE)
        report = self.optimize()
        self.assertEqual(Path(report.mapping["images/a.png"]).name, "a.png")
        self.assertEqual(Path(report.mapping["images/b.jpeg"]).name, "b.jpeg")

    def test_duplicate_output_raises(self):
        # a.tiff → a.tiff.png は、元からある a.tiff.png と同じ名前になる
        solid_image(self.book / "images" / "a.tiff", BLUE)
        solid_image(self.book / "images" / "a.tiff.png", RED)
        with self.assertRaisesRegex(ValueError, "ファイル名が同じ"):
            self.optimize()

    def test_case_only_difference_raises(self):
        # 大文字小文字を区別しないファイルシステム（macOS・Windows）では同じファイルになる
        solid_image(self.book / "images" / "Fig.png", BLUE)
        solid_image(self.book / "images" / "fig.png", RED)
        if len(list((self.book / "images").iterdir())) < 2:
            self.skipTest("大文字小文字を区別しないファイルシステム")
        with self.assertRaisesRegex(ValueError, "ファイル名が同じ"):
            self.optimize()

    def test_cached_run_keeps_images_separate(self):
        solid_image(self.book / "images" / "diagram.png", RED)
        solid_image(self.book / "images" / "diagram.gif", BLUE, fmt="GIF")
        self.optimize()
        report = self.optimize()  # 2 回目はキャッシュを使う
        self.assertTrue(all(r.cached for r in report.results))
        self.assertTrue(close(center_color(Path(report.mapping["images/diagram.png"])), RED))
        self.assertTrue(close(center_color(Path(report.mapping["images/diagram.gif"])), BLUE))


@unittest.skipUnless(have_pillow(), "Pillow が必要です")
class MetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "book"
        self.cache = Path(self.tmp.name) / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def optimize(self):
        return images.optimize_book_images(self.book, {}, self.cache, None)

    def assert_no_private_metadata(self, path: Path):
        from PIL import Image

        data = path.read_bytes()
        self.assertFalse(images.jpeg_has_gps(data), f"{path.name} に GPS 情報が残っています")
        self.assertNotIn(b"TestPhone", data, f"{path.name} に機種名が残っています")
        with Image.open(path) as im:
            exif = im.getexif()
            self.assertNotIn(0x8825, exif)
            self.assertNotIn(0x0110, exif)

    def test_unchanged_jpeg_loses_gps_without_recompression(self):
        from PIL import Image

        src = solid_image(self.book / "images" / "photo.jpg", RED, exif=gps_exif().tobytes(), quality=90)
        self.assertTrue(images.jpeg_has_gps(src.read_bytes()), "テスト用の画像に GPS 情報が入っていること")

        report = self.optimize()
        out = Path(report.mapping["images/photo.jpg"])
        self.assert_no_private_metadata(out)
        self.assertIn("メタデータを削除", report.results[0].actions)
        # 再圧縮していない（画素がまったく同じ）
        with Image.open(src) as a, Image.open(out) as b:
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_resized_jpeg_loses_gps(self):
        src = solid_image(self.book / "images" / "big.jpg", RED, size=(3200, 2400), exif=gps_exif().tobytes())
        self.assertTrue(images.jpeg_has_gps(src.read_bytes()))
        report = self.optimize()
        self.assert_no_private_metadata(Path(report.mapping["images/big.jpg"]))

    def test_xmp_comment_removed_icc_kept(self):
        from PIL import Image, ImageCms

        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), RED).save(buf, "JPEG", icc_profile=icc, comment=b"secret note",
                                                xmp=b"<x:xmpmeta>secret-xmp</x:xmpmeta>")
        (self.book / "images").mkdir(parents=True)
        (self.book / "images" / "c.jpg").write_bytes(buf.getvalue())

        report = self.optimize()
        data = Path(report.mapping["images/c.jpg"]).read_bytes()
        self.assertNotIn(b"secret note", data)
        self.assertNotIn(b"secret-xmp", data)
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.info.get("icc_profile"), icc, "ICC プロファイル（色の情報）は残すこと")

    def test_progressive_jpeg_is_still_valid(self):
        from PIL import Image

        im = Image.effect_noise((800, 600), 60).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", progressive=True, exif=gps_exif().tobytes())
        stripped = images.strip_jpeg_metadata(buf.getvalue())
        self.assertFalse(images.jpeg_has_gps(stripped))
        with Image.open(io.BytesIO(buf.getvalue())) as a, Image.open(io.BytesIO(stripped)) as b:
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_png_text_and_exif_chunks_removed(self):
        from PIL import Image, PngImagePlugin

        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "secret-text")
        (self.book / "images").mkdir(parents=True)
        Image.new("RGB", (800, 600), RED).save(self.book / "images" / "d.png", pnginfo=info,
                                                exif=gps_exif().tobytes())
        report = self.optimize()
        data = Path(report.mapping["images/d.png"]).read_bytes()
        self.assertNotIn(b"secret-text", data)
        self.assertNotIn(b"eXIf", data)
        self.assertNotIn(b"TestPhone", data)
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.size, (800, 600))

    def test_find_gps_images(self):
        solid_image(self.book / "images" / "gps.jpg", RED, exif=gps_exif().tobytes())
        solid_image(self.book / "images" / "plain.jpg", BLUE)
        self.assertEqual(images.find_gps_images(self.book, skip=[]), ["images/gps.jpg"])

    def test_broken_data_is_returned_unchanged(self):
        self.assertEqual(images.strip_metadata(b"\xff\xd8garbage", ".jpg"), b"\xff\xd8garbage")
        self.assertEqual(images.strip_metadata(b"not an image", ".png"), b"not an image")


if __name__ == "__main__":
    unittest.main()
