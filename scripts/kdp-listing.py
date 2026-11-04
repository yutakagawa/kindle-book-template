#!/usr/bin/env python3
"""KDP の「本の詳細」に入力する内容紹介・キーワード・カテゴリの下書きを作るスクリプト。

使い方:
    python3 scripts/kdp-listing.py books/my-book          # 1 冊分 → dist/my-book-kdp-listing.md
    python3 scripts/kdp-listing.py --all                  # books/ 以下の全ての本
    python3 scripts/kdp-listing.py books/my-book --json   # JSON も書き出す（dist/my-book-kdp-listing.json）
    python3 scripts/kdp-listing.py books/my-book --stdout # ファイルを作らず標準出力へ
    python3 scripts/kdp-listing.py --all --strict         # KDP の制限を超えたら終了コード 1

book.yaml の title / subtitle / description / keywords と原稿（chapters）から作ります。
book.yaml に kdp: セクションを書くと、その値が優先されます（docs/kdp-listing.md を参照）。

ここで出すのはあくまで「下書き」です。KDP に貼り付ける前に必ず読み直して手直ししてください。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import ROOT, BuildError, as_list, load_config  # noqa: E402

# ---------------------------------------------------------------------------
# KDP の制限（KDP ヘルプ「本の内容紹介の入力」「キーワードを利用して本を見つけやすくする」
# 「KDP カテゴリー」「本のメタデータのガイドライン」に基づく。docs/kdp-listing.md を参照）
# ---------------------------------------------------------------------------

DESCRIPTION_MAX = 4000      # 内容紹介: HTML タグを含めて 4,000 文字まで
KEYWORD_SLOTS = 7           # キーワード: 最大 7 つ
KEYWORD_MAX = 50            # キーワード 1 つあたりの入力欄の上限（KDP の入力欄の仕様。ヘルプには数値の記載なし）
CATEGORY_MAX = 3            # カテゴリー: 最大 3 つ

# 内容紹介で使える HTML タグ（KDP ヘルプ「本の内容紹介の入力」）
ALLOWED_TAGS = {"br", "p", "b", "strong", "i", "em", "u", "h4", "h5", "h6", "ol", "ul", "li"}

# KDP のメタデータのガイドラインで、内容紹介やキーワードに入れてはいけないとされているもの。
# 機械的に見つけられるものだけを警告する（最終的な判断は人が行う）
PROHIBITED_PATTERNS = [
    (re.compile(r"https?://|www\.", re.I), "URL"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "メールアドレス"),
    (re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}"), "電話番号"),
    (re.compile(r"[0-9０-９,，]+\s*円|￥|¥|\$\s*\d"), "価格"),
    (re.compile(r"無料|タダ|セール|割引|値引|キャンペーン|期間限定|今だけ|特典|ポイント還元|Kindle\s*Unlimited|読み放題", re.I),
     "宣伝・価格・期間限定の表現"),
    (re.compile(r"ベストセラー|売上(?:第|No\.?)\s*[1１一]|ランキング\s*[1１一]位|[1１一]位(?:獲得|になった)|話題の|大人気|best\s*sell", re.I),
     "売れ行き・順位の表現"),
    (re.compile(r"新刊|最新刊|近日|発売予定|予約|新発売"), "時期によって変わる表現"),
    (re.compile(r"レビュー|書評|絶賛|推薦の声|★"), "レビュー・推薦文"),
]

# 原稿から語を拾うときに除く、どの本にも出てくる語
STOPWORDS = set("""
本書 本章 次章 前章 各章 以下 以上 場合 必要 方法 部分 内容 説明 紹介 確認 使用 利用 作成 実行 設定 入力 出力 表示 変更 追加 指定
今回 最初 最後 全体 一部 一覧 自分 自身 結果 理由 意味 問題 状態 程度 可能 簡単 便利 普通 通常 基本 注意 参照 記号 記法 項目 番号
ファイル ディレクトリ フォルダ コマンド サンプル テンプレート ページ スクリプト テキスト タイトル ファイル名 デフォルト
はじめに まえがき あとがき おわりに 付録 目次 第章 毎日 毎朝 一つ 二つ 三つ 一年 時間 五分
工夫 段階 準備 手順 数字 書籍 実践 本文 本文中 一括 生成 考え方 読者 著者 以降 前後 途中 同様 一般 具体 実際 特定
""".split())

# ---------------------------------------------------------------------------
# カテゴリーの候補（Amazon.co.jp の Kindle ストアの分類をもとにした目安）
# KDP の「カテゴリー」の選択画面で、この名前を手がかりに探して選んでください。
# 画面に出る名前や階層は変わることがあるので、そのまま存在するとは限りません。
# 本の分野に合わせて、この表に行を足して使えます。
# ---------------------------------------------------------------------------

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("コンピュータ・IT > プログラミング",
     ["プログラミング", "プログラム", "スクリプト", "コード", "Python", "JavaScript", "TypeScript", "Ruby", "Java",
      "Go", "Rust", "関数", "変数", "ライブラリ", "API", "Git", "GitHub"]),
    ("コンピュータ・IT > 開発・ツール",
     ["ツール", "ビルド", "Pandoc", "Markdown", "コマンドライン", "ターミナル", "CI", "GitHub Actions",
      "自動化", "エディタ", "Lint", "textlint"]),
    ("コンピュータ・IT > Web・インターネット",
     ["Web", "HTML", "CSS", "ブラウザ", "サイト", "ホームページ", "ブログ", "SNS", "インターネット"]),
    ("コンピュータ・IT > アプリケーション（オフィス・業務）",
     ["Excel", "エクセル", "Word", "PowerPoint", "スプレッドシート", "表計算", "メール", "業務効率"]),
    ("コンピュータ・IT > AI・データサイエンス",
     ["AI", "人工知能", "機械学習", "ディープラーニング", "データ分析", "統計", "生成AI", "ChatGPT", "Claude", "LLM"]),
    ("コンピュータ・IT > 電子出版・DTP",
     ["電子書籍", "Kindle", "KDP", "EPUB", "出版", "DTP", "組版", "縦書き", "表紙", "ペーパーバック", "原稿"]),
    ("ビジネス・経済 > 仕事術・整理術",
     ["仕事術", "仕事", "効率化", "時短", "生産性", "習慣", "タスク", "段取り", "整理", "作業", "記録"]),
    ("ビジネス・経済 > 経営・マーケティング",
     ["マーケティング", "経営", "起業", "集客", "ブランディング", "営業", "販売", "副業"]),
    ("投資・金融・会社経営 > 投資・資産運用",
     ["投資", "株", "資産運用", "NISA", "iDeCo", "不動産", "FX", "お金", "家計"]),
    ("人文・思想 > 心理学",
     ["心理", "心理学", "メンタル", "感情", "モチベーション", "認知"]),
    ("暮らし・健康・子育て > 健康",
     ["健康", "ダイエット", "睡眠", "運動", "食事", "ストレス"]),
    ("暮らし・健康・子育て > 子育て",
     ["子育て", "育児", "子ども", "子供", "親子", "教育"]),
    ("趣味・実用 > 料理",
     ["料理", "レシピ", "献立", "お菓子", "調理"]),
    ("趣味・実用 > 写真・カメラ",
     ["写真", "カメラ", "撮影", "レンズ"]),
    ("語学・辞事典・年鑑 > 英語",
     ["英語", "英会話", "TOEIC", "英単語", "英文法"]),
    ("資格・検定・就職",
     ["資格", "試験", "検定", "合格", "就職", "転職", "面接"]),
    ("文学・評論 > 小説・文芸",
     ["小説", "物語", "短編", "長編", "主人公", "ミステリー", "ファンタジー", "恋愛"]),
    ("文学・評論 > エッセイ・随筆",
     ["エッセイ", "随筆", "日記", "体験記"]),
]


class ListingWarnings(list):
    def add(self, msg: str) -> None:
        self.append(msg)


# ---------------------------------------------------------------------------
# 原稿の読み込みと Markdown の除去
# ---------------------------------------------------------------------------

def chapter_paths(book_dir: Path, cfg: dict) -> list[Path]:
    chapters = [book_dir / c for c in as_list(cfg.get("chapters"))]
    if not chapters:
        chapters = sorted((book_dir / "chapters").glob("*.md"))
    if not chapters:
        raise BuildError("原稿（chapters）がありません")
    for c in chapters:
        if not c.exists():
            raise BuildError(f"原稿が見つかりません: {c}")
    return chapters


FENCE_RE = re.compile(r"^(```|~~~)")
CODE_MARK = "\x01"   # インラインコードがあった場所。内容紹介ではその文を使わない
ATTR_RE = re.compile(r"\s*\{[^{}]*\}\s*$")          # 見出しの {#sec:x .unnumbered}


def strip_inline(text: str) -> str:
    """Markdown のインライン記法を取り除いて、地の文だけにする。"""
    text = re.sub(r"\{([^{}|]+)\|[^{}]+\}", r"\1", text)            # ルビ {漢字|かんじ}
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?", "", text)    # 画像
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)            # リンク
    text = re.sub(r"\[\^[^\]]+\]", "", text)                       # 脚注の参照
    text = re.sub(r"\^\[[^\]]*\]", "", text)                        # インライン脚注
    text = re.sub(r"\[?@(?:sec|fig|tbl|lst):[\w-]+\]?", "", text)   # 相互参照
    text = re.sub(r"`[^`]*`", CODE_MARK, text)                      # インラインコード（印を残す）
    text = re.sub(r"\[([^\]]*)\]\{[^}]*\}", r"\1", text)            # [文字]{.class}
    text = re.sub(r"(\*\*|__|\*|_|~~)(.+?)\1", r"\2", text)         # 強調
    text = re.sub(r"<[^>]+>", "", text)                             # HTML
    text = text.replace("\\", "")
    return text.strip()


def parse_chapter(path: Path) -> dict:
    """1 つの原稿ファイルから、見出しと本文の段落を取り出す。"""
    headings: list[tuple[int, str, str]] = []   # (レベル, 見出し, 属性)
    paragraphs: list[str] = []
    buf: list[str] = []
    in_fence = False
    in_div = 0

    def flush() -> None:
        if buf:
            para = strip_inline("".join(s.strip() for s in buf))
            if para:
                paragraphs.append(para)
            buf.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE_RE.match(line.strip()):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        s = line.strip()
        if s.startswith(":::"):
            # 囲み（::: note など）の中身も本文として扱う。区切り行だけ読み飛ばす
            flush()
            in_div += -1 if s == ":::" else 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush()
            attrs = ""
            title = m.group(2)
            am = ATTR_RE.search(title)
            if am:
                attrs = am.group(0)
                title = title[: am.start()]
            headings.append((len(m.group(1)), strip_inline(title).replace(CODE_MARK, ""), attrs))
            continue
        if not s or s.startswith(("|", ">", "- ", "* ", "+ ", "!")) or re.match(r"^\d+\.\s", s) \
                or re.match(r"^[-=:| ]+$", s) or s.startswith("[^"):
            flush()
            # 箇条書きは段落としては使わないが、語の抽出には使う
            if s and not re.match(r"^[-=:| ]+$", s):
                paragraphs.append("\0" + strip_inline(re.sub(r"^([-*+>|!]|\d+\.)\s*", "", s)))
            continue
        buf.append(s)
    flush()
    return {"path": path, "headings": headings, "paragraphs": paragraphs}


def body_paragraphs(chapter: dict) -> list[str]:
    """箇条書きなどを除いた、地の文の段落。"""
    return [p for p in chapter["paragraphs"] if not p.startswith("\0")]


def all_text(chapter: dict) -> str:
    return "\n".join(p.lstrip("\0").replace(CODE_MARK, " ") for p in chapter["paragraphs"])


# ---------------------------------------------------------------------------
# 内容紹介
# ---------------------------------------------------------------------------

def is_front_matter(attrs: str, title: str) -> bool:
    return ".unnumbered" in attrs or title in ("はじめに", "まえがき", "序章", "プロローグ", "本書について")


def chapter_titles(chapters: list[dict]) -> list[tuple[str, list[str]]]:
    """目次に載せる章（番号付きの章と付録）と、その節の見出し。"""
    result = []
    for ch in chapters:
        current = None
        for level, title, attrs in ch["headings"]:
            if level == 1:
                if is_front_matter(attrs, title) and ".appendix" not in attrs:
                    current = None
                    continue
                current = (title, [])
                result.append(current)
            elif level == 2 and current is not None:
                current[1].append(title)
    return result


def first_sentences(paragraphs: list[str], limit: int) -> str:
    """段落を先頭から、limit 文字に収まるまで（文の切れ目で）つなげる。"""
    out = ""
    for para in paragraphs:
        for sent in re.findall(r"[^。！？!?]+[。！？!?」』）)]*", para):
            if CODE_MARK in sent:
                break      # コードを除くと意味が通らなくなる文（と、それに続く同じ段落の文）は使わない
            if len(out) + len(sent) > limit:
                return out.strip()
            out += sent
        if out:
            out += "\n"
    return out.strip()


def esc(text: str) -> str:
    """KDP の内容紹介では < > & を HTML エンティティにする必要がある。"""
    return html.escape(text, quote=False)


def build_description(cfg: dict, chapters: list[dict], kdp: dict, warnings: ListingWarnings) -> dict:
    title = str(cfg.get("title", "")).strip()
    summary = str(kdp.get("description") or cfg.get("description") or "").strip()
    if not summary:
        warnings.add("book.yaml に description がありません。内容紹介の書き出しは原稿の冒頭から作りました")

    # 「はじめに」「まえがき」の冒頭を、読者への語りかけとして使う
    preface = next((ch for ch in chapters if ch["headings"]
                    and is_front_matter(ch["headings"][0][2], ch["headings"][0][1])), None)
    intro = ""
    if kdp.get("intro") is not None:
        intro = str(kdp.get("intro") or "").strip()
    elif preface:
        intro = first_sentences(body_paragraphs(preface), int(kdp.get("intro_length", 300)))

    toc = chapter_titles(chapters)
    include_sections = bool(kdp.get("toc_sections", True))
    closing = str(kdp.get("closing") or "").strip()

    def render(with_sections: bool, n_chapters: int) -> tuple[str, str]:
        parts_html: list[str] = []
        parts_text: list[str] = []
        lead = summary or intro
        if lead:
            parts_html.append("<p>" + "<br>".join(esc(x) for x in lead.splitlines() if x.strip()) + "</p>")
            parts_text.append(lead)
        if summary and intro and intro not in summary:
            parts_html.append("<p>" + "<br>".join(esc(x) for x in intro.splitlines() if x.strip()) + "</p>")
            parts_text.append(intro)
        if toc and n_chapters:
            parts_html.append("<h4>本書の内容</h4>")
            parts_text.append("■本書の内容")
            items_html, items_text = [], []
            for name, sections in toc[:n_chapters]:
                line = esc(name)
                tline = "・" + name
                if with_sections and sections:
                    line += "<br>" + esc("（" + "／".join(sections) + "）")
                    tline += "（" + "／".join(sections) + "）"
                items_html.append(f"<li>{line}</li>")
                items_text.append(tline)
            if n_chapters < len(toc):
                items_html.append("<li>ほか</li>")
                items_text.append("・ほか")
            parts_html.append("<ul>" + "".join(items_html) + "</ul>")
            parts_text.append("\n".join(items_text))
        if closing:
            parts_html.append("<p>" + "<br>".join(esc(x) for x in closing.splitlines() if x.strip()) + "</p>")
            parts_text.append(closing)
        return "".join(parts_html), "\n\n".join(parts_text)

    limit = int(kdp.get("description_max", DESCRIPTION_MAX))
    # 4,000 文字に収まるまで、節の見出し → 章の数の順に削る
    candidates = [(include_sections, len(toc))] if include_sections else []
    candidates += [(False, n) for n in range(len(toc), -1, -1)]
    body_html, body_text = render(*candidates[0]) if candidates else render(False, 0)
    trimmed = False
    for with_sections, n in candidates:
        body_html, body_text = render(with_sections, n)
        if len(body_html) <= limit:
            break
        trimmed = True
    if trimmed:
        warnings.add(f"内容紹介が {limit} 文字を超えるため、目次の一部を省きました")
    if len(body_html) > limit:
        warnings.add(f"内容紹介が {len(body_html)} 文字で、KDP の上限（HTML タグを含めて {limit} 文字）を超えています")

    check_prohibited("内容紹介", body_text, title, warnings)
    check_tags(body_html, warnings)
    if re.search(r"[​-‏ -‮﻿]", body_html):
        warnings.add("内容紹介に見えない文字（ゼロ幅スペースなど）が含まれています。KDP でエラーになります")
    return {"html": body_html, "text": body_text, "length": len(body_html), "limit": limit}


def check_tags(body_html: str, warnings: ListingWarnings) -> None:
    for tag in sorted(set(t.lower() for t in re.findall(r"</?\s*([a-zA-Z0-9]+)", body_html))):
        if tag not in ALLOWED_TAGS:
            warnings.add(f"内容紹介に KDP で使えない HTML タグ <{tag}> があります")


def check_prohibited(field: str, text: str, title: str, warnings: ListingWarnings) -> None:
    for pattern, label in PROHIBITED_PATTERNS:
        for m in pattern.finditer(text):
            # タイトルに含まれる語（例: 本のテーマが「キャンペーン」）は誤検出として除く
            if m.group(0) and m.group(0) in title:
                continue
            warnings.add(f"{field}に「{m.group(0)}」があります（{label}は KDP のメタデータのガイドラインで禁止）")
            break


# ---------------------------------------------------------------------------
# キーワード
# ---------------------------------------------------------------------------

TERM_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z]{2,}"       # 英単語（Python, EPUB3, C++）
    r"|[ァ-ヴー]{3,}(?:・[ァ-ヴー]{2,})*"                          # カタカナ語
    r"|(?<![一-龠々])[一-龠々]{2,6}(?![一-龠々ぁ-ゖ])"              # 漢字の複合語（後ろに送りがながないもの）
    r"|(?<![一-龠々])[一-龠々]{2,6}(?=[のをにはがでともやへ])"       # 漢字の複合語 + 助詞
)


def normalize(term: str) -> str:
    return unicodedata.normalize("NFKC", term).strip()


def extract_terms(cfg: dict, chapters: list[dict]) -> Counter:
    """原稿から、キーワードになりそうな語を重み付きで数える。見出しの語は重く数える。"""
    counts: Counter = Counter()
    for ch in chapters:
        for level, title, _ in ch["headings"]:
            for t in TERM_RE.findall(normalize(title)):
                counts[t] += 5 if level == 1 else 3
        for t in TERM_RE.findall(normalize(all_text(ch))):
            counts[t] += 1
    for key in ("title", "subtitle", "description"):
        for t in TERM_RE.findall(normalize(str(cfg.get(key) or ""))):
            counts[t] += 4
    for t in list(counts):
        if t in STOPWORDS or len(t) < 2 or t.isdigit() or re.fullmatch(r"[a-z]{2}", t):
            del counts[t]
    return counts


def build_keywords(cfg: dict, chapters: list[dict], kdp: dict, warnings: ListingWarnings) -> dict:
    title = normalize(str(cfg.get("title", "")))
    subtitle = normalize(str(cfg.get("subtitle", "") or ""))
    authors = [normalize(a["name"] if isinstance(a, dict) else str(a)) for a in as_list(cfg.get("author"))]
    max_len = int(kdp.get("keyword_max", KEYWORD_MAX))

    fixed = [normalize(str(k)) for k in as_list(kdp.get("keywords"))]
    from_yaml = [normalize(str(k)) for k in as_list(cfg.get("keywords"))]
    counts = extract_terms(cfg, chapters)

    selected: list[dict] = []
    seen: set[str] = set()

    def add(term: str, source: str) -> None:
        key = term.casefold()
        if not term or key in seen or len(selected) >= KEYWORD_SLOTS:
            return
        seen.add(key)
        selected.append({"keyword": term, "source": source, "length": len(term)})

    for k in fixed:
        add(k, "book.yaml の kdp.keywords")
    if not fixed:
        for k in from_yaml:
            add(k, "book.yaml の keywords")
        # タイトル・著者名と同じ語は、KDP では既にメタデータに含まれるので入れない
        # 短い一般的な語より、長く具体的な語を優先する（KDP ヘルプ: 具体的な語の方が効果がある）
        ranked = sorted(counts.items(), key=lambda kv: -kv[1] * (1 + 0.25 * max(0, len(kv[0]) - 2)))
        for term, n in ranked:
            if len(selected) >= KEYWORD_SLOTS:
                break
            if term == title or term == subtitle or term in authors:
                continue
            # 既に選んだ語の一部・または既に選んだ語を含む語は避ける（「自動化」と「自動」など）
            if any(term in s["keyword"] or s["keyword"] in term for s in selected):
                continue
            if n < 3:
                continue
            add(term, f"原稿から抽出（出現の重み {n}）")

    others = [t for t, n in counts.most_common(40) if n >= 3 and t.casefold() not in seen
              and not any(t in s["keyword"] or s["keyword"] in t for s in selected)][:15]

    for kw in selected:
        k = kw["keyword"]
        if len(k) > max_len:
            warnings.add(f"キーワード「{k}」が {len(k)} 文字で、入力欄の上限（{max_len} 文字）を超えています")
        if "<" in k or ">" in k:
            warnings.add(f"キーワード「{k}」に HTML タグがあります（KDP では使えません）")
        if k in (title, subtitle):
            warnings.add(f"キーワード「{k}」はタイトル・サブタイトルと同じです（既にメタデータにあるため入れても効果がありません）")
        if k in authors:
            warnings.add(f"キーワード「{k}」は著者名です（既にメタデータにあるため入れても効果がありません）")
        check_prohibited(f"キーワード「{k}」", k, "", warnings)
    if len(fixed) > KEYWORD_SLOTS:
        warnings.add(f"kdp.keywords が {len(fixed)} 個あります。KDP に入力できるのは {KEYWORD_SLOTS} 個までです")
    if len(selected) < KEYWORD_SLOTS:
        warnings.add(f"キーワードが {len(selected)} 個しか作れませんでした。残りの欄は「その他の候補」などから補ってください")
    return {"keywords": selected, "others": others, "slots": KEYWORD_SLOTS, "max_length": max_len}


# ---------------------------------------------------------------------------
# カテゴリー
# ---------------------------------------------------------------------------

def build_categories(cfg: dict, chapters: list[dict], kdp: dict, keywords: dict,
                     warnings: ListingWarnings) -> dict:
    fixed = [str(c) for c in as_list(kdp.get("categories"))]
    if len(fixed) > CATEGORY_MAX:
        warnings.add(f"kdp.categories が {len(fixed)} 個あります。KDP で選べるのは {CATEGORY_MAX} 個までです")

    meta_text = normalize(" ".join(str(cfg.get(k) or "") for k in ("title", "subtitle", "description"))
                          + " " + " ".join(str(k) for k in as_list(cfg.get("keywords")))
                          + " " + " ".join(k["keyword"] for k in keywords["keywords"]))
    body = normalize("\n".join(all_text(ch) + "\n" + "\n".join(h[1] for h in ch["headings"]) for ch in chapters))

    def hits(word: str, text: str) -> int:
        if re.fullmatch(r"[A-Za-z0-9 +#.\-]+", word):
            return len(re.findall(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.I))
        return text.count(word)

    scored = []
    for path, words in CATEGORY_RULES:
        score = 0
        matched = []
        for w in words:
            m, b = hits(w, meta_text), hits(w, body)
            if m or b:
                score += m * 5 + min(b, 10)
                matched.append(w)
        if score:
            scored.append({"category": path, "score": score, "matched": matched})
    scored.sort(key=lambda c: -c["score"])

    chosen = [{"category": c, "score": None, "matched": [], "source": "book.yaml の kdp.categories"}
              for c in fixed[:CATEGORY_MAX]]
    for c in scored:
        if len(chosen) >= CATEGORY_MAX:
            break
        if any(c["category"] == x["category"] for x in chosen):
            continue
        chosen.append({**c, "source": "原稿から推定"})
    if not chosen:
        warnings.add("カテゴリーの候補が見つかりませんでした。scripts/kdp-listing.py の CATEGORY_RULES に分野を足すか、"
                     "book.yaml の kdp.categories に書いてください")
    alternatives = [c for c in scored if all(c["category"] != x["category"] for x in chosen)][:3]
    return {"categories": chosen, "alternatives": alternatives, "max": CATEGORY_MAX}


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def render_markdown(book_name: str, cfg: dict, listing: dict) -> str:
    d, k, c = listing["description"], listing["keywords"], listing["categories"]
    lines = [
        f"# KDP 登録情報の下書き: {cfg.get('title', book_name)}",
        "",
        f"`scripts/kdp-listing.py` が `books/{book_name}/book.yaml` と原稿から作った**下書き**です。"
        "KDP に貼り付ける前に、必ず読み直して手直ししてください。",
        "",
    ]
    if listing["warnings"]:
        lines += ["## 確認が必要なこと", ""]
        lines += [f"- {w}" for w in listing["warnings"]]
        lines.append("")
    lines += [
        "## 内容紹介",
        "",
        f"文字数: **{d['length']} / {d['limit']}**（KDP は HTML タグも含めて数えます）",
        "",
        "KDP の「内容紹介」欄に、次の HTML をそのまま貼り付けます。",
        "",
        "```html",
        d["html"].replace("</p>", "</p>\n").replace("</h4>", "</h4>\n").replace("</li>", "</li>\n")
        .replace("<ul>", "<ul>\n").rstrip(),
        "```",
        "",
        "<details><summary>プレーンテキスト版（読み直し用）</summary>",
        "",
        "```text",
        d["text"],
        "```",
        "",
        "</details>",
        "",
        "## キーワード（7 つ）",
        "",
        f"KDP の「キーワード」欄に 1 つずつ入力します（1 欄 {k['max_length']} 文字まで）。",
        "",
        "| # | キーワード | 文字数 | 出どころ |",
        "|---|---|---|---|",
    ]
    for i in range(k["slots"]):
        if i < len(k["keywords"]):
            kw = k["keywords"][i]
            lines.append(f"| {i + 1} | {kw['keyword']} | {kw['length']} | {kw['source']} |")
        else:
            lines.append(f"| {i + 1} | （空き） | | |")
    if k["others"]:
        lines += ["", "その他の候補（入れ替えや組み合わせに）: " + "、".join(k["others"])]
    lines += [
        "",
        "## カテゴリーの候補（3 つまで）",
        "",
        "KDP の「カテゴリー」の選択画面で、次の分類を探して選びます。"
        "分類の名前や階層は Amazon 側で変わることがあるので、画面に出る一番近いものを選んでください。",
        "",
    ]
    for i, cat in enumerate(c["categories"], 1):
        reason = f"（{cat['source']}" + (f": {'・'.join(cat['matched'][:6])}" if cat["matched"] else "") + "）"
        lines.append(f"{i}. {cat['category']} {reason}")
    if c["alternatives"]:
        lines += ["", "ほかの候補: " + "、".join(a["category"] for a in c["alternatives"])]
    lines.append("")
    return "\n".join(lines)


def make_listing(book_dir: Path) -> tuple[dict, dict]:
    book_dir = book_dir.resolve()
    cfg = load_config(book_dir)
    if not cfg.get("title"):
        raise BuildError("book.yaml に title がありません")
    kdp = cfg.get("kdp") or {}
    if not isinstance(kdp, dict):
        raise BuildError("book.yaml の kdp は「キー: 値」の形で書いてください")
    chapters = [parse_chapter(p) for p in chapter_paths(book_dir, cfg)]
    warnings = ListingWarnings()
    description = build_description(cfg, chapters, kdp, warnings)
    keywords = build_keywords(cfg, chapters, kdp, warnings)
    categories = build_categories(cfg, chapters, kdp, keywords, warnings)
    listing = {
        "book": book_dir.name,
        "title": cfg.get("title"),
        "subtitle": cfg.get("subtitle"),
        "description": description,
        "keywords": keywords,
        "categories": categories,
        "warnings": list(dict.fromkeys(warnings)),
    }
    return cfg, listing


def has_limit_errors(listing: dict) -> bool:
    d, k, c = listing["description"], listing["keywords"], listing["categories"]
    return (d["length"] > d["limit"]
            or any(kw["length"] > k["max_length"] for kw in k["keywords"])
            or len(k["keywords"]) > k["slots"]
            or len(c["categories"]) > c["max"]
            or any("使えない HTML タグ" in w or "見えない文字" in w for w in listing["warnings"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KDP の内容紹介・キーワード・カテゴリーの下書きを作る")
    parser.add_argument("books", nargs="*", help="本のディレクトリ（book.yaml がある場所）")
    parser.add_argument("--all", action="store_true", help="books/ 以下の全ての本")
    parser.add_argument("-o", "--output-dir", default=str(ROOT / "dist"), help="出力先（既定: dist/）")
    parser.add_argument("--json", action="store_true", help="Markdown に加えて JSON も書き出す")
    parser.add_argument("--stdout", action="store_true", help="ファイルを作らず、Markdown を標準出力に出す")
    parser.add_argument("--strict", action="store_true", help="KDP の制限を超えた項目があれば終了コード 1 にする")
    args = parser.parse_args(argv)

    books = [Path(b) for b in args.books]
    if args.all:
        books += sorted(p.parent for p in (ROOT / "books").glob("*/book.yaml"))
    if not books:
        parser.error("本のディレクトリを指定するか --all を付けてください")

    out_dir = Path(args.output_dir)
    status = 0
    for book in books:
        try:
            cfg, listing = make_listing(book)
        except BuildError as e:
            print(f"[kdp-listing] エラー: {book}: {e}", file=sys.stderr)
            status = 1
            continue
        md = render_markdown(listing["book"], cfg, listing)
        if args.stdout:
            print(md)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            md_path = out_dir / f"{listing['book']}-kdp-listing.md"
            md_path.write_text(md, encoding="utf-8")
            print(f"[kdp-listing] {md_path}", file=sys.stderr)
            if args.json:
                json_path = out_dir / f"{listing['book']}-kdp-listing.json"
                json_path.write_text(json.dumps(listing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"[kdp-listing] {json_path}", file=sys.stderr)
        d = listing["description"]
        print(f"[kdp-listing]   内容紹介 {d['length']}/{d['limit']} 文字・キーワード "
              f"{len(listing['keywords']['keywords'])}/{KEYWORD_SLOTS} 個・カテゴリー "
              f"{len(listing['categories']['categories'])}/{CATEGORY_MAX} 個", file=sys.stderr)
        for w in listing["warnings"]:
            print(f"[kdp-listing]   注意: {w}", file=sys.stderr)
        if args.strict and has_limit_errors(listing):
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
