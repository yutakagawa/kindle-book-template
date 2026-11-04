#!/usr/bin/env python3
"""原稿と book.yaml から、KDP の登録画面に入力する「内容紹介」「キーワード 7 つ」「カテゴリ候補」の
下書きを書き出すスクリプト。

使い方:
    python3 scripts/kdp-listing.py books/horizontal-sample      # → dist/horizontal-sample-listing.md
    python3 scripts/kdp-listing.py --all                        # books/ 以下を全部
    python3 scripts/kdp-listing.py books/my-book --stdout       # ファイルに書かずに画面に出す
    python3 scripts/kdp-listing.py books/my-book --json         # JSON でも書き出す（-listing.json）
    python3 scripts/kdp-listing.py books/my-book --check        # KDP の制限を超えていたら終了コード 1

出力はあくまで「下書き」です。内容紹介は読み直して書き直し、キーワードとカテゴリは
KDP の画面で実際に選べるものを確かめてから入力してください（docs/kdp-listing.md）。

KDP の制限（KDP ヘルプ「内容紹介」「キーワード」「カテゴリー」「メタデータのガイドライン」に基づく）:
    内容紹介   4,000 文字以内（HTML タグも文字数に含めて数える）。使える HTML タグは限られる
    キーワード 最大 7 個（7 つの入力欄）、1 欄あたり 50 文字以内
    カテゴリー 最大 3 つ
    タイトル   タイトルとサブタイトルを合わせて 200 文字未満
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要です: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent

# ---- KDP の制限 ---------------------------------------------------------------
DESCRIPTION_MAX = 4000          # 内容紹介の最大文字数（HTML タグを含む）
KEYWORD_SLOTS = 7               # キーワードの入力欄の数
KEYWORD_MAX = 50                # 1 欄あたりの最大文字数
CATEGORY_MAX = 3                # 選べるカテゴリーの数
TITLE_MAX = 200                 # タイトル＋サブタイトルの合計（これ未満）

# 内容紹介で使える HTML タグ（KDP ヘルプ「内容紹介」）。これ以外は削除されるか、そのまま表示される
ALLOWED_TAGS = {"br", "p", "b", "em", "i", "u", "h4", "h5", "h6", "ol", "ul", "li"}

# キーワード・内容紹介に入れてはいけない語（KDP「キーワード」「メタデータのガイドライン」）
#   - 主観的な評価・宣伝（ベストセラー、No.1 など）
#   - 一時的な情報（新刊、セール中、無料 など）
#   - Amazon のプログラム名（Kindle Unlimited、KDP セレクトなど）
#   - ほとんどの商品に共通する語（本、書籍、電子書籍 など）
PROHIBITED_TERMS = {
    "宣伝・主観的な評価": ["ベストセラー", "ランキング1位", "1位", "no.1", "ナンバーワン", "最高", "最強", "神本",
                     "名著", "必読", "おすすめ", "オススメ", "人気", "話題", "絶賛", "bestseller", "best seller",
                     "best", "#1"],
    "一時的な情報": ["新刊", "新作", "最新刊", "発売中", "予約", "セール", "セール中", "期間限定", "今だけ", "値下げ",
               "割引", "無料", "0円", "キャンペーン", "free", "sale", "new release", "on sale"],
    "Amazon のプログラム名": ["kindle unlimited", "kindleunlimited", "キンドルアンリミテッド", "読み放題",
                         "kdp select", "kdpセレクト", "kdp セレクト", "prime reading", "プライムリーディング"],
    "どの商品にも当てはまる語": ["本", "書籍", "電子書籍", "kindle本", "kindle版", "ebook", "e-book", "book"],
}

# キーワード候補から外す、文章によく出るが検索語にならない語
STOPWORDS = set("""
本書 本章 次章 前章 各章 本文 原稿 章末 巻末 付録 目次 場合 必要 以下 以上 部分 今回 最初 最後 自分 一つ 二つ 三つ
方法 説明 紹介 理由 内容 結果 確認 注意 使用 利用 可能 一般 程度 状態 一覧 時間 意味 一度 全体 簡単 問題 大切 重要
実際 具体 具体的 基本 基本的 以外 以前 以後 同様 様子 前後 途中 毎回 毎日 毎朝 少し 他人 相手 自身 気持 仕組 手順
今日 明日 昨日 一日 一年 二十時間 五分 二時間 数字 記事 行目 番目 文字 部分的 対象 段階 第一段階 第二段階 第三段階
本当 普通 通常 特別 例外 種類 参照 見出 記法 表記 表示 生成 工夫 準備 実行 効果 記録 観察 一括 宛先 面倒 本文中 自動
作成 変更 指定 出力 入力 設定 追加 削除 修正 用意 実行 処理 操作 動作 対応 選択 機能 項目 情報 完成 作業 手作業
""".split())
STOP_ASCII = set("""
a an the and or of to in on for with by is are be this that it as at from you your we our not no yes if then
else do does can will just more most other some such than too very also only into out up down over under
md yaml html epub3 pdf jpg png id src img
""".split())

KANJI_NUMERALS = set("〇一二三四五六七八九十百千万億兆")

# カテゴリー候補の表（Kindle ストア > Kindle 本 の下の分類をもとにした目安の名前）と、判定に使う語。
# KDP の「カテゴリーを選択」画面の名前とは細部が異なることがあるので、画面で近いものを選び直す前提。
CATEGORY_TABLE: list[tuple[str, list[str]]] = [
    ("コンピュータ・IT > プログラミング",
     ["プログラミング", "プログラム", "スクリプト", "python", "javascript", "typescript", "ruby", "java", "go言語",
      "rust", "関数", "変数", "コード", "ソースコード", "開発", "git", "github", "lua", "ライブラリ"]),
    ("コンピュータ・IT > Web・インターネット",
     ["web", "ウェブ", "html", "css", "サイト", "ホームページ", "ブログ", "インターネット", "http", "ブラウザ"]),
    ("コンピュータ・IT > アプリケーション",
     ["excel", "エクセル", "word", "スプレッドシート", "アプリ", "ソフト", "ツール", "notion", "スライド"]),
    ("コンピュータ・IT > OS",
     ["windows", "macos", "linux", "ubuntu", "ターミナル", "コマンド", "シェル", "bash", "powershell"]),
    ("コンピュータ・IT > データベース", ["データベース", "sql", "mysql", "postgresql", "テーブル設計"]),
    ("コンピュータ・IT > ネットワーク・サーバー", ["ネットワーク", "サーバー", "クラウド", "aws", "インフラ"]),
    ("コンピュータ・IT > AI・機械学習",
     ["ai", "人工知能", "機械学習", "深層学習", "生成ai", "chatgpt", "claude", "llm", "プロンプト"]),
    ("コンピュータ・IT > 情報セキュリティ", ["セキュリティ", "暗号", "パスワード", "脆弱性", "不正アクセス"]),
    ("コンピュータ・IT > グラフィック・DTP",
     ["dtp", "組版", "epub", "電子出版", "レイアウト", "フォント", "pdf", "印刷", "縦書き", "横書き", "markdown",
      "pandoc"]),
    ("ビジネス・経済 > 仕事術・整理術",
     ["仕事術", "効率化", "時短", "自動化", "生産性", "タスク", "業務", "作業", "段取り", "整理術"]),
    ("ビジネス・経済 > 自己啓発", ["自己啓発", "習慣", "目標", "成功", "モチベーション", "成長", "考え方"]),
    ("ビジネス・経済 > マーケティング・セールス", ["マーケティング", "集客", "販売", "広告", "ブランディング", "sns"]),
    ("ビジネス・経済 > 起業・独立・副業",
     ["起業", "副業", "個人事業", "フリーランス", "独立", "個人出版", "セルフパブリッシング", "kdp", "出版"]),
    ("ビジネス・経済 > 経営・マネジメント", ["経営", "マネジメント", "組織", "リーダー", "チーム", "部下"]),
    ("投資・金融・会社経営 > 投資・資産運用", ["投資", "株式", "資産", "nisa", "ideco", "配当", "投資信託"]),
    ("人文・思想 > 心理学", ["心理", "心理学", "感情", "メンタル", "認知"]),
    ("文学・評論 > エッセー・随筆", ["エッセイ", "エッセー", "随筆", "日記"]),
    ("暮らし・健康・子育て > 健康・家庭医学", ["健康", "運動", "睡眠", "食事", "ダイエット", "ストレス"]),
    ("暮らし・健康・子育て > 家事・生活", ["家事", "片付け", "掃除", "収納", "節約", "家計"]),
    ("暮らし・健康・子育て > 子育て", ["子育て", "育児", "子ども", "子供", "妊娠"]),
    ("教育・学参・受験 > 学習法", ["勉強", "学習", "勉強法", "記憶", "試験", "受験"]),
    ("資格・検定・就職", ["資格", "検定", "就職", "転職", "面接"]),
    ("語学・辞事典・年鑑", ["英語", "英会話", "中国語", "韓国語", "単語", "文法"]),
    ("アート・建築・デザイン", ["デザイン", "イラスト", "写真", "絵", "配色"]),
    ("科学・テクノロジー", ["科学", "物理", "化学", "数学", "工学", "生物"]),
    ("歴史・地理", ["歴史", "戦国", "江戸", "古代", "地理"]),
    ("旅行ガイド・マップ", ["旅行", "観光", "ホテル", "温泉"]),
    ("スポーツ・アウトドア", ["スポーツ", "筋トレ", "ランニング", "登山", "キャンプ", "ゴルフ"]),
    ("趣味・実用 > 料理・レシピ", ["料理", "レシピ", "献立", "お弁当"]),
]


class ListingError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[listing] {msg}", file=sys.stderr)


def norm(s: str) -> str:
    """比較用の正規化（全角英数→半角、大文字→小文字、空白の除去）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).lower())


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------------------
# 原稿の読み込み（Markdown → 見出しと段落のプレーンテキスト）
# ---------------------------------------------------------------------------

