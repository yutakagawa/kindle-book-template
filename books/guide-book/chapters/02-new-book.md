# 新しい本を作る {#sec:new-book}

この章では、自分の本のディレクトリを作り、書誌情報と表紙を設定します。
本書のディレクトリ `books/guide-book/` を例に説明します。

## サンプルをコピーする

新しい本は、サンプルのディレクトリをコピーして作ります。
横書きの本なら `horizontal-sample`、縦書きの本なら `vertical-sample` をコピーします。

```bash
cp -r books/horizontal-sample books/my-book
python3 -c "import uuid; print(uuid.uuid4())"   # 新しいUUIDを作る
```

2行目で表示されたUUIDを、`book.yaml` の `uuid` の値にします。
UUIDは本を識別するための値です。**1冊ずつ必ず新しい値**にしてください[^uuid]。

[^uuid]: KDPの電子書籍にISBNは必要ありません。AmazonがASINという識別番号を割り当てます。EPUBの規格では識別子が必須なので、ISBNが無い本はUUIDを識別子にします。

## ディレクトリの構成

1冊の本は、[@fig:bookdir]のような構成になります。
`--all` を付けてビルドすると、`book.yaml` を含むディレクトリがすべて「本」として扱われます。

![1冊の本のディレクトリ構成](images/fig-bookdir.png){#fig:bookdir}

`chapters/` には原稿を、`images/` には図版を置きます。
`textlint.json` は、この本だけチェックの規則を変えたいときに置く任意のファイルです。

## `book.yaml` を書く

`book.yaml` には、書誌情報・表紙・章の順番・組版の設定を書きます。
本書の設定から主な部分を抜き出したものが[@lst:bookyaml]です。

```{.yaml #lst:bookyaml caption="本書のbook.yaml（抜粋）"}
title: Markdownで作るKindle本 入門
subtitle: テンプレートで原稿からKDP出版まで
author:
  - name: 山田 太郎
    kana: ヤマダ タロウ
contributors:
  - name: 鈴木 花子
    role: edt                  # 編集
language: ja
uuid: ea91fda0-3c31-46ed-b1a7-13cbcb5c0e2b

chapters:
  - chapters/00-preface.md
  - chapters/01-overview.md

layout:
  writing_mode: horizontal     # vertical にすると縦書き
  toc_depth: 2
```

よく使うキーを[@tbl:bookyaml]にまとめます。

| キー                  | 必須 | 説明                                         |
|:----------------------|:----:|:---------------------------------------------|
| `title`               | ○    | 書名。EPUBの `dc:title` になる               |
| `author`              | ○    | 著者。文字列か、`name` と `kana` のリスト    |
| `uuid`                | 推奨 | ISBNが無い場合の識別子。本ごとに固定         |
| `cover_design`        | –    | 表紙を自動で作る設定（次の節）               |
| `chapters`            | –    | 原稿の順番。省略するとファイル名順           |
| `layout.writing_mode` | –    | `horizontal`（既定）か `vertical`            |

: `book.yaml` の主なキー {#tbl:bookyaml}

::: caution
`uuid` を別の本と同じ値のままにすると、EPUBの識別子が重複し、電子書籍リーダーや管理ソフトで2冊が同じ本として扱われることがあります。
コピーした直後に、必ず書き換えてください。
:::

## 表紙を自動で作る

`book.yaml` に `cover_design` を書くと、ビルドのたびに書名・副題・著者名から表紙を作り、
EPUBに埋め込みます。表紙の画像を自分で用意する必要はありません。

```{.yaml #lst:cover caption="本書の表紙の設定"}
cover_design:
  style: auto                  # 横書きの本なので横組みのデザイン
  colors: ["#0f2a44", "#1f5f8b", "#2a7f8f"]
  gradient: diagonal           # 斜めのグラデーション
  accent_color: "#f2c14e"      # 飾り罫の色
  font: sans                   # ゴシック体
  title: "Markdownで作る\nKindle本 入門"   # \n で改行位置を決める
  author_suffix: " 著"
```

[@lst:cover]の設定でビルドすると、`dist/guide-book-cover.jpg` に表紙ができます。
表紙だけを試したいときは、次のコマンドを使います。

```bash
python3 scripts/cover.py books/guide-book                    # 表紙だけを作る
python3 scripts/cover.py books/guide-book --style vertical   # 縦組みのデザインを試す
```

表紙の主な設定は[@tbl:cover]のとおりです。

| キー           | 既定             | 説明                                   |
|:---------------|:-----------------|:---------------------------------------|
| `style`        | `auto`           | `vertical` / `horizontal`              |
| `colors`       | デザインごと     | 1色なら単色、2色以上ならグラデーション |
| `background`   | –                | 背景画像。`colors` の代わりに使う      |
| `font`         | 横書きは `sans`  | `serif`（明朝）か `sans`（ゴシック）   |

: `cover_design` の主な設定 {#tbl:cover}

文字は枠に収まる最大の大きさに自動で調整され、禁則処理をしたうえで改行されます。

::: warning
市販のフォントを表紙に使うときは、**商用の画像に使えるライセンスか**を確認してください。
Noto CJKフォントとIPAフォントは使えます。
:::
