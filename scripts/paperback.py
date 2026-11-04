#!/usr/bin/env python3
"""同じ原稿から KDP ペーパーバック（紙の本）用の本文 PDF を作る。

build.py の --paperback から呼ばれる（単体でも python3 scripts/paperback.py books/my-book で動く）。

    Markdown ──pandoc（EPUB と同じ Lua フィルタ）──▶ HTML ──Vivliostyle（CSS 組版）──▶ PDF

判型・余白・裁ち落とし・ノンブルは book.yaml の paperback で設定する。
寸法は KDP の「ペーパーバックの本文の書式設定」の要件に合わせている:

  - PDF のページサイズ = 判型（裁ち落としなし）
                       = 判型の幅 + 0.125 インチ × 高さ + 0.25 インチ（裁ち落としあり。
                         上・下・小口の 3 辺に 0.125 インチ。ノド側には付けない）
  - ノド（内側の余白）はページ数で決まる最小値以上（KDP_GUTTERS）。
    ページ数は組んでみないと分からないので、組版 → ページ数を数える → ノドが足りなければ組み直す
  - 外側（天・地・小口）の余白は 0.25 インチ以上（裁ち落としありは 0.375 インチ以上）
  - トンボ（トリムマーク）は付けない（KDP はトンボ付きの PDF を受け付けない）
  - フォントはすべて埋め込む（Chromium が生成する PDF はサブセット埋め込みになる）
  - ページ数は 24 以上
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

if __name__ == "__main__":
    # bash scripts/setup.sh が作った .venv があれば、その Python（PyYAML・Pillow 入り）で起動し直す
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from use_venv import reexec_in_venv
    reexec_in_venv(__file__)

ROOT = Path(__file__).resolve().parent.parent
FILTERS = ROOT / "filters"
STYLES = ROOT / "styles"
TEMPLATE = ROOT / "templates" / "paperback.html"

MM_PER_IN = 25.4

# KDP の標準の判型（インチ）。キーは book.yaml の paperback.trim に書く名前
KDP_TRIM_SIZES: dict[str, tuple[float, float]] = {
    "5x8": (5.0, 8.0),
    "5.06x7.81": (5.06, 7.81),
    "5.25x8": (5.25, 8.0),
    "5.5x8.5": (5.5, 8.5),
    "6x9": (6.0, 9.0),
    "6.14x9.21": (6.14, 9.21),
    "6.69x9.61": (6.69, 9.61),
    "7x10": (7.0, 10.0),
    "7.44x9.69": (7.44, 9.69),
    "7.5x9.25": (7.5, 9.25),
    "8x10": (8.0, 10.0),
    "8.25x6": (8.25, 6.0),
    "8.25x8.25": (8.25, 8.25),
    "8.5x8.5": (8.5, 8.5),
    "8.5x11": (8.5, 11.0),
    "a4": (8.27, 11.69),
}
# 日本の判型。KDP では「カスタムの判型」として幅・高さを入力する
JIS_TRIM_SIZES: dict[str, tuple[float, float]] = {
    "a5": (148 / MM_PER_IN, 210 / MM_PER_IN),
    "b6": (128 / MM_PER_IN, 182 / MM_PER_IN),
    "shinsho": (103 / MM_PER_IN, 182 / MM_PER_IN),   # 新書判（約 4.06×7.17 インチ。KDP のカスタム判型の範囲内）
    "bunko": (105 / MM_PER_IN, 148 / MM_PER_IN),     # 文庫判（高さ約 5.83 インチが KDP の最小 6 インチ未満なので不可）
}
# KDP のカスタム判型として受け付けられる範囲（インチ）
CUSTOM_WIDTH = (4.0, 8.5)
CUSTOM_HEIGHT = (6.0, 11.69)

BLEED_IN = 0.125
# ページ数 → ノドの最小値（インチ）
KDP_GUTTERS = [(150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875)]
MIN_OUTSIDE_IN = 0.25
MIN_OUTSIDE_BLEED_IN = 0.375
MIN_PAGES, MAX_PAGES = 24, 828
# 用紙 1 枚あたりの厚さ（インチ）。表紙 PDF の背幅の計算に使う
PAPER_THICKNESS = {"white": 0.002252, "cream": 0.0025, "color": 0.002347}

FONT_STACKS = {
    "serif": '"Noto Serif CJK JP", "Noto Serif JP", "Source Han Serif JP", "Source Han Serif", '
             '"IPAexMincho", "IPAMincho", "Hiragino Mincho ProN", "Yu Mincho", serif',
    "sans": '"Noto Sans CJK JP", "Noto Sans JP", "Source Han Sans JP", "Source Han Sans", '
            '"IPAexGothic", "IPAGothic", "Hiragino Sans", "Yu Gothic", sans-serif',
    "mono": '"Noto Sans Mono CJK JP", "Source Han Code JP", "DejaVu Sans Mono", '
            '"Liberation Mono", "IPAGothic", monospace',
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


class PaperbackError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[paperback] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 寸法
# ---------------------------------------------------------------------------

def to_inch(value, name: str) -> float:
    """'15mm' / '0.5in' / '12pt' / 数値（mm とみなす）をインチに直す。"""
    if isinstance(value, (int, float)):
        return float(value) / MM_PER_IN
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(mm|cm|in|pt|q)?\s*", str(value), re.I)
    if not m:
        raise PaperbackError(f"paperback.{name} の長さを読めません: {value}（例: 15mm, 0.5in）")
    num, unit = float(m.group(1)), (m.group(2) or "mm").lower()
    return {"mm": num / MM_PER_IN, "cm": num * 10 / MM_PER_IN, "in": num,
            "pt": num / 72, "q": num * 0.25 / MM_PER_IN}[unit]


def fmt_in(v: float) -> str:
    return f"{v:.4f}in"


def fmt_mm(v: float) -> str:
    return f"{v * MM_PER_IN:.1f}mm"


def parse_trim(value, warnings: list[str]) -> tuple[str, float, float]:
    """判型の名前（6x9 / a5 など）か {width, height} を (表示名, 幅, 高さ) に直す。"""
    if isinstance(value, dict):
        w, h = to_inch(value.get("width"), "trim.width"), to_inch(value.get("height"), "trim.height")
        label = f"{fmt_mm(w)}×{fmt_mm(h)}"
        custom = True
    else:
        key = str(value).strip().lower().replace("×", "x").replace(" ", "")
        # 単位（6inx9in / 6"x9"）は数字の直後だけ取り除く（"shinsho" の "in" を消さないように）
        key = re.sub(r'(?<=\d)(?:in|")', "", key)
        if key in KDP_TRIM_SIZES:
            w, h = KDP_TRIM_SIZES[key]
            return f'{w:g}"×{h:g}"', w, h
        if key in JIS_TRIM_SIZES:
            w, h = JIS_TRIM_SIZES[key]
            label = f"{key.upper()}（{fmt_mm(w)}×{fmt_mm(h)}）"
            custom = True
        else:
            names = ", ".join(list(KDP_TRIM_SIZES) + ["a5", "b6"])
            raise PaperbackError(f"paperback.trim が分かりません: {value}（{names}、または width/height を指定）")
    if custom:
        if not (CUSTOM_WIDTH[0] <= w <= CUSTOM_WIDTH[1] and CUSTOM_HEIGHT[0] <= h <= CUSTOM_HEIGHT[1]):
            raise PaperbackError(
                f"判型 {label} は KDP のカスタム判型の範囲外です"
                f"（幅 {CUSTOM_WIDTH[0]}〜{CUSTOM_WIDTH[1]} インチ、高さ {CUSTOM_HEIGHT[0]}〜{CUSTOM_HEIGHT[1]} インチ）"
            )
        warnings.append(f"判型 {label} は KDP の標準サイズではありません。KDP では「カスタムの判型」で "
                        f"{w:.2f} × {h:.2f} インチを入力してください")
    return label, w, h


def kdp_min_gutter(pages: int) -> float:
    for limit, gutter in KDP_GUTTERS:
        if pages <= limit:
            return gutter
    return KDP_GUTTERS[-1][1]


@dataclass
class Geometry:
    trim_label: str
    trim_w: float
    trim_h: float
    bleed: bool
    top: float
    bottom: float
    outside: float
    inside: float       # ユーザー指定のノド（KDP の最小値との大きい方を使う）

    @property
    def bleed_in(self) -> float:
        return BLEED_IN if self.bleed else 0.0

    @property
    def page_w(self) -> float:
        return self.trim_w + self.bleed_in

    @property
    def page_h(self) -> float:
        return self.trim_h + 2 * self.bleed_in

    def gutter_for(self, pages: int) -> float:
        return max(self.inside, kdp_min_gutter(pages))

    def text_width(self, gutter: float) -> float:
        return self.trim_w - gutter - self.outside


def read_settings(cfg: dict, writing_mode: str, warnings: list[str]) -> dict:
    pb = cfg.get("paperback") or {}
    if not isinstance(pb, dict):
        raise PaperbackError("book.yaml の paperback は項目の一覧（key: value）で書いてください")
    label, w, h = parse_trim(pb.get("trim", "a5"), warnings)
    bleed = bool(pb.get("bleed", False))
    margins = pb.get("margins") or {}
    vertical = writing_mode == "vertical"
    defaults = {"top": "18mm", "bottom": "20mm", "outside": "15mm", "inside": "18mm"}
    if vertical:
        defaults.update({"top": "20mm", "bottom": "20mm", "outside": "16mm"})
    geo = Geometry(label, w, h, bleed,
                   *(to_inch(margins.get(k, defaults[k]), f"margins.{k}") for k in ("top", "bottom", "outside", "inside")))
    min_out = MIN_OUTSIDE_BLEED_IN if bleed else MIN_OUTSIDE_IN
    for k in ("top", "bottom", "outside"):
        if getattr(geo, k) < min_out:
            raise PaperbackError(
                f"paperback.margins.{k}（{fmt_mm(getattr(geo, k))}）が KDP の最小値 {fmt_mm(min_out)} "
                f"（{min_out} インチ{'、裁ち落としあり' if bleed else ''}）より小さいです"
            )
    paper = str(pb.get("paper", "cream" if vertical else "white"))
    if paper not in PAPER_THICKNESS:
        raise PaperbackError(f"paperback.paper は {', '.join(PAPER_THICKNESS)} のいずれかです: {paper}")
    font = str(pb.get("font", "serif"))
    body_font = FONT_STACKS.get(font, f'"{font}", {FONT_STACKS["serif"]}')
    return {
        "geo": geo,
        "paper": paper,
        "font_size": pb.get("font_size", "9pt" if vertical else "9.5pt"),
        "line_height": pb.get("line_height", 1.75 if vertical else 1.7),
        "body_font": body_font,
        "heading_font": FONT_STACKS.get(str(pb.get("heading_font", "sans")), f'"{pb.get("heading_font")}", sans-serif'),
        "page_numbers": bool(pb.get("page_numbers", True)),
        "running_heads": bool(pb.get("running_heads", True)),
        "colophon": bool(pb.get("colophon", True)),
        "isbn": str(pb.get("isbn") or ""),
        "notes": [str(n) for n in (pb.get("colophon_notes") or [])],
        "author_suffix": str(pb.get("author_suffix", "　著")),
        "output": pb.get("output"),
        "css": pb.get("css") or [],
    }


def page_css(s: dict, gutter: float, writing_mode: str) -> str:
    """判型・余白・ノンブル・柱の @page を作る。

    左右のページで余白を入れ替える。物理的に「右側のページ」はノドが左、「左側のページ」はノドが右。
    右綴じ（縦書き）では 1 ページ目が左側のページになる（Vivliostyle が綴じ方向に合わせて :left/:right を決める）。
    裁ち落としありのときは、ページを天・地・小口へ 0.125 インチずつ広げ、その分だけ余白も広げる
    （= 判型の中での余白は変わらない）。
    """
    g = s["geo"]
    b = g.bleed_in
    top, bottom, outside = g.top + b, g.bottom + b, g.outside + b
    # ノンブルは縦書きの本も横組みのアラビア数字で、地の小口側に置く（和書の一般的な体裁）
    num = "counter(page)" if s["page_numbers"] else "none"
    # first-except: 章の最初のページ（見出しのあるページ）には柱を入れない
    head = "string(chapter, first-except)" if s["running_heads"] else "none"
    # 柱・ノンブルは版面の外（余白）に置くが、判型の端から KDP の最小余白以上は離れる位置にする
    # 余白の箱（@top-* / @bottom-*）には :root の変数が届かないので書体は直接書く。縦書きの本でも横組みにする
    margin_box = (f"font-family: {s['heading_font']}; font-size: 7.5pt; color: black; "
                  "writing-mode: horizontal-tb; white-space: nowrap;")
    text_w = g.text_width(gutter)
    text_h = g.trim_h - g.top - g.bottom
    return f"""@charset "UTF-8";