@dataclass
class Chapter:
    title: str
    kind: str                     # numbered / unnumbered / appendix
    paragraphs: list[str] = field(default_factory=list)   # 本文の全ての段落・箇条書き（キーワード抽出用）
    prose: list[str] = field(default_factory=list)        # 紹介文に使える段落（コード・参照・URL を含まない）
    headings: list[str] = field(default_factory=list)   # 節（##）以下の見出し
    label: str = ""               # 「第1章」など


def strip_inline(text: str) -> str:
    """インライン記法を取り除いて、読める文字だけにする。"""
    t = text
    t = re.sub(r"<!--.*?-->", "", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?", "", t)          # 画像
    t = re.sub(r"\[@[^\]]+\]", "", t)                               # 相互参照 [@sec:x]
    t = re.sub(r"(?<!\w)@(sec|fig|tbl|lst):[\w-]+", "", t)
    t = re.sub(r"\[\^[^\]]+\]", "", t)                              # 脚注の参照
    t = re.sub(r"\[([^\]]+)\]\{[^}]*ruby=[^}]*\}", r"\1", t)        # [漢字]{ruby="かんじ"}
    t = re.sub(r"\{([^{}|]+)(\|[^{}]+)+\}", r"\1", t)               # {漢字|かんじ}
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                  # リンク
    t = re.sub(r"\[([^\]]+)\]\{[^}]*\}", r"\1", t)                  # [文字]{.class}
    t = re.sub(r"`[^`]*`", "", t)                                   # インラインコード（紹介文には使わない）
    t = re.sub(r"<[^>]+>", "", t)                                   # HTML タグ
    t = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", t)  # 強調
    t = t.replace("\\", "")
    return re.sub(r"[ \t]+", " ", t).strip()


def parse_heading(line: str) -> tuple[int, str, str] | None:
    m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
    if not m:
        return None
    level, text = len(m.group(1)), m.group(2)
    attrs = ""
    am = re.search(r"\s*\{([^}]*)\}\s*$", text)
    if am:
        attrs, text = am.group(1), text[: am.start()]
    return level, strip_inline(text.rstrip("#").strip()), attrs


def read_chapters(paths: list[Path]) -> list[Chapter]:
    chapters: list[Chapter] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        current: Chapter | None = None
        para: list[str] = []
        fence: str | None = None
        in_footnote = False

        def flush(is_list: bool = False):
            nonlocal para
            if para and current is not None:
                raw = "".join(s.strip() for s in para)
                text = strip_inline(raw)
                if text:
                    current.paragraphs.append(text)
                    # インラインコード・相互参照・URL を消すと文が壊れるので、紹介文には使わない
                    if not is_list and not re.search(r"`|\[@|@(sec|fig|tbl|lst):|<https?:|https?://|\{#", raw):
                        current.prose.append(text)
            para = []

        for line in lines:
            stripped = line.strip()
            if fence:                                  # コードブロックの中は読まない
                if stripped.startswith(fence):
                    fence = None
                continue
            fm = re.match(r"^(`{3,}|~{3,})", stripped)
            if fm:
                flush()
                fence = fm.group(1)
                continue
            if in_footnote:
                if line.startswith(("    ", "\t")) and stripped:
                    continue
                in_footnote = False
            if re.match(r"^\[\^[^\]]+\]:", stripped):  # 脚注の本文は紹介文に使わない
                flush()
                in_footnote = True
                continue
            heading = parse_heading(line)
            if heading:
                flush()
                level, text, attrs = heading
                if level == 1:
                    kind = "numbered"
                    if re.search(r"(^|\s)\.appendix\b", attrs):
                        kind = "appendix"
                    elif re.search(r"(^|\s)(\.unnumbered|-)(\s|$)", attrs):
                        kind = "unnumbered"
                    current = Chapter(title=text, kind=kind)
                    chapters.append(current)
                elif current is not None:
                    current.headings.append(text)
                continue
            if not stripped or stripped.startswith((":::", "|", "<!--")) or re.match(r"^[-=+:| ]{3,}$", stripped):
                flush()
                continue
            if stripped.startswith(">"):
                stripped = stripped.lstrip("> ")
            if re.match(r"^([-*+]|\d+[.)])\s+", stripped):   # 箇条書きは 1 項目 = 1 段落
                flush()
                para.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped))
                flush(is_list=True)
                continue
            if re.match(r"^:\s", stripped) or re.match(r"^\[\^?[^\]]+\]:", stripped):  # 表のキャプション・参照定義
                flush()
                continue
            if current is None:                         # 見出しの前の文章は 1 つの章として扱う
                current = Chapter(title="", kind="unnumbered")
                chapters.append(current)
            para.append(stripped)
        flush()
    return chapters


