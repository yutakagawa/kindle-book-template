#!/usr/bin/env python3
"""book.yaml の書誌情報から Kindle (KDP) 用の表紙画像を生成するスクリプト。

使い方:
    python3 scripts/cover.py books/horizontal-sample              # → dist/horizontal-sample-cover.jpg
    python3 scripts/cover.py --all                                # books/ 以下を全部
    python3 scripts/cover.py books/my-book --style vertical       # 縦書きデザインで生成
    python3 scripts/cover.py books/my-book -o cover.jpg           # 出力先を指定（.tif なら TIFF）
    python3 scripts/cover.py books/my-book --background images/bg.jpg

book.yaml に cover_design があれば、scripts/build.py がビルドのたびにこの処理で表紙を作り、
EPUB の表紙（cover-image）として埋め込みます。

出力は KDP の電子書籍の表紙の推奨値に合わせています（README「表紙の自動生成」参照）:
    幅 1600 × 高さ 2560 px（高さ:幅 = 1.6:1）、JPEG、RGB（sRGB プロファイル埋め込み）、300 ppi、50MB 以下
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__":
    # bash scripts/setup.sh が作った .venv があれば、その Python（PyYAML・Pillow 入り）で起動し直す
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from use_venv import reexec_in_venv
    reexec_in_venv(__file__)

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要です: bash scripts/setup.sh を実行してください（.venv に入ります）")

ROOT = Path(__file__).resolve().parent.parent

# ---- KDP の推奨値 ------------------------------------------------------------
COVER_WIDTH = 1600            # px
COVER_HEIGHT = 2560           # px（高さ:幅 = 1.6:1）
COVER_DPI = 300               # KDP ヘルプの推奨解像度（ppi）
MIN_WIDTH, MIN_HEIGHT = 625, 1000
MAX_SIDE = 10000
MAX_FILE_BYTES = 50 * 1024 * 1024
JPEG_QUALITY = 92

# 和文フォントの em ボックス上端からベースラインまでの距離（多くの和文フォントは 880/1000）
EM_ASCENT = 0.88


class CoverError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[cover] {msg}", file=sys.stderr)


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat, features
    except ImportError:
        raise CoverError("表紙の生成には Pillow が必要です: pip install -r requirements.txt")
    return Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat, features


# =============================================================================
# フォント
# =============================================================================

FAMILIES = {
    "serif": [
        "Noto Serif CJK JP", "Noto Serif JP", "Source Han Serif JP", "Source Han Serif",
        "BIZ UDPMincho", "BIZ UDMincho", "Hiragino Mincho ProN", "Hiragino Mincho Pro",
        "Yu Mincho", "YuMincho", "IPAexMincho", "IPAPMincho", "IPAMincho", "MS PMincho", "MS Mincho",
    ],
    "sans": [
        "Noto Sans CJK JP", "Noto Sans JP", "Source Han Sans JP", "Source Han Sans",
        "BIZ UDPGothic", "BIZ UDGothic", "Hiragino Kaku Gothic ProN", "Hiragino Sans",
        "Yu Gothic", "YuGothic", "Meiryo", "IPAexGothic", "IPAPGothic", "IPAGothic", "MS PGothic",
    ],
}

# fontconfig が無い環境（Windows / 一部の macOS）向けの既知のパス。（太字, 標準）の順
FONT_PATHS = {
    "serif": [
        ("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        ("C:/Windows/Fonts/yumindb.ttf", "C:/Windows/Fonts/yumin.ttf"),
        ("C:/Windows/Fonts/BIZ-UDMinchoM.ttc", "C:/Windows/Fonts/BIZ-UDMinchoM.ttc"),
        ("C:/Windows/Fonts/msmincho.ttc", "C:/Windows/Fonts/msmincho.ttc"),
    ],
    "sans": [
        ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
        ("C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/YuGothM.ttc"),
        ("C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/meiryo.ttc"),
        ("C:/Windows/Fonts/msgothic.ttc", "C:/Windows/Fonts/msgothic.ttc"),
    ],
}

WEIGHT_WORDS = [
    ("extralight", 200), ("ultralight", 200), ("thin", 100), ("light", 300),
    ("semibold", 600), ("demibold", 600), ("extrabold", 800), ("ultrabold", 800),
    ("black", 900), ("heavy", 900), ("bold", 700), ("medium", 500),
    ("regular", 400), ("normal", 400), ("book", 400), ("roman", 400),
]


@dataclass(frozen=True)
class FontSpec:
    path: str
    index: int = 0

    def label(self) -> str:
        return f"{Path(self.path).name}" + (f"#{self.index}" if self.index else "")


def style_weight(style: str) -> int:
    s = style.lower().replace(" ", "").replace("-", "")
    m = re.search(r"w(\d)", s)
    if m:
        return int(m.group(1)) * 100
    for word, w in WEIGHT_WORDS:
        if word in s:
            return w
    return 400


def fontconfig_fonts() -> list[tuple[str, int, list[str], str]]:
    if not shutil.which("fc-list"):
        return []
    try:
        out = subprocess.run(
            ["fc-list", ":lang=ja", "--format", "%{file}|%{index}|%{family}|%{style}\n"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    fonts = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        path, index, family, style = parts
        families = [f.strip().replace("\\-", "-") for f in family.split(",")]
        # 複数の言語のスタイル名が並ぶことがあるので、英語らしい最初のものを使う
        style = style.split(",")[0]
        try:
            fonts.append((path, int(index or 0), families, style))
        except ValueError:
            continue
    return fonts


_FC_CACHE: list | None = None


def find_font(kind: str, weight: int) -> FontSpec | None:
    """和文フォントを探す。kind は serif / sans、weight は 400（標準）や 700（太字）。"""
    global _FC_CACHE
    if _FC_CACHE is None:
        _FC_CACHE = fontconfig_fonts()
    for family in FAMILIES[kind]:
        cands = [f for f in _FC_CACHE if any(name.lower() == family.lower() for name in f[2])]
        if cands:
            path, index, _, _ = min(cands, key=lambda f: (abs(style_weight(f[3]) - weight), f[0]))
            return FontSpec(path, index)
    for bold, regular in FONT_PATHS[kind]:
        path = bold if weight >= 600 else regular
        if Path(path).exists():
            return FontSpec(path, 0)
    return None


def resolve_font(value, weight: int, book_dir: Path, warnings: list[str]) -> FontSpec:
    value = value or "serif"
    if isinstance(value, dict):
        path, index = value.get("path"), int(value.get("index", 0))
    else:
        path, index = str(value), 0
    if path in ("serif", "sans", "mincho", "gothic"):
        kind = "serif" if path in ("serif", "mincho") else "sans"
        spec = find_font(kind, weight)
        if spec is None:
            other = "sans" if kind == "serif" else "serif"
            spec = find_font(other, weight)
            if spec is not None:
                warnings.append(f"{'明朝' if kind == 'serif' else 'ゴシック'}体の和文フォントが見つからないため {spec.label()} を使います")
        if spec is None:
            raise CoverError(
                "日本語フォントが見つかりません。Noto CJK などをインストールするか、"
                "cover_design.font にフォントファイルのパスを書いてください"
                "（Ubuntu: sudo apt install fonts-noto-cjk / macOS・Windows は標準のフォントで動きます）"
            )
        return spec
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (book_dir / p) if (book_dir / p).exists() else (ROOT / p)
    if not p.exists():
        raise CoverError(f"フォントが見つかりません: {path}")
    return FontSpec(str(p), index)


# =============================================================================
# テキストの分割（禁則処理つき）
# =============================================================================

# 行頭に来てはいけない文字（前の文字にくっつける）
NO_START = set(
    "、。，．,.・：；:;？！?!‼⁇⁈⁉ー‐－–—―〜～…‥）)」』】〕］]｝}〉》〟’”"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ々ゝゞヽヾ"
)
# 行末に来てはいけない文字（次の文字にくっつける）
NO_END = set("（(「『【〔［[｛{〈《〝‘“")

PARTICLES = set("のはがをにでともへや")

TOKEN_RE = re.compile(r"\n|[ \t]+|\u3000|[!-~]+|.", re.S)


@dataclass
class Token:
    text: str
    kind: str  # cjk / latin / space / nl


@dataclass
class Atom:
    tokens: list[Token] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(t.text for t in self.tokens)

    @property
    def kind(self) -> str:
        return self.tokens[0].kind if len(self.tokens) == 1 and self.tokens[0].kind in ("space", "nl") else "word"


def tokenize(text: str) -> list[Token]:
    tokens = []
    for m in TOKEN_RE.finditer(text):
        s = m.group(0)
        if s == "\n":
            kind = "nl"
        elif s.isspace():
            kind = "space"
        elif s.isascii():
            kind = "latin"
        else:
            kind = "cjk"
        tokens.append(Token(s, kind))
    return tokens


def make_atoms(text: str) -> list[Atom]:
    """改行してよい位置で区切った単位（Atom）に分ける。英単語は分割せず、禁則文字は前後にくっつける。"""
    text = re.sub(r"\n\s*\n+", "\n", text.strip())
    atoms: list[Atom] = []
    glue_next = False
    for tok in tokenize(text):
        if tok.kind in ("space", "nl"):
            atoms.append(Atom([tok]))
            glue_next = False
            continue
        prev_word = atoms and atoms[-1].kind == "word"
        if prev_word and (glue_next or tok.text[0] in NO_START):
            atoms[-1].tokens.append(tok)
        else:
            atoms.append(Atom([tok]))
        glue_next = tok.text[-1] in NO_END
    return atoms


def char_class(ch: str) -> str:
    o = ord(ch)
    if ch.isascii():
        return "latin" if ch.isalnum() else "punct"
    if 0x3041 <= o <= 0x309F:
        return "hira"
    if 0x30A0 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
        return "kata"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or ch in "々〆ヶ":
        return "kanji"
    if 0xFF10 <= o <= 0xFF5A:
        return "latin"
    return "punct"


def break_penalty(a: Atom, b: Atom) -> float:
    """a と b の間で改行したときの不自然さ（0 = 自然）。"""
    if a.kind != "word" or b.kind != "word":
        return 0.0
    last, first = a.text[-1], b.text[0]
    ca, cb = char_class(last), char_class(first)
    if ca == "punct" or cb == "punct":
        return 0.0
    if ca == "hira" and last in PARTICLES and cb != "hira":
        return 0.2
    if ca == "hira" and last in PARTICLES:
        return 0.6
    if ca != cb:
        # 漢字→ひらがなは送り仮名の途中（「作|る」）のことが多いので避ける
        return {("hira", "kanji"): 0.4, ("kanji", "hira"): 2.5}.get((ca, cb), 0.6)
    return 3.0  # 同じ文字種の途中（単語の途中である可能性が高い）


# =============================================================================
# 計測・配置
# =============================================================================

class Fonts:
    def __init__(self, spec: FontSpec):
        self.spec = spec
        self._cache: dict[int, object] = {}
        _, _, _, ImageFont, _, _, features = _pil()
        self._ImageFont = ImageFont
        self.raqm = bool(features.check("raqm"))

    def get(self, size: int):
        if size not in self._cache:
            try:
                self._cache[size] = self._ImageFont.truetype(self.spec.path, size, index=self.spec.index)
            except OSError as e:
                raise CoverError(f"フォントを読み込めません: {self.spec.path}（{e}）")
        return self._cache[size]


def is_tcy(text: str) -> bool:
    """縦中横（横に並べて 1 文字分に収める）にする英数字か。"""
    return bool(re.fullmatch(r"\d{1,2}|[!?]{1,2}|[A-Za-z]", text))


@dataclass
class Element:
    text: str
    fonts: Fonts
    vertical: bool
    max_size: int
    min_size: int
    max_lines: int
    pitch: float          # 行（列）送り / 文字サイズ
    tracking: float = 0.0  # 字間（em）。縦書きのみ
    palt: bool = False     # 横書きでプロポーショナル詰めを使う


@dataclass
class Layout:
    size: int
    lines: list[list[Atom]]
    widths: list[float]  # 各行の長さ（px）
    cost: float = 0.0    # 不自然な改行と行の長さの不揃いの合計（小さいほど自然）

    @property
    def count(self) -> int:
        return len(self.lines)


def token_advance(tok: Token, font, size: int, el: Element) -> float:
    if tok.kind == "space":
        return size * (1.0 if tok.text == "\u3000" else 0.5)
    if tok.kind == "latin":
        if is_tcy(tok.text):
            return size * (1 + el.tracking)
        return font.getlength(tok.text) + size * el.tracking
    return size * (1 + el.tracking) * len(tok.text)


def atom_length(atom: Atom, font, size: int, el: Element) -> float:
    if atom.kind == "nl":
        # 改行は文字ではないので測らない（libraqm で "\n" を測ると Pillow 13 では RuntimeError になる）
        return 0.0
    if el.vertical:
        return sum(token_advance(t, font, size, el) for t in atom.tokens)
    if atom.kind == "space":
        return font.getlength(atom.text)
    if el.palt and el.fonts.raqm:
        return font.getlength(atom.text, features=["palt"])
    return font.getlength(atom.text)


def line_text_length(atoms: list[Atom], font, size: int, el: Element) -> float:
    atoms = trim(atoms)
    if not el.vertical:
        text = "".join(a.text for a in atoms)
        if el.palt and el.fonts.raqm:
            return font.getlength(text, features=["palt"])
        return font.getlength(text)
    total = sum(atom_length(a, font, size, el) for a in atoms)
    return total - size * el.tracking if atoms else 0.0


def trim(atoms: list[Atom]) -> list[Atom]:
    s, e = 0, len(atoms)
    while s < e and atoms[s].kind == "space":
        s += 1
    while e > s and atoms[e - 1].kind == "space":
        e -= 1
    return atoms[s:e]


def partition(atoms: list[Atom], lengths: list[float], limit: float, n: int) -> tuple[float, list[tuple[int, int]]] | None:
    """atoms を n 行にちょうど分ける最良の分け方（行の長さが揃い、自然な位置で改行するもの）。"""
    m = len(atoms)
    prefix = [0.0]
    for x in lengths:
        prefix.append(prefix[-1] + x)

    def width(i: int, j: int) -> float:
        while i < j and atoms[i].kind == "space":
            i += 1
        while j > i and atoms[j - 1].kind == "space":
            j -= 1
        return prefix[j] - prefix[i]

    total = sum(lengths[i] for i in range(m) if atoms[i].kind == "word")
    mean = total / n
    INF = float("inf")
    # dp[k][p]: 先頭から k 行を置いて、次の行が p から始まるときの最小コスト
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(n):
        for p in range(m):
            if dp[k][p] == INF:
                continue
            for j in range(p + 1, m + 1):
                if atoms[j - 1].kind == "nl":
                    break
                w = width(p, j)
                if w > limit:
                    break
                if w == 0:
                    continue
                if j < m and atoms[j].kind == "nl":
                    nxt, pen = j + 1, 0.0
                else:
                    nxt = j
                    pen = break_penalty(atoms[j - 1], atoms[j]) if j < m else 0.0
                # 明示的な改行で区切られた行は長さを揃えなくてよい
                bal = 0.0 if any(a.kind == "nl" for a in atoms) else ((w - mean) / limit) ** 2 * 6
                cost = dp[k][p] + bal + pen
                if cost < dp[k + 1][nxt]:
                    dp[k + 1][nxt] = cost
                    back[k + 1][nxt] = (p, j)
    if dp[n][m] == INF:
        return None
    ranges = []
    k, p = n, m
    while k > 0:
        s, e = back[k][p]
        ranges.append((s, e))
        p, k = s, k - 1
    return dp[n][m], ranges[::-1]


def layout_at(el: Element, atoms: list[Atom], size: int, limit: float, stack: float,
              split_words: bool = False) -> Layout | None:
    font = el.fonts.get(size)
    lengths = [atom_length(a, font, size, el) for a in atoms]
    # 1 つの単語が行に収まらないときは文字単位で分ける（split_words のときだけ）
    if any(l > limit and a.kind == "word" for a, l in zip(atoms, lengths)):
        if not split_words:
            return None
        split: list[Atom] = []
        for a, l in zip(atoms, lengths):
            if l > limit and a.kind == "word":
                for t in a.tokens:
                    for ch in t.text:
                        split.append(Atom([Token(ch, t.kind)]))
            else:
                split.append(a)
        atoms = split
        lengths = [atom_length(a, font, size, el) for a in atoms]
        if any(l > limit for a, l in zip(atoms, lengths) if a.kind == "word"):
            return None
    forced = sum(1 for a in atoms if a.kind == "nl") + 1
    best: tuple[float, Layout] | None = None
    for n in range(forced, el.max_lines + 1):
        extent = size * (1 + (n - 1) * el.pitch)
        if extent > stack:
            break
        res = partition(atoms, lengths, limit, n)
        if res is None:
            continue
        lines = [trim(atoms[s:e]) for s, e in res[1]]
        widths = [line_text_length(l, font, size, el) for l in lines]
        if max(widths) > limit:  # カーニング等で実測が長くなった
            continue
        # 行数は少ないほうがよいが、不自然な改行を避けるためなら 1 行増やしてもよい
        cost = res[0] + (n - forced) * 1.5
        if best is None or cost < best[0]:
            best = (cost, Layout(size, lines, widths, cost))
    return best[1] if best else None


# 自然な改行のために文字を小さくしてよい割合と、縮小 1 割あたりのコスト
SHRINK_RANGE = 0.15
SHRINK_COST = 10.0


def prefer_natural_breaks(el: Element, atoms: list[Atom], best: Layout, limit: float, stack: float) -> Layout:
    """最大の文字サイズでは不自然な位置（「作|る」など）でしか改行できないとき、少し小さくして自然に改行できるサイズを選ぶ。"""
    # 小さくするほど単語は行に収まりやすくなるので、単語の途中で分けるのは best でも分けていたときだけになる
    lowest = max(el.min_size, int(best.size * (1 - SHRINK_RANGE)))
    chosen, chosen_score = best, best.cost
    for size in range(best.size - 1, lowest - 1, -1):
        lay = layout_at(el, atoms, size, limit, stack, split_words=True)
        if lay is None:
            continue
        score = lay.cost + (1 - size / best.size) * SHRINK_COST
        if score < chosen_score:
            chosen, chosen_score = lay, score
    return chosen


def fit(el: Element, limit: float, stack: float, name: str, warnings: list[str]) -> Layout | None:
    """枠（行の長さ limit × 積み重ね方向 stack）に収まる最大の文字サイズで配置する。"""
    if not el.text.strip():
        return None
    atoms = make_atoms(el.text)

    forced = sum(1 for a in atoms if a.kind == "nl") + 1

    def search(split_words: bool, max_lines: int = el.max_lines) -> Layout | None:
        e = Element(**{**el.__dict__, "max_lines": max_lines})
        lo, hi, found = 8, el.max_size, None
        while lo <= hi:  # 二分探索（大きいほど行数が増え、収まりにくくなる）
            mid = (lo + hi) // 2
            lay = layout_at(e, atoms, mid, limit, stack, split_words)
            if lay:
                found, lo = lay, mid + 1
            else:
                hi = mid - 1
        return found

    # まずは英単語を途中で切らずに縮小で収め、小さくなりすぎるときだけ単語の途中でも改行する
    # \n で改行位置が指定されていれば、まずはそのとおりの行数で収める
    best = search(False, forced) if forced > 1 else None
    if best is None or best.size < el.min_size:
        best = search(False)
    if best is None or best.size < el.min_size * 0.6:
        split = search(True)
        if split and (best is None or split.size > best.size):
            best = split
    if best is None:
        raise CoverError(f"{name}が長すぎて表紙に収まりません: {el.text!r}")
    best = prefer_natural_breaks(el, atoms, best, limit, stack)
    if best.size < el.min_size:
        warnings.append(f"{name}が長いため文字を小さくしました（{best.size}px）。サムネイルで読みにくい場合は短くするか cover_design で改行位置を指定してください")
    return best


# =============================================================================
# 描画
# =============================================================================

ROTATE = set("ー‐－–—―〜～…‥（）()「」『』【】〔〕［］[]｛｝{}〈〉《》<>＜＞＝=→←")
SHIFT_UP_RIGHT = {"、": 0.55, "。": 0.55, "，": 0.55, "．": 0.55}
SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")


@dataclass
class Placed:
    x0: float
    y0: float
    x1: float
    y1: float


class Painter:
    def __init__(self, layer, color):
        Image, ImageDraw, *_ = _pil()
        self.Image = Image
        self.layer = layer
        self.draw = ImageDraw.Draw(layer)
        self.color = color

    # ---- 横書き -------------------------------------------------------------
    def horizontal(self, el: Element, lay: Layout, box: tuple, align: str = "center", valign: str = "center") -> Placed:
        x0, y0, x1, y1 = box
        font = el.fonts.get(lay.size)
        size = lay.size
        extent = size * (1 + (lay.count - 1) * el.pitch)
        top = {"start": y0, "center": (y0 + y1 - extent) / 2, "end": y1 - extent}[valign]
        kw = {"features": ["palt"]} if el.palt and el.fonts.raqm else {}
        left_most, right_most = x1, x0
        for i, (atoms, w) in enumerate(zip(lay.lines, lay.widths)):
            x = {"start": x0, "center": (x0 + x1 - w) / 2, "end": x1 - w}[align]
            baseline = top + i * size * el.pitch + EM_ASCENT * size
            self.draw.text((x, baseline), "".join(a.text for a in atoms), font=font, fill=self.color, anchor="ls", **kw)
            left_most, right_most = min(left_most, x), max(right_most, x + w)
        return Placed(left_most, top, right_most, top + extent)

    # ---- 縦書き -------------------------------------------------------------
    def vertical(self, el: Element, lay: Layout, box: tuple, align: str = "start", halign: str = "start") -> Placed:
        """縦書き。列は右から左へ。halign は列の並び（start = 右寄せ）、align は列内の天地（start = 天）。"""
        x0, y0, x1, y1 = box
        size = lay.size
        font = el.fonts.get(size)
        extent = size * (1 + (lay.count - 1) * el.pitch)
        right = {"start": x1, "center": (x0 + x1 + extent) / 2, "end": x0 + extent}[halign]
        tops = []
        for i, (atoms, length) in enumerate(zip(lay.lines, lay.widths)):
            cx = right - size / 2 - i * size * el.pitch
            y = {"start": y0, "center": (y0 + y1 - length) / 2, "end": y1 - length}[align]
            tops.append((y, y + length))
            for atom in atoms:
                for tok in atom.tokens:
                    y += self._vtoken(tok, font, size, cx, y, el)
        return Placed(right - extent, min(t[0] for t in tops), right, max(t[1] for t in tops))

    def _vtoken(self, tok: Token, font, size: int, cx: float, y: float, el: Element) -> float:
        adv = token_advance(tok, font, size, el)
        track = size * el.tracking
        if tok.kind == "space":
            return adv
        if tok.kind == "latin":
            if is_tcy(tok.text):
                self._paste_upright(tok.text, font, size, cx, y)
            else:
                self._paste_rotated(tok.text, font, size, cx, y)
            return adv
        for ch in tok.text:
            self._vchar(ch, font, size, cx, y)
            y += size + track
        return adv

    def _vchar(self, ch: str, font, size: int, cx: float, y: float) -> None:
        left, baseline = cx - size / 2, y + EM_ASCENT * size
        if ch == " " or ch == "\u3000":
            return
        # libraqm があれば、フォントの縦書き用字形（vert）を使う。句読点・小書き・括弧・長音も正しくなる
        raqm_ok = getattr(self, "_raqm", None)
        if raqm_ok is None:
            _, _, _, _, _, _, features = _pil()
            raqm_ok = self._raqm = bool(features.check("raqm"))
        if raqm_ok:
            self.draw.text((left, baseline), ch, font=font, fill=self.color, anchor="ls", features=["vert", "vrt2"])
            return
        # libraqm が無いときの代替: 回転・位置ずらしで近似する
        if ch in ROTATE:
            self._paste_rotated(ch, font, size, cx, y, center=True)
        elif ch in SHIFT_UP_RIGHT:
            d = SHIFT_UP_RIGHT[ch] * size
            self.draw.text((left + d, baseline - d), ch, font=font, fill=self.color, anchor="ls")
        elif ch in SMALL_KANA:
            d = 0.1 * size
            self.draw.text((left + d, baseline - d), ch, font=font, fill=self.color, anchor="ls")
        else:
            self.draw.text((left, baseline), ch, font=font, fill=self.color, anchor="ls")

    def _render(self, text: str, font, size: int):
        w = max(1, int(round(font.getlength(text))) + 2)
        img = self.Image.new("RGBA", (w, size), (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(img).text((1, EM_ASCENT * size), text, font=font, fill=self.color, anchor="ls")
        return img

    def _paste_rotated(self, text: str, font, size: int, cx: float, y: float, center: bool = False) -> None:
        """英単語などを時計回りに 90° 回して置く（縦書きの横倒し）。"""
        img = self._render(text, font, size).rotate(-90, expand=True)
        # 回転後: 幅 = size（em ボックスの高さ）、高さ = 文字列の長さ
        x = int(round(cx - img.width / 2))
        self.layer.alpha_composite(img, (x, int(round(y))))

    def _paste_upright(self, text: str, font, size: int, cx: float, y: float) -> None:
        """縦中横: 横に並べて 1 文字分の幅に収める。"""
        img = self._render(text, font, size)
        limit = int(size * 0.95)
        if img.width > limit:
            img = img.resize((limit, img.height), self.Image.LANCZOS)
        self.layer.alpha_composite(img, (int(round(cx - img.width / 2)), int(round(y))))


# =============================================================================
# 背景
# =============================================================================

def parse_color(value, name: str) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(int(v) for v in value)
    s = str(value).strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})", s)
    if not m:
        raise CoverError(f"{name} の色の形式が正しくありません（例: \"#1d3557\"）: {value}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient(size: tuple[int, int], colors: list[tuple[int, int, int]], direction: str):
    Image, *_ = _pil()
    w, h = size
    if len(colors) == 1:
        return Image.new("RGB", size, colors[0])
    # 縮小した画像で計算してから拡大する（なめらかで速い）
    sw, sh = max(2, w // 8), max(2, h // 8)
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    n = len(colors) - 1
    for yy in range(sh):
        for xx in range(sw):
            fx, fy = xx / (sw - 1), yy / (sh - 1)
            if direction == "horizontal":
                t = fx
            elif direction == "diagonal":
                t = (fx + fy) / 2
            elif direction == "radial":
                t = min(1.0, (((fx - 0.5) ** 2 + (fy - 0.4) ** 2) ** 0.5) / 0.75)
            else:  # vertical
                t = fy
            seg = min(int(t * n), n - 1)
            lt = t * n - seg
            c0, c1 = colors[seg], colors[seg + 1]
            px[xx, yy] = tuple(int(round(c0[i] + (c1[i] - c0[i]) * lt)) for i in range(3))
    return small.resize(size, Image.BICUBIC)


def load_background(path: Path, size: tuple[int, int], position, warnings: list[str]):
    Image, _, _, _, ImageOps, _, _ = _pil()
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                base = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(base, im)
            im = im.convert("RGB")
    except OSError as e:
        raise CoverError(f"背景画像を開けません: {path}（{e}）")
    w, h = im.size
    scale = max(size[0] / w, size[1] / h)
    if scale > 1.05:
        warnings.append(
            f"背景画像が小さいため {scale:.1f} 倍に拡大しました（{w}×{h}px）。"
            f"{size[0]}×{size[1]}px 以上の画像を使うときれいです"
        )
    return ImageOps.fit(im, size, method=Image.LANCZOS, centering=position)


# =============================================================================
# 表紙の組み立て
# =============================================================================

STYLE_DEFAULTS = {
    "horizontal": {"colors": ["#14213d", "#2c4f7c"], "gradient": "diagonal", "accent_color": "#e2b450", "font": "sans"},
    "vertical": {"colors": ["#f7f2e8", "#e8dcc6"], "gradient": "vertical", "accent_color": "#a33a2a", "font": "serif"},
}


@dataclass
class CoverText:
    title: str
    subtitle: str
    author: str


def texts_from_config(cfg: dict, design: dict) -> CoverText:
    title = design.get("title", cfg.get("title"))
    if not title:
        raise CoverError("book.yaml に title がありません")
    subtitle = design.get("subtitle", cfg.get("subtitle")) or ""
    author = design.get("author")
    if author is None:
        raw = cfg.get("author") or []
        names = [a if isinstance(a, str) else (a or {}).get("name", "") for a in (raw if isinstance(raw, list) else [raw])]
        author = "・".join(n for n in names if n)
    author = str(author or "")
    if author and design.get("author_suffix"):
        author += str(design["author_suffix"])
    return CoverText(str(title), str(subtitle), author)


def render_cover(cfg: dict, book_dir: Path, style: str, warnings: list[str], design: dict | None = None):
    """表紙画像（PIL.Image, RGB）を作る。"""
    Image, ImageDraw, ImageFilter, _, _, ImageStat, _ = _pil()
    design = design_of(cfg) if design is None else dict(design)
    if style not in STYLE_DEFAULTS:
        raise CoverError(f"cover_design.style は vertical / horizontal / auto のいずれかです: {style}")
    d = {**STYLE_DEFAULTS[style], **{k: v for k, v in design.items() if v is not None}}
    W = int(d.get("width", COVER_WIDTH))
    H = int(d.get("height", COVER_HEIGHT))
    if W < MIN_WIDTH or H < MIN_HEIGHT or max(W, H) > MAX_SIDE:
        raise CoverError(f"表紙のサイズは幅 {MIN_WIDTH}〜{MAX_SIDE}px・高さ {MIN_HEIGHT}〜{MAX_SIDE}px にしてください（{W}×{H}）")
    if abs(H / W - 1.6) > 0.01:
        warnings.append(f"表紙のサイズ {W}×{H}px は KDP の推奨比率（高さ:幅 = 1.6:1）と異なります")
    s = W / COVER_WIDTH  # 文字サイズなどの基準（1600px 幅のときに 1）
    texts = texts_from_config(cfg, design)

    # ---- 背景 ----
    bg_value = d.get("background")
    if bg_value:
        bg_path = (book_dir / bg_value).resolve()
        if not bg_path.exists():
            raise CoverError(f"背景画像が見つかりません: {bg_path}")
        pos = d.get("background_position", [0.5, 0.5])
        if isinstance(pos, str):
            pos = {"top": (0.5, 0.0), "center": (0.5, 0.5), "bottom": (0.5, 1.0)}.get(pos, (0.5, 0.5))
        bg = load_background(bg_path, (W, H), tuple(float(v) for v in pos), warnings)
        overlay = float(d.get("overlay", 0.35))
        if overlay > 0:
            ov = Image.new("RGB", (W, H), parse_color(d.get("overlay_color", "#000000"), "overlay_color"))
            bg = Image.blend(bg, ov, min(overlay, 1.0))
    else:
        colors = d.get("colors")
        if isinstance(colors, str):
            colors = [colors]
        if not colors:
            raise CoverError("cover_design.colors に 1 色以上を指定してください")
        direction = d.get("gradient", "vertical")
        if direction not in ("vertical", "horizontal", "diagonal", "radial"):
            raise CoverError(f"cover_design.gradient は vertical / horizontal / diagonal / radial のいずれかです: {direction}")
        bg = gradient((W, H), [parse_color(c, "colors") for c in colors], direction)

    # ---- 文字色（auto なら背景の明るさで白か黒を選ぶ） ----
    text_color = d.get("text_color", "auto")
    if text_color == "auto":
        lum = ImageStat.Stat(bg.convert("L")).mean[0]
        text_rgb = (30, 30, 30) if lum > 150 else (255, 255, 255)
    else:
        text_rgb = parse_color(text_color, "text_color")
    accent = parse_color(d.get("accent_color"), "accent_color")
    deco = bool(d.get("decoration", True))

    # ---- フォント ----
    base_font = d.get("font")
    title_fonts = Fonts(resolve_font(d.get("title_font", base_font), 700, book_dir, warnings))
    sub_fonts = Fonts(resolve_font(d.get("subtitle_font", base_font), 500, book_dir, warnings))
    author_fonts = Fonts(resolve_font(d.get("author_font", base_font), 500, book_dir, warnings))
    if not title_fonts.raqm:
        warnings.append("Pillow が libraqm なしでビルドされているため、縦書きの約物は簡易的な配置になります")

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    painter = Painter(layer, text_rgb + (255,))
    draw = ImageDraw.Draw(layer)
    accent_rgba = accent + (255,)

    if style == "horizontal":
        mx = 0.09 * W
        title = Element(texts.title, title_fonts, False, int(190 * s), int(96 * s), 4, 1.28, palt=True)
        sub = Element(texts.subtitle, sub_fonts, False, int(84 * s), int(44 * s), 3, 1.45, palt=True)
        auth = Element(texts.author, author_fonts, False, int(76 * s), int(40 * s), 2, 1.4, palt=True)
        tbox = (mx, 0.15 * H, W - mx, 0.52 * H)
        lay = fit(title, tbox[2] - tbox[0], tbox[3] - tbox[1], "タイトル", warnings)
        painter.horizontal(title, lay, tbox, "center", "end" if texts.subtitle else "center")
        rule_y = 0.555 * H
        if deco:
            draw.rectangle((W / 2 - 0.09 * W, rule_y - 3 * s, W / 2 + 0.09 * W, rule_y + 3 * s), fill=accent_rgba)
        sbox = (mx, 0.59 * H, W - mx, 0.73 * H)
        lay = fit(sub, sbox[2] - sbox[0], sbox[3] - sbox[1], "サブタイトル", warnings)
        if lay:
            painter.horizontal(sub, lay, sbox, "center", "start")
        abox = (mx, 0.82 * H, W - mx, 0.91 * H)
        lay = fit(auth, abox[2] - abox[0], abox[3] - abox[1], "著者名", warnings)
        if lay:
            painter.horizontal(auth, lay, abox, "center", "center")
    else:
        title = Element(texts.title, title_fonts, True, int(230 * s), int(110 * s), 3, 1.32, tracking=0.06)
        sub = Element(texts.subtitle, sub_fonts, True, int(92 * s), int(48 * s), 2, 1.5, tracking=0.04)
        auth = Element(texts.author, author_fonts, True, int(80 * s), int(40 * s), 2, 1.5, tracking=0.04)
        if deco:
            inset, lw = 0.035 * W, max(2, int(4 * s))
            draw.rectangle((inset, inset, W - inset, H - inset), outline=accent_rgba, width=lw)
            draw.rectangle((inset + 3 * lw, inset + 3 * lw, W - inset - 3 * lw, H - inset - 3 * lw), outline=accent_rgba, width=max(1, lw // 2))
        tbox = (0.36 * W, 0.09 * H, 0.87 * W, 0.80 * H)
        lay = fit(title, tbox[3] - tbox[1], tbox[2] - tbox[0], "タイトル", warnings)
        tp = painter.vertical(title, lay, tbox, "start", "start")
        gap = 0.05 * W
        sbox = (0.10 * W, tbox[1] + 0.06 * H, tp.x0 - gap, 0.66 * H)
        lay = fit(sub, sbox[3] - sbox[1], sbox[2] - sbox[0], "サブタイトル", warnings) if sbox[2] - sbox[0] > 40 * s else None
        if lay:
            sp = painter.vertical(sub, lay, sbox, "start", "start")
            if deco:
                x = (tp.x0 + sp.x1) / 2
                draw.rectangle((x - 2 * s, sp.y0, x + 2 * s, sp.y1), fill=accent_rgba)
        elif texts.subtitle and sbox[2] - sbox[0] <= 40 * s:
            raise CoverError("タイトルが長いためサブタイトルを置く場所がありません。タイトルを短くするか cover_design.subtitle を空にしてください")
        abox = (0.09 * W, 0.70 * H, 0.32 * W, 0.91 * H)
        lay = fit(auth, abox[3] - abox[1], abox[2] - abox[0], "著者名", warnings)
        if lay:
            painter.vertical(auth, lay, abox, "end", "end")

    # ---- 影（背景画像の上では文字を読みやすくする） ----
    if d.get("shadow", bool(bg_value)):
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(10 * s))
        shadow_rgb = (0, 0, 0) if sum(text_rgb) > 384 else (255, 255, 255)
        shadow = Image.new("RGBA", (W, H), shadow_rgb + (0,))
        shadow.putalpha(alpha.point(lambda v: int(v * 0.6)))
        base = bg.convert("RGBA")
        base.alpha_composite(shadow, (int(4 * s), int(6 * s)))
    else:
        base = bg.convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")


def save_cover(img, output: Path) -> Path:
    Image, *_ = _pil()
    output.parent.mkdir(parents=True, exist_ok=True)
    kw: dict = {"dpi": (COVER_DPI, COVER_DPI)}
    try:
        from PIL import ImageCms
        kw["icc_profile"] = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:  # pragma: no cover - littlecms なしの Pillow
        pass
    ext = output.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        img.save(output, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True, **kw)
    elif ext in (".tif", ".tiff"):
        img.save(output, "TIFF", compression="tiff_lzw", **kw)
    else:
        raise CoverError(f"表紙は JPEG（.jpg）か TIFF（.tif）で保存します: {output.name}")
    if output.stat().st_size > MAX_FILE_BYTES:
        raise CoverError(f"表紙のファイルサイズが 50MB を超えました: {output}")
    return output


def resolve_style(cfg: dict, writing_mode: str | None, override: str | None = None) -> str:
    style = override or design_of(cfg).get("style", "auto")
    if style == "auto":
        style = writing_mode or (cfg.get("layout") or {}).get("writing_mode", "horizontal")
    return style


def design_enabled(cfg: dict) -> bool:
    """book.yaml に cover_design があるか（`cover_design:` だけ・`{}`・`true` でも既定のデザインで生成する）。"""
    return "cover_design" in cfg and cfg["cover_design"] is not False


def design_of(cfg: dict) -> dict:
    d = cfg.get("cover_design")
    if d is None or isinstance(d, bool):
        return {}
    if not isinstance(d, dict):
        raise CoverError("cover_design の形式が正しくありません")
    return dict(d)


def generate_book_cover(book_dir: Path, cfg: dict, output: Path, writing_mode: str | None,
                        warnings: list[str], style: str | None = None, background: str | None = None) -> Path:
    """book.yaml の設定から表紙を生成して output に保存する（build.py からも使う）。"""
    design = design_of(cfg)
    if background:
        design["background"] = str(Path(background).resolve())
    if cfg.get("cover") and design_enabled(cfg):
        warnings.append(f"cover_design があるため cover（{cfg['cover']}）ではなく自動生成した表紙を使います")
    style = resolve_style(cfg, writing_mode, style)
    img = render_cover(cfg, book_dir, style, warnings, design)
    return save_cover(img, output)


def default_output(book_dir: Path, cfg: dict, out_dir: Path) -> Path:
    stem = Path(cfg.get("output") or f"{book_dir.name}.epub").stem
    return out_dir / f"{stem}-cover.jpg"


def load_config(book_dir: Path) -> dict:
    path = book_dir / "book.yaml"
    if not path.exists():
        raise CoverError(f"{path} がありません")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise CoverError(f"{path} の形式が正しくありません")
    return cfg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="book.yaml から KDP 用の表紙画像（1600×2560px の JPEG）を生成します")
    parser.add_argument("books", nargs="*", help="本のディレクトリ（book.yaml がある場所）")
    parser.add_argument("--all", action="store_true", help="books/ 以下の全ての本の表紙を生成")
    parser.add_argument("--style", choices=["vertical", "horizontal"], help="デザイン（既定: cover_design.style、なければ layout.writing_mode）")
    parser.add_argument("--background", help="背景画像（cover_design.background を一時的に上書き）")
    parser.add_argument("-o", "--output", help="出力ファイル（本を 1 冊だけ指定したとき。.jpg / .tif）")
    parser.add_argument("--output-dir", default=str(ROOT / "dist"), help="出力ディレクトリ（既定: dist）")
    args = parser.parse_args(argv)

    books = [Path(b) for b in args.books]
    if args.all:
        books += sorted(p.parent for p in (ROOT / "books").glob("*/book.yaml"))
    if not books:
        parser.print_help()
        return 2
    if args.output and len(books) > 1:
        parser.error("-o は本を 1 冊だけ指定したときに使えます")

    failed = 0
    for b in books:
        warnings: list[str] = []
        try:
            b = b.resolve()
            cfg = load_config(b)
            out = Path(args.output).resolve() if args.output else default_output(b, cfg, Path(args.output_dir).resolve())
            path = generate_book_cover(b, cfg, out, None, warnings, args.style, args.background)
            for w in warnings:
                log("警告: " + w)
            log(f"出力: {os.path.relpath(path)}")
        except CoverError as e:
            for w in warnings:
                log("警告: " + w)
            log(f"エラー（{b}）: {e}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
