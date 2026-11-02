# Kindle 本テンプレート（実用書・技術書向け）

Markdown で書いた原稿から、**Kindle Direct Publishing（KDP）にそのままアップロードできる EPUB3** を、コマンド 1 つで作るテンプレートです。

- 原稿は **章ごとの Markdown ファイル**に分けて書く
- `book.yaml` の 1 行で **縦書き（右綴じ）と横書き（左綴じ）を切り替え**
- 縦書きでも **コードブロック・表・英数字** が読みやすいように CSS を調整済み
- 見出し／自動目次／シンタックスハイライト／表／図番号／囲み／脚注／ルビに対応
- **ISBN なし**で出版できるメタデータ（固定 UUID）を `book.yaml` で管理
- **GitHub Actions** で push のたびに縦書き版・横書き版の両方をビルドし、EPUBCheck で検証

```bash
make            # → dist/horizontal-sample.epub, dist/vertical-sample.epub
```

---

## 目次

1. [ディレクトリ構成](#ディレクトリ構成)
2. [セットアップ](#セットアップ)
3. [ビルド方法](#ビルド方法)
4. [新しい本を作る](#新しい本を作る)
5. [設定ファイル book.yaml](#設定ファイル-bookyaml)
6. [原稿の書き方](#原稿の書き方)
7. [縦書きの表示の工夫](#縦書きの表示の工夫)
8. [Kindle Previewer での確認方法](#kindle-previewer-での確認方法)
9. [KDP へのアップロード手順](#kdp-へのアップロード手順)
10. [GitHub Actions](#github-actions)
11. [設計上の判断（KDP ガイドラインに基づいて決めたこと）](#設計上の判断kdp-ガイドラインに基づいて決めたこと)
12. [トラブルシューティング](#トラブルシューティング)

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
│   └── setup.sh               # ツールのインストール
├── .github/workflows/build.yml
├── Makefile
└── requirements.txt
```

## セットアップ

### ツールの選定

| ツール | 用途 | 選んだ理由 |
|:--|:--|:--|
| [Pandoc](https://pandoc.org/) 3.1 以上（CI は 3.9 に固定） | Markdown → EPUB3 変換 | EPUB3 を直接出力でき、目次（nav / NCX）・脚注（`epub:type="noteref"`）・シンタックスハイライト・綴じ方向（`page-progression-direction`）に標準対応。Lua フィルタで日本語向けの拡張を足せる |
| Python 3.9 以上 + PyYAML | ビルドスクリプト・設定ファイルの読み込み | macOS / Linux / Windows のどれでも動く |
| [EPUBCheck](https://www.w3.org/publishing/epubcheck/)（任意・Java 11 以上） | EPUB の規格チェック | W3C 公式の検証ツール。KDP でのエラーを事前に減らせる |
| [Kindle Previewer 3](https://kdp.amazon.co.jp/ja_JP/help/topic/G202131170)（任意） | Kindle での見え方の確認 | Amazon 公式。KDP と同じ変換エンジンで表示できる |

### macOS / Linux / WSL

```bash
bash scripts/setup.sh
```

`setup.sh` は次を行います。

- pandoc が無ければインストール（macOS は Homebrew、Debian/Ubuntu は公式 .deb）
- `pip install -r requirements.txt`（PyYAML・Pillow）
- EPUBCheck を `tools/` にダウンロード（Java が必要）

### Windows

1. Pandoc をインストール: `winget install --id JohnMacFarlane.Pandoc`（または [公式インストーラ](https://pandoc.org/installing.html)）
2. Python をインストールして `py -m pip install -r requirements.txt`
3. （任意）EPUBCheck: [リリースページ](https://github.com/w3c/epubcheck/releases) から zip を取得し、展開した `epubcheck.jar` のパスを環境変数 `EPUBCHECK_JAR` に設定

`make` が無い場合は `py scripts\build.py --all` のように直接実行してください（WSL を使うと macOS / Linux と同じ手順でビルドできます）。

## ビルド方法

```bash
make                 # books/ 以下の全ての本をビルド → dist/*.epub
make check           # ビルド後に EPUBCheck で検証
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
| `--check` | ビルド後に EPUBCheck を実行（`tools/epubcheck*/epubcheck.jar` → `EPUBCHECK_JAR` → `epubcheck` コマンドの順に探す） |
| `--writing-mode vertical\|horizontal` | `layout.writing_mode` を一時的に上書き |
| `-o DIR` | 出力先（既定 `dist/`） |
| `--pandoc PATH` | 使う pandoc（環境変数 `PANDOC` でも可） |

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
- 画像は `images/` に置く。JPEG（写真）か PNG（図）を使い、幅 1,200px 以上を目安にする
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

1. Pandoc（3.9 に固定）・EPUBCheck（5.3.0）・Python・Java をセットアップ
2. `python3 scripts/build.py --all --check` で `books/` 以下の全ての本（縦書き版・横書き版）をビルドし、EPUBCheck で検証
3. 生成した EPUB を **Artifacts**（`epub`）としてアップロード

ビルド結果は GitHub の「Actions」タブ → 該当の実行 → 「Artifacts」の `epub` からダウンロードできます。EPUBCheck でエラーがあるとジョブが失敗します。手動実行（workflow_dispatch）にも対応しています。

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

### メタデータ・表紙

| 決めたこと | 理由 |
|:--|:--|
| ISBN は任意。無い場合は `book.yaml` の固定 UUID を `dc:identifier` にする | KDP の電子書籍は ISBN 不要（ASIN が付与される）。EPUB には一意な識別子が必須で、ビルドごとに変わると別の本として扱われるため固定 |
| 表紙は 1600×2560px（縦横比 1.6:1）の JPEG を推奨し、外れると警告 | KDP ヘルプの表紙の推奨値（理想 2560×1600px、JPEG または TIFF、RGB）。KDP では表紙を EPUB とは別にアップロードする |
| 表紙画像は EPUB にも埋め込む（`cover-image`） | Kindle Previewer やほかのリーダーでも表紙が出るように。販売ページの表紙は KDP でアップロードしたものが使われる |
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

このテンプレートを作成した環境からは kdp.amazon.com に接続できなかったため、上の判断は Kindle Publishing Guidelines と KDP ヘルプについての既知の内容をもとにしています。生成した EPUB は EPUBCheck（エラー・警告 0）と Chromium での縦書き・横書きの表示で確認していますが、Kindle Previewer での確認はしていません。出版前に、[Kindle Previewer での確認方法](#kindle-previewer-での確認方法)の項目を実機またはプレビューアーで確認してください。

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
| EPUBCheck が見つからない | `bash scripts/setup.sh` を実行するか、`EPUBCHECK_JAR=/path/to/epubcheck.jar` を設定 |
