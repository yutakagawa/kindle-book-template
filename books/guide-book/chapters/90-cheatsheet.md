# 記法とコマンドの早見表 {.appendix #sec:cheatsheet}

本文で紹介した記法とコマンドを、1か所にまとめます。
付録の図表には「表A.1」のように、アルファベットの付録番号が付きます。

## 記法

| 書きたいもの     | 記法                                  |
|:-----------------|:--------------------------------------|
| 章（番号なし）   | `# はじめに {.unnumbered}`            |
| 章（参照用ID）   | `# 原稿を書く {#sec:writing}`         |
| 付録             | `# 早見表 {.appendix}`                |
| 図               | `![説明](images/a.png){#fig:a}`       |
| 表キャプション   | `: 説明 {#tbl:a}`                     |
| リスト番号       | ```` ```{.python #lst:a caption="説明"} ```` |
| 相互参照         | `@fig:a` / `[@tbl:a]`                 |
| 囲み             | `::: note` 〜 `:::`                   |
| 脚注             | `本文[^a]` と `[^a]: 内容`            |
| ルビ             | `[漢字]{ruby="かんじ"}`               |
| 縦中横（手動）   | `[12]{.tcy}`                          |
| 改ページ         | `::: pagebreak` 〜 `:::`              |

: 記法の一覧 {#tbl:cheatsheet}

ルビは本文中なら短縮記法 `{漢字|かんじ}` でも書けます（[@tbl:cheatsheet]）。

## コマンド

| やりたいこと                     | コマンド                                    |
|:---------------------------------|:--------------------------------------------|
| 原稿をチェックする               | `npm run lint -- books/guide-book`          |
| EPUBをビルドする                 | `make book BOOK=books/guide-book`           |
| ビルドして検証する               | `make check`                                |
| 縦書き・横書きの両方で検証する   | `make check-modes`                          |
| 表紙だけを作る                   | `python3 scripts/cover.py books/guide-book` |
| 本文PDFを作る                    | `make paperback-book BOOK=books/guide-book` |
| `dist/` を消す                   | `make clean`                                |

: よく使うコマンド {#tbl:commands}
