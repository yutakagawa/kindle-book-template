#!/usr/bin/env python3
"""新しい本の雛形を books/ の下に対話形式で作るスクリプト。

使い方:
    python3 scripts/new-book.py                 # 対話形式で質問に答える
    python3 scripts/new-book.py my-book         # ディレクトリ名を先に指定する
    python3 scripts/new-book.py my-book --title "本のタイトル" --author "山田 太郎" --writing-mode vertical
                                                # 全部指定すれば質問せずに作る

作るもの（books/<ディレクトリ名>/）:
    book.yaml           書誌情報・章の順番・組版の設定（uuid は新しく生成）
    chapters/*.md       まえがき・第 1 章・あとがきの原稿の雛形
    images/             図版の置き場所（表紙は cover_design で自動生成）
    textlint.json       縦書きのときだけ（漢数字を許可するチェック設定）
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "books"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MODES = {"horizontal": "horizontal", "h": "horizontal", "横": "horizontal", "横書き": "horizontal", "1": "horizontal",
         "vertical": "vertical", "v": "vertical", "縦": "vertical", "縦書き": "vertical", "2": "vertical"}


def q(value: str) -> str:
    """YAML の文字列として安全に書く（JSON の文字列は YAML としても正しい）。"""
    return json.dumps(value, ensure_ascii=False)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            print()
            sys.exit("中断しました")
        if answer:
            return answer
        if default:
            return default
        print("  入力してください")


def validate_name(name: str) -> str | None:
    if not NAME_RE.match(name):
        return "ディレクトリ名は半角の英小文字・数字・ - _ . で付けてください（例: my-book）"
    if (BOOKS / name).exists():
        return f"books/{name} はすでにあります"
    return None


def ask_name(default: str | None) -> str:
    while True:
        name = ask("ディレクトリ名（books/ の下に作る。半角英数字。例: my-book）", default)
        err = validate_name(name)
        if not err:
            return name
        print(f"  {err}")
        default = None


def ask_mode() -> str:
    print("組版を選んでください")
    print("  1) 横書き（左綴じ）… 技術書向け")
    print("  2) 縦書き（右綴じ）… 実用書・読み物向け")
    while True:
        answer = ask("番号", "1")
        mode = MODES.get(answer.lower())
        if mode:
            return mode
        print("  1 か 2 を入力してください")


# ---------------------------------------------------------------------------
# 生成するファイルの中身
# ---------------------------------------------------------------------------

CHAPTERS = {
    "horizontal": {
        "00-preface.md": """\
# まえがき {.unnumbered}

この本を書いた理由と、どんな読者に向けた本なのかを書きます。

## 本書の構成

各章で何を扱うのかを簡単に紹介します。
""",
        "01-chapter1.md": """\
# 第1章のタイトル {#sec:chapter1}

ここから本文を書きます。`#` が章タイトル（1ファイルに1つ）、`##` が節、`###` が項です。
章を増やすときは `chapters/` にファイルを足し、`book.yaml` の `chapters` に並べます。

## 最初の節

段落は空行で区切ります。
""",
        "99-afterword.md": """\
# あとがき {.unnumbered}

最後まで読んでくださった読者へのお礼などを書きます。
""",
    },
    "vertical": {
        "00-preface.md": """\
# まえがき {.unnumbered}

この本を書いた理由と、どんな読者に向けた本なのかを書きます。

## 本書の構成

各章で何を扱うのかを簡単に紹介します。
""",
        "01-chapter1.md": """\
# 第一章のタイトル {#sec:chapter1}

ここから本文を書きます。`#` が章タイトル（一ファイルに一つ）、`##` が節、`###` が項です。
章を増やすときは `chapters/` にファイルを足し、`book.yaml` の `chapters` に並べます。

## 最初の節

段落は空行で区切ります。
""",
        "99-afterword.md": """\
# あとがき {.unnumbered}

最後まで読んでくださった読者へのお礼などを書きます。
""",
    },
}

COVER_COLORS = {
    "horizontal": ('["#14213d", "#2c4f7c"]', "diagonal", "sans"),
    "vertical": ('["#f7f2e8", "#e8dcc6"]', "vertical", "serif"),
}

VERTICAL_TEXTLINT = {"rules": {"preset-ja-technical-writing": {"arabic-kanji-numbers": False}}}


def book_yaml(title: str, author: str, mode: str, chapters: list[str]) -> str:
    today = datetime.date.today()
    colors, gradient, font = COVER_COLORS[mode]
    mode_label = "縦書き" if mode == "vertical" else "横書き"
    chapter_lines = "\n".join(f"  - chapters/{c}" for c in chapters)
    return f"""\
# =====================================================================
# 本の設定ファイル（scripts/new-book.py で作成。{mode_label}）
# 設定項目の詳細は README の「設定ファイル book.yaml」を参照してください。
# =====================================================================

# ---- 書誌情報（EPUB のメタデータになります） ----
title: {q(title)}
# title_kana: ""                                    # 読み（並べ替え用。省略可）
# subtitle: ""
author:
  - name: {q(author)}
    # kana: ""                                      # 読み（省略可）