def label_chapters(chapters: list[Chapter], layout: dict) -> None:
    chapter_label = layout.get("chapter_label", "第{n}章")
    appendix_label = layout.get("appendix_label", "付録{n}")
    numbered = bool(layout.get("number_chapters", True))
    n = a = 0
    for ch in chapters:
        if ch.kind == "numbered" and numbered:
            n += 1
            ch.label = chapter_label.replace("{n}", str(n))
        elif ch.kind == "appendix" and numbered:
            a += 1
            ch.label = appendix_label.replace("{n}", chr(ord("A") + a - 1) if "{A}" in appendix_label else str(a))
            ch.label = ch.label.replace("{A}", chr(ord("A") + a - 1))


# ---------------------------------------------------------------------------
# 内容紹介
# ---------------------------------------------------------------------------

def first_sentence(text: str, limit: int = 80) -> str:
    m = re.match(r"(.+?[。！？!?])", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[: limit - 1] + "…"


def html_length(html: str) -> int:
    return len(html)


def html_to_text(html: str) -> str:
    t = re.sub(r"</(p|h[4-6]|li|ul|ol)>", "\n", html)
    t = re.sub(r"<li>", "・", t)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def build_description(cfg: dict, chapters: list[Chapter]) -> tuple[str, list[str]]:
    """内容紹介の HTML を組み立てる。4,000 文字を超えるときは後ろの要素から削る。"""
    notes: list[str] = []
    lead = str(cfg.get("description") or "").strip()
    if not lead:
        notes.append("book.yaml に description が無いため、まえがきから書き出しました")

    # まえがき（本文の章より前にある番号なしの章）の冒頭の段落
    preface: list[str] = []
    for ch in chapters:
        if ch.kind != "unnumbered":
            break
        preface.extend(ch.prose)
    # 「本書はこのテンプレートのサンプル」のような、読者向けでない段落は除く
    preface = [p for p in preface if not re.search(r"サンプル|テンプレート|この(章|節)では", p)]
    preface = [p for p in preface if norm(p) != norm(lead)]

    body = [ch for ch in chapters if ch.kind in ("numbered", "appendix") and ch.title]
    items = []
    for ch in body:
        name = f"{ch.label}　{ch.title}" if ch.label else ch.title
        summary = ""
        if ch.prose:
            summary = first_sentence(ch.prose[0])
        elif ch.headings:
            summary = "／".join(ch.headings[:4])
        items.append((name, summary))

    def render(n_preface: int, with_summary: bool, n_items: int) -> str:
        parts = []
        if lead:
            parts.append(f"<p>{escape(lead, quote=False)}</p>")
        for p in preface[:n_preface]:
            parts.append(f"<p>{escape(p, quote=False)}</p>")
        if items[:n_items]:
            parts.append("<h4>本書の内容</h4>")
            lis = []
            for name, summary in items[:n_items]:
                text = escape(name, quote=False)
                if with_summary and summary:
                    text = f"<b>{text}</b><br>{escape(summary, quote=False)}"
                lis.append(f"<li>{text}</li>")
            parts.append("<ul>" + "".join(lis) + "</ul>")
        return "\n".join(parts)

    # 長すぎたら「章の要約 → まえがきの段落 → 章の一覧」の順に削る
    candidates = []
    for n_pre in range(min(len(preface), 3), -1, -1):
        candidates.append((n_pre, True, len(items)))
    for n_pre in range(min(len(preface), 3), -1, -1):
        candidates.append((n_pre, False, len(items)))
    for n_it in range(len(items) - 1, -1, -1):
        candidates.append((0, False, n_it))
    for n_pre, summary, n_it in candidates:
        html = render(n_pre, summary, n_it)
        if html_length(html) <= DESCRIPTION_MAX:
            if (n_pre, summary, n_it) != candidates[0]:
                notes.append(f"{DESCRIPTION_MAX:,} 文字に収めるため、まえがき・章の要約の一部を省きました")
            return html, notes
    # description だけで超える場合は切り詰める
    html = render(0, False, 0)
    cut = DESCRIPTION_MAX - len("</p>") - 1
    notes.append(f"book.yaml の description が長すぎるため {DESCRIPTION_MAX:,} 文字で切りました")
    return html[:cut] + "…</p>", notes


def check_description(html: str) -> list[str]:
    """KDP の内容紹介のルールに反していそうな箇所を返す。"""
    problems = []
    length = html_length(html)
    if length > DESCRIPTION_MAX:
        problems.append(f"文字数が {length:,} 文字です（上限 {DESCRIPTION_MAX:,} 文字。HTML タグも数える）")
    for tag in sorted({t.lower() for t in re.findall(r"</?\s*([a-zA-Z0-9]+)", html)} - ALLOWED_TAGS):
        problems.append(f"KDP の内容紹介で使えない HTML タグ <{tag}> があります")
    text = html_to_text(html)
    if re.search(r"https?://|www\.", text):
        problems.append("URL（Web サイトへのリンク）は内容紹介に書けません")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        problems.append("メールアドレスなどの連絡先は内容紹介に書けません")
    if re.search(r"0\d{1,4}-\d{1,4}-\d{3,4}", text):
        problems.append("電話番号などの連絡先は内容紹介に書けません")
    for reason, words in PROHIBITED_TERMS.items():
        if reason == "どの商品にも当てはまる語":
            continue
        hits = [w for w in words if len(w) >= 2 and contains_term(text, w)]
        if hits:
            problems.append(f"{reason}にあたる語があります: {', '.join(hits)}")
    return problems


def contains_term(text: str, term: str) -> bool:
    n_text, n_term = norm(text), norm(term)
    if re.fullmatch(r"[a-z0-9 .#+-]+", n_term):
        return re.search(rf"(?<![a-z0-9]){re.escape(n_term)}(?![a-z0-9])", n_text) is not None
    return n_term in n_text


# ---------------------------------------------------------------------------
# キーワード
# ---------------------------------------------------------------------------

TERM_PATTERNS = [
    re.compile(r"[A-Z][A-Za-z0-9+#.\-]*(?: [A-Z][A-Za-z0-9+#.\-]*)+"),   # Kindle Previewer など
    re.compile(r"[A-Za-z][A-Za-z0-9+#\-]*[A-Za-z0-9+#]"),                # EPUB3, Python, C++
    re.compile(r"[ァ-ヴー][ァ-ヴー・]{2,}"),                              # カタカナ語
    re.compile(r"[一-龯々]{2,6}(?:[きしり](?![ぁ-ん]{0,1}[ぁ-ゖ]{2}))?"),    # 漢字の熟語（縦書き・見出し など）
]


def extract_terms(chapters: list[Chapter]) -> Counter:
    """原稿から検索語になりそうな語を数える。見出しの語は重く数える。"""
    score: Counter = Counter()
    spread: dict[str, set[int]] = {}
    display: dict[str, str] = {}
    for idx, ch in enumerate(chapters):
        weighted = [(ch.title, 4)] + [(h, 2) for h in ch.headings] + [(p, 1) for p in ch.paragraphs]
        for text, weight in weighted:
            found: list[str] = []
            for pat in TERM_PATTERNS:
                for m in pat.finditer(text):
                    term = m.group(0).strip("・-.")
                    if any(term in f for f in found if f != term):  # 長い語の一部は数えない
                        continue
                    found.append(term)
            for term in found:
                key = norm(term)
                if not is_candidate(term, key):
                    continue
                score[key] += weight
                spread.setdefault(key, set()).add(idx)
                display.setdefault(key, term)
    # 複数の章に出てくる語を優先する
    ranked: Counter = Counter()
    for key, s in score.items():
        term = display[key]
        weight = 1 + 0.5 * (len(spread[key]) - 1)
        # 漢字 2 文字の語（「表示」「準備」など）は一般的な語が多いので控えめに数える
        if re.fullmatch(r"[一-龯々]{2}", term):
            weight *= 0.4
        if s < 2:          # 1 回しか出てこない語は候補にしない
            continue
        ranked[term] = s * weight
    return ranked


def is_candidate(term: str, key: str) -> bool:
    if len(key) < 2 or len(term) > KEYWORD_MAX:
        return False
    if term in STOPWORDS or key in STOP_ASCII:
        return False
    if re.fullmatch(r"[a-z]{2}", key) and key not in {"ai", "ui", "ux", "os", "go", "r"}:
        return False
    if re.fullmatch(r"第?[0-9〇一二三四五六七八九十]+[章節項部]", term):
        return False
    if all(c in KANJI_NUMERALS for c in term):
        return False
    if re.fullmatch(r"[0-9.\-]+", key):
        return False
    return True


def prohibited_reason(term: str) -> str | None:
    key = norm(term)
    for reason, words in PROHIBITED_TERMS.items():
        for w in words:
            nw = norm(w)
            if key == nw or (len(nw) >= 3 and contains_term(term, w) and reason != "どの商品にも当てはまる語"):
                return reason
    return None


@dataclass
class Keyword:
    text: str
    source: str


def choose_keywords(cfg: dict, listing: dict, chapters: list[Chapter]) -> tuple[list[Keyword], list[str], list[tuple[str, str]]]:
    """7 つの入力欄に入れるキーワードを選ぶ。戻り値は（採用, その他の候補, 除外した語と理由）。"""
    metadata_terms = [str(cfg.get(k) or "") for k in ("title", "subtitle", "publisher")]
    for p in as_list(cfg.get("author")) + as_list(cfg.get("contributors")):
        metadata_terms.append(p.get("name", "") if isinstance(p, dict) else str(p))
    metadata_norm = [norm(t) for t in metadata_terms if t]
    excluded_user = {norm(str(k)) for k in as_list(listing.get("exclude_keywords"))}

    chosen: list[Keyword] = []
    rejected: list[tuple[str, str]] = []
    others: list[str] = []

    def overlaps(key: str) -> bool:
        for kw in chosen:
            k2 = norm(kw.text)
            if key == k2 or (len(key) >= 2 and key in k2) or (len(k2) >= 2 and k2 in key):
                return True
        return False

    def consider(term: str, source: str, forced: bool = False) -> None:
        term = str(term).strip()
        if not term:
            return
        key = norm(term)
        if len(term) > KEYWORD_MAX:
            rejected.append((term, f"{KEYWORD_MAX} 文字を超えている（{len(term)} 文字）"))
            return
        reason = prohibited_reason(term)
        if reason:
            rejected.append((term, f"KDP のガイドラインで使えない語（{reason}）"))
            return
        if not forced:
            if key in excluded_user:
                return
            if any(key and key in m for m in metadata_norm):
                rejected.append((term, "タイトル・サブタイトル・著者名などに含まれている（検索対象になるので不要）"))
                return
        if overlaps(key):
            return
        if len(chosen) < KEYWORD_SLOTS:
            chosen.append(Keyword(term, source))
        else:
            others.append(term)

    for k in as_list(listing.get("keywords")):
        consider(k, "book.yaml の listing.keywords", forced=True)
    for k in as_list(cfg.get("keywords")):
        consider(k, "book.yaml の keywords")
    for term, _ in extract_terms(chapters).most_common(60):
        if len(others) >= 15:
            break
        consider(term, "原稿から抽出")
    # 原稿由来の除外は数が多いので、book.yaml に書いた語の除外だけを報告する
    user_terms = {norm(str(k)) for k in as_list(cfg.get("keywords")) + as_list(listing.get("keywords"))}
    rejected = [(t, r) for t, r in rejected if norm(t) in user_terms or "ガイドライン" in r]
    seen = set()
    rejected = [x for x in rejected if not (x[0] in seen or seen.add(x[0]))]
    return chosen, others, rejected


# ---------------------------------------------------------------------------
# カテゴリー
# ---------------------------------------------------------------------------

def suggest_categories(cfg: dict, chapters: list[Chapter], keywords: list[Keyword]) -> list[tuple[str, int, list[str]]]:
    parts = [str(cfg.get("title") or ""), str(cfg.get("subtitle") or ""), str(cfg.get("description") or "")]
    parts += [str(k) for k in as_list(cfg.get("keywords"))] + [k.text for k in keywords]
    heads = []
    for ch in chapters:
        heads.append(ch.title)
        heads.extend(ch.headings)
    text_meta = norm(" ".join(parts))
    text_heads = norm(" ".join(heads))
    text_body = norm(" ".join(p for ch in chapters for p in ch.paragraphs))

    def count(text: str, word: str) -> int:
        w = norm(word)
        if re.fullmatch(r"[a-z0-9+#.]+", w):
            return len(re.findall(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text))
        return text.count(w)

    results = []
    for name, words in CATEGORY_TABLE:
        score = 0
        hits = []
        for w in words:
            s = 5 * count(text_meta, w) + 3 * count(text_heads, w) + count(text_body, w)
            if s:
                score += s
                hits.append((s, w))
        if score:
            hits.sort(reverse=True)
            results.append((name, score, [w for _, w in hits[:5]]))
    results.sort(key=lambda r: -r[1])
    return results


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    book: str
    title: str
    subtitle: str
    authors: list[str]
    description_html: str
    description_notes: list[str]
    description_problems: list[str]
    description_source: str
    keywords: list[Keyword]
    other_keywords: list[str]
    rejected_keywords: list[tuple[str, str]]
    categories_pinned: list[str]
    categories: list[tuple[str, int, list[str]]]
    problems: list[str]           # KDP の制限・ルールに反している（--check で失敗にする）
    notes: list[str]              # 参考（失敗にはしない）


def make_listing(book_dir: Path) -> Listing:
    path = book_dir / "book.yaml"
    if not path.exists():
        raise ListingError(f"{path} がありません")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict) or not cfg.get("title"):
        raise ListingError(f"{path} に title がありません")
    listing = cfg.get("listing") or {}
    if not isinstance(listing, dict):
        raise ListingError("book.yaml の listing は key: value の形で書いてください")

    paths = [book_dir / c for c in as_list(cfg.get("chapters"))] or sorted((book_dir / "chapters").glob("*.md"))
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise ListingError(f"原稿が見つかりません: {missing[0]}")
    if not paths:
        raise ListingError("原稿（chapters）がありません")
    chapters = read_chapters(paths)
    label_chapters(chapters, cfg.get("layout") or {})

    problems: list[str] = []
    title, subtitle = str(cfg["title"]), str(cfg.get("subtitle") or "")
    if len(title) + len(subtitle) >= TITLE_MAX:
        problems.append(f"タイトルとサブタイトルの合計が {len(title) + len(subtitle)} 文字です（{TITLE_MAX} 文字未満にする）")
    for t in (title, subtitle):
        for reason, words in PROHIBITED_TERMS.items():
            if reason != "どの商品にも当てはまる語" and any(len(w) >= 2 and contains_term(t, w) for w in words):
                problems.append(f"タイトル・サブタイトルに{reason}にあたる語があります: {t}")
                break

    if listing.get("description"):
        html = str(listing["description"]).strip()
        desc_notes, source = [], "book.yaml の listing.description（手で書いたもの）"
    else:
        html, desc_notes = build_description(cfg, chapters)
        source = "book.yaml の description と原稿から自動で作った下書き"
    desc_problems = check_description(html)
    problems += ["内容紹介: " + p for p in desc_problems]

    notes: list[str] = []
    keywords, others, rejected = choose_keywords(cfg, listing, chapters)
    if len(keywords) < KEYWORD_SLOTS:
        notes.append(f"キーワードが {len(keywords)} 個しか見つかりませんでした（{KEYWORD_SLOTS} 個まで入力できる）")
    for kw in as_list(listing.get("keywords")):
        if len(str(kw)) > KEYWORD_MAX:
            problems.append(f"キーワード「{kw}」が {KEYWORD_MAX} 文字を超えています")
    if len(as_list(listing.get("keywords"))) > KEYWORD_SLOTS:
        problems.append(f"listing.keywords が {KEYWORD_SLOTS} 個を超えています（入りきらない分は「その他の候補」に回しました）")

    pinned = [str(c) for c in as_list(listing.get("categories"))]
    if len(pinned) > CATEGORY_MAX:
        problems.append(f"listing.categories が {len(pinned)} 個あります（KDP で選べるのは {CATEGORY_MAX} つまで）")
    categories = suggest_categories(cfg, chapters, keywords)

    authors = [p.get("name", "") if isinstance(p, dict) else str(p) for p in as_list(cfg.get("author"))]
    return Listing(book_dir.name, title, subtitle, authors, html, desc_notes, desc_problems, source,
                   keywords, others, rejected, pinned, categories, problems, notes)


