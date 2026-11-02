# ビルドと検証 {#sec:build}

## EPUBを生成する

リポジトリのルートで次のコマンドを実行すると、`dist/` にEPUBが生成されます。

```bash
# サンプルを含め、books/ 以下の全ての本をビルド
make

# 特定の本だけビルド
python3 scripts/build.py books/horizontal-sample
```

ビルドの流れは[@fig:pipeline]のとおりです。Pandocが原稿を読み込み、
Luaフィルタで章番号や図番号を付けたあと、EPUB3として書き出します。

![ビルドの処理の流れ](images/pipeline.png){#fig:pipeline}

## 縦書きと横書きを切り替える

`book.yaml` の `layout.writing_mode` を変えるだけで切り替えられます。

```yaml
layout:
  writing_mode: vertical    # 縦書き・右綴じ
  # writing_mode: horizontal  # 横書き・左綴じ
```

それぞれの設定で、EPUBの中身は[@tbl:modes]のように変わります。

| 項目             | 横書き（horizontal） | 縦書き（vertical）   |
|:-----------------|:---------------------|:---------------------|
| 綴じ方向         | 左綴じ（ltr）        | 右綴じ（rtl）        |
| `writing-mode`   | `horizontal-tb`      | `vertical-rl`        |
| 段落             | 字下げなし・段落間あり | 1字下げ            |
| 2桁の数字        | そのまま             | 縦中横               |

: 縦書きと横書きの違い {#tbl:modes}

## 検証する

`--check` を付けると、EPUBの規格チェックツールであるEPUBCheckで検証します[^epubcheck]。

```bash
python3 scripts/build.py --all --check
```

::: important
KDPにアップロードする前に、必ずKindle Previewerで表示を確認しましょう。
EPUBCheckでエラーがなくても、Kindle端末での見え方が意図どおりとは限りません。
:::

[^epubcheck]: EPUBCheckはW3Cが開発しているEPUBの検証ツールです。Javaで動作します。
