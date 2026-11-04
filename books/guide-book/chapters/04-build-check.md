# ビルドと検証 {#sec:build-check}

この章では、原稿をチェックしてからEPUBをビルドし、EPUBCheckで検証します。
3つのチェックを[@fig:checks]の順に通すと、問題を早い段階で見つけられます。

![品質を守る3段のチェック](images/fig-checks.png){#fig:checks}

## 原稿をチェックする

`npm run lint` で、表記ゆれ・文章の誤りと、リンク切れ・参照ミスをまとめてチェックします。

```bash
npm run lint                         # すべての本をチェック
npm run lint -- books/guide-book     # この本だけ
npm run lint:fix                     # 自動で直せる指摘を原稿に反映する
```

結果は本ごとに、ファイル・行・列とともに表示されます。

```text
📖 guide-book（横書き・原稿 8 ファイル）
  表記・文章     ✔ 問題なし
  リンク・参照   ✔ 問題なし  外部 URL 1 件
```

チェックの種類は[@tbl:lint]のとおりです。

| 種類         | チェックすること                                   |
|:-------------|:---------------------------------------------------|
| 表記ゆれ     | 「ユーザ」と「利用者」のような同じ意味の語の混在       |
| 表記ルール   | 辞書で決めた表記か（`Javascript` → `JavaScript`）  |
| 文章         | 文の長さ・読点の数・同じ助詞の連続など             |
| リンク・参照 | 画像・相互参照・脚注・外部URLの参照先があるか      |

: 原稿のチェックの種類 {#tbl:lint}

エラーは直すべきもので、1件でもあるとコマンドが失敗します。
警告は文体の提案なので、書き手の判断で直すかどうかを決めます。

::: tip
表記の規則は `lint/dict/project.yml` に追加できます。
シリーズで統一したい用語があれば、ここに書いておきましょう。
:::

## EPUBをビルドする

ビルドには `make` か、ビルドスクリプトを直接使います（[@lst:build]）。

```{.bash #lst:build caption="EPUBをビルドするコマンド"}
make                                    # books/ 以下のすべての本
make book BOOK=books/guide-book         # 1冊だけ
python3 scripts/build.py books/guide-book -v   # 実行したpandocのコマンドも表示
```

出力先は `dist/` です。本書なら `dist/guide-book.epub` と、
自動で作った表紙 `dist/guide-book-cover.jpg` ができます。

### 画像は自動で最適化される

ビルドのたびに、本のディレクトリの画像をKindle向けに最適化してからEPUBに入れます。
元の画像は変更されず、最適化した画像は `dist/.image-cache/` に置かれます。

| 対象                         | 処理                         |
|:-----------------------------|:-----------------------------|
| 幅1600px・高さ2560pxを超える | 縦横比を保って縮小する       |
| 透過PNG・透過GIF             | 白い背景に合成する           |
| TIFF・BMP・WebP              | PNGかJPEGに変換する          |
| 変更のない画像               | 前回の結果をそのまま使う     |

: 画像の最適化 {#tbl:images}

本書の図版も、幅1600pxの透過の無いPNGで用意しています[^figures]。

[^figures]: 本書の図版は `books/guide-book/figures/make_figures.py` で作っています。図を直したいときは、このスクリプトを書き換えて実行します。

## EPUBCheckで検証する

`make check` は、ビルドしたEPUBをEPUBCheck[^epubcheck]で検証します。
このテンプレートは、**エラーだけでなく警告が1件でもあれば失敗**にします。

```bash
make check                       # ビルドして検証
make validate EPUB=dist/guide-book.epub   # ビルド済みのEPUBを検証するだけ
```

[^epubcheck]: EPUBCheckは、W3Cが公開しているEPUBの公式の検証ツールです。KDPでの変換エラーを事前に減らせます。

失敗の基準は[@tbl:severity]のとおりです。

| 重大度          | 意味                                 | 既定の扱い |
|:----------------|:-------------------------------------|:----------:|
| FATAL / ERROR   | 規格違反。表示が崩れる可能性がある   | 失敗       |
| WARNING         | 問題になりやすい書き方               | 失敗       |
| INFO / USAGE    | 参考情報                             | 表示のみ   |

: EPUBCheckの重大度と扱い {#tbl:severity}

基準は `make check FAIL_ON=error` のように変えられますが、警告も0件に保つことをおすすめします。

## 縦書きと横書きを切り替える

`book.yaml` の `layout.writing_mode` を変えると、縦書きと横書きが切り替わります。
一時的に切り替えるだけなら、`--writing-mode` を使います。

```bash
python3 scripts/build.py books/guide-book --writing-mode vertical
make check-modes      # すべての本を縦書き・横書きの両方で検証
```

`--writing-mode` で切り替えたEPUBは `guide-book-vertical.epub` のように名前が変わるため、
普段のEPUBを上書きしません。

::: note
`cover_design.style` が `auto` なので、縦書きでビルドすると表紙も縦組みのデザインになります。
:::

## GitHub Actionsで自動化する

リポジトリをGitHubに置くと、pushのたびにGitHub Actionsが次を実行します。

- すべての本のビルドとEPUBCheckによる検証（縦書き・横書きの両方）
- 原稿のチェック（`npm run lint`）
- ペーパーバックの本文PDFの作成（縦書き・横書きの両方）

できたEPUBとPDFは、実行結果のページの「Artifacts」からダウンロードできます。
手元で確認し忘れても、プルリクエストの段階で問題に気づけます。