def render_markdown(ls: Listing) -> str:
    out: list[str] = []
    w = out.append
    w(f"# KDP 登録情報の下書き: {ls.title}")
    w("")
    w("> `scripts/kdp-listing.py` が自動で作った**下書き**です。そのまま使わず、読み直して書き直してください。")
    w("> キーワードとカテゴリーは、KDP の画面で実際に選べるもの・本の内容に合うものかを確かめてから入力します。")
    w("")
    w("## タイトル・著者（確認用）")
    w("")
    w("| 項目 | 値 | 文字数 |")
    w("|:--|:--|--:|")
    w(f"| タイトル | {ls.title} | {len(ls.title)} |")
    if ls.subtitle:
        w(f"| サブタイトル | {ls.subtitle} | {len(ls.subtitle)} |")
    w(f"| 著者 | {' / '.join(ls.authors)} | |")
    w("")
    w(f"タイトルとサブタイトルの合計: {len(ls.title) + len(ls.subtitle)} 文字（KDP の上限: {TITLE_MAX} 文字未満）")
    w("")

    length = html_length(ls.description_html)
    w(f"## 内容紹介（{length:,} / {DESCRIPTION_MAX:,} 文字）")
    w("")
    w(f"元にしたもの: {ls.description_source}。KDP の「内容紹介」欄に、下の HTML をそのまま貼り付けます。")
    w("")
    w("```html")
    w(ls.description_html)
    w("```")
    w("")
    w("<details><summary>表示イメージ（タグを除いた文章）</summary>")
    w("")
    w("```text")
    w(html_to_text(ls.description_html))
    w("```")
    w("")
    w("</details>")
    w("")
    for n in ls.description_notes:
        w(f"- メモ: {n}")
    if ls.description_problems:
        for p in ls.description_problems:
            w(f"- **要修正**: {p}")
    else:
        w("- 文字数・HTML タグ・禁止事項（URL・連絡先・宣伝文句・一時的な情報）のチェック: 問題なし")
    w("- 書き直すときのヒント: 冒頭の 2〜3 行で「誰の・どんな悩みを・どう解決する本か」を伝える。"
      "対象読者・読んで得られることを足すと、販売ページで読まれやすくなります")
    w("")

    w(f"## キーワード（{len(ls.keywords)} / {KEYWORD_SLOTS} 個、各 {KEYWORD_MAX} 文字以内）")
    w("")
    w("KDP の 7 つの入力欄に、上から 1 つずつ入力します。1 つの欄に関連する語を空白区切りで複数入れてもかまいません（50 文字以内）。")
    w("")
    w("| 欄 | キーワード | 文字数 | 由来 |")
    w("|--:|:--|--:|:--|")
    for i, kw in enumerate(ls.keywords, 1):
        w(f"| {i} | {kw.text} | {len(kw.text)} | {kw.source} |")
    w("")
    if ls.other_keywords:
        w("その他の候補（入れ替えや、1 つの欄にまとめるときに）: " + "、".join(ls.other_keywords))
        w("")
    if ls.rejected_keywords:
        w("候補から外した語:")
        w("")
        for term, reason in ls.rejected_keywords:
            w(f"- {term} … {reason}")
        w("")

    w(f"## カテゴリー候補（KDP で選べるのは {CATEGORY_MAX} つまで）")
    w("")
    if ls.categories_pinned:
        w("book.yaml の `listing.categories` で指定したカテゴリー:")
        w("")
        for c in ls.categories_pinned:
            w(f"- {c}")
        w("")
    if ls.categories:
        w("原稿に出てくる語から推定した候補です（上ほど当てはまりがよい）。名前は Kindle ストアの分類をもとにした目安なので、"
          "KDP の「カテゴリーを選択」画面で近いものを選んでください。")
        w("")
        w("| 順位 | カテゴリー（目安） | 根拠になった語 |")
        w("|--:|:--|:--|")
        for i, (name, _score, hits) in enumerate(ls.categories[:6], 1):
            mark = "**" if i <= CATEGORY_MAX else ""
            w(f"| {i} | {mark}{name}{mark} | {'、'.join(hits)} |")
        w("")
    else:
        w("原稿から推定できるカテゴリーがありませんでした。KDP の画面で本の内容に合うものを選んでください。")
        w("")

    w("## チェック結果")
    w("")
    if ls.problems:
        for p in ls.problems:
            w(f"- **要修正**: {p}")
    else:
        w("- KDP の文字数・個数の制限やルールに反している項目はありません")
    for n in ls.notes:
        w(f"- 参考: {n}")
    w("")
    return "\n".join(out)


