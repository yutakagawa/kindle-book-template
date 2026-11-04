# よく使うコマンドのまとめ（make が無い環境では python3 scripts/build.py を直接使う）
# bash scripts/setup.sh が作る .venv（Python の仮想環境）があれば、その Python を使う
PYTHON   ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD    := $(PYTHON) scripts/build.py
VALIDATE := $(PYTHON) scripts/validate.py
# EPUBCheck で失敗にする重大度: fatal / error / warning（既定）/ info / usage
FAIL_ON  ?= warning

.PHONY: all build check check-modes validate lint lint-fix vertical horizontal book paperback paperback-modes paperback-book listing listing-book test test-python test-node clean setup

all: build

## books/ 以下の全ての本をビルド → dist/*.epub
build:
	$(BUILD) --all

## ビルドして EPUBCheck で検証（警告が 1 件でもあれば失敗）
check:
	$(BUILD) --all --check --fail-on $(FAIL_ON)

## 全ての本を縦書き・横書きの両方でビルドして検証 → dist/modes/*-{vertical,horizontal}.epub
check-modes:
	$(BUILD) --all --writing-mode vertical   -o dist/modes --check --fail-on $(FAIL_ON)
	$(BUILD) --all --writing-mode horizontal -o dist/modes --check --fail-on $(FAIL_ON)

## ビルド済みの EPUB を検証するだけ: make validate EPUB="dist/my-book.epub"
EPUB ?= $(wildcard dist/*.epub)
validate:
	$(VALIDATE) --fail-on $(FAIL_ON) $(EPUB)

## 原稿の品質チェック（表記ゆれ・文章・リンク切れ）。先に npm install が必要
lint:
	npm run lint

lint-fix:
	npm run lint:fix

## サンプル単体のビルド
vertical:
	$(BUILD) books/vertical-sample

horizontal:
	$(BUILD) books/horizontal-sample

## 特定の本: make book BOOK=books/my-book
book:
	$(BUILD) $(BOOK)

## KDP ペーパーバック用の本文 PDF（books/ 以下の全ての本）→ dist/*-paperback.pdf。先に npm install が必要
paperback:
	$(BUILD) --all --paperback

## 全ての本を縦書き・横書きの両方で PDF にする → dist/modes/*-{vertical,horizontal}-paperback.pdf
paperback-modes:
	$(BUILD) --all --paperback --writing-mode vertical   -o dist/modes
	$(BUILD) --all --paperback --writing-mode horizontal -o dist/modes

## 特定の本の PDF: make paperback-book BOOK=books/my-book
paperback-book:
	$(BUILD) --paperback $(BOOK)

## KDP の内容紹介・キーワード・カテゴリー候補の下書き（全ての本）→ dist/*-listing.md
listing:
	$(PYTHON) scripts/kdp-listing.py --all

## 特定の本の下書き: make listing-book BOOK=books/my-book
listing-book:
	$(PYTHON) scripts/kdp-listing.py $(BOOK)

## scripts/ のテスト（tests/）。先に pip install -r tests/requirements.txt と npm install が必要
test: test-python test-node

test-python:
	$(PYTHON) -m pytest

test-node:
	node --test "tests/*.test.mjs"

setup:
	bash scripts/setup.sh

clean:
	rm -rf dist
