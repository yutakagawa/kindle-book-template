# よく使うコマンドのまとめ（make が無い環境では python3 scripts/build.py を直接使う）
PYTHON   ?= python3
BUILD    := $(PYTHON) scripts/build.py
VALIDATE := $(PYTHON) scripts/validate.py
# EPUBCheck で失敗にする重大度: fatal / error / warning（既定）/ info / usage
FAIL_ON  ?= warning

.PHONY: all build check check-modes validate lint lint-fix vertical horizontal book clean setup

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

setup:
	bash scripts/setup.sh

clean:
	rm -rf dist
