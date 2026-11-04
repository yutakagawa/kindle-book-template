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

```bash
make            # → dist/horizontal-sample.epub, dist/vertical-sample.epub
```

---

## 目次

1. [ディレクトリ構成](#ディレクトリ構成)
2. [セットアップ](#セットアップ)
3. [ビルド方法](#ビルド方法)
4. [EPUBCheck による検証](#epubcheck-による検証)
5. [新しい本を作る](#新しい本を作る)
6. [設定ファイル book.yaml](#設定ファイル-bookyaml)
7. [原稿の書き方](#原稿の書き方)
8. [画像の最適化](#画像の最適化)
9. [縦書きの表示の工夫](#縦書きの表示の工夫)
10. [Kindle Previewer での確認方法](#kindle-previewer-での確認方法)
11. [KDP へのアップロード手順](#kdp-へのアップロード手順)
12. [GitHub Actions](#github-actions)
13. [設計上の判断（KDP ガイドラインに基づいて決めたこと）](#設計上の判断kdp-ガイドラインに基づいて決めたこと)
14. [トラブルシューティング](#トラブルシューティング)

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
│   └── kindle.theme           #   シンタックスハイライトの配色（E-ink でも区別できる）
├── scripts/
│   ├── build.py               # ビルドスクリプト（本体）
│   ├── images.py              # 画像の Kindle 向け最適化（build.py から呼ばれる）
│   ├── validate.py            # EPUBCheck による検証（警告以上で失敗）
│   └── setup.sh               # ツールのインストール
├── .github/
│   ├── workflows/build.yml    # CI（ビルド + 縦書き・横書きの両方で検証）
│   └── actions/setup-tools/   # CI 用のツールのセットアップ
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

### macOS / Linux / WSL

```bash
bash scripts/setup.sh
```

`setup.sh` は次を行います。

- pandoc が無ければインストール（macOS は Homebrew、Debian/Ubuntu は公式 .deb）
- `pip install -r requirements.txt`（PyYAML・Pillow）
- EPUBCheck を `tools/` にダウンロードし、Java で起動できるか確認（Java 11 以上が無ければインストール方法を表示）

### Windows

1. Pandoc をインストール: `winget install --id JohnMacFarlane.Pandoc`（または [公式インストーラ](https://pandoc.org/installing.html)）
2. Python をインストールして `py -m pip install -r requirements.txt`
3. （任意）EPUBCheck: 下の「[EPUBCheck による検証](#epubcheck-による検証)」を参照

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
4. `make book BOOK=books/my-book`

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
   - 内容紹介、キーワード（最大 7 個）、カテゴリー
   - 出版に関して必要な権利: 自分が著作権を持っていれば「私は著作権を所有しており…」を選択
3. **電子書籍のコンテンツ**
   - 原稿: 「電子書籍の原稿をアップロード」で `dist/*.epub` を選択。DRM の有無を選ぶ
   - 表紙: 「表紙をアップロード」で表紙画像（`images/cover.jpg` と同じもの、1600×2560px の JPEG 推奨）を選択
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
| `Build (book.yaml)` | `books/` 以下の全ての本を `book.yaml` の設定どおりにビルドし、EPUBCheck で検証 | `epub`（KDP にアップロードする EPUB）、`epubcheck-reports`（JSON レポート） |
| `Validate (vertical)` | 全ての本を **縦書き** でビルドし、EPUBCheck で検証 | `epub-vertical` |
| `Validate (horizontal)` | 全ての本を **横書き** でビルドし、EPUBCheck で検証 | `epub-horizontal` |

- ツールのバージョンは `build.yml` の `env` で固定（Pandoc 3.9・EPUBCheck 5.3.0）。セットアップは `.github/actions/setup-tools` にまとめている
- **エラーまたは警告が 1 件でもあるとジョブが失敗**します。各ジョブの「Summary」に EPUB ごとの件数の表が出ます
- 縦書き・横書きの両方で検証するのは、片方のモードでしか使われない CSS（`vertical.css` / `horizontal.css`）やフィルタの処理も毎回検証するため。縦書きの本を横書きにしても、その逆でも、規格違反が出ないことを確認します
- ビルド結果は GitHub の「Actions」タブ → 該当の実行 → 「Artifacts」からダウンロードできます。手動実行（workflow_dispatch）にも対応しています

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
| 画像の変更が EPUB に反映されない | `make clean` で `dist/.image-cache/` を消してビルドし直す |
| `Pillow が無いため画像を最適化していません` | `pip install -r requirements.txt` |
| EPUBCheck が見つからない | `bash scripts/setup.sh` を実行するか、`EPUBCHECK_JAR=/path/to/epubcheck.jar` を設定 |
| `Java が見つかりません` | Java 11 以上をインストール（[EPUBCheck による検証](#epubcheck-による検証)） |
| `EPUBCheck で warning 以上のメッセージが見つかりました` | 表示された場所（EPUB 内のファイル・行）を確認する。`dist/*.epub` は ZIP なので展開して該当の XHTML を見られる。原稿（Markdown）・`book.yaml`・`css` で追加した CSS のどれが原因かを特定して直す |
| 原稿に書いた生の HTML でエラーになる | EPUB の XHTML は XML なので、`<br>` ではなく `<br />` のように閉じる。HTML5 で廃止された要素（`<center>`・`<font>` など）は使わない |
