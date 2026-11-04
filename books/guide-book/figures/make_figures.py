#!/usr/bin/env python3
"""『Markdownで作るKindle本 入門』の図版（images/fig-*.png）を作り直すスクリプト。

使い方（リポジトリのルートで）:
    python3 books/guide-book/figures/make_figures.py

- Pillow と日本語フォント（Noto Sans CJK JP など。Linux では fonts-noto-cjk）が必要
- 幅 1600px・白背景・透過なしの PNG を書き出す（Kindle の白黒端末でも区別できるよう、
  色だけに頼らず線の太さ・塗りの濃さ・文字で区別する）
- ビルドには不要。図を直したいときだけ実行する
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "images"
W = 1600

INK = (33, 37, 41)
SUB = (90, 96, 104)
LINE = (60, 64, 70)
FILL = {
    "plain": (255, 255, 255),
    "light": (236, 241, 247),
    "mid": (208, 220, 235),
    "dark": (32, 58, 96),
    "ok": (226, 240, 228),
}


def font_path(bold: bool) -> str:
    pattern = "Noto Sans CJK JP:style=Bold" if bold else "Noto Sans CJK JP:style=Regular"
    try:
        path = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                              capture_output=True, text=True, check=True).stdout.strip()
        if path:
            return path
    except (OSError, subprocess.CalledProcessError):
        pass
    raise SystemExit("日本語フォントが見つかりません（sudo apt install fonts-noto-cjk）")


FONT_R = font_path(False)
FONT_B = font_path(True)


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_B if bold else FONT_R, size, index=0)


class Canvas:
    def __init__(self, height: int):
        self.img = Image.new("RGB", (W, height), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)

    def text_center(self, cx, cy, text, size, bold=False, color=INK, max_width=None):
        lines = text.split("\n")
        f = font(size, bold)
        while max_width and size > 20 and max(f.getlength(line) for line in lines) > max_width:
            size -= 2   # 枠に収まるまで小さくする
            f = font(size, bold)
        heights = [f.getbbox(line)[3] - f.getbbox(line)[1] for line in lines]
        gap = int(size * 0.35)
        total = sum(heights) + gap * (len(lines) - 1)
        y = cy - total / 2
        for line, h in zip(lines, heights):
            self.d.text((cx, y + h / 2), line, font=f, fill=color, anchor="mm")
            y += h + gap

    def box(self, x, y, w, h, title, sub="", style="light", radius=22, width=4, dashed=False):
        fill = FILL[style]
        color = (255, 255, 255) if style == "dark" else INK
        subcolor = (220, 228, 240) if style == "dark" else SUB
        if dashed:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius, fill=fill)
            self._dashed_rect(x, y, w, h, width)
        else:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius, fill=fill, outline=LINE, width=width)
        if sub:
            self.text_center(x + w / 2, y + h * 0.36, title, 40, True, color, w - 40)
            self.text_center(x + w / 2, y + h * 0.72, sub, 28, False, subcolor, w - 40)
        else:
            self.text_center(x + w / 2, y + h / 2, title, 40, True, color, w - 40)
        return (x, y, w, h)

    def _dashed_rect(self, x, y, w, h, width, dash=18):
        for x0 in range(int(x), int(x + w), dash * 2):
            self.d.line((x0, y, min(x0 + dash, x + w), y), fill=LINE, width=width)
            self.d.line((x0, y + h, min(x0 + dash, x + w), y + h), fill=LINE, width=width)
        for y0 in range(int(y), int(y + h), dash * 2):
            self.d.line((x, y0, x, min(y0 + dash, y + h)), fill=LINE, width=width)
            self.d.line((x + w, y0, x + w, min(y0 + dash, y + h)), fill=LINE, width=width)

    def arrow(self, x1, y1, x2, y2, label="", width=6, head=26):
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        bx, by = x2 - head * math.cos(ang), y2 - head * math.sin(ang)
        self.d.line((x1, y1, bx, by), fill=LINE, width=width)
        left = (bx + head * 0.6 * math.cos(ang + math.pi / 2), by + head * 0.6 * math.sin(ang + math.pi / 2))
        right = (bx + head * 0.6 * math.cos(ang - math.pi / 2), by + head * 0.6 * math.sin(ang - math.pi / 2))
        self.d.polygon([(x2, y2), left, right], fill=LINE)
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            f = font(28)
            bbox = self.d.textbbox((mx, my), label, font=f, anchor="mm")
            pad = 8
            if abs(y2 - y1) > abs(x2 - x1):   # 縦の矢印はラベルを右に置く
                bbox = self.d.textbbox((mx + 16, my), label, font=f, anchor="lm")
                self.d.rectangle((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), fill=(255, 255, 255))
                self.d.text((mx + 16, my), label, font=f, fill=SUB, anchor="lm")
            else:
                self.d.rectangle((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), fill=(255, 255, 255))
                self.d.text((mx, my), label, font=f, fill=SUB, anchor="mm")

    def save(self, name: str):
        path = OUT / name
        self.img.save(path, optimize=True)
        print(f"wrote {path.relative_to(OUT.parent.parent.parent)}  {self.img.size[0]}×{self.img.size[1]}")


def fig_overview():
    """第1章: テンプレートの全体像（入力 → build.py → 出力）"""
    c = Canvas(860)
    c.text_center(W / 2, 60, "原稿を書けば、ビルドは 1 コマンド", 44, True)
    inputs = [("原稿", "chapters/*.md"), ("設定", "book.yaml"), ("図版", "images/*.png")]
    for i, (t, s) in enumerate(inputs):
        c.box(60, 150 + i * 230, 380, 170, t, s, "light")
    c.box(610, 300, 380, 280, "build.py", "Pandoc + Lua フィルタ\n+ CSS", "dark")
    outputs = [("EPUB", "Kindle 電子書籍"), ("本文 PDF", "ペーパーバック"), ("表紙", "1600×2560 JPEG")]
    for i, (t, s) in enumerate(outputs):
        c.box(1160, 150 + i * 230, 380, 170, t, s, "mid")
    for i in range(3):
        c.arrow(440, 235 + i * 230, 610, 440 + (i - 1) * 70)
        c.arrow(990, 440 + (i - 1) * 70, 1160, 235 + i * 230)
    c.save("fig-overview.png")


def fig_bookdir():
    """第2章: 1 冊の本のディレクトリ構成"""
    c = Canvas(900)
    c.box(560, 50, 480, 130, "books/guide-book/", "", "dark")
    items = [
        ("book.yaml", "書誌情報・表紙・\n章の順番・組版", "mid"),
        ("chapters/", "原稿\n1 章 = 1 ファイル", "light"),
        ("images/", "図版・写真\n（表紙の背景）", "light"),
        ("textlint.json", "この本だけの\nチェック設定（任意）", "plain"),
    ]
    xs = [40, 430, 820, 1210]
    for x, (t, s, st) in zip(xs, items):
        c.box(x, 330, 350, 260, t, s, st, dashed=(st == "plain"))
        c.d.line((800, 180, 800, 255), fill=LINE, width=5)
        c.d.line((x + 175, 255, 800, 255), fill=LINE, width=5)
        c.arrow(x + 175, 255, x + 175, 330)
    c.text_center(W / 2, 690, "↓  python3 scripts/build.py books/guide-book", 34, True, SUB)
    c.box(140, 760, 600, 110, "dist/guide-book.epub", "", "ok", width=3)
    c.box(820, 760, 640, 110, "dist/guide-book-cover.jpg", "", "ok", width=3)
    c.save("fig-bookdir.png")


def fig_crossref():
    """第3章: ID を付けて参照すると番号付きのリンクになる"""
    c = Canvas(760)
    c.text_center(400, 60, "原稿に書くこと", 40, True)
    c.text_center(1200, 60, "EPUB での表示", 40, True)
    rows = [
        ("![流れ](images/a.png){#fig:a}", "図3.1　流れ"),
        (": 記法の一覧 {#tbl:a}", "表3.1　記法の一覧"),
        ("```{.yaml #lst:a caption=\"…\"}", "リスト3.1　…"),
        ("[@fig:a]のように…", "図3.1のように…（リンク）"),
    ]
    for i, (src, out) in enumerate(rows):
        y = 130 + i * 150
        c.box(40, y, 720, 110, "", "", "light")
        c.d.text((70, y + 55), src, font=font(32), fill=INK, anchor="lm")
        c.box(840, y, 720, 110, "", "", "ok" if i == 3 else "mid")
        c.d.text((870, y + 55), out, font=font(34, True), fill=INK, anchor="lm")
        c.arrow(760, y + 55, 840, y + 55)
    c.text_center(W / 2, 730, "番号は章ごとに数え直され、章や図を並べ替えても自動で振り直される", 30, False, SUB)
    c.save("fig-crossref.png")


def fig_checks():
    """第4章: 品質を守る 3 段のチェック"""
    c = Canvas(700)
    steps = [
        ("npm run lint", "表記ゆれ・文章\nリンク切れ・参照ミス", "light"),
        ("make", "EPUB を作る\n画像を自動で最適化", "mid"),
        ("make check", "EPUBCheck で検証\n警告 1 件でも失敗", "dark"),
    ]
    for i, (t, s, st) in enumerate(steps):
        x = 40 + i * 420
        c.box(x, 140, 360, 300, t, s, st)
        c.arrow(x + 360, 290, x + 420, 290)
    c.box(1300, 190, 260, 200, "合格", "KDP へ", "ok", width=6)
    c.text_center(W / 2, 70, "原稿 → 検査 → ビルド → 検証 の順に、早い段階で問題を見つける", 36, True)
    c.text_center(W / 2, 540, "GitHub Actions でも push のたびに同じチェックを実行（縦書き・横書きの両方）", 30, False, SUB)
    c.text_center(W / 2, 610, "どこかでエラーが出たら、表示されたファイル・行を直してやり直す", 30, False, SUB)
    c.save("fig-checks.png")


def fig_publish():
    """第5章: 電子書籍とペーパーバックの出版の流れ"""
    c = Canvas(820)
    c.text_center(W / 2, 55, "同じ原稿から、電子書籍と紙の本を出版する", 40, True)
    lanes = [
        (150, "make check", "dist/guide-book.epub", "Kindle Previewer", "KDP 電子書籍"),
        (480, "make paperback", "…-paperback.pdf", "印刷プレビューアー", "KDP ペーパーバック"),
    ]
    for y, cmd, file, check, kdp in lanes:
        c.box(40, y, 300, 170, cmd, "", "light")
        c.box(420, y, 360, 170, "出力", file, "mid")
        c.box(860, y, 320, 170, "確認", check, "plain", dashed=True)
        c.box(1260, y, 300, 170, kdp, "", "dark")
        c.arrow(340, y + 85, 420, y + 85)
        c.arrow(780, y + 85, 860, y + 85)
        c.arrow(1180, y + 85, 1260, y + 85)
    c.text_center(W / 2, 395, "表紙（dist/guide-book-cover.jpg）は電子書籍の「表紙」欄にもアップロードする", 28, False, SUB)
    c.text_center(W / 2, 730, "紙の本の表紙 PDF（表 1・背・表 4）は、ビルド時に表示される寸法で別に作る", 28, False, SUB)
    c.save("fig-publish.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig_overview()
    fig_bookdir()
    fig_crossref()
    fig_checks()
    fig_publish()


if __name__ == "__main__":
    main()
