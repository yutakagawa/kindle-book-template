# テンプレートの全体像とセットアップ {#sec:overview}

この章では、テンプレートで何ができるのかを確認し、ビルドに必要なツールを準備します。
最後にサンプルをビルドして、環境が整ったことを確かめます。

## テンプレートでできること

このテンプレートは、Markdownの原稿と設定ファイル1つから、出版に必要なファイルを作ります。

- 章ごとのMarkdownファイルから、KDPにアップロードできる**EPUB3**を作る
- 設定の1行で、**横書き（左綴じ）と縦書き（右綴じ）**を切り替える
- 書名と著者名から、KDPの推奨サイズの**表紙画像**を自動で作る
- 同じ原稿から、KDPペーパーバックの**本文PDF**を作る
- **EPUBCheck**で検証し、警告が1件でもあれば失敗にする
- 表記ゆれ・リンク切れなど、**原稿の誤り**をまとめてチェックする

全体の仕組みは[@fig:overview]のとおりです。
原稿・設定・図版を入力にして、ビルドスクリプト `scripts/build.py` が
Pandoc[^pandoc]とLuaフィルタで変換し、EPUB・本文PDF・表紙を出力します。

![テンプレートの全体像](images/fig-overview.png){#fig:overview}

[^pandoc]: Pandocは、Markdown・HTML・EPUB・Wordなど多数の形式を相互に変換するオープンソースのツールです。変換の途中にLuaで書いたフィルタの処理を足せるので、章番号や囲みなど、日本語の本に必要な機能を追加しています。

## 必要なツール

ビルドに使うツールを[@tbl:tools]にまとめます。
EPUBを作るだけなら、PandocとPythonがあれば足ります。

| ツール               | 用途                         | 必須 |
|:---------------------|:-----------------------------|:----:|
| Pandoc 3.1以上       | MarkdownからEPUB3への変換    | ○    |
| Python 3.9以上       | ビルドスクリプトの実行       | ○    |
| Pillow               | 画像の最適化・表紙の生成     | 推奨 |
| Java 11以上          | EPUBCheckの実行              | 推奨 |
| Node.js 20以上       | 原稿のチェック・PDFの組版    | 任意 |
| 日本語フォント       | 表紙とPDFの文字              | 推奨 |

: ビルドに使うツール {#tbl:tools}

表の「任意」のツールは、使う機能に合わせて後から入れてもかまいません。

## セットアップする

macOS・Linux・WSLでは、付属のスクリプトでまとめてインストールできます（[@lst:setup]）。

```{.bash #lst:setup caption="ツールをまとめてインストールする"}
# リポジトリを取得する
git clone https://github.com/yutakagawa/kindle-book-template.git
cd kindle-book-template

# Pandoc・Pythonのパッケージ・EPUBCheckを入れる
bash scripts/setup.sh

# 原稿のチェックとPDFの組版に使うツールを入れる
npm install
```

`setup.sh` は、EPUBCheckを `tools/` の下にダウンロードします。
このディレクトリはGitの管理対象外なので、リポジトリには含まれません。

::: tip
Linuxで表紙やPDFの日本語が表示されないときは、`sudo apt install fonts-noto-cjk` で
Noto CJKフォントを入れてください。macOSとWindowsは標準のフォントが使われます。
:::

### Windowsの場合

Windowsでは、`winget` でPandocとPythonを入れます。

```powershell
winget install --id JohnMacFarlane.Pandoc
py -m pip install -r requirements.txt
```

`make` が無い環境では、`py scripts\build.py --all` のようにスクリプトを直接実行します。
WSLを使うと、macOS・Linuxと同じ手順でビルドできます。

## 動作を確かめる

セットアップが終わったら、同梱の本をすべてビルドして検証します。

```bash
make check
```

次のように表示されれば成功です。`dist/` にEPUBができています。

```text
[build] guide-book: horizontal でビルドします（pandoc 3.9）
[build] 出力: dist/guide-book.epub
[epubcheck]   EPUBCheck 5.3.0・EPUB 3.3: 0 fatal / 0 error / 0 warning
[epubcheck]   ✓ 問題ありません
```

::: important
`make check` が失敗するときは、まずエラーメッセージに出ているツール名を確認します。
よくある原因は、JavaかEPUBCheckが見つからないことです。
`java -jar tools/epubcheck-5.3.0/epubcheck.jar --version` で動くか確かめてください。
:::
