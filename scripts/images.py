"""原稿の画像を Kindle (KDP) 向けに最適化する。

build.py から呼ばれる。元の画像は変更せず、最適化した画像を
<出力先>/.image-cache/<本のディレクトリ名>/ に作り、pandoc にはそちらを渡す。

方針（Kindle Publishing Guidelines / KDP ヘルプに基づく。詳細は README「画像の最適化」）:
- 形式は JPEG（写真）か PNG（図）にする。TIFF・BMP・WebP などは変換し、
  GIF は静止画として PNG に変換する（アニメーション GIF は 1 フレーム目）
- 透過（アルファチャンネル・透過色）は白背景に合成して消す。
  Kindle では透過部分がダークモードで黒くなるなど、表示が崩れやすいため
- CMYK・16 ビットなどは 8 ビット RGB（グレースケールはそのまま）にする
- 表示サイズに対して大きすぎる画像は縮小する（既定は幅 1600 × 高さ 2560px 以内。
  拡大はしない）。不要に大きい画像は配信コスト（70% ロイヤリティの配信料）も増やす
- 1 枚あたり 5MB 以内に収める（JPEG は画質を段階的に下げ、PNG は JPEG に切り替える）
- EXIF の回転情報を反映してからメタデータを取り除く。再エンコードしない画像（「変更なし」）も、
  EXIF（GPS 位置情報・機種名など）・XMP・IPTC・コメントを取り除いてから使う（画質は変わらない）
- 拡張子が変わる画像は元の拡張子を名前に残す（diagram.tiff → diagram.tiff.png）。
  diagram.png と diagram.tiff が両方あっても、別々の画像として扱う
- SVG はそのまま使う（変換しない）

キャッシュ: 元画像の内容（SHA-256）と設定が前回と同じで、出力が残っていれば再処理しない。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# 設定やアルゴリズムを変えたら上げる（キャッシュを作り直させるため）
OPTIMIZER_VERSION = 2

RASTER_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp"}
PASSTHROUGH_EXTS = {".svg"}

DEFAULTS = {
    "optimize": True,
    "max_width": 1600,          # 本文の画像の最大幅（px）
    "max_height": 2560,         # 本文の画像の最大高さ（px）
    "jpeg_quality": 85,         # JPEG の画質（1〜95）
    "max_file_size_kb": 5120,   # 1 枚あたりの上限（KB）
    "background": "#ffffff",    # 透過部分を合成する背景色
    "min_width": 600,           # これより小さい画像は「解像度が低い」と警告する
}

# 表紙: KDP の推奨は 1600×2560px（1.6:1）の RGB JPEG
COVER_LIMITS = {"max_width": 1600, "max_height": 2560}


@dataclass
class Result:
    rel: str                    # 本のディレクトリからの相対パス（元画像）
    src_bytes: int
    out_bytes: int
    src_size: tuple[int, int] | None
    out_size: tuple[int, int] | None
    actions: list[str] = field(default_factory=list)
    cached: bool = False


@dataclass
class OptimizeReport:
    mapping: dict[str, str]     # 元画像の相対パス → 最適化版の絶対パス
    cover: Path | None
    results: list[Result]
    warnings: list[str]


def load_settings(cfg: dict) -> dict:
    s = dict(DEFAULTS)
    user = cfg.get("images") or {}
    if not isinstance(user, dict):
        raise ValueError("book.yaml の images は key: value の形式で書いてください")
    unknown = set(user) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"images に不明な設定があります: {', '.join(sorted(unknown))}")
    s.update(user)
    for key in ("max_width", "max_height", "jpeg_quality", "max_file_size_kb", "min_width"):
        if not isinstance(s[key], int) or s[key] <= 0:
            raise ValueError(f"images.{key} は正の整数で指定してください: {s[key]}")
    s["jpeg_quality"] = min(s["jpeg_quality"], 95)
    return s


def find_images(book_dir: Path, skip: list[Path]) -> list[Path]:
    """本のディレクトリ内の画像（隠しディレクトリと出力先は除く）。"""
    found = []
    for p in sorted(book_dir.rglob("*")):
        rel = p.relative_to(book_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(p.is_relative_to(s) for s in skip):
            continue
        if p.is_file() and p.suffix.lower() in RASTER_EXTS | PASSTHROUGH_EXTS:
            found.append(p)
    return found


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def optimize_book_images(book_dir: Path, cfg: dict, cache_root: Path, cover: Path | None) -> OptimizeReport:
    from PIL import Image  # 呼び出し側で ImportError を処理する

    settings = load_settings(cfg)
    cache_dir = cache_root / book_dir.name
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != OPTIMIZER_VERSION:
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
    old_entries = manifest.get("images", {})
    new_entries: dict[str, dict] = {}

    mapping: dict[str, str] = {}
    results: list[Result] = []
    warnings: list[str] = []
    cover_out: Path | None = None

    for src in find_images(book_dir, skip=[cache_root]):
        rel = src.relative_to(book_dir).as_posix()
        is_cover = cover is not None and src == cover
        limits = dict(settings)
        if is_cover:
            limits.update(COVER_LIMITS)
        fingerprint = json.dumps({"s": limits, "cover": is_cover}, sort_keys=True)
        digest = sha256(src)
        src_bytes = src.stat().st_size

        prev = old_entries.get(rel)
        prev_out = cache_dir / prev["output"] if prev else None
        if prev and prev["sha256"] == digest and prev["settings"] == fingerprint and prev_out.exists():
            entry = prev
            res = Result(rel, src_bytes, prev_out.stat().st_size,
                         tuple(entry["src_size"]) if entry.get("src_size") else None,
                         tuple(entry["out_size"]) if entry.get("out_size") else None,
                         list(entry["actions"]), cached=True)
            warnings += entry.get("warnings", [])
        else:
            if prev_out and prev_out.exists():
                prev_out.unlink()
            entry_warnings: list[str] = []
            if src.suffix.lower() in PASSTHROUGH_EXTS:
                out_rel = rel
                dest = cache_dir / out_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                res = Result(rel, src_bytes, dest.stat().st_size, None, None, ["そのまま（SVG）"])
            else:
                with Image.open(src) as im:
                    data, ext, res = process_image(im, src, rel, limits, is_cover, entry_warnings)
                if data is None:
                    # 再エンコードしない画像も、位置情報などのメタデータだけは取り除く
                    original = src.read_bytes()
                    data = strip_metadata(original, ext)
                    if data != original:
                        res.actions = [a for a in res.actions if a != "変更なし"] + ["メタデータを削除"]
                out_rel = output_name(rel, ext)
                dest = cache_dir / out_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                res.out_bytes = dest.stat().st_size
            entry = {
                "sha256": digest,
                "settings": fingerprint,
                "output": out_rel,
                "src_size": list(res.src_size) if res.src_size else None,
                "out_size": list(res.out_size) if res.out_size else None,
                "actions": res.actions,
                "warnings": entry_warnings,
            }
            warnings += entry_warnings

        clash = next((r for r, e in new_entries.items() if e["output"].casefold() == entry["output"].casefold()), None)
        if clash is not None:
            raise ValueError(
                f"画像 {clash} と {rel} の最適化後のファイル名が同じ（{entry['output']}）になります。"
                "どちらかの名前を変えてください"
            )
        new_entries[rel] = entry
        out_path = (cache_dir / entry["output"]).resolve()
        mapping[rel] = str(out_path)
        if is_cover:
            cover_out = out_path
        results.append(res)

    # 元画像が消えた・名前が変わったものの古い出力を片付ける
    keep = {e["output"] for e in new_entries.values()}
    for rel, e in old_entries.items():
        if rel not in new_entries and e["output"] not in keep:
            stale = cache_dir / e["output"]
            if stale.exists():
                stale.unlink()

    manifest_path.write_text(
        json.dumps({"version": OPTIMIZER_VERSION, "images": new_entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return OptimizeReport(mapping, cover_out, results, warnings)


def output_name(rel: str, ext: str) -> str:
    """最適化版の相対パス。拡張子が変わるときは元の拡張子を残す（a.tiff → a.tiff.png）。

    拡張子だけを置き換えると、a.tiff と a.png が両方あるときに同じ a.png になり、
    片方の画像がもう片方で上書きされてしまう。
    """
    return rel if Path(rel).suffix == ext else rel + ext


# ---------------------------------------------------------------------------
# メタデータの削除（再エンコードせずに、位置情報などを含む部分だけを取り除く）
# ---------------------------------------------------------------------------

# 残す JPEG の APP セグメント: APP0（JFIF）、APP2 の ICC プロファイル、APP14（Adobe。色の変換方法）
_JPEG_KEEP_APP = {0xE0, 0xEE}
# 削除する PNG の補助チャンク（テキスト・EXIF・更新日時）。色の情報（iCCP・sRGB・gAMA）や pHYs は残す
_PNG_DROP_CHUNKS = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def strip_metadata(data: bytes, ext: str) -> bytes:
    """JPEG / PNG のバイト列から EXIF・XMP・IPTC・コメントなどを取り除く（画素データはそのまま）。

    解釈できない形式のときは元のバイト列を返す。
    """
    ext = ext.lower()
    if ext in (".jpg", ".jpeg") and data[:2] == b"\xff\xd8":
        return strip_jpeg_metadata(data)
    if ext == ".png" and data[:8] == b"\x89PNG\r\n\x1a\n":
        return strip_png_metadata(data)
    return data


def _jpeg_segments(data: bytes):
    """JPEG のヘッダ部分のセグメントを (マーカー, 開始位置, 終了位置) で返す。最後は SOS 以降（画像データ）。"""
    pos = 2
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF:
            raise ValueError("JPEG のセグメントを解釈できません")
        marker = data[pos + 1]
        if marker == 0xFF:  # 詰め物
            pos += 1
            continue
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            yield marker, pos, pos + 2
            pos += 2
            continue
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        end = pos + 2 + length
        if length < 2 or end > n:
            raise ValueError("JPEG のセグメントの長さが正しくありません")
        if marker == 0xDA:  # SOS: ここから画像データ。最初の EOI まで
            eoi = _find_eoi(data, end)
            yield marker, pos, eoi
            return
        yield marker, pos, end
        pos = end
    raise ValueError("JPEG に画像データ（SOS）がありません")


def _find_eoi(data: bytes, start: int) -> int:
    """画像データ（エントロピー符号化部分）の後の最初の EOI の直後の位置。

    画像データ中の 0xFF は 0xFF00 か RST（0xFFD0〜D7）になるので、それ以外のマーカーで終わる。
    EOI より後ろ（MPO の 2 枚目以降の画像など。それぞれに EXIF がある）は捨てる。
    """
    pos = start
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            return len(data)
        nxt = data[pos + 1]
        if nxt == 0xD9:
            return pos + 2
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7 or nxt == 0xFF:
            pos += 1
            continue
        # プログレッシブ JPEG: 次のスキャンの DHT / SOS などのセグメント
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        pos += 2 + length


def _keep_jpeg_segment(data: bytes, marker: int, start: int, end: int) -> bool:
    if marker == 0xFE:  # COM
        return False
    if 0xE0 <= marker <= 0xEF:
        if marker == 0xE2:
            return data[start + 4:start + 16] == b"ICC_PROFILE\x00"
        return marker in _JPEG_KEEP_APP
    return True


def strip_jpeg_metadata(data: bytes) -> bytes:
    try:
        segments = list(_jpeg_segments(data))
    except ValueError:
        return data
    out = bytearray(data[:2])
    for marker, start, end in segments:
        if marker == 0xD8:
            continue
        if _keep_jpeg_segment(data, marker, start, end):
            out += data[start:end]
    return bytes(out)


def strip_png_metadata(data: bytes) -> bytes:
    out = bytearray(data[:8])
    pos = 8
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return data
        if ctype not in _PNG_DROP_CHUNKS:
            out += data[pos:end]
        pos = end
        if ctype == b"IEND":
            break
    return bytes(out)


def jpeg_has_gps(data: bytes) -> bool:
    """JPEG の EXIF に GPS 情報（GPS IFD へのポインタ 0x8825）があるか。Pillow 無しで使える。"""
    if data[:2] != b"\xff\xd8":
        return False
    try:
        segments = list(_jpeg_segments(data))
    except ValueError:
        return False
    for marker, start, end in segments:
        if marker == 0xE1 and data[start + 4:start + 10] == b"Exif\x00\x00":
            return _tiff_ifd0_has_tag(data[start + 10:end], 0x8825)
    return False


def _tiff_ifd0_has_tag(tiff: bytes, tag: int) -> bool:
    if tiff[:2] == b"II":
        order = "little"
    elif tiff[:2] == b"MM":
        order = "big"
    else:
        return False
    offset = int.from_bytes(tiff[4:8], order)
    if offset + 2 > len(tiff):
        return False
    count = int.from_bytes(tiff[offset:offset + 2], order)
    for i in range(count):
        entry = offset + 2 + i * 12
        if entry + 2 > len(tiff):
            return False
        if int.from_bytes(tiff[entry:entry + 2], order) == tag:
            return True
    return False


def find_gps_images(book_dir: Path, skip: list[Path]) -> list[str]:
    """位置情報（GPS）付きの JPEG の一覧（画像の最適化を使わないときの警告用）。"""
    found = []
    for p in find_images(book_dir, skip):
        if p.suffix.lower() in (".jpg", ".jpeg"):
            try:
                if jpeg_has_gps(p.read_bytes()):
                    found.append(p.relative_to(book_dir).as_posix())
            except OSError:
                pass
    return found


def parse_color(value: str) -> tuple[int, int, int]:
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(str(value))[:3]
    except ValueError:
        raise ValueError(f"images.background の色を解釈できません: {value}")


def has_transparency(im) -> bool:
    if im.mode in ("RGBA", "LA", "PA"):
        # アルファが全面不透明なら透過なしとみなす
        alpha = im.getchannel("A")
        return alpha.getextrema()[0] < 255
    if im.mode in ("P", "L", "RGB") and "transparency" in im.info:
        return True
    return False


def process_image(im, src: Path, rel: str, s: dict, is_cover: bool, warnings: list[str]):
    """画像を変換して (書き出すバイト列 or None=そのままコピー, 拡張子, Result) を返す。"""
    from PIL import Image, ImageOps

    actions: list[str] = []
    fmt = (im.format or "").upper()
    src_size = im.size
    src_bytes = src.stat().st_size
    max_bytes = s["max_file_size_kb"] * 1024

    if getattr(im, "n_frames", 1) > 1:
        actions.append("アニメーション→1 フレーム目")
    im.seek(0)

    # 出力形式を決める
    if is_cover:
        target = "JPEG"
    elif fmt in ("JPEG", "MPO"):
        target = "JPEG"
    elif fmt == "PNG":
        target = "PNG"
    else:
        # TIFF・BMP・WebP・GIF など: 色数が少なければ図として PNG、多ければ写真として JPEG
        probe = im.convert("RGBA") if im.mode not in ("RGB", "RGBA", "L") else im
        target = "PNG" if fmt == "GIF" or probe.getcolors(256) is not None else "JPEG"
    if target != fmt and not (fmt == "MPO" and target == "JPEG"):
        actions.append(f"{fmt or src.suffix}→{target}")

    needs_encode = bool(actions)

    # EXIF の回転を反映
    orientation = im.getexif().get(0x0112, 1)
    if orientation != 1:
        im = ImageOps.exif_transpose(im)
        actions.append("回転を反映")
        needs_encode = True

    # 透過を背景色に合成
    if has_transparency(im):
        bg = Image.new("RGB", im.size, parse_color(s["background"]))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        im = bg if not _is_gray(rgba) else bg.convert("L")
        actions.append("透過→背景合成")
        needs_encode = True

    # カラーモード: RGB / L（8 ビット）に揃える
    if im.mode not in ("RGB", "L"):
        before = im.mode
        if im.mode in ("I;16", "I;16B", "I;16L", "I"):
            im = im.convert("I").point(lambda v: v * (1 / 256)).convert("L")
        elif im.mode == "P" and target == "PNG":
            pass  # 透過のないパレット PNG は小さいのでそのまま
        else:
            im = im.convert("RGB")
        if im.mode != before:
            actions.append(f"{before}→{im.mode}")
            needs_encode = True

    # 縮小（拡大はしない）
    w, h = im.size
    scale = min(s["max_width"] / w, s["max_height"] / h, 1.0)
    if scale < 1.0:
        new = (max(1, round(w * scale)), max(1, round(h * scale)))
        if im.mode == "P":
            im = im.convert("RGB")
        im = im.resize(new, Image.LANCZOS)
        actions.append(f"縮小 {w}×{h}→{new[0]}×{new[1]}")
        needs_encode = True

    if not is_cover and im.size[0] < s["min_width"]:
        warnings.append(
            f"{rel}: 幅 {im.size[0]}px は小さく、Kindle で粗く見える可能性があります"
            f"（表示サイズに対して 300ppi 相当、幅 {s['min_width']}px 以上が目安）"
        )

    if not needs_encode and src_bytes <= max_bytes:
        if target == "PNG":
            # 再圧縮して小さくなるときだけ採用（PNG は可逆なので画質は変わらない）
            data = encode(im, "PNG", s)
            if len(data) < src_bytes:
                return data, src.suffix if src.suffix.lower() == ".png" else ".png", \
                    Result(rel, src_bytes, len(data), src_size, im.size, ["再圧縮"])
        # JPEG は再圧縮すると劣化するのでそのまま使う
        return None, src.suffix, Result(rel, src_bytes, src_bytes, src_size, im.size, ["変更なし"])

    data = encode(im, target, s)
    if len(data) > max_bytes and target == "PNG":
        target = "JPEG"
        data = encode(im, "JPEG", s)
        actions.append("サイズ上限超過のため PNG→JPEG")
    if target == "JPEG":
        q = s["jpeg_quality"]
        while len(data) > max_bytes and q > 40:
            q -= 10
            data = encode(im, "JPEG", s, quality=q)
        if q != s["jpeg_quality"]:
            actions.append(f"画質 {q}")
    if len(data) > max_bytes:
        warnings.append(f"{rel}: 最適化後も {len(data) / 1024 / 1024:.1f}MB あります。画像を小さくしてください")
    if not actions:
        actions.append("再圧縮")

    ext = ".jpg" if target == "JPEG" else ".png"
    if target == "JPEG" and src.suffix.lower() in (".jpg", ".jpeg"):
        ext = src.suffix
    if target == "PNG" and src.suffix.lower() == ".png":
        ext = src.suffix
    return data, ext, Result(rel, src_bytes, len(data), src_size, im.size, actions)


def _is_gray(im) -> bool:
    if im.mode in ("L", "LA"):
        return True
    rgb = im.convert("RGB")
    r, g, b = rgb.split()
    from PIL import ImageChops
    return ImageChops.difference(r, g).getbbox() is None and ImageChops.difference(g, b).getbbox() is None


def encode(im, fmt: str, s: dict, quality: int | None = None) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(buf, "JPEG", quality=quality or s["jpeg_quality"], optimize=True,
                progressive=False, subsampling="4:2:0", dpi=(300, 300))
    else:
        im.save(buf, "PNG", optimize=True, dpi=(300, 300))
    # Pillow は元画像のコメントなどを引き継いで書き込むことがあるので、ここでも取り除く
    return strip_metadata(buf.getvalue(), ".jpg" if fmt == "JPEG" else ".png")


# ---------------------------------------------------------------------------
# 一覧表示
# ---------------------------------------------------------------------------

def human(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    if n < 1024:
        return f"{n}B"
    return f"{n / 1024:.0f}KB"


def dims(size) -> str:
    return f"{size[0]}×{size[1]}" if size else "-"


def _width(text: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    fill = " " * max(0, width - _width(text))
    return fill + text if right else text + fill


def format_report(results: list[Result]) -> list[str]:
    header = ["画像", "最適化前", "", "最適化後", "", "削減", "処理"]
    rows = []
    total_src = total_out = 0
    for r in results:
        total_src += r.src_bytes
        total_out += r.out_bytes
        saved = (1 - r.out_bytes / r.src_bytes) * 100 if r.src_bytes else 0
        note = "キャッシュ: " if r.cached else ""
        rows.append([r.rel, dims(r.src_size), human(r.src_bytes), dims(r.out_size), human(r.out_bytes),
                     f"{saved:.0f}%", note + "、".join(r.actions)])
    saved = (1 - total_out / total_src) * 100 if total_src else 0
    rows.append(["合計", "", human(total_src), "", human(total_out), f"{saved:.0f}%",
                 f"{sum(not r.cached for r in results)} 枚を処理、{sum(r.cached for r in results)} 枚はキャッシュ"])
    widths = [max(_width(row[i]) for row in rows + [header]) for i in range(len(header))]
    right = {1, 2, 3, 4, 5}
    lines = []
    for i, row in enumerate([header] + rows):
        if i == len(rows):  # 合計の前に区切り
            lines.append("  ".join("-" * w for w in widths))
        lines.append("  ".join(_pad(c, widths[j], j in right) for j, c in enumerate(row)).rstrip())
    return lines
