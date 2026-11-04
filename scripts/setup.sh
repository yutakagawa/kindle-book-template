#!/usr/bin/env bash
# =====================================================================
# ビルドに必要なツールをインストールする（macOS / Linux / WSL）
#   - Pandoc        … Markdown → EPUB3 変換
#   - Python 依存   … PyYAML（設定ファイルの読み込み）, Pillow（表紙サイズの確認・任意）
#   - EPUBCheck     … EPUB の検証（Java が必要）。tools/ に展開する
#   - npm パッケージ … textlint（原稿の品質チェック）・Vivliostyle（ペーパーバック PDF の組版）
#
# 使い方: bash scripts/setup.sh
# バージョンは環境変数で変更できる: PANDOC_VERSION=3.9 EPUBCHECK_VERSION=5.3.0 bash scripts/setup.sh
# =====================================================================
set -euo pipefail

PANDOC_VERSION="${PANDOC_VERSION:-3.9}"
EPUBCHECK_VERSION="${EPUBCHECK_VERSION:-5.3.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/tools"

info() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }

# ---- Pandoc ---------------------------------------------------------
if command -v pandoc >/dev/null 2>&1; then
  info "pandoc は導入済みです: $(pandoc --version | head -1)"
else
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        info "Homebrew で pandoc をインストールします"
        brew install pandoc
      else
        warn "Homebrew がありません。https://pandoc.org/installing.html から pandoc をインストールしてください"
        exit 1
      fi
      ;;
    Linux)
      arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
      if command -v dpkg >/dev/null 2>&1; then
        info "pandoc ${PANDOC_VERSION} (.deb) をインストールします"
        tmp="$(mktemp -d)"
        curl -fsSL -o "$tmp/pandoc.deb" \
          "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${arch}.deb"
        sudo dpkg -i "$tmp/pandoc.deb"
        rm -rf "$tmp"
      else
        warn "https://pandoc.org/installing.html を参照して pandoc をインストールしてください"
        exit 1
      fi
      ;;
    *)
      warn "この OS は自動インストールに対応していません。README の手順を参照してください"
      exit 1
      ;;
  esac
fi

# ---- Python 依存 ----------------------------------------------------
info "Python パッケージをインストールします"
python3 -m pip install --user -r "$ROOT/requirements.txt" \
  || python3 -m pip install -r "$ROOT/requirements.txt"

# ---- EPUBCheck ------------------------------------------------------
if [ -f "$TOOLS/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar" ]; then
  info "EPUBCheck ${EPUBCHECK_VERSION} は導入済みです"
else
  info "EPUBCheck ${EPUBCHECK_VERSION} を tools/ にダウンロードします"
  mkdir -p "$TOOLS"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/epubcheck.zip" \
    "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip"
  (cd "$TOOLS" && unzip -q -o "$tmp/epubcheck.zip")
  rm -rf "$tmp"
fi
# ---- Java（EPUBCheck の実行に必要）-----------------------------------
java_major() {
  # "openjdk version "21.0.5"" / "java version "1.8.0_x"" から主バージョンを取り出す
  local v
  v="$(java -version 2>&1 | grep -Eo 'version "[^"]+"' | head -1 | cut -d'"' -f2)"
  case "$v" in
    1.*) echo "${v#1.}" | cut -d. -f1 ;;
    *)   echo "$v" | cut -d. -f1 ;;
  esac
}
if ! command -v java >/dev/null 2>&1; then
  warn "Java が見つかりません。EPUBCheck（make check）には Java 11 以上が必要です"
  warn "  macOS:         brew install openjdk@21"
  warn "  Debian/Ubuntu: sudo apt-get install -y openjdk-21-jre-headless"
  warn "  Windows:       winget install EclipseAdoptium.Temurin.21.JRE"
elif [ "$(java_major)" -lt 11 ] 2>/dev/null; then
  warn "Java $(java_major) は古すぎます。EPUBCheck には Java 11 以上が必要です"
else
  # EPUBCheck が実際に起動できるか確認する
  if java -jar "$TOOLS/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar" --version >/dev/null 2>&1; then
    info "EPUBCheck ${EPUBCHECK_VERSION} を確認しました（Java $(java_major)）"
  else
    warn "EPUBCheck を起動できませんでした: java -jar tools/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar --version"
  fi
fi

# ---- npm パッケージ（原稿の品質チェック・ペーパーバック PDF の組版に使う）--------
if command -v npm >/dev/null 2>&1; then
  info "npm パッケージ（textlint・Vivliostyle）をインストールします"
  (cd "$ROOT" && npm install --no-fund --no-audit)
else
  warn "Node.js（npm）が見つかりません。'make lint' と 'make paperback' には Node.js 20 以上が必要です"
fi

info "完了しました。'make' でビルド、'make check' でビルドと EPUBCheck による検証、'make paperback' でペーパーバック用 PDF ができます"