/* scripts/paperback.py が生成（判型 {g.trim_label}、裁ち落とし{'あり' if g.bleed else 'なし'}、ノド {fmt_mm(gutter)}） */
:root {{
  --pb-font-size: {s['font_size']};
  --pb-line-height: {s['line_height']};
  --pb-font-body: {s['body_font']};
  --pb-font-heading: {s['heading_font']};
  --pb-font-mono: {FONT_STACKS['mono']};
  /* 版面（本文の領域）の大きさ。画像の最大サイズや扉・奥付の配置に使う */
  --pb-text-width: {fmt_in(text_w)};
  --pb-text-height: {fmt_in(text_h)};
}}
@page {{
  size: {fmt_in(g.page_w)} {fmt_in(g.page_h)};
  marks: none;
  bleed: 0;
  margin-top: {fmt_in(top)};
  margin-bottom: {fmt_in(bottom)};
}}
@page :right {{
  margin-left: {fmt_in(gutter)};
  margin-right: {fmt_in(outside)};
  @bottom-right {{ content: {num}; {margin_box} vertical-align: middle; text-align: right; }}
  @top-right {{ content: {head}; {margin_box} vertical-align: middle; text-align: right; }}
}}
@page :left {{
  margin-left: {fmt_in(outside)};
  margin-right: {fmt_in(gutter)};
  @bottom-left {{ content: {num}; {margin_box} vertical-align: middle; text-align: left; }}
  @top-left {{ content: {head}; {margin_box} vertical-align: middle; text-align: left; }}
}}
/* 扉・空白ページ・奥付にはノンブルと柱を入れない。目次には柱を入れない */
@page titlepage, colophon, :blank {{
  @top-left {{ content: none; }} @top-right {{ content: none; }}
  @bottom-left {{ content: none; }} @bottom-right {{ content: none; }}
}}
/* 目次には柱を入れない */
@page frontmatter {{
  @top-left {{ content: none; }} @top-right {{ content: none; }}
}}
"""


# ---------------------------------------------------------------------------
# PDF の簡易解析（ページ数・ページサイズ・フォントの埋め込み）
# ---------------------------------------------------------------------------

def _pdf_objects(data: bytes) -> list[bytes]:
    """PDF の中の辞書（オブジェクトストリームの中身も展開する）を雑に集める。"""
    chunks = [data]
    for m in re.finditer(rb"<<(?:(?!>>).){0,400}?/Type\s*/ObjStm.*?>>\s*stream\r?\n", data, re.S):
        start = m.end()
        end = data.find(b"endstream", start)
        try:
            chunks.append(zlib.decompress(data[start:end].rstrip(b"\r\n")))
        except zlib.error:
            pass
    return chunks


def inspect_pdf(path: Path) -> dict:
    data = path.read_bytes()
    chunks = _pdf_objects(data)
    text = b"\n".join(chunks)
    pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", text))
    boxes = re.findall(rb"/MediaBox\s*\[\s*([-\d.\s]+)\]", text)
    sizes = set()
    for box in boxes:
        nums = [float(x) for x in box.split()]
        if len(nums) == 4:
            sizes.add((round((nums[2] - nums[0]) / 72, 3), round((nums[3] - nums[1]) / 72, 3)))
    fonts = set(re.findall(rb"/FontName\s*/([^\s/\[\]<>()]+)", text))
    embedded = len(re.findall(rb"/FontFile[23]?\b", text))
    unembedded = len(re.findall(rb"/Subtype\s*/(?:TrueType|Type1|CIDFontType[02])\b", text)) and embedded == 0
    return {"pages": pages, "sizes": sizes, "fonts": sorted(f.decode("latin-1") for f in fonts),
            "embedded": embedded, "unembedded": bool(unembedded)}


# ---------------------------------------------------------------------------
# 組版
# ---------------------------------------------------------------------------

def find_vivliostyle() -> list[str]:
    exe = os.environ.get("VIVLIOSTYLE")
    if exe:
        return [exe]
    local = ROOT / "node_modules" / ".bin" / ("vivliostyle.cmd" if os.name == "nt" else "vivliostyle")
    if local.exists():
        return [str(local)]
    if shutil.which("vivliostyle"):
        return ["vivliostyle"]
    raise PaperbackError("Vivliostyle CLI が見つかりません。リポジトリの直下で npm install を実行してください")


def browser_args(args) -> list[str]:
    path = getattr(args, "browser", None) or os.environ.get("VIVLIOSTYLE_BROWSER")
    return ["--executable-browser", path] if path else []


def collect_images(book_dir: Path, work: Path) -> dict[str, str]:
    """原稿の画像を作業ディレクトリへコピーし、images.lua 用の対応表（元の相対パス → コピー先）を返す。

    紙の本は 300dpi 以上が望ましいので、Kindle 向けに縮小した版ではなく元画像を使う。
    """
    mapping = {}
    dest_root = work / "assets"
    for p in sorted(book_dir.rglob("*")):
        if p.suffix.lower() not in IMAGE_EXTS or not p.is_file():
            continue
        rel = p.relative_to(book_dir)
        if any(part.startswith(".") or part == "dist" for part in rel.parts):
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        mapping[rel.as_posix()] = dest.relative_to(work).as_posix()
    return mapping


def check_image_resolution(html_text: str, work: Path, text_width_in: float, warnings: list[str]) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    seen = set()
    for src in re.findall(r'<img[^>]+src="([^"]+)"', html_text):
        src = html.unescape(src)
        if src in seen or src.startswith(("http:", "https:", "data:")):
            continue
        seen.add(src)
        p = work / src
        if not p.exists() or p.suffix.lower() == ".svg":
            continue
        with Image.open(p) as im:
            w, _ = im.size
        dpi = w / text_width_in
        if dpi < 300:
            warnings.append(f"画像 {Path(src).name}（幅 {w}px）は版面の幅いっぱいに置くと約 {dpi:.0f}dpi です。"
                            f"KDP の推奨は 300dpi 以上（この判型なら幅 {int(text_width_in * 300)}px 以上）")


def build_paperback(book_dir: Path, cfg: dict, meta: dict, chapters: list[Path], writing_mode: str,
                    output: Path, args, pandoc_cmd: list[str], warnings: list[str]) -> Path:
    """pandoc で HTML を作り、Vivliostyle で PDF にする。ページ数に合わせてノドを決め直す。"""
    s = read_settings(cfg, writing_mode, warnings)
    geo: Geometry = s["geo"]
    work = output.parent / ".paperback" / output.stem
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # ---- pandoc: Markdown → HTML ----
    for src in [STYLES / "base.css", STYLES / f"{writing_mode}.css", STYLES / "print.css"]:
        shutil.copy2(src, work / src.name)
    css = ["base.css", f"{writing_mode}.css", "print.css", "page.css"]
    for i, extra in enumerate(list(cfg.get("css") or []) + list(s["css"])):
        p = book_dir / extra
        if not p.exists():
            raise PaperbackError(f"CSS が見つかりません: {p}")
        shutil.copy2(p, work / f"extra-{i}.css")
        css.append(f"extra-{i}.css")

    title = meta["title"][0]["text"]
    subtitle = next((t["text"] for t in meta["title"] if t.get("type") == "subtitle"), "")
    authors = [c["text"] for c in meta["creator"] if c.get("role") == "aut"]
    kbt = dict(meta["kbt"])
    kbt["images"] = collect_images(book_dir, work)
    html_meta = {
        "title": title,
        "subtitle": subtitle,
        "author": authors,
        "lang": meta.get("lang", "ja"),
        "toc-title": meta.get("toc-title", "目次"),
        "css": css,
        "kbt": kbt,
        "pb": {
            "publisher": meta.get("publisher", ""),
            "date": format_date(str(cfg.get("date") or "")),
            "rights": meta.get("rights", ""),
            "isbn": s["isbn"],
            "notes": s["notes"],
            "colophon": s["colophon"],
            "author_suffix": s["author_suffix"],
        },
    }
    meta_file = work / "metadata.json"
    meta_file.write_text(json.dumps(html_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    html_file = work / "index.html"
    cmd = pandoc_cmd + [
        "--to", "html5",
        "--standalone",
        "--template", str(TEMPLATE),
        "--section-divs",
        "--reference-location=section",
        "--metadata-file", str(meta_file),
        "-o", str(html_file),
    ] + [str(c) for c in chapters]
    if args.verbose:
        log(" ".join(cmd))
    result = subprocess.run(cmd, cwd=book_dir, capture_output=True, text=True)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise PaperbackError(f"pandoc が失敗しました（終了コード {result.returncode}）")
    html_text = html_file.read_text(encoding="utf-8")

    # ---- Vivliostyle: HTML → PDF（ノドが KDP の最小値を満たすまで組み直す） ----
    viv = find_vivliostyle()
    gutter = geo.gutter_for(MIN_PAGES)
    info = None
    for attempt in range(4):
        (work / "page.css").write_text(page_css(s, gutter, writing_mode), encoding="utf-8")
        cmd = viv + [
            "build", "index.html",
            "-o", str(output),
            "--reading-progression", "rtl" if writing_mode == "vertical" else "ltr",
            "--log-level", "info" if args.verbose else "silent",
            "--timeout", str(getattr(args, "timeout", None) or 600),
        ] + browser_args(args)
        log(f"Vivliostyle で組版します（判型 {geo.trim_label}、ノド {fmt_mm(gutter)}）")
        if args.verbose:
            log(" ".join(cmd))
        result = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
        if result.returncode != 0 or not output.exists():
            sys.stderr.write(result.stdout + result.stderr)
            raise PaperbackError(f"Vivliostyle が失敗しました（終了コード {result.returncode}）")
        info = inspect_pdf(output)
        need = geo.gutter_for(info["pages"])
        if need <= gutter + 1e-9:
            break
        log(f"{info['pages']} ページのため、ノドを {fmt_mm(need)} 以上にして組み直します")
        gutter = need
    else:
        raise PaperbackError("ノドの幅が決まりませんでした")

    verify_pdf(output, info, geo, gutter, warnings)
    check_image_resolution(html_text, work, geo.text_width(gutter), warnings)
    report_cover(info["pages"], geo, s["paper"])
    if not getattr(args, "keep_html", False):
        shutil.rmtree(work, ignore_errors=True)
    else:
        log(f"組版用の HTML を残しました: {html_file}")
    return output


def format_date(value: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
    if m:
        return f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日"
    return value


def verify_pdf(path: Path, info: dict, geo: Geometry, gutter: float, warnings: list[str]) -> None:
    """KDP の要件を満たしているか確認する（満たさなければエラー、注意点は警告）。"""
    pages = info["pages"]
    if pages == 0:
        raise PaperbackError(f"PDF のページ数を数えられませんでした: {path}")
    want = (round(geo.page_w, 3), round(geo.page_h, 3))
    bad = [sz for sz in info["sizes"] if abs(sz[0] - want[0]) > 0.01 or abs(sz[1] - want[1]) > 0.01]
    if bad:
        raise PaperbackError(f"PDF のページサイズ {bad[0][0]}×{bad[0][1]} インチが期待値 "
                             f"{want[0]}×{want[1]} インチと違います")
    if info["unembedded"]:
        raise PaperbackError("PDF にフォントが埋め込まれていません（KDP ではすべてのフォントの埋め込みが必要です）")
    if pages < MIN_PAGES:
        warnings.append(f"{pages} ページです。KDP のペーパーバックは {MIN_PAGES} ページ以上が必要です")
    if pages > MAX_PAGES:
        warnings.append(f"{pages} ページです。KDP のペーパーバックの上限（{MAX_PAGES} ページ、判型・用紙で変わる）を超えています")
    if pages % 2:
        warnings.append(f"{pages} ページ（奇数）です。KDP は偶数に切り上げ、最後に白紙ページを 1 枚足します")
    fonts = ", ".join(sorted({f.split("+", 1)[-1] for f in info["fonts"]})) or "（不明）"
    log(f"PDF を確認しました: {pages} ページ、ページサイズ {want[0]}×{want[1]} インチ"
        f"（{fmt_mm(geo.page_w)}×{fmt_mm(geo.page_h)}）、ノド {fmt_mm(gutter)}、埋め込みフォント: {fonts}")


def report_cover(pages: int, geo: Geometry, paper: str) -> None:
    """表紙（表 1・背・表 4 を 1 枚にした PDF）を作るときの寸法を表示する。"""
    even = pages + pages % 2
    spine = even * PAPER_THICKNESS[paper]
    width = BLEED_IN + geo.trim_w + spine + geo.trim_w + BLEED_IN
    height = BLEED_IN + geo.trim_h + BLEED_IN
    paper_ja = {"white": "白・モノクロ", "cream": "クリーム・モノクロ", "color": "カラー"}[paper]
    log(f"表紙 PDF の寸法（{paper_ja}、{even} ページ）: 幅 {width:.3f} × 高さ {height:.3f} インチ"
        f"（{fmt_mm(width)}×{fmt_mm(height)}）、背幅 {spine:.3f} インチ（{fmt_mm(spine)}）"
        + ("" if even > 79 else "。80 ページ未満なので背表紙に文字は入れられません"))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build

    sys.exit(build.main(["--paperback", *sys.argv[1:]]))