# publisher: ""                                     # 個人出版なら著者名やレーベル名（省略可）
language: ja
date: {today.isoformat()}                                    # 出版日（YYYY-MM-DD）
description: >-
  （本の紹介文を書きます）
keywords: []
rights: {q(f"© {today.year} {author}")}

# ---- 識別子 ----
# KDP の電子書籍に ISBN は不要です。uuid はこの本専用の値です（変更しないでください）。
isbn: ""
uuid: {uuid.uuid4()}

# ---- 表紙 ----
# 表紙画像を用意したら images/cover.jpg に置き、下の cover のコメントを外して cover_design を消します。
# KDP 推奨: 高さ 2560 × 幅 1600 ピクセル（縦横比 1.6:1）、JPEG、RGB。
# cover: images/cover.jpg
# それまでは title / author から表紙を自動生成します（dist/<名前>-cover.jpg）。
cover_design:
  style: auto                    # auto（layout.writing_mode に合わせる）/ vertical / horizontal
  colors: {colors}
  gradient: {gradient}               # vertical / horizontal / diagonal / radial
  font: {font}                      # serif（明朝）/ sans（ゴシック）/ フォントファイルのパス

# ---- 原稿（この順番で 1 冊になります） ----
chapters:
{chapter_lines}

# ---- 組版 ----
layout:
  writing_mode: {mode}{" " * (12 - len(mode))}   # horizontal = 横書き・左綴じ / vertical = 縦書き・右綴じ
  toc_title: 目次
  toc_depth: 2                 # 目次に載せる見出しの深さ（1〜3）
  number_chapters: true        # 章番号を付ける（{{.unnumbered}} を付けた章は除く）
  chapter_label: "第{{n}}章"
  appendix_label: "付録{{n}}"
  figure_label: "図{{c}}.{{n}}"     # {{c}}=章番号, {{n}}=章内の通し番号
  table_label: "表{{c}}.{{n}}"
  listing_label: "リスト{{c}}.{{n}}"
  vertical:                    # 縦書きのときだけ使う設定
    code_blocks: sideways      # sideways / horizontal / vertical
    tables: sideways
    tcy_digits: 2              # 何桁までの数字を縦中横にするか

# ---- ペーパーバック（紙の本。python3 scripts/build.py --paperback で本文 PDF を作る） ----
paperback:
  trim: a5                     # 判型: 5x8 / 5.5x8.5 / 6x9 などの KDP 標準サイズ、a5 / b6
  bleed: false                 # 裁ち落とし（画像や色を紙の端まで印刷するときだけ true）
  paper: {"cream" if mode == "vertical" else "white"}                 # white（白）/ cream（クリーム）/ color（カラー）
  font: serif                  # 本文の書体: serif（明朝）/ sans（ゴシック）/ フォント名
  font_size: {"9pt  " if mode == "vertical" else "9.5pt"}             # 本文の文字の大きさ
  line_height: {"1.75" if mode == "vertical" else "1.7 "}            # 行送り（文字の大きさに対する倍率）
"""


def create_book(name: str, title: str, author: str, mode: str) -> Path:
    book_dir = BOOKS / name
    chapters = CHAPTERS[mode]
    (book_dir / "chapters").mkdir(parents=True)
    (book_dir / "images").mkdir()
    (book_dir / "images" / ".gitkeep").touch()
    for filename, text in chapters.items():
        (book_dir / "chapters" / filename).write_text(text, encoding="utf-8")
    (book_dir / "book.yaml").write_text(book_yaml(title, author, mode, list(chapters)), encoding="utf-8")
    if mode == "vertical":
        (book_dir / "textlint.json").write_text(
            json.dumps(VERTICAL_TEXTLINT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return book_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="新しい本の雛形を books/ の下に作ります（足りない項目は対話形式で質問します）")
    parser.add_argument("name", nargs="?", help="books/ の下に作るディレクトリ名（例: my-book）")
    parser.add_argument("--title", help="本のタイトル")
    parser.add_argument("--author", help="著者名")
    parser.add_argument("--writing-mode", choices=["horizontal", "vertical"], help="横書き / 縦書き")
    args = parser.parse_args()

    if args.name:
        err = validate_name(args.name)
        if err:
            sys.exit(err)
        name = args.name
    else:
        name = ask_name(None)
    title = args.title or ask("タイトル")
    author = args.author or ask("著者名")
    mode = args.writing_mode or ask_mode()

    book_dir = create_book(name, title, author, mode)
    rel = book_dir.relative_to(ROOT)
    print()
    print(f"{rel}/ を作りました（{'縦書き' if mode == 'vertical' else '横書き'}）")
    for p in sorted(book_dir.rglob("*")):
        if p.is_file() and p.name != ".gitkeep":
            print(f"  {p.relative_to(ROOT)}")
    print()
    print("次にやること:")
    print(f"  1. {rel}/book.yaml の description などを書き換える")
    print(f"  2. {rel}/chapters/ に原稿を書く")
    print(f"  3. make book BOOK={rel}    （または python3 scripts/build.py {rel}）")


if __name__ == "__main__":
    main()
