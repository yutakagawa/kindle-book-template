# よく使うコマンドのまとめ（make が無い環境では python3 scripts/build.py を直接使う）
PYTHON ?= python3
BUILD  := $(PYTHON) scripts/build.py

.PHONY: all build check vertical horizontal clean setup

all: build

## books/ 以下の全ての本をビルド → dist/*.epub
build:
	$(BUILD) --all

## ビルドして EPUBCheck で検証
check:
	$(BUILD) --all --check

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
