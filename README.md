# Kindle 本テンプレート（実用書・技術書向け）

Markdown で書いた原稿から、**Kindle Direct Publishing（KDP）にそのままアップロードできる EPUB3** を、コマンド 1 つで作るテンプレートです。

- 原稿は **章ごとの Markdown ファイル**に分けて書く
- `book.yaml` の 1 行で **縦書き（右綴じ）と横書き（左綴じ）を切り替え**
- 縦書きでも **コードブロック・表・英数字** が読みやすいように CSS を調整済み
- 見出し／自動目次／シンタックスハイライト／表／図番号／囲み／脚注／ルビに対応
- 原稿の画像をビルド時に **Kindle 向けに自動で最適化**（縮小・透過の除去・形式変換。元画像はそのまま）
- **ISBN なし**で出版できるメタデータ（固定 UUID）を `book.yaml` で管理
- **EPUBCheck** で検証し、エラーだけでなく**警告が 1 件でもあれば失敗**にする（`make check`）
- **GitHub Actions** で push のたびに全ての本を縦書き版・横書き版の両方でビルドし、EPUBCheck で検証
- `npm run lint` で **表記ゆれ・文章・リンク切れ** をまとめてチェック（[原稿のチェック](#原稿のチェック)）
- 同じ原稿から **KDP ペーパーバック（紙の本）の本文 PDF** も作れる。判型・余白・ノンブル・裁ち落としは KDP の要件どおり、縦書き・横書きの両方に対応（`make paperback`。[ペーパーバック（紙の本）](#ペーパーバック紙の本)）
- KDP に入力する **内容紹介・キーワード 7 つ・カテゴリーの候補** の下書きを、`book.yaml` と原稿から作る。文字数などの KDP の制限も確認（`make listing`。[docs/kdp-listing.md](docs/kdp-listing.md)）

```bash
make            # → dist/horizontal-sample.epub, dist/vertical-sample.epub
make paperback  # → dist/horizontal-sample-paperback.pdf, dist/vertical-sample-paperback.pdf
```

---

## 目次

1. [ディレクトリ構成](#ディレクトリ構成)
2. [セットアップ](#セットアップ)
3. [ビルド方法](#ビルド方法)
4. [EPUBCheck による検証](#epubcheck-による検証)
5. [新しい本を作る](#新しい本を作る)
6. [設定ファイル book.yaml](#設定ファイル-bookyaml)
7. [表紙の自動生成](#表紙の自動生成)
8. [ペーパーバック（紙の本）](#ペーパーバック紙の本)
9. [原稿の書き方](#原稿の書き方)
10. [画像の最適化](#画像の最適化)
11. [原稿のチェック](#原稿のチェック)
12. [縦書きの表示の工夫](#縦書きの表示の工夫)
13. [Kindle Previewer での確認方法](#kindle-previewer-での確認方法)
14. [KDP へのアップロード手順](#kdp-へのアップロード手順)
15. [GitHub Actions](#github-actions)
16. [設計上の判断（KDP ガイドラインに基づいて決めたこと）](#設計上の判断kdp-ガイドラインに基づいて決めたこと)
17. [トラブルシューティング](#トラブルシューティング)

---

## ディレクトリ構成

```text
.
├── books/
│   ├── horizontal-sample/     # 横書き版サンプル（技術書: このテンプレートの使い方）
│   │   ├── book.yaml          #   本の設定（書誌情報・表紙・章の順番・組版）
│   │   ├── chapters/*.md      #   原稿（1 章 = 1 ファイル）
│   │   └── images/            #   表紙・図版
│   └── vertical-sample/       # 縦書き版サンプル（実用書: 小さな自動化のすすめ）
│       └── textlint.json      #   この本だけのチェック設定（漢数字を許可）
├── filters/                   # Pandoc の Lua フィルタ
│   ├── images.lua             #   画像の参照先を最適化版に差し替える
│   ├── linebreaks.lua         #   日本語の改行で空白が入らないようにする
│   ├── crossref.lua           #   章番号・図/表/リスト番号・相互参照
│   ├── admonition.lua         #   注意書きなどの囲み
│   ├── ruby.lua               #   ルビ
│   └── vertical.lua           #   縦中横、縦書き時のコード・表の表示方式
├── styles/
│   ├── base.css               #   共通スタイル
│   ├── horizontal.css         #   横書き用
│   ├── vertical.css           #   縦書き用
│   ├── print.css              #   ペーパーバック（紙の本）用
│   └── kindle.theme           #   シンタックスハイライトの配色（E-ink でも区別できる）
├── scripts/
│   ├── build.py               # ビルドスクリプト（本体）
│   ├── cover.py               # 表紙画像の自動生成
│   ├── images.py              # 画像の Kindle 向け最適化（build.py から呼ばれる）
│   ├── paperback.py           # ペーパーバック用の本文 PDF（build.py --paperback から呼ばれる）
│   ├── validate.py            # EPUBCheck による検証（警告以上で失敗）
│   ├── kdp-listing.py         # KDP の内容紹介・キーワード・カテゴリーの下書き
│   ├── check-manuscript.mjs   # 原稿のチェック（npm run lint）
│   └── setup.sh               # ツールのインストール
├── templates/paperback.html   # ペーパーバック用 HTML のテンプレート（扉・目次・本文・奥付）
├── docs/
│   ├── tutorial.md            # はじめての人向けのチュートリアル（原稿から KDP へのアップロードまで）
│   └── kdp-listing.md         # KDP の内容紹介・キーワード・カテゴリーの下書きの作り方
├── lint/                      # 原稿のチェックの設定
│   ├── dict/technical.yml     #   技術書向けの表記ルール（辞書）
│   ├── dict/project.yml       #   プロジェクト独自の表記ルール（辞書）
│   ├── linkcheck.json         #   リンクチェックの設定
│   └── textlint-plugin-pandoc/#   Pandoc の記法を textlint に正しく読ませるプラグイン
├── .github/
│   ├── workflows/build.yml    # CI（ビルド + 縦書き・横書きの両方で検証）
│   ├── workflows/lint.yml     # CI（原稿のチェック）
│   └── actions/setup-tools/   # CI 用のツールのセットアップ
├── .textlintrc.json           # textlint のルール設定
├── package.json               # チェック用ツール・Vivliostyle（Node.js）
├── Makefile
└── requirements.txt
```

## セットアップ

### ツールの選定

| ツール | 用途 | 選んだ理由 |
|:--|:--|:--|
| [Pandoc](https://pandoc.org/) 3.1 以上（CI は 3.9 に固定） | Markdown → EPUB3 変換 | EPUB3 を直接出力でき、目次（nav / NCX）・脚注（`epub:type="noteref"`）・シンタックスハイライト・綴じ方向（`page-progression-direction`）に標準対応。Lua フィルタで日本語向けの拡張を足せる |
| Python 3.9 以上 + PyYAML | ビルドスクリプト・設定ファイルの読み込み | macOS / Linux / Windows のどれでも動く |
| [Pillow](https://python-pillow.org/)（推奨） | 画像の最適化・表紙の確認 | Python 製で追加のネイティブツール（ImageMagick など）が要らない。無い場合は最適化をスキップして元画像を使う |
| [EPUBCheck](https://www.w3.org/publishing/epubcheck/)（任意・Java 11 以上） | EPUB の規格チェック | W3C 公式の検証ツール。KDP でのエラーを事前に減らせる |
| [Kindle Previewer 3](https://kdp.amazon.co.jp/ja_JP/help/topic/G202131170)（任意） | Kindle での見え方の確認 | Amazon 公式。KDP と同じ変換エンジンで表示できる |
| [Vivliostyle CLI](https://vivliostyle.org/)（任意・Node.js 20 以上） | ペーパーバックの本文 PDF の組版 | CSS 組版（CSS Paged Media）で縦書き・右綴じ・ノンブル・柱・目次のページ参照に対応し、日本語の組版の実績がある。Pandoc の HTML 出力をそのまま使えるので、EPUB と同じ原稿・フィルタ・CSS を共有できる（LaTeX のように別の組版系を保守しなくてよい） |
| [Node.js](https://nodejs.org/) 20 以上 + [textlint](https://textlint.org/)（任意） | 原稿のチェック | 日本語の表記ゆれ・技術文書向けのルールが最も充実している校正ツール（[詳細](#チェックの内容とツール)） |

### macOS / Linux / WSL

```bash
bash scripts/setup.sh
```

`setup.sh` は次を行います。

- pandoc が無ければインストール（macOS は Homebrew、Debian/Ubuntu は公式 .deb）
- `pip install -r requirements.txt`（PyYAML・Pillow）
- EPUBCheck を `tools/` にダウンロードし、Java で起動できるか確認（Java 11 以上が無ければインストール方法を表示）

原稿のチェックを使う場合は、Node.js 20 以上を入れてから、リポジトリのルートで `npm install` を実行します。

### Windows

1. Pandoc をインストール: `winget install --id JohnMacFarlane.Pandoc`（または [公式インストーラ](https://pandoc.org/installing.html)）
2. Python をインストールして `py -m pip install -r requirements.txt`
3. （任意）EPUBCheck: 下の「[EPUBCheck による検証](#epubcheck-による検証)」を参照
4. （任意）原稿のチェック: `winget install OpenJS.NodeJS.LTS` で Node.js を入れ、`npm install`

`make` が無い場合は `py scripts\build.py --all` のように直接実行してください（WSL を使うと macOS / Linux と同じ手順でビルドできます）。

## ビルド方法

```bash
make                 # books/ 以下の全ての本をビルド → dist/*.epub
make check           # ビルド後に EPUBCheck で検証（警告が 1 件でもあれば失敗）
make check-modes     # 全ての本を縦書き・横書きの両方でビルドして検証（CI と同じ）
make validate        # ビルド済みの dist/*.epub を検証するだけ
make vertical        # 縦書きサンプルだけ
make horizontal      # 横書きサンプルだけ
make book BOOK=books/my-book
```

`make` を使わずに直接実行する場合:

```bash
python3 scripts/build.py books/my-book            # 1 冊
python3 scripts/build.py --all --check            # 全部 + 検証
python3 scripts/build.py books/my-book --writing-mode vertical   # 設定を一時的に上書き（出力は my-book-vertical.epub）
python3 scripts/build.py books/my-book -v         # 実行した pandoc のコマンドを表示
```

| オプション | 意味 |
|:--|:--|
| `--all` | `books/*/book.yaml` がある全ての本をビルド |
| `--check` | ビルド後に EPUBCheck で検証（[詳細](#epubcheck-による検証)） |
| `--fail-on LEVEL` | `--check` で失敗にする重大度。`fatal` / `error` / `warning`（既定）/ `info` / `usage` |
| `--report-dir DIR` | `--check` の結果を JSON レポートとして保存 |
| `--writing-mode vertical\|horizontal` | `layout.writing_mode` を一時的に上書き |
| `-o DIR` | 出力先（既定 `dist/`）。最適化した画像は `DIR/.image-cache/` に置かれる |
| `--no-optimize-images` | 画像を最適化せず、元画像をそのまま使う |
| `--pandoc PATH` | 使う pandoc（環境変数 `PANDOC` でも可） |

## EPUBCheck による検証

[EPUBCheck](https://www.w3.org/publishing/epubcheck/) は W3C 公式の EPUB 検証ツールです。KDP は EPUBCheck の結果をそのまま使うわけではありませんが、規格違反があると変換で内容が欠けたり、アップロード時にエラーになったりする原因になるため、**エラーと警告がともに 0 件**の状態を保ちます。

### 必要なツール

| ツール | 入れ方 |
|:--|:--|
| Java 11 以上 | macOS: `brew install openjdk@21` / Debian・Ubuntu: `sudo apt-get install -y openjdk-21-jre-headless` / Windows: `winget install EclipseAdoptium.Temurin.21.JRE` |
| EPUBCheck 5.3.0 | `bash scripts/setup.sh` で `tools/epubcheck-5.3.0/` に展開される（CI と同じバージョン）。macOS は `brew install epubcheck` でも可 |

手動で入れる場合は [リリースページ](https://github.com/w3c/epubcheck/releases) から `epubcheck-5.3.0.zip` を取得して展開し、`epubcheck.jar` の場所を次のどれかで指定します。

- `tools/` の下に展開する（`tools/epubcheck-5.3.0/epubcheck.jar`）
- 環境変数 `EPUBCHECK_JAR=/path/to/epubcheck.jar`（Windows: `set EPUBCHECK_JAR=C:\path\to\epubcheck.jar`）
- `--epubcheck-jar /path/to/epubcheck.jar` オプション

検索順は `--epubcheck-jar` → `EPUBCHECK_JAR` → `tools/epubcheck-*/epubcheck.jar`（新しい版を優先）→ `PATH` 上の `epubcheck` コマンドです。インストールできたかは `java -jar tools/epubcheck-5.3.0/epubcheck.jar --version` で確認できます。

### 実行方法

```bash
make check                                   # 全ての本をビルドして検証
make check-modes                             # 全ての本を縦書き・横書きの両方でビルドして検証（CI と同じ）
make validate                                # dist/*.epub を検証するだけ
make validate EPUB=dist/my-book.epub         # 特定の EPUB を検証
python3 scripts/validate.py dist/*.epub --report-dir dist/reports   # JSON レポートも保存
```

出力例:

```text
[epubcheck] 検証: dist/vertical-sample.epub
[epubcheck]   EPUBCheck 5.3.0・EPUB 3.3: 0 fatal / 0 error / 0 warning / 0 info / 0 usage
[epubcheck]   ✓ 問題ありません
```

問題があると、次のように場所（EPUB 内のファイル・行・列）とメッセージが表示され、終了コード 1 で終わります。

```text
  ERROR(RSC-007): my-book.epub/EPUB/nav.xhtml(14,120): Referenced resource "EPUB/text/missing.xhtml" could not be found in the EPUB.
```

### 失敗にする基準

EPUBCheck 本体は警告があっても終了コード 0 を返すため、`scripts/validate.py` が JSON レポート（`--json`）を読んで判定します。

| 重大度 | 意味 | 既定の扱い |
|:--|:--|:--|
| FATAL / ERROR | 規格違反。リーダーや KDP で正しく処理されない可能性が高い | **失敗** |
| WARNING | 規格上は許されるが問題になりやすい書き方 | **失敗** |
| INFO / USAGE | 参考情報・非推奨の書き方（EPUBCheck の `-u` で表示） | 表示のみ |

基準は `make check FAIL_ON=usage`（もっとも厳しい）や `--fail-on error`（警告を許す）で変えられます。このテンプレートのサンプルは USAGE まで含めて 0 件です。

## 新しい本を作る

```bash
cp -r books/horizontal-sample books/my-book     # 縦書きなら vertical-sample をコピー
python3 -c "import uuid; print(uuid.uuid4())"   # 新しい UUID を作る
```

1. `books/my-book/book.yaml` のタイトル・著者・**uuid（必ず新しい値に）**・表紙を書き換える
2. `chapters/` の原稿を書き換え、`book.yaml` の `chapters` に順番どおり並べる
3. `images/cover.jpg` を差し替える
4. `npm run lint -- books/my-book` で原稿をチェック（[原稿のチェック](#原稿のチェック)）
5. `make book BOOK=books/my-book`

サンプルが不要になったら `books/horizontal-sample` と `books/vertical-sample` は削除してかまいません（`--all` は `books/` にある本だけをビルドします）。

## 設定ファイル book.yaml

```yaml
title: Markdownで作るKindle技術書
title_kana: マークダウンデツクルキンドルギジュツショ   # 読み（並べ替え用・省略可）
subtitle: 原稿からKDP出版まで
author:
  - name: 山田 太郎
    kana: ヤマダ タロウ
publisher: サンプル出版
language: ja
date: 2026-11-01
description: 内容紹介
keywords: [Kindle, KDP]
rights: © 2026 山田 太郎

isbn: ""                                         # 無ければ空のまま（KDP の電子書籍は ISBN 不要）
uuid: 6f1c2a8e-3b4d-4e5f-9a10-2b3c4d5e6f70       # 本ごとに固定の値

cover: images/cover.jpg                          # 1600×2560px の JPEG 推奨

chapters:
  - chapters/00-preface.md
  - chapters/01-writing.md

layout:
  writing_mode: horizontal     # horizontal = 横書き・左綴じ / vertical = 縦書き・右綴じ
  toc_title: 目次
  toc_depth: 2
  number_chapters: true
  chapter_label: "第{n}章"
  appendix_label: "付録{n}"
  figure_label: "図{c}.{n}"     # {c}=章番号, {n}=章内の通し番号
  table_label: "表{c}.{n}"
  listing_label: "リスト{c}.{n}"
  vertical:
    code_blocks: sideways      # sideways / horizontal / vertical
    tables: sideways
    tcy_digits: 2
```

| キー | 必須 | 説明 |
|:--|:--:|:--|
| `title` / `subtitle` | ○ / – | 書名・副題。EPUB の `dc:title` になる |
| `title_kana` | – | 書名の読み（`file-as`）。並べ替え用 |
| `author` | ○ | 文字列、または `name` / `kana` / `role` のリスト（`role` の既定は `aut`＝著者） |
| `contributors` | – | イラスト（`ill`）、編集（`edt`）、翻訳（`trl`）など。[MARC relator コード](https://www.loc.gov/marc/relators/relaterm.html) |
| `publisher` / `date` / `description` / `keywords` / `rights` | – | 出版者・出版日・内容紹介・キーワード・著作権表示 |
| `isbn` | – | ISBN（10 桁 / 13 桁）。あれば識別子は ISBN になる |
| `uuid` | 推奨 | ISBN が無い場合の識別子。**本ごとに固定**。省略するとタイトルと著者から生成（警告が出る） |
| `cover` | 推奨 | 表紙画像。比率やサイズが KDP の推奨から外れると警告が出る |
| `cover_design` | – | 書いておくと表紙を自動生成して使う（`cover` より優先）。[表紙の自動生成](#表紙の自動生成)参照 |
| `chapters` | – | 原稿の順番。省略すると `chapters/*.md` をファイル名順 |
| `layout.writing_mode` | – | `horizontal`（既定）か `vertical` |
| `layout.toc_depth` | – | 目次に載せる見出しの深さ（既定 2 = 節まで） |
| `layout.number_chapters` | – | 章番号を付けるか（既定 `true`） |
| `layout.*_label` | – | 章・付録・図・表・リストの番号書式 |
| `layout.highlight_style` | – | ハイライト配色。pandoc の `.theme` ファイルか `tango` などの名前 |
| `layout.vertical.code_blocks` / `tables` | – | 縦書き時のコード・表の表示方式（[後述](#縦書きの表示の工夫)） |
| `layout.vertical.tcy_digits` | – | 何桁までの数字を縦中横にするか（既定 2） |
| `images.*` | – | 画像の最適化の設定（[後述](#画像の最適化)） |
| `css` | – | 追加の CSS ファイル（本のディレクトリからの相対パス） |
| `fonts` | – | 埋め込むフォント（通常は不要。[設計上の判断](#設計上の判断kdp-ガイドラインに基づいて決めたこと)参照） |
| `output` | – | 出力ファイル名（既定 `<ディレクトリ名>.epub`） |

## 表紙の自動生成

`scripts/cover.py` は、`book.yaml` のタイトル・サブタイトル・著者名から **KDP の推奨値どおりの表紙画像** を作ります。背景は単色・グラデーション・任意の画像から選べ、縦書き（右上から縦組み）と横書き（中央揃えの横組み）の 2 種類のデザインがあります。

### 使い方

`book.yaml` に `cover_design` を書くと、**ビルドのたびに表紙が作り直され、EPUB の表紙として自動で埋め込まれます**（`cover` を書いていても、こちらが優先されます）。

```yaml
cover_design: {}          # これだけでも既定のデザインで生成する
```

```bash
make book BOOK=books/my-book
# → dist/my-book.epub と dist/my-book-cover.jpg（KDP に別途アップロードする表紙）
```

表紙だけを作る・試すときは、スクリプトを直接実行します（`cover_design` が無い本でも使えます）。

```bash
python3 scripts/cover.py books/my-book                     # → dist/my-book-cover.jpg
python3 scripts/cover.py --all                             # books/ 以下の全ての本
python3 scripts/cover.py books/my-book --style vertical    # デザインを一時的に切り替え
python3 scripts/cover.py books/my-book --background photo.jpg -o cover.jpg
python3 scripts/cover.py books/my-book -o cover.tif        # TIFF で保存
```

### 設定（cover_design）

```yaml
cover_design:
  style: auto                     # auto（layout.writing_mode に合わせる）/ vertical / horizontal
  colors: ["#14213d", "#2c4f7c"]  # 1 色なら単色、2 色以上ならグラデーション
  gradient: diagonal              # vertical / horizontal / diagonal / radial
  background: images/cover-bg.jpg # 背景画像（任意）。指定すると colors の代わりに使う
  overlay: 0.35                   # 背景画像を暗くする割合（0〜1）。文字を読みやすくする
  text_color: auto                # auto = 背景の明るさから白か黒を選ぶ。"#ffffff" なども可
  accent_color: "#e2b450"         # 飾り罫の色
  font: sans                      # serif（明朝）/ sans（ゴシック）/ フォントファイルのパス
  title: "Markdownで作る\nKindle技術書"   # 表紙だけの書き方（\n で改行位置を指定）
  author_suffix: " 著"
```

| キー | 既定 | 説明 |
|:--|:--|:--|
| `style` | `auto` | `vertical`（縦書き）/ `horizontal`（横書き）。`auto` は `layout.writing_mode`（`--writing-mode` で上書きしたときはその値）に合わせる |
| `colors` | デザインごと | 背景色。縦書きは生成り色、横書きは紺のグラデーション |
| `gradient` | デザインごと | グラデーションの向き |
| `background` | – | 背景画像（本のディレクトリからの相対パス）。縦横比が違う場合は中央を基準に切り抜く。`background_position: top` などで切り抜く位置を変えられる |
| `overlay` / `overlay_color` | `0.35` / 黒 | 背景画像に重ねる色と濃さ |
| `shadow` | 背景画像のときだけ `true` | 文字に影を付ける |
| `text_color` / `accent_color` | `auto` / デザインごと | 文字と飾り罫の色 |
| `decoration` | `true` | 飾り罫（横書きはタイトル下の線、縦書きは枠と縦線）を描くか |
| `font` | 縦書き `serif`・横書き `sans` | 全体のフォント。`title_font` / `subtitle_font` / `author_font` で個別にも指定できる |
| `title` / `subtitle` / `author` | `book.yaml` の値 | 表紙だけ表記を変えたいとき。`subtitle: ""` でサブタイトルを出さない。複数の著者は「・」でつなぐ |
| `author_suffix` | – | 著者名の後ろに付ける文字（`" 著"` など） |
| `width` / `height` | `1600` / `2560` | 通常は変更不要 |

### 文字の配置（はみ出さないための処理）

- タイトル・サブタイトル・著者名はそれぞれ決まった枠に置き、**枠に収まる最大の文字サイズ**を自動で選ぶ。長い文字列は自動で改行し、それでも収まらなければ縮小する
- 改行は **禁則処理**（句読点・閉じ括弧・小書きの仮名・長音を行頭に置かない、開き括弧を行末に置かない）をしたうえで、行の長さがなるべく揃い、単語の途中（「自動｜化」「作｜る」など）で切れにくい位置を選ぶ。英単語は途中で切らない
- 改行位置を自分で決めたいときは、`cover_design.title` などに `\n` を入れる
- 文字が小さくなりすぎた（サムネイルで読みにくい）ときは警告が出る。枠にどうしても収まらないときはエラーになる
- 縦書きでは、フォントの縦書き用字形（OpenType の `vert`）で句読点・括弧・長音・小書きの仮名を正しい向き・位置にし、2 桁までの数字と 1 文字の英字は縦中横、それ以外の英単語は横倒しにする（Pillow が libraqm なしの場合は回転・位置ずらしで近似し、警告が出る）

### フォント

日本語フォントは自動で探します（明朝: Noto Serif CJK JP → 源ノ明朝 → BIZ UD明朝 → ヒラギノ明朝 → 游明朝 → IPAex明朝 …、ゴシック: Noto Sans CJK JP → 源ノ角ゴシック → BIZ UDゴシック → ヒラギノ角ゴシック → 游ゴシック → メイリオ → IPAexゴシック …）。タイトルは太字、そのほかは中くらいの太さを選びます。

| OS | 必要な作業 |
|:--|:--|
| macOS / Windows | 不要（ヒラギノ・游書体などの標準フォントを使う） |
| Ubuntu / Debian / WSL | `sudo apt install fonts-noto-cjk` |

市販のフォントなどを使うときは `font: fonts/MyFont-Bold.otf` のようにパスを書きます（`.ttc` の場合は `font: {path: ..., index: 1}` で番号を指定）。**表紙に使うフォントのライセンスが商用の画像に使えるものか確認してください**（Noto CJK・IPA フォントは使えます）。

### 出力形式（KDP の推奨値に合わせたこと）

| 項目 | 値 | 根拠（KDP ヘルプ「電子書籍の表紙の作成」） |
|:--|:--|:--|
| サイズ | 幅 1600 × 高さ 2560 px | 理想のサイズは高さ 2,560 × 幅 1,600 px（高さ:幅 = 1.6:1）。最小は高さ 1,000 × 幅 625 px、最大 10,000 px |
| 形式 | JPEG（品質 92、色差の間引きなしで文字をくっきりさせる）。`-o *.tif` で TIFF | 受け付ける形式は JPEG と TIFF |
| 色 | RGB（sRGB の ICC プロファイルを埋め込む） | RGB が必要（CMYK は不可） |
| 解像度 | 300 ppi | 推奨の解像度は 300 ppi 以上 |
| ファイルサイズ | 50MB を超えたらエラー（通常は 1MB 未満） | 50MB 以下 |

KDP ではタイトル・著者名が書誌情報と一致していることが求められるため、表紙の文字は `book.yaml` の値をそのまま使います（表記を変えるときは KDP の入力欄とも合わせてください）。EPUB には JPEG を埋め込みます（EPUB の表紙に TIFF は使えないため）。

> このテンプレートを作成した環境からは kdp.amazon.com に接続できなかったため、上の値は KDP ヘルプの検索結果と既知の内容に基づいています。アップロード前に [電子書籍の表紙の作成（KDP ヘルプ）](https://kdp.amazon.co.jp/ja_JP/help/topic/G6GTK3T3NUHKLEFX) で最新の値を確認してください。

## ペーパーバック（紙の本）

同じ原稿から、**KDP ペーパーバックの本文 PDF** も作れます。縦書き（右綴じ）・横書き（左綴じ）のどちらにも対応し、判型・余白・ノンブル・裁ち落としは KDP の本文の要件に合わせて自動で決まります。

```text
原稿（Markdown）──pandoc（EPUB と同じ Lua フィルタ）──▶ HTML ──Vivliostyle（CSS 組版）──▶ 本文 PDF
```

### 準備

組版には [Vivliostyle CLI](https://vivliostyle.org/)（Node.js 製。縦書きの組版・ページ番号・目次のページ参照に対応）を使います。Node.js 20 以上を入れてから、リポジトリの直下で次を実行します（`bash scripts/setup.sh` でも入ります）。

```bash
npm install
```

- Vivliostyle は Chrome（Chromium）で組版します。初回の実行時に自動でダウンロードされます。インストール済みの Chrome を使う場合は `--browser /path/to/chrome`、または環境変数 `VIVLIOSTYLE_BROWSER` で指定します
- 明朝体・ゴシック体の日本語フォントが必要です。Linux では `sudo apt install fonts-noto-cjk`。macOS・Windows は OS 標準のフォント（ヒラギノ・游明朝など）が使われます

### 使い方

```bash
make paperback                                   # books/ 以下の全ての本 → dist/<名前>-paperback.pdf
make paperback-book BOOK=books/my-book           # 1 冊だけ
make paperback-modes                             # 縦書き版・横書き版の両方 → dist/modes/<名前>-{vertical,horizontal}-paperback.pdf
```

```bash
python3 scripts/build.py books/my-book --paperback
```

```bash
python3 scripts/build.py books/my-book --paperback --writing-mode vertical
```

縦書き・横書きは EPUB と同じく `layout.writing_mode` で決まり、`--writing-mode` で一時的に上書きできます。組版に使った HTML を見たいときは `--keep-html` を付けると `dist/.paperback/` に残ります。

ビルドすると、PDF の確認結果と、表紙を作るときの寸法が表示されます。

```text
[paperback] Vivliostyle で組版します（判型 A5（148.0mm×210.0mm）、ノド 18.0mm）
[paperback] PDF を確認しました: 17 ページ、ページサイズ 5.827×8.268 インチ（148.0mm×210.0mm）、ノド 18.0mm、埋め込みフォント: …
[paperback] 表紙 PDF の寸法（クリーム・モノクロ、18 ページ）: 幅 11.949 × 高さ 8.518 インチ（303.5mm×216.4mm）、背幅 0.045 インチ（1.1mm）
```

### 設定（book.yaml の paperback）

```yaml
paperback:
  trim: a5            # 判型（下の表）。{width: 128mm, height: 182mm} のように直接書くこともできる
  bleed: false        # 裁ち落とし。画像や色を紙の端まで印刷するときだけ true
  paper: cream        # white / cream / color（表紙の背幅の計算に使う）
  font: serif         # 本文の書体: serif（明朝）/ sans（ゴシック）/ フォント名
  font_size: 9pt      # 本文の文字の大きさ（既定: 縦書き 9pt、横書き 9.5pt）
  line_height: 1.75   # 行送り（既定: 縦書き 1.75、横書き 1.7）
  margins:            # 余白（mm / in / pt。数字だけなら mm）
    top: 20mm         #   天
    bottom: 20mm      #   地
    outside: 16mm     #   小口（外側）
    inside: 18mm      #   ノド（内側）。ページ数に応じた KDP の最小値より狭くはならない
  page_numbers: true  # ノンブル
  running_heads: true # 柱（章タイトル）
  colophon: true      # 巻末の奥付
  isbn: ""            # ペーパーバックの ISBN（奥付に入る）
  colophon_notes: []  # 奥付に足す行
  author_suffix: "　著" # 扉の著者名の後ろに付ける文字
  css: []             # 紙の本だけに使う追加の CSS
  output: my-book-paperback.pdf
```

`paperback` を書かなくても、上の既定値（A5・裁ち落としなし）で PDF を作れます。

| `trim` | 寸法 | 備考 |
|:--|:--|:--|
| `5x8` / `5.06x7.81` / `5.25x8` / `5.5x8.5` / `6x9` / `6.14x9.21` / `6.69x9.61` / `7x10` / `7.44x9.69` / `7.5x9.25` / `8x10` / `8.25x6` / `8.25x8.25` / `8.5x8.5` / `8.5x11` / `a4` | インチ（幅×高さ）。`a4` は 8.27×11.69 | KDP の標準の判型 |
| `a5` | 148×210mm | KDP では「カスタムの判型」に幅・高さ（インチ）を入力する（ビルド時に値を表示） |
| `b6` | 128×182mm | 同上 |
| `{width: …, height: …}` | 任意 | 幅 4〜8.5 インチ・高さ 6〜11.69 インチ（KDP のカスタム判型の範囲）。新書判・文庫判は幅が 4 インチ未満なので作れない |

### KDP の要件に合わせていること

| 項目 | 内容 |
|:--|:--|
| ページサイズ | 裁ち落としなし: 判型と同じ。裁ち落としあり: **幅 + 0.125 インチ、高さ + 0.25 インチ**（天・地・小口に 3.2mm ずつ。ノド側には付けない） |
| ノド（内側の余白） | ページ数で決まる最小値以上: 24〜150 ページ 0.375 インチ（9.5mm）、151〜300 ページ 0.5 インチ（12.7mm）、301〜500 ページ 0.625 インチ（15.9mm）、501〜700 ページ 0.75 インチ（19.1mm）、701〜828 ページ 0.875 インチ（22.2mm）。ページ数は組んでみないと分からないので、**組版 → ページ数を数える → 足りなければノドを広げて組み直す** を自動で行う |
| 外側の余白（天・地・小口） | 0.25 インチ（6.4mm）以上、裁ち落としありは 0.375 インチ（9.5mm）以上。下回る設定はエラー |
| 左右のページ | 右側のページはノドが左、左側のページはノドが右。**縦書き（右綴じ）では 1 ページ目が左側のページ**になり、余白・ノンブルの位置も入れ替わる |
| ノンブル | 地の小口側にアラビア数字（縦書きの本も横組み）。扉・白ページ・奥付には入れない |
| 柱 | 天の小口側に章タイトル。章の最初のページと目次には入れない |
| 章の始まり | 奇数ページ（横書きは右側、縦書きは左側のページ）から始め、必要なら白ページを入れる |
| トンボ | 付けない（KDP はトンボ付きの PDF を受け付けない） |
| フォント | すべて PDF に埋め込む（埋め込まれていなければエラー） |
| 画像 | Kindle 向けに縮小した版ではなく**元画像**を使う。版面の幅いっぱいに置いたとき 300dpi 未満になる画像は警告 |
| ページ数 | 24 ページ未満・828 ページ超は警告。奇数ページなら「KDP が最後に白ページを足す」と警告 |

ほかに、ページの構成は **扉 → 目次（ページ番号付き） → 本文 → 奥付** です。脚注は章末にまとめて出ます。

### 表紙

KDP のペーパーバックでは、本文の PDF とは別に、**表 1（表紙）・背・表 4（裏表紙）を 1 枚にした表紙 PDF** をアップロードします（または KDP の表紙作成ツールを使う）。電子書籍用の表紙画像（`cover` / `cover_design`）は本文 PDF には入りません。ビルド時に表示される寸法（背幅は KDP の用紙の厚さ: 白 0.002252 インチ／ページ、クリーム 0.0025、カラー 0.002347 から計算）で作ってください。80 ページ未満の本は背表紙に文字を入れられません。

### KDP へのアップロード

1. KDP の本棚で「ペーパーバック」を作成（電子書籍と同じタイトルにすると商品ページがまとまる）
2. 「印刷オプション」で、インクと用紙（`paper` と同じもの）、判型（`trim`。`a5`・`b6` は「カスタムの判型」）、裁ち落とし（`bleed`）を選ぶ
3. 縦書きの本は「読む方向」を **右から左** にする
4. 「原稿」に `dist/<名前>-paperback.pdf`、「表紙」に表紙 PDF をアップロード
5. **印刷プレビューアーで余白・ノド・裁ち落としの警告がないことを確認**してから、校正刷り（著者用コピー）を注文して実物を確認する

> この機能を作成した環境からは kdp.amazon.com に接続できなかったため、上の数値は KDP ヘルプ「ペーパーバックの本文の書式設定」「判型、裁ち落とし、余白」の既知の内容をもとにしています。出版前に KDP の印刷プレビューアーで確認してください。

## 原稿の書き方

原稿は Pandoc の Markdown です。サンプル `books/horizontal-sample/chapters/01-writing.md` に全要素の実例があり、ビルドした EPUB で見え方を確認できます。

### ファイルの分け方

- **1 ファイル = 1 章**。ファイルの先頭に `# 章タイトル` を 1 つだけ書く
- ファイル名は `01-intro.md` のように番号を付けると順番がわかりやすい
- 章ごとに EPUB 内の XHTML ファイルが分かれ、各章は新しいページから始まる

### 見出し・章番号

```markdown
# はじめに {.unnumbered}          ← 番号なしの章（まえがき・あとがき）
# 原稿の書き方 {#sec:writing}     ← 「第1章 原稿の書き方」になる
## 節
### 項
# 記法早見表 {.appendix}          ← 「付録A 記法早見表」になる
```

### 段落・強調

- 段落は空行で区切る。**日本語の文中で改行しても空白は入らない**（行頭が英数字でも大丈夫）
- `**太字**`、`*斜体*`、`` `インラインコード` ``、`[リンク](https://example.com)`

### 目次

自動生成されます。`layout.toc_depth` までの見出しが載ります。EPUB には次の 2 種類が入ります。

- 論理目次（EPUB3 の nav と、互換用の NCX）… Kindle のメニュー「目次」に表示
- HTML 目次ページ … 本文の前に「目次」ページとして表示

### コードブロック（シンタックスハイライト）

````markdown
```python
print("こんにちは")
```

```{.javascript #lst:fetch caption="APIからデータを取得する"}
const res = await fetch(url);
```
````

- 言語名を付けるとハイライトされる（[対応言語](https://github.com/jgm/skylighting/tree/master/skylighting-core/xml)は `pandoc --list-highlight-languages`）
- `caption` を付けると「リスト1.1」のような番号付きキャプションになる
- Kindle は横スクロールできないため、長い行は折り返して表示される。**1 行 60 文字程度まで**が目安

### 表

```markdown
| 記法 | 用途       |
|:-----|:-----------|
| `#`  | 章タイトル |

: 主なMarkdown記法 {#tbl:syntax}
```

- 表の直後の `: キャプション {#tbl:ID}` で「表1.1」のような番号が付く
- 小さな画面でも収まるよう、**列は 3〜4 列程度**に。大きな表は分割するか画像にする
- 表の中で `|` を書くときは `\|`（ルビの短縮記法は表の中では使えないので `[漢字]{ruby="かんじ"}` を使う）

### 画像と図番号

```markdown
![原稿からEPUBができるまで](images/build-flow.png){#fig:flow}
```

- キャプションがある画像には「図1.1」のような番号が付く
- 画像は `images/` に置く。JPEG（写真）か PNG（図）を使い、幅 1,200px 以上を目安にする（大きすぎる画像や透過 PNG はビルド時に[自動で調整](#画像の最適化)される）
- 段落の途中に置いた画像は図にならない（キャプション・番号なし）

### 相互参照

`@fig:flow`、`@tbl:syntax`、`@lst:fetch`、`@sec:writing` と書くと「図1.1」「表1.1」「リスト1.1」「第1章」へのリンクになります。`[@fig:flow]` のように角括弧で囲んでもかまいません。参照先が無いとビルド時に警告が出ます。

### 囲み（注意書き・コラム）

```markdown
::: warning
読者が失敗しやすい点を書きます。
:::

::: {.column title="コラム：独自の見出し"}
本文
:::
```

| クラス | 既定の見出し |
|:--|:--|
| `note` | メモ |
| `tip` | ヒント |
| `important` | 重要 |
| `warning` | 注意 |
| `caution` | 警告 |
| `column` | コラム |

`title="..."` で見出しを変更、`title=""` で見出しなしになります。

### 脚注

```markdown
本文です[^1]。

[^1]: 脚注の内容。
```

各章の末尾にまとめて出力され、Kindle では番号をタップするとポップアップで表示されます。

### ルビ

```markdown
{薔薇|ばら}            グループルビ
{東京|とう|きょう}     モノルビ（親文字の数と読みの数が同じとき 1 文字ずつ）
[憂鬱]{ruby="ゆううつ"}  span 記法
```

### その他

| 書き方 | 効果 |
|:--|:--|
| `[12]{.tcy}` | 縦中横（縦書きのみ。自動判定されない箇所に） |
| `[AI]{.upright}` | 英字を 1 文字ずつ正立（縦書きのみ） |
| `[ABC]{.sideways}` | 横倒し（縦書きのみ） |
| `::: pagebreak` → `:::` | 改ページ |
| `::: center` / `::: right` → `:::` | 中央揃え / 右（縦書きでは下）揃え |

## 画像の最適化

ビルドのたびに、本のディレクトリ内の画像（表紙を含む）を Kindle 向けに最適化してから EPUB に入れます。**原稿の書き方を変える必要はありません**。`![説明](images/photo.png)` と書けば、EPUB には `photo.png` の最適化版が入ります。

- **元画像は変更しません。** 最適化版は `dist/.image-cache/<本のディレクトリ名>/` に、元と同じフォルダ構成で作られます
- **変更のない画像は再処理しません。** 元画像の内容（SHA-256）と設定が前回と同じなら、キャッシュをそのまま使います。画像を差し替えたり設定を変えたりした分だけ処理し直し、消した画像の最適化版は削除します
- キャッシュを作り直したいときは `make clean`（`dist/` ごと削除）

### 行う処理

| 対象 | 処理 | 理由 |
|:--|:--|:--|
| 幅 1600px・高さ 2560px を超える画像 | 縦横比を保って縮小（拡大はしない） | Kindle の画面に対して 300ppi 相当あれば十分。大きすぎる画像はファイルが重くなり、70% ロイヤリティの配信料（MB 単位）も増える |
| 透過 PNG・透過 GIF | 白背景（`images.background`）に合成して透過を消す | Kindle Publishing Guidelines は透過を含む画像に非対応としている。ダークモードで透過部分が黒くなり、黒い線画が見えなくなる |
| TIFF・BMP・WebP | 図（256 色以下）は PNG、写真は JPEG に変換 | Kindle は TIFF に非対応。KDP の本文画像は JPEG・PNG・GIF が基本 |
| GIF | PNG に変換。アニメーション GIF は 1 フレーム目だけ | Kindle はアニメーション GIF に非対応 |
| CMYK・16 ビット | 8 ビットの RGB（グレースケール画像はグレースケールのまま） | 端末は RGB で表示する。CMYK は色が大きく変わることがある |
| EXIF の回転情報 | 回転を反映してからメタデータを削除 | 端末によっては回転情報が無視され、横倒しで表示されるため |
| 5MB を超える画像 | JPEG は画質を段階的に下げる。PNG は JPEG に切り替える | 1 枚が大きすぎると変換・配信で問題になる（目安として 5MB を上限にしている） |
| PNG（変更不要なもの） | 可逆圧縮で再圧縮し、小さくなったときだけ採用 | 画質を変えずにファイルを小さくする |
| JPEG（変更不要なもの） | そのまま使う | 再圧縮すると画質が落ちるため |
| 表紙（`cover`） | 1600×2560px 以内の JPEG にする | KDP の表紙の推奨（1600×2560px・RGB・JPEG） |
| SVG | そのまま使う | 変換しない |

幅が 600px（`images.min_width`）未満の画像は、Kindle で粗く見える可能性があるため警告が出ます（拡大はしません）。

### ビルド時の一覧

最適化の前後のサイズが一覧で表示されます（表示例）。

```text
[build] 画像の最適化（5 枚）:
[build]   画像               最適化前           最適化後          削減  処理
[build]   images/alpha.png  3000×1200    21KB   1600×640    37KB  -73%  透過→背景合成、縮小 3000×1200→1600×640
[build]   images/cover.jpg  1600×2560   186KB  1600×2560   186KB    0%  キャッシュ: 変更なし
[build]   images/photo.jpg  5000×3500  21.5MB  1600×1120   707KB   97%  縮小 5000×3500→1600×1120
[build]   images/scan.tiff  1800×1200   6.2MB  1600×1067   3.7MB   40%  TIFF→PNG、縮小 1800×1200→1600×1067
[build]   images/steps.png   1600×520    36KB   1600×520    36KB    0%  キャッシュ: 変更なし
[build]   ----------------  ---------  ------  ---------  ------  ----  ------------------------------
[build]   合計                         27.9MB              4.6MB   84%  3 枚を処理、2 枚はキャッシュ
```

「キャッシュ:」が付いた行は、前回の結果を再利用したものです。透過を消した画像は、白背景の分だけ最適化後のほうが大きくなることがあります（削減がマイナス）。

### 設定（book.yaml）

既定値のままで使えます。変えたいものだけ書いてください。

```yaml
images:
  optimize: true          # false で最適化しない（コマンドの --no-optimize-images でも可）
  max_width: 1600         # 本文の画像の最大幅（px）
  max_height: 2560        # 本文の画像の最大高さ（px）
  jpeg_quality: 85        # JPEG に書き出すときの画質（1〜95）
  max_file_size_kb: 5120  # 1 枚あたりの上限（KB）
  background: "#ffffff"   # 透過部分を合成する背景色
  min_width: 600          # これより幅が小さい画像は警告する
```

画像の処理には Pillow を使います（`pip install -r requirements.txt` で入ります）。Pillow が無い場合は警告を出して最適化を省略し、元画像をそのまま使います。

> **注記:** このテンプレートを作成した環境からは kdp.amazon.com に接続できなかったため、上の数値は、ほかのサイトに引用されていた Kindle Publishing Guidelines の記述（画像は表示サイズに対して 300ppi 相当、72ppi 未満は変換に失敗する、透過画像・TIFF・アニメーション GIF は非対応）と KDP ヘルプの表紙の推奨値をもとに決めています。1 枚あたり 5MB の上限は公式の数値として確認できなかったため、安全側の目安です。出版前に最新の [Kindle Publishing Guidelines](https://kdp.amazon.co.jp/ja_JP/help/topic/G200645680) を確認してください。

## 原稿のチェック

表記ゆれ・文章の誤りと、リンク切れ・参照ミスを **1 つのコマンドで** チェックします。

```bash
npm install          # 初回だけ（Node.js 20 以上）
npm run lint         # books/ 以下の全ての本をチェック（make lint でも可）
```

| コマンド | 内容 |
|:--|:--|
| `npm run lint` | すべてのチェック |
| `npm run lint -- books/my-book` | 1 冊だけ |
| `npm run lint:fix` | 自動で直せる指摘（表記の統一など）を原稿に反映してからチェック（`make lint-fix` でも可） |
| `npm run lint:text` | 表記・文章だけ |
| `npm run lint:links` | リンク・参照だけ |
| `npm run lint -- --no-external` | 外部 URL の確認を省く（オフラインのとき） |

リンクチェックでは、ビルドと同じ Pandoc で原稿を解析します（`pandoc` が必要。場所は環境変数 `PANDOC` でも指定可）。

### 結果の見方

本ごと・チェックの種類ごとに、ファイル・行・列とともに表示し、最後にまとめを出します。

```text
📖 my-book（横書き・原稿 1 ファイル）
  表記・文章     ✖ エラー 3 件
    books/my-book/chapters/01-intro.md
         3:14  ✖ サーバー => サーバ (自動修正可) [prh]
         3:14  ✖ 同義語である「サーバ」と「サーバー」が利用されています [@textlint-ja/no-synonyms]
         3:24  ✖ 行ない => 行い (自動修正可) [prh]
  リンク・参照   ✖ エラー 2 件  外部 URL 0 件
    books/my-book/chapters/01-intro.md
          5:6  ✖ 参照先が見つかりません: @sec:deploy（{#sec:deploy} を付けた見出し・図・表・リストがありません）
          7:8  ✖ 画像が見つかりません: images/architecture.png（books/my-book/ と books/my-book/images/ から探しました）

────────────────────────────────────────────────────────
まとめ
  my-book                表記・文章 ✖ エラー 3 件   リンク・参照 ✖ エラー 2 件

✖ エラー 5 件、警告 0 件
```

- **✖ エラー** … 直すべきもの。1 件でもあるとコマンドが失敗する（終了コード 1）
- **⚠ 警告** … 文体の提案（一文に同じ助詞が続く、文が長いなど）や、外部サイトの一時的な不調など、判断を書き手にゆだねるもの。コマンドは成功する
- `[ ]` の中はルール名。誤検出を抑えるときに使う（[後述](#誤検出を抑える)）

サンプル原稿はエラー 0 件で通ります（文体の警告が数件出ます）。

### チェックの内容とツール

| 種類 | チェックすること | 使っているもの |
|:--|:--|:--|
| 表記ゆれ | 同じ本の中で同じ意味の語の書き方が混ざっていないか（サーバ／サーバー、行う／行なう など） | [@textlint-ja/textlint-rule-no-synonyms](https://github.com/textlint-ja/textlint-rule-no-synonyms)（Sudachi 同義語辞書） |
| 表記ルール | 辞書で決めた表記になっているか（行なう → 行う、Javascript → JavaScript など）。全角の英字（ＥＰＵＢ）も検出 | [textlint-rule-prh](https://github.com/textlint-rule/textlint-rule-prh) + `lint/dict/*.yml`、textlint-rule-no-mixed-zenkaku-and-hankaku-alphabet |
| ひらがなで書く語 | 形式名詞（事 → こと）・副詞（殆ど → ほとんど）・補助動詞（〜して下さい → ください） | textlint-rule-ja-hiragana-keishikimeishi / -fukushi / -hojodoushi |
| 文章 | 文の長さ、読点の数、「ですます」と「である」の混在、二重否定、ら抜き言葉、句点の有無、括弧の対応 など | [textlint-rule-preset-ja-technical-writing](https://github.com/textlint-ja/textlint-rule-preset-ja-technical-writing) |
| 空白 | 全角文字どうしの間の空白、感嘆符・疑問符の後の空白 など | [textlint-rule-preset-ja-spacing](https://github.com/textlint-ja/textlint-rule-preset-ja-spacing)（一部） |
| 相互参照 | `@sec:` / `@fig:` / `@tbl:` / `@lst:` の参照先があるか、ID が章をまたいで重複していないか | `scripts/check-manuscript.mjs`（Pandoc で解析） |
| 内部リンク | `[…](#id)` のリンク先の ID があるか。`[…](02-build.md)` のような章ファイルへのリンク（EPUB では切れる）がないか | 〃 |
| 画像 | 参照している画像ファイルがあるか（`book.yaml` の表紙も）、Kindle で使える形式か | 〃 |
| 外部 URL | ページがなくなっていないか（HTTP 404 / 410、ドメインなし、証明書エラーはエラー。403・タイムアウトなどは警告） | 〃（`lint/linkcheck.json` で除外・タイムアウトを設定） |

**textlint を選んだ理由**: 日本語向けのルール（textlint-ja）が最も充実しており、技術書向けのプリセットや表記ゆれ検出、辞書による表記統一（prh）をそのまま組み合わせられるためです。RedPen なども候補ですが、Java が必要で、日本語のルールや辞書の選択肢が少なくなります。

**Pandoc の記法への対応**: textlint は CommonMark として原稿を読むため、そのままでは `::: note` の囲みや `{#sec:id}` の属性、`{漢字|かんじ}` のルビ、`: キャプション` の表キャプションを文章と見なして誤検出します。`lint/textlint-plugin-pandoc` がこれらを検査の対象から外します（原稿のテキストは変えないので、位置がずれず `--fix` でも壊れません）。リンクの解析には、ビルドと同じ Pandoc を使っています。

> **注意**: `npx textlint` で直接実行すると、このプラグインより標準の Markdown 処理が優先され、Pandoc の記法が誤検出されます。チェックは `npm run lint` で実行してください。

### 表記ルールの辞書

表記ルールは [prh](https://github.com/prh/prh) 形式の YAML 辞書に書きます。

| ファイル | 内容 |
|:--|:--|
| `lint/dict/technical.yml` | 技術書に共通する一般的なルール（送り仮名、接続詞のひらがな、記号、製品名の大文字小文字など） |
| `lint/dict/project.yml` | **プロジェクト独自のルール**。用語の統一やカタカナ語の長音など、この本（シリーズ）で決めた表記を書く |

```yaml
# lint/dict/project.yml に追加する例
rules:
  - expected: ログイン             # 正しい表記
    pattern:                       # 誤りとして検出する表記（複数書ける）
      - ログオン
      - サインオン
  - expected: GitHub Actions
    pattern: /GitHub actions|Github Actions/   # /…/ で正規表現
  - expected: 行$1                  # 正規表現の () は $1 で使える
    pattern: /行な([わいうえお])/
    specs:                         # 自己テスト（辞書を読み込むときに確かめられる）
      - from: 行なう
        to: 行う
```

- `pattern` を省略すると、`expected` の大文字小文字・全角半角の違いを検出します
- 指摘は `npm run lint:fix` で `expected` の表記に直せます
- カタカナ語の語末の長音は、サンプル原稿に合わせて省略する側（フォルダ・エディタ・フィルタ・サーバ）にしています。「フォルダー」のように長音を付けたい場合は、`project.yml` の該当ルールの `expected` と `pattern` を入れ替えてください

### 本ごとの設定

`books/<本>/textlint.json` を置くと、その本だけルートの `.textlintrc.json` に設定を重ねられます。辞書（`prh` の `rulePaths`）は置き換えではなく **追加** されます（パスは本のディレクトリから）。

```json
{
  "rules": {
    "preset-ja-technical-writing": {
      "arabic-kanji-numbers": false,
      "sentence-length": { "max": 120 }
    },
    "prh": { "rulePaths": ["dict.yml"] }
  }
}
```

縦書きサンプル（`books/vertical-sample/textlint.json`）では、縦書きの本で一般的な漢数字（「三つの段階」など）を許可するため、算用数字を求めるルールを切っています。

### 誤検出を抑える

| 方法 | 書き方 |
|:--|:--|
| 原稿の一部だけチェックを止める | `<!-- textlint-disable ルール名 -->` 〜 `<!-- textlint-enable ルール名 -->`（ルール名を省くと全ルール）。HTML のコメントなので EPUB では表示されない |
| 特定の語句を常に許可する | `.textlintrc.json` の `filters.allowlist.allow` に文字列か `/正規表現/` を追加 |
| 同義語の組み合わせを許可する | `.textlintrc.json` で `"@textlint-ja/no-synonyms": { "allows": ["ログイン", "サインイン"] }` |
| ルールを切る・警告にする | `.textlintrc.json` で `false`、または `{ "severity": "warning" }` |
| 外部 URL を確認しない | `lint/linkcheck.json` の `external.ignore` に正規表現を追加 |

エラーと警告の分け方も `.textlintrc.json` の `severity` で決めています。文体の提案に近いルール（弱い表現、助詞の連続、文の長さ、読点の数、冗長な表現）は警告にしています。

## 縦書きの表示の工夫

`layout.writing_mode: vertical` にすると、次の処理が行われます。

| 対象 | 処理 |
|:--|:--|
| 綴じ方向 | OPF の `<spine page-progression-direction="rtl">`（右綴じ）と `primary-writing-mode` を設定 |
| 本文 | `writing-mode: vertical-rl`（`-webkit-` / `-epub-` 付きも併記）、禁則処理 `line-break: strict` |
| 英単語 | `text-orientation: mixed` で横倒し（縦書きの標準的な組み方） |
| 2 桁までの数字・`!!` `!?` | 自動で **縦中横**（`text-combine-upright`）。3 桁以上・小数・英単語に隣接する数字は横倒しのまま |
| インラインコード | 横倒し（`text-orientation: sideways`）で、英数字がそのまま読める向きに |
| 余白・罫線 | 横書き前提の上下左右を縦書き用に付け替え（引用の罫線は上、リストの字下げは上など） |
| 画像 | ページの幅・高さの両方に収まるよう縮小（画像自体は回転しない） |

### コードブロックと表の表示方式

縦書きの本の中でコードや表をどう見せるかは、`layout.vertical.code_blocks` / `tables` で選べます。

| 値 | 表示 | 向いている用途 |
|:--|:--|:--|
| `sideways`（既定） | 横組みの内容を **90° 回転** した表示。端末を右に傾けると横書きのコード・表として読める | コードの多い本。長いコードもページの高さで折り返して次ページへ流れるので**途切れない** |
| `horizontal` | 縦書きページの中に **横組みのブロック** を置く | 短いコード（15 行程度まで）・小さい表だけの本。ブロックが 1 ページに収まらないと切れるため、**必ず Kindle Previewer で確認** |
| `vertical` | 縦組みのまま（和文は正立、英数字は横倒し、短い数字は縦中横） | 和文中心の表 |

既定を `sideways` にしたのは、どのリーダーでも表示が崩れず、内容が欠けない方式だからです。縦組みの中に横組みのブロックを入れる表示（`horizontal`）は、電書協 EPUB 3 制作ガイドでも推奨されておらず、リーダーによって表示が異なるため、選択式にしています。

## Kindle Previewer での確認方法

KDP にアップロードする前に、[Kindle Previewer 3](https://kdp.amazon.co.jp/ja_JP/help/topic/G202131170)（Windows / macOS、無料）で必ず確認してください。KDP と同じ変換処理で表示されます。

1. Kindle Previewer 3 をダウンロードしてインストールする
2. 起動して「ファイル」→「本を開く」で `dist/*.epub` を開く（ドラッグ＆ドロップでも可）。変換に数十秒かかる
3. 左側の「デバイスタイプ」で **タブレット / 電話 / Kindle E-reader** を切り替え、それぞれで確認する
4. 「向き」で縦向き・横向きを、フォントサイズを大小に変えて崩れないか確認する
5. 「Enhanced Typesetting（強化された組版）」が「サポートされています」になっているか確認する（左下の書籍情報）

確認するポイント:

- [ ] 目次（メニューの「目次」と本文前の目次ページ）から各章へ移動できる
- [ ] **縦書きの本はページが右から左へ進む**（右綴じ）。横書きは左から右へ
- [ ] 縦書きで、2 桁の数字が縦中横に、英単語が横倒しになっている
- [ ] コードブロックが途中で切れていない（特に `horizontal` を選んだ場合）。長い行が折り返されている
- [ ] 表が画面からはみ出していない
- [ ] 画像が鮮明で、図番号・キャプションが付いている
- [ ] 脚注の番号をタップするとポップアップが出る
- [ ] ルビが正しい位置に出ている
- [ ] E-reader（白黒）表示でハイライトや囲みが判別できる。ダークモード（背景黒）でも文字が読める

問題が無ければ、KDP には **EPUB をそのままアップロード** します。

### EPUBCheck を通っても Kindle Previewer で確認が必要な点

EPUBCheck が調べるのは **EPUB の規格に合っているか** だけで、Kindle 形式（KF8 / KFX）に変換したときの見え方は調べません。次の点は EPUBCheck が 0 件でも Kindle Previewer で確認してください。

| 確認すること | 理由・対処 |
|:--|:--|
| **変換時の警告**（Kindle Previewer で本を開いたときのメッセージ、メニューの変換ログ） | Kindle 独自の変換で出る警告は EPUBCheck とは別物。警告が出たら内容を確認する |
| **Enhanced Typesetting が有効になっているか** | 縦書き・ルビ・縦中横などの日本語組版は Enhanced Typesetting で処理される。無効になっていたら、変換ログの原因（未対応の CSS など）を直す |
| **綴じ方向とページ送り**（縦書きは右綴じ） | `page-progression-direction` と Kindle 独自の `primary-writing-mode` メタデータで指定している。後者は EPUB の規格外のため EPUBCheck は確認しない |
| **縦書き用 CSS が効いているか**（縦中横・英字の向き・`sideways` のコード） | Kindle は `-webkit-` / `-epub-` 接頭辞付きのプロパティで縦書きを処理する。EPUBCheck は CSS の文法は確認するが、Kindle が対応しているかは確認しない。CSS を書き換えたら接頭辞付きのものも残す |
| **ルビ** | ルビの括弧（`<rp>`）は EPUB 3.3 で非推奨のため出力していない。Kindle はルビに対応しているが、ルビ非対応のリーダーでは「薔薇ばら」のように親文字と続けて表示される。ルビの位置と、ルビが本文に混ざっていないかを確認する |
| **画像の大きさ**（特に縦書き） | 縦書きの画像は `vw` / `vh` でページ内に収めている。端末によって単位の扱いが異なるため、タブレット・電話・E-reader のすべてで見切れていないか確認する |
| **表のはみ出し** | Kindle は大きな表をタップで拡大表示する場合がある。小さな画面（電話）で読めるか確認する |
| **「最初から読む」の位置** | nav の landmarks の `bodymatter` で指定（最初の章＝まえがき）。メニューの「最初に移動」で本文の先頭に飛ぶか確認する |
| **表紙** | 販売ページと端末の本棚の表紙は、KDP で**別にアップロードした画像**が使われる。EPUB 内の表紙と同じ画像にする |
| **フォントを埋め込んだ場合**（`fonts`） | 埋め込みフォントの使用許諾（電子書籍への埋め込み可か）は EPUBCheck では分からない。Kindle では読者がフォントを変えると埋め込みフォントは使われない |
| **ダークモード・セピア** | 文字色・背景色を指定していないので通常は問題ないが、画像（透過 PNG の黒い線など）が背景に溶けないか確認する |

> **補足**: EPUB 内の `META-INF/com.apple.ibooks.display-options.xml`（pandoc が出力する Apple Books 用の設定）や `toc.ncx`（EPUB2 互換の目次）は Kindle では無視されるか互換用に使われるだけで、害はありません。

## KDP へのアップロード手順

事前に [KDP](https://kdp.amazon.co.jp/) のアカウントを作り、著者情報・支払い（銀行口座）・税務情報を登録しておきます。

1. **本棚** で「＋ 電子書籍または有料マンガを作成」→「電子書籍」
2. **電子書籍の詳細**
   - 言語: 日本語
   - 本のタイトル・サブタイトル、その **フリガナ** と **ローマ字**（日本語の本では入力が必要）
   - 著者名とフリガナ・ローマ字。`book.yaml` の `title` / `author` と**同じ表記**にする
   - 内容紹介、キーワード（最大 7 個）、カテゴリー（最大 3 つ）。`python3 scripts/kdp-listing.py books/my-book` で下書きを作れる（[docs/kdp-listing.md](docs/kdp-listing.md)）
   - 出版に関して必要な権利: 自分が著作権を持っていれば「私は著作権を所有しており…」を選択
3. **電子書籍のコンテンツ**
   - 原稿: 「電子書籍の原稿をアップロード」で `dist/*.epub` を選択。DRM の有無を選ぶ
   - 表紙: 「表紙をアップロード」で表紙画像（`images/cover.jpg` と同じもの、1600×2560px の JPEG 推奨）を選択。[自動生成](#表紙の自動生成)した場合は `dist/<名前>-cover.jpg`
   - AI 生成コンテンツの有無を回答する
   - 「プレビューアーを起動」で表示を確認（縦書きの本が右綴じになっているか）
   - ISBN: **入力不要**（KDP が ASIN を割り当てる。ISBN を持っている場合のみ入力）
4. **価格設定**
   - KDP セレクトへの登録（任意）、出版地域、ロイヤリティプラン（35% / 70%）、販売価格
5. 「Kindle 本を出版」。審査を経て通常 72 時間以内に販売開始されます

### 改訂版を出すとき

原稿を直して再ビルドし、KDP の本棚から「電子書籍のコンテンツを編集」で EPUB を差し替えます。**`uuid` は変えないでください**（同じ本の改訂として扱うため）。

## GitHub Actions

`.github/workflows/build.yml` が、push・プルリクエストのたびに次を実行します。

| ジョブ | 内容 | Artifacts |
|:--|:--|:--|
| `Build (book.yaml)` | `books/` 以下の全ての本を `book.yaml` の設定どおりにビルドし、EPUBCheck で検証。KDP の登録情報の下書きも作り、上限を超えていれば失敗 | `epub`（KDP にアップロードする EPUB）、`epubcheck-reports`（JSON レポート）、`kdp-listing`（内容紹介・キーワード・カテゴリーの下書き） |
| `Validate (vertical)` | 全ての本を **縦書き** でビルドし、EPUBCheck で検証 | `epub-vertical` |
| `Validate (horizontal)` | 全ての本を **横書き** でビルドし、EPUBCheck で検証 | `epub-horizontal` |
| `Paperback PDF (vertical)` / `(horizontal)` | 全ての本のペーパーバック用の本文 PDF を縦書き・横書きで作り、ページサイズ・フォントの埋め込みを確認 | `paperback-vertical` / `paperback-horizontal` |

- ツールのバージョンは `build.yml` の `env` で固定（Pandoc 3.9・EPUBCheck 5.3.0）。セットアップは `.github/actions/setup-tools` にまとめている
- **エラーまたは警告が 1 件でもあるとジョブが失敗**します。各ジョブの「Summary」に EPUB ごとの件数の表が出ます
- 縦書き・横書きの両方で検証するのは、片方のモードでしか使われない CSS（`vertical.css` / `horizontal.css`）やフィルタの処理も毎回検証するため。縦書きの本を横書きにしても、その逆でも、規格違反が出ないことを確認します
- ビルド結果は GitHub の「Actions」タブ → 該当の実行 → 「Artifacts」からダウンロードできます。手動実行（workflow_dispatch）にも対応しています

`.github/workflows/lint.yml` は、同じタイミングで [原稿のチェック](#原稿のチェック)（`npm run lint`）を実行します。

1. Node.js 22 と Pandoc（3.9）をセットアップし、`npm ci` でチェック用のツールを入れる
2. `npm run lint` で全ての本の表記・文章とリンク・参照をチェック
3. 指摘はプルリクエストの「Files changed」で該当行に注釈として表示される。エラーがあるとジョブが失敗する（警告だけなら成功）

## 設計上の判断（KDP ガイドラインに基づいて決めたこと）

[Kindle Publishing Guidelines](https://kdp.amazon.co.jp/ja_JP/help/topic/G200645680)（Amazon が公開している Kindle 本の制作ガイドライン）と KDP ヘルプの内容に沿って、次のように決めました。ガイドラインは改訂されるため、出版前に最新版を確認してください。

### ファイル形式

| 決めたこと | 理由 |
|:--|:--|
| **EPUB3（リフロー型）** を出力 | KDP が推奨するアップロード形式。MOBI は現在 KDP では受け付けられない |
| 論理目次（nav + NCX）と HTML 目次の両方を入れる | Kindle Publishing Guidelines は論理目次を必須、HTML 目次を推奨としている |
| landmarks に `bodymatter`（本文の開始位置）を追加 | Kindle が「本の最初から読む」位置として使う。pandoc は出力しないため後処理で追加 |
| 脚注は `epub:type="noteref"` / `"footnote"` 付きで各章末に出力 | Kindle のポップアップ脚注に対応させるため（相互リンク付き） |
| 章ごとに XHTML ファイルを分割 | 章が新しいページから始まり、1 ファイルが大きくなりすぎない |
| 見出しの ID を ASCII のみにする（`ascii_identifiers`） | 日本語を含む ID・リンクは変換ツールによって扱いが不安定なため |
| `mimetype` を ZIP の先頭に無圧縮で格納 | EPUB（OCF）の要件 |
| EPUBCheck は**警告も失敗**として扱い、CI で縦書き・横書きの両方を検証 | 警告を放置すると本物の問題が埋もれる。モードごとに使う CSS が違うため、片方だけの検証では見落としが出る |
| ルビに `<rp>`（括弧）を出力しない | EPUB 3.3 で非推奨（EPUBCheck の HTM_055）。Kindle を含む EPUB3 リーダーはルビに対応している |

### メタデータ・表紙

| 決めたこと | 理由 |
|:--|:--|
| ISBN は任意。無い場合は `book.yaml` の固定 UUID を `dc:identifier` にする | KDP の電子書籍は ISBN 不要（ASIN が付与される）。EPUB には一意な識別子が必須で、ビルドごとに変わると別の本として扱われるため固定 |
| 表紙は 1600×2560px（縦横比 1.6:1）の JPEG を推奨し、外れると警告 | KDP ヘルプの表紙の推奨値（理想 2560×1600px、JPEG または TIFF、RGB）。KDP では表紙を EPUB とは別にアップロードする |
| 表紙画像は EPUB にも埋め込む（`cover-image`） | Kindle Previewer やほかのリーダーでも表紙が出るように。販売ページの表紙は KDP でアップロードしたものが使われる |
| 扉ページの書名・副題・著者は `dc:title`（main / subtitle）と `dc:creator` だけから作る | pandoc の `author` / `subtitle` も併せて渡すと、扉に副題が 2 回・著者名が 2 回出るため |
| タイトル・著者に読み（`file-as`）を持たせる | 日本語書名の並べ替えに使われる。KDP の入力欄のフリガナとは別物なので、KDP 側でも入力する |

### CSS

| 決めたこと | 理由 |
|:--|:--|
| 本文（`body` / `p`）にフォント・文字サイズ・文字色・行間・左右余白を指定しない | Kindle Publishing Guidelines は、読者がフォント・サイズ・行間・背景色を変えられるよう本文の固定指定を避けるよう求めている。黒の文字色を指定するとダークモードで読めなくなる |
| サイズ・余白は `em` / `%` の相対単位 | 端末や文字サイズに追従させるため。`position` / `float` に依存したレイアウトは使わない |
| 背景色ではなく罫線で囲む | E-ink（白黒）とダークモードの両方で崩れないため |
| コードは `white-space: pre-wrap` で折り返す | Kindle は横スクロールできず、はみ出した部分が読めなくなるため |
| ハイライトは中間調の色 + 太字・斜体（`styles/kindle.theme`） | E-ink（グレースケール）で色の差が消えても、キーワード（太字）とコメント（斜体）が区別できるように。明るすぎる色は E-ink で、暗すぎる色はダークモードで見えなくなる |
| フォントは埋め込まない（`fonts` で任意に追加可） | Kindle には日本語フォント（明朝・ゴシック）が内蔵されており、埋め込むとファイルが大きくなり配信コストも上がる。読者のフォント変更も効かなくなる |

### 縦書き

| 決めたこと | 理由 |
|:--|:--|
| 右綴じは `page-progression-direction="rtl"`、縦書きは `writing-mode: vertical-rl` | EPUB3 の標準的な指定。Kindle 用に `primary-writing-mode` メタデータと `-webkit-` / `-epub-` 接頭辞付きのプロパティも併記 |
| 縦中横は `text-combine-upright` に `-webkit-text-combine: horizontal` / `-epub-text-combine: horizontal` を併記し、既定で 2 桁まで | Kindle を含む WebKit 系リーダーは接頭辞付きの旧プロパティで縦中横を処理するため。3 桁以上は 1 文字幅に収めると潰れて読みにくい |
| コード・表は既定で 90° 回転表示（`sideways`） | 縦組みの中に横組みのブロックを入れる指定は対応がリーダーによって異なり、ページに収まらないと内容が欠ける。回転表示なら長くても次ページへ流れて欠けない（[詳細](#コードブロックと表の表示方式)） |

### 制作環境についての注記

このテンプレートを作成した環境からは kdp.amazon.com に接続できなかったため、上の判断は Kindle Publishing Guidelines と KDP ヘルプについての既知の内容をもとにしています。生成した EPUB は EPUBCheck 5.3.0（縦書き・横書きの両方でエラー・警告・USAGE とも 0）と Chromium での縦書き・横書きの表示で確認していますが、Kindle Previewer での確認はしていません。出版前に、[Kindle Previewer での確認方法](#kindle-previewer-での確認方法)の項目を実機またはプレビューアーで確認してください。

### 参考資料

- [Kindle Publishing Guidelines（KDP ヘルプ）](https://kdp.amazon.co.jp/ja_JP/help/topic/G200645680)
- [電子書籍の原稿のフォーマット（KDP ヘルプ）](https://kdp.amazon.co.jp/ja_JP/help/topic/G200634390)
- [電子書籍の表紙の作成（KDP ヘルプ）](https://kdp.amazon.co.jp/ja_JP/help/topic/G6GTK3T3NUHKLEFX)
- [Kindle Previewer（KDP ヘルプ）](https://kdp.amazon.co.jp/ja_JP/help/topic/G202131170)
- [Pandoc User's Guide: EPUB Metadata](https://pandoc.org/MANUAL.html#epub-metadata)
- [EPUB 3.3](https://www.w3.org/TR/epub-33/) / [EPUBCheck](https://www.w3.org/publishing/epubcheck/)
- [電書協 EPUB 3 制作ガイド](https://dpfj.or.jp/counsel/guide)

## トラブルシューティング

| 症状 | 対処 |
|:--|:--|
| `pandoc が見つかりません` | `bash scripts/setup.sh` を実行するか、`PANDOC=/path/to/pandoc` を指定 |
| `PyYAML が必要です` | `pip install -r requirements.txt` |
| `参照先が見つかりません: @fig:xxx` | ID の綴りを確認。図は `{#fig:xxx}`、表はキャプション行の末尾に `{#tbl:xxx}` |
| `[WARNING] Could not load translations for ja` | pandoc 3.1 系の無害な警告。pandoc 3.9 では出ない |
| 日本語の文中に空白が入る | 半角スペースを入れていないか確認（改行は自動で詰められる） |
| 縦書きでコードが切れる | `layout.vertical.code_blocks` を `sideways` に戻すか、コードを短く分割する |
| 表がはみ出す | 列を減らすか表を分割する。縦書きでは `tables: sideways` を使う |
| 表紙の警告が出る | 1600×2560px・RGB の JPEG にする |
| `日本語フォントが見つかりません` | `sudo apt install fonts-noto-cjk`（Linux）、または `cover_design.font` にフォントファイルのパスを書く |
| 表紙の文字が小さい・改行位置が不自然 | `cover_design.title` などに `\n` を入れて改行位置を指定するか、表記を短くする |
| 画像の変更が EPUB に反映されない | `make clean` で `dist/.image-cache/` を消してビルドし直す |
| `Pillow が無いため画像を最適化していません` | `pip install -r requirements.txt` |
| EPUBCheck が見つからない | `bash scripts/setup.sh` を実行するか、`EPUBCHECK_JAR=/path/to/epubcheck.jar` を設定 |
| `Java が見つかりません` | Java 11 以上をインストール（[EPUBCheck による検証](#epubcheck-による検証)） |
| `EPUBCheck で warning 以上のメッセージが見つかりました` | 表示された場所（EPUB 内のファイル・行）を確認する。`dist/*.epub` は ZIP なので展開して該当の XHTML を見られる。原稿（Markdown）・`book.yaml`・`css` で追加した CSS のどれが原因かを特定して直す |
| 原稿に書いた生の HTML でエラーになる | EPUB の XHTML は XML なので、`<br>` ではなく `<br />` のように閉じる。HTML5 で廃止された要素（`<center>`・`<font>` など）は使わない |
| `Vivliostyle CLI が見つかりません` | リポジトリのルートで `npm install` を実行 |
| ペーパーバックの PDF が豆腐（□）になる・書体が違う | 日本語フォントを入れる（Linux は `sudo apt install fonts-noto-cjk`）。`paperback.font` にインストール済みのフォント名を書くこともできる |
| `paperback.margins.… が KDP の最小値 … より小さいです` | 天・地・小口の余白を 6.4mm（裁ち落としありは 9.5mm）以上にする |
| ペーパーバックで画像の dpi の警告が出る | 元画像を大きい解像度のものに差し替える（表示された幅の px 以上が目安）。小さく置く画像なら無視してよい |
| `textlint が見つかりません` | リポジトリのルートで `npm install` を実行 |
| `npm run lint` で外部リンクが「接続できませんでした」 | 社内ネットワークなどで外に出られない。`npm run lint -- --no-external` で省略するか、`HTTPS_PROXY` を設定する（自動でプロキシを使う） |
| `Error while loading rule 'prh': … spec failed` | 辞書の `specs` の結果が `to` と違う。`lint/dict/*.yml` のそのルールの `pattern` を見直す |
| `npx textlint` だと `:::` やルビが指摘される | `npm run lint` を使う（[Pandoc の記法への対応](#チェックの内容とツール)） |