def to_json(ls: Listing) -> dict:
    return {
        "book": ls.book,
        "title": ls.title,
        "subtitle": ls.subtitle,
        "authors": ls.authors,
        "description": {"html": ls.description_html, "text": html_to_text(ls.description_html),
                        "length": html_length(ls.description_html), "max": DESCRIPTION_MAX,
                        "problems": ls.description_problems},
        "keywords": [{"text": k.text, "length": len(k.text), "source": k.source} for k in ls.keywords],
        "other_keywords": ls.other_keywords,
        "rejected_keywords": [{"text": t, "reason": r} for t, r in ls.rejected_keywords],
        "categories": {"pinned": ls.categories_pinned,
                       "suggested": [{"name": n, "score": s, "matched": h} for n, s, h in ls.categories]},
        "limits": {"description": DESCRIPTION_MAX, "keyword_slots": KEYWORD_SLOTS, "keyword_length": KEYWORD_MAX,
                   "categories": CATEGORY_MAX, "title_and_subtitle": TITLE_MAX},
        "problems": ls.problems,
        "notes": ls.notes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KDP の内容紹介・キーワード・カテゴリー候補の下書きを作る")
    ap.add_argument("books", nargs="*", type=Path, help="本のディレクトリ（book.yaml がある場所）")
    ap.add_argument("--all", action="store_true", help="books/ 以下の全ての本")
    ap.add_argument("-o", "--output-dir", default=str(ROOT / "dist"), help="出力先（既定: dist）")
    ap.add_argument("--stdout", action="store_true", help="ファイルに書かずに標準出力に出す")
    ap.add_argument("--json", action="store_true", help="<名前>-listing.json も書き出す（--stdout なら JSON を出す）")
    ap.add_argument("--check", action="store_true", help="KDP の制限を超える項目があれば終了コード 1 にする")
    args = ap.parse_args(argv)

    books = list(args.books)
    if args.all:
        books += sorted(p.parent for p in (ROOT / "books").glob("*/book.yaml"))
    if not books:
        ap.error("本のディレクトリか --all を指定してください")

    failed = False
    out_dir = Path(args.output_dir)
    for book in books:
        try:
            ls = make_listing(book.resolve())
        except ListingError as e:
            log(f"エラー: {e}")
            failed = True
            continue
        if args.stdout:
            if args.json:
                print(json.dumps(to_json(ls), ensure_ascii=False, indent=2))
            else:
                print(render_markdown(ls))
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            md = out_dir / f"{ls.book}-listing.md"
            md.write_text(render_markdown(ls), encoding="utf-8")
            log(f"出力: {md}")
            if args.json:
                js = out_dir / f"{ls.book}-listing.json"
                js.write_text(json.dumps(to_json(ls), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                log(f"出力: {js}")
        for p in ls.problems:
            log(f"{ls.book}: 要修正: {p}")
        for n in ls.notes:
            log(f"{ls.book}: 参考: {n}")
        if args.check and ls.problems:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
