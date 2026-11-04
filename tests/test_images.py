"""scripts/images.py（Kindle 向けの画像の最適化）のテスト。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

import images
from conftest import make_image


def settings(**kw) -> dict:
    return images.load_settings({"images": kw} if kw else {})


def process(path: Path, is_cover: bool = False, **kw):
    warnings: list[str] = []
    s = settings(**kw)
    if is_cover:
        s.update(images.COVER_LIMITS)
    with Image.open(path) as im:
        data, ext, res = images.process_image(im, path, path.name, s, is_cover, warnings)
    return data, ext, res, warnings


def decode(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def noise(size: tuple[int, int], mode: str = "RGB") -> Image.Image:
    """写真らしい（色数が多く、圧縮しにくい）画像。"""
    return Image.frombytes(mode, size, os.urandom(size[0] * size[1] * len(mode)))


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_defaults(self):
        assert settings() == images.DEFAULTS

    def test_override_and_clamp_quality(self):
        s = settings(max_width=800, jpeg_quality=100)
        assert s["max_width"] == 800
        assert s["jpeg_quality"] == 95

    def test_unknown_key(self):
        with pytest.raises(ValueError, match="不明な設定"):
            settings(maxwidth=800)

    @pytest.mark.parametrize("value", [0, -1, "800", 1.5])
    def test_invalid_number(self, value):
        with pytest.raises(ValueError, match="正の整数"):
            settings(max_width=value)

    def test_not_a_mapping(self):
        with pytest.raises(ValueError, match="key: value"):
            images.load_settings({"images": ["a"]})


def test_find_images_skips_hidden_and_cache(tmp_path):
    for rel in ("images/a.png", "images/sub/b.jpg", "c.svg", ".hidden/d.png", "images/.e.png", "cache/f.png",
                "notes.txt", "images/g.PNG"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    found = [p.relative_to(tmp_path).as_posix() for p in images.find_images(tmp_path, skip=[tmp_path / "cache"])]
    assert found == ["c.svg", "images/a.png", "images/g.PNG", "images/sub/b.jpg"]


def test_parse_color():
    assert images.parse_color("#ff0000") == (255, 0, 0)
    assert images.parse_color("white") == (255, 255, 255)
    with pytest.raises(ValueError, match="background"):
        images.parse_color("not-a-color")


class TestHasTransparency:
    def test_rgba(self):
        assert images.has_transparency(Image.new("RGBA", (4, 4), (0, 0, 0, 0)))
        assert not images.has_transparency(Image.new("RGBA", (4, 4), (0, 0, 0, 255)))

    def test_transparency_info(self):
        im = Image.new("P", (4, 4))
        im.info["transparency"] = 0
        assert images.has_transparency(im)
        assert not images.has_transparency(Image.new("RGB", (4, 4)))


# ---------------------------------------------------------------------------
# 1 枚の画像の変換
# ---------------------------------------------------------------------------

class TestProcessImage:
    def test_small_jpeg_is_copied_as_is(self, tmp_path):
        src = make_image(tmp_path / "a.jpg", (800, 600))
        data, ext, res, warnings = process(src)
        assert data is None and ext == ".jpg"
        assert res.actions == ["変更なし"]
        assert warnings == []

    def test_png_recompressed_only_when_smaller(self, tmp_path):
        src = tmp_path / "a.png"
        Image.new("RGB", (800, 600), (10, 20, 30)).save(src, compress_level=0)
        data, ext, res, _ = process(src)
        assert data is not None and len(data) < src.stat().st_size
        assert ext == ".png" and res.actions == ["再圧縮"]
        # 再圧縮しても小さくならなければそのまま使う
        src2 = tmp_path / "b.png"
        src2.write_bytes(data)
        data2, _, res2, _ = process(src2)
        if data2 is None:
            assert res2.actions == ["変更なし"]
        else:
            assert len(data2) < len(data)

    def test_downscale_keeps_aspect_ratio(self, tmp_path):
        src = make_image(tmp_path / "wide.jpg", (3200, 1000))
        data, ext, res, _ = process(src)
        assert decode(data).size == (1600, 500)
        assert res.out_size == (1600, 500)
        assert "縮小 3200×1000→1600×500" in res.actions

    def test_downscale_by_height(self, tmp_path):
        src = make_image(tmp_path / "tall.png", (1000, 5120))
        data, _, _, _ = process(src)
        assert decode(data).size == (500, 2560)

    def test_never_upscale_and_warn_small(self, tmp_path):
        src = make_image(tmp_path / "small.png", (300, 200))
        data, _, res, warnings = process(src)
        assert res.out_size == (300, 200)
        assert any("幅 300px" in w for w in warnings)

    def test_custom_limits(self, tmp_path):
        src = make_image(tmp_path / "a.jpg", (1200, 800))
        data, _, _, _ = process(src, max_width=600, min_width=100)
        assert decode(data).size == (600, 400)

    def test_transparency_composited_on_background(self, tmp_path):
        src = tmp_path / "t.png"
        im = Image.new("RGBA", (800, 400), (255, 0, 0, 0))
        im.paste((255, 0, 0, 255), (0, 0, 400, 400))
        im.save(src)
        data, ext, res, _ = process(src, background="#00ff00")
        out = decode(data)
        assert out.mode == "RGB" and ext == ".png"
        assert out.getpixel((100, 100)) == (255, 0, 0)
        assert out.getpixel((700, 100)) == (0, 255, 0)
        assert "透過→背景合成" in res.actions

    def test_gray_with_alpha_stays_gray(self, tmp_path):
        src = tmp_path / "g.png"
        Image.new("LA", (800, 400), (100, 0)).save(src)
        data, _, _, _ = process(src)
        out = decode(data)
        assert out.mode == "L"
        assert out.getpixel((0, 0)) == 255  # 白背景

    def test_cmyk_to_rgb(self, tmp_path):
        src = tmp_path / "c.jpg"
        Image.new("CMYK", (800, 600), (0, 100, 200, 0)).save(src)
        data, ext, res, _ = process(src)
        assert decode(data).mode == "RGB"
        assert "CMYK→RGB" in res.actions and ext == ".jpg"

    def test_16bit_gray_to_8bit(self, tmp_path):
        src = tmp_path / "16.png"
        Image.new("I;16", (800, 600), 65535).save(src)
        data, _, res, _ = process(src)
        out = decode(data)
        assert out.mode == "L"
        assert out.getpixel((0, 0)) == 255
        assert any(a.endswith("→L") for a in res.actions)

    def test_bmp_diagram_becomes_png(self, tmp_path):
        src = make_image(tmp_path / "d.bmp", (800, 600))
        data, ext, res, _ = process(src)
        assert ext == ".png" and decode(data).format == "PNG"
        assert "BMP→PNG" in res.actions

    def test_tiff_photo_becomes_jpeg(self, tmp_path):
        src = tmp_path / "p.tif"
        noise((800, 600)).save(src)
        data, ext, res, _ = process(src)
        assert ext == ".jpg" and decode(data).format == "JPEG"
        assert "TIFF→JPEG" in res.actions

    def test_animated_gif_first_frame_png(self, tmp_path):
        src = tmp_path / "a.gif"
        frames = [Image.new("P", (800, 400), i) for i in (1, 2, 3)]
        frames[0].save(src, save_all=True, append_images=frames[1:])
        data, ext, res, _ = process(src)
        assert ext == ".png"
        assert "アニメーション→1 フレーム目" in res.actions and "GIF→PNG" in res.actions
        assert getattr(decode(data), "n_frames", 1) == 1

    def test_exif_rotation_applied_and_metadata_removed(self, tmp_path):
        src = tmp_path / "r.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6  # 90° 回転
        make_image(src, (800, 600), exif=exif.tobytes())
        data, _, res, _ = process(src)
        out = decode(data)
        assert out.size == (600, 800)
        assert "回転を反映" in res.actions
        assert out.getexif().get(0x0112) is None

    def test_cover_is_jpeg_with_cover_limits(self, tmp_path):
        src = make_image(tmp_path / "cover.png", (3200, 5120))
        data, ext, res, warnings = process(src, is_cover=True, max_width=800, max_height=800)
        out = decode(data)
        assert out.format == "JPEG" and ext == ".jpg"
        assert out.size == (1600, 2560)  # 本文用の max_width/max_height ではなく表紙の上限
        assert warnings == []

    def test_png_over_limit_switches_to_jpeg(self, tmp_path):
        src = tmp_path / "big.png"
        noise((1000, 1000)).save(src)
        data, ext, res, _ = process(src, max_file_size_kb=500)
        assert ext == ".jpg" and len(data) <= 500 * 1024
        assert "サイズ上限超過のため PNG→JPEG" in res.actions

    def test_jpeg_quality_lowered_to_fit(self, tmp_path):
        src = tmp_path / "big.jpg"
        noise((1500, 1500)).save(src, quality=95)
        data, ext, res, warnings = process(src, max_file_size_kb=700)
        assert any(a.startswith("画質 ") for a in res.actions)
        if len(data) > 700 * 1024:
            assert any("最適化後も" in w for w in warnings)
        else:
            assert warnings == []

    def test_outputs_300dpi(self, tmp_path):
        src = make_image(tmp_path / "wide.jpg", (3200, 1000))
        data, _, _, _ = process(src)
        dpi = decode(data).info.get("dpi")
        assert dpi and round(dpi[0]) == 300


# ---------------------------------------------------------------------------
# 本全体（キャッシュ）
# ---------------------------------------------------------------------------

class TestOptimizeBookImages:
    def make(self, tmp_path):
        book = tmp_path / "mybook"
        make_image(book / "images" / "a.png", (3200, 1600))
        make_image(book / "images" / "b.jpg", (800, 600))
        (book / "images" / "c.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        make_image(book / "images" / "cover.jpg", (3200, 5120))
        return book

    def test_mapping_and_cover(self, tmp_path):
        book = self.make(tmp_path)
        cache = tmp_path / "dist" / ".image-cache"
        report = images.optimize_book_images(book, {}, cache, book / "images" / "cover.jpg")
        assert set(report.mapping) == {"images/a.png", "images/b.jpg", "images/c.svg", "images/cover.jpg"}
        for rel, out in report.mapping.items():
            assert Path(out).is_file() and Path(out).is_relative_to(cache / "mybook")
        assert report.cover == Path(report.mapping["images/cover.jpg"])
        with Image.open(report.cover) as im:
            assert im.size == (1600, 2560)
        assert Path(report.mapping["images/c.svg"]).read_text(encoding="utf-8").startswith("<svg")
        # 元画像は変更しない
        with Image.open(book / "images" / "a.png") as im:
            assert im.size == (3200, 1600)
        manifest = json.loads((cache / "mybook" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["version"] == images.OPTIMIZER_VERSION

    def test_cache_hit_and_invalidation(self, tmp_path):
        book = self.make(tmp_path)
        cache = tmp_path / "cache"
        first = images.optimize_book_images(book, {}, cache, None)
        assert not any(r.cached for r in first.results)
        second = images.optimize_book_images(book, {}, cache, None)
        assert all(r.cached for r in second.results)
        assert second.mapping == first.mapping

        # 設定を変えたら作り直す
        third = images.optimize_book_images(book, {"images": {"max_width": 800}}, cache, None)
        assert not any(r.cached for r in third.results if r.rel == "images/a.png")
        with Image.open(third.mapping["images/a.png"]) as im:
            assert im.size == (800, 400)

        # 元画像を変えたら作り直す
        make_image(book / "images" / "b.jpg", (900, 600))
        fourth = images.optimize_book_images(book, {"images": {"max_width": 800}}, cache, None)
        res = {r.rel: r for r in fourth.results}
        assert not res["images/b.jpg"].cached and res["images/a.png"].cached

    def test_cache_warnings_are_repeated(self, tmp_path):
        book = tmp_path / "b"
        make_image(book / "images" / "tiny.png", (100, 100))
        cache = tmp_path / "cache"
        assert images.optimize_book_images(book, {}, cache, None).warnings
        again = images.optimize_book_images(book, {}, cache, None)
        assert again.results[0].cached and again.warnings

    def test_deleted_output_is_regenerated(self, tmp_path):
        book = self.make(tmp_path)
        cache = tmp_path / "cache"
        first = images.optimize_book_images(book, {}, cache, None)
        Path(first.mapping["images/a.png"]).unlink()
        second = images.optimize_book_images(book, {}, cache, None)
        assert Path(second.mapping["images/a.png"]).exists()
        assert not {r.rel: r for r in second.results}["images/a.png"].cached

    def test_stale_outputs_removed(self, tmp_path):
        book = self.make(tmp_path)
        cache = tmp_path / "cache"
        first = images.optimize_book_images(book, {}, cache, None)
        old = Path(first.mapping["images/b.jpg"])
        (book / "images" / "b.jpg").rename(book / "images" / "renamed.jpg")
        second = images.optimize_book_images(book, {}, cache, None)
        assert not old.exists()
        assert "images/renamed.jpg" in second.mapping and "images/b.jpg" not in second.mapping

    def test_format_change_removes_previous_output(self, tmp_path):
        """同じ元画像の出力の拡張子が変わったら（PNG→JPEG）、古い出力は消す。"""
        book = tmp_path / "b"
        src = book / "images" / "x.png"
        src.parent.mkdir(parents=True)
        noise((800, 800)).save(src)
        cache = tmp_path / "cache"
        first = images.optimize_book_images(book, {}, cache, None)
        assert first.mapping["images/x.png"].endswith(".png")
        second = images.optimize_book_images(book, {"images": {"max_file_size_kb": 200}}, cache, None)
        assert second.mapping["images/x.png"].endswith(".jpg")
        assert not Path(first.mapping["images/x.png"]).exists()

    def test_corrupt_manifest_is_ignored(self, tmp_path):
        book = self.make(tmp_path)
        cache = tmp_path / "cache"
        (cache / book.name).mkdir(parents=True)
        (cache / book.name / "manifest.json").write_text("{broken", encoding="utf-8")
        report = images.optimize_book_images(book, {}, cache, None)
        assert len(report.results) == 4

    def test_invalid_settings_raise(self, tmp_path):
        book = self.make(tmp_path)
        with pytest.raises(ValueError):
            images.optimize_book_images(book, {"images": {"bogus": 1}}, tmp_path / "cache", None)


# ---------------------------------------------------------------------------
# 一覧表示
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, text", [(0, "0B"), (1023, "1023B"), (2048, "2KB"), (5 * 1024 * 1024, "5.0MB")])
def test_human(n, text):
    assert images.human(n) == text


def test_format_report():
    results = [
        images.Result("images/写真.jpg", 2048, 1024, (3200, 2000), (1600, 1000), ["縮小 3200×2000→1600×1000"]),
        images.Result("images/b.png", 1000, 1000, (10, 10), (10, 10), ["変更なし"], cached=True),
        images.Result("images/empty.png", 0, 0, None, None, ["そのまま（SVG）"]),
    ]
    lines = images.format_report(results)
    assert lines[0].startswith("画像")
    assert set(lines[-2]) <= {"-", " "}  # 合計の前の区切り線
    assert lines[-1].startswith("合計")
    assert "2 枚を処理、1 枚はキャッシュ" in lines[-1]
    assert "50%" in lines[1] and "キャッシュ: 変更なし" in lines[2]
    assert "-" in lines[3]  # 大きさの分からない画像
    # 全角文字を 2 桁として列が揃う（右寄せの「最適化前」の列の終わりの位置が同じ）
    ends = set()
    for line, size in zip(lines[1:4], ["2KB", "1000B", "0B"]):
        ends.add(images._width(line[:line.index(size) + len(size)]))
    assert len(ends) == 1
