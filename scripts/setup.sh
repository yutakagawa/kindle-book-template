#!/usr/bin/env bash
# =====================================================================
# ビルドに必要なツールをインストールする（macOS / Linux / WSL）
#   - Pandoc        … Markdown → EPUB3 変換（3.1 以上。古ければ入れ直す）
#   - Python 依存   … PyYAML（設定ファイルの読み込み）, Pillow（画像の最適化・表紙）。
#                     リポジトリ直下の .venv（仮想環境）に入れる
#   - EPUBCheck     … EPUB の検証（Java が必要）。tools/ に展開する
#   - npm パッケージ … textlint（原稿の品質チェック）・Vivliostyle（ペーパーバック PDF の組版）
#
# 使い方: bash scripts/setup.sh
# バージョンは環境変数で変更できる: PANDOC_VERSION=3.9 EPUBCHECK_VERSION=5.3.0 bash scripts/setup.sh
#
# Python のパッケージは、システムの Python ではなく .venv に入れる。
# Ubuntu 23.04 以降（WSL の Ubuntu 24.04 を含む）・Debian 12・Homebrew の Python は
# PEP 668（externally-managed-environment）により、pip install --user が拒否されるため。
# make や python3 scripts/build.py は .venv があれば自動でそれを使う。
#
# 途中の手順が失敗しても残りの手順は続け、最後に失敗した手順をまとめて表示する（終了コード 1）。
# =====================================================================
set -uo pipefail

PANDOC_VERSION="${PANDOC_VERSION:-3.9}"
EPUBCHECK_VERSION="${EPUBCHECK_VERSION:-5.3.0}"
MIN_PANDOC="3.1"          # scripts/build.py の MIN_PANDOC と揃える
MIN_NODE="22.12.0"        # package.json の engines と揃える
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TOOLS="$ROOT/tools"
VENV="${VENV:-$ROOT/.venv}"
REQUIREMENTS="${REQUIREMENTS:-$ROOT/requirements.txt}"
PYTHON="${PYTHON:-python3}"

FAILED=()

info() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }
fail() { warn "$*"; FAILED+=("$1"); }

# version_ge 3.1.3 3.1 → 真（左が右以上）。数字以外の部分は無視する
version_ge() {
  local IFS=.
  local -a a b
  read -r -a a <<<"${1//[^0-9.]/}"
  read -r -a b <<<"${2//[^0-9.]/}"
  local i x y
  for ((i = 0; i < ${#a[@]} || i < ${#b[@]}; i++)); do
    x="${a[i]:-0}"; y="${b[i]:-0}"
    ((10#$x > 10#$y)) && return 0
    ((10#$x < 10#$y)) && return 1
  done
  return 0
}

# コマンドの出力からバージョン番号（最初の x.y[.z...]）を取り出す
extract_version() { grep -Eo '[0-9]+(\.[0-9]+)+' | head -1; }

need_cmd() {
  # need_cmd curl "インストール方法" → 無ければ失敗として記録して偽を返す
  if command -v "$1" >/dev/null 2>&1; then return 0; fi
  fail "$1 が見つかりません。$2"
  return 1
}

# ---- Pandoc ---------------------------------------------------------
pandoc_status() {
  # ok / old / missing を表示する
  if ! command -v pandoc >/dev/null 2>&1; then echo missing; return; fi
  local v
  v="$(pandoc --version 2>/dev/null | head -1 | extract_version)"
  if [ -n "$v" ] && version_ge "$v" "$MIN_PANDOC"; then echo ok; else echo old; fi
}

install_pandoc() {
  local status
  status="$(pandoc_status)"
  if [ "$status" = ok ]; then
    info "pandoc は導入済みです: $(pandoc --version | head -1)"
    return 0
  fi
  if [ "$status" = old ]; then
    warn "pandoc $(pandoc --version | head -1 | extract_version) は古すぎます（${MIN_PANDOC} 以上が必要）。${PANDOC_VERSION} を入れ直します"
  fi
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        info "Homebrew で pandoc をインストールします"
        if [ "$status" = old ]; then brew upgrade pandoc || brew install pandoc; else brew install pandoc; fi \
          || fail "pandoc のインストールに失敗しました（brew install pandoc）"
      else
        fail "Homebrew がありません。https://pandoc.org/installing.html から pandoc ${MIN_PANDOC} 以上をインストールしてください"
      fi
      ;;
    Linux)
      if command -v dpkg >/dev/null 2>&1; then
        need_cmd curl "sudo apt-get install -y curl を実行してください" || return 1
        local arch tmp
        arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
        info "pandoc ${PANDOC_VERSION} (.deb) をインストールします"
        tmp="$(mktemp -d)"
        if curl -fsSL -o "$tmp/pandoc.deb" \
          "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${arch}.deb" \
          && sudo dpkg -i "$tmp/pandoc.deb"; then
          hash -r
          [ "$(pandoc_status)" = ok ] \
            || fail "pandoc を入れましたが、古い pandoc が先に見つかります（$(command -v pandoc)）。PATH を確認してください"
        else
          fail "pandoc のインストールに失敗しました。https://pandoc.org/installing.html を参照してください"
        fi
        rm -rf "$tmp"
      else
        fail "https://pandoc.org/installing.html を参照して pandoc ${MIN_PANDOC} 以上をインストールしてください"
      fi
      ;;
    *)
      fail "この OS は自動インストールに対応していません。README の手順を参照してください"
      ;;
  esac
}

# ---- Python 依存（.venv に入れる）------------------------------------
venv_python() {
  if [ -x "$VENV/bin/python" ]; then echo "$VENV/bin/python"; else echo "$VENV/Scripts/python.exe"; fi
}

install_python_deps() {
  need_cmd "$PYTHON" "Python 3.10 以上をインストールしてください" || return 1
  if [ ! -x "$(venv_python)" ]; then
    info "Python の仮想環境を作ります: ${VENV#"$ROOT"/}"
    if ! "$PYTHON" -m venv "$VENV"; then
      rm -rf "$VENV"
      fail "Python の仮想環境を作れませんでした。Debian / Ubuntu では sudo apt-get install -y python3-venv を実行してから、もう一度 bash scripts/setup.sh を実行してください"
      return 1
    fi
  fi
  info "Python パッケージを ${VENV#"$ROOT"/} にインストールします"
  if ! "$(venv_python)" -m pip install --disable-pip-version-check -q -r "$REQUIREMENTS"; then
    fail "Python パッケージのインストールに失敗しました: $(venv_python) -m pip install -r requirements.txt"
    return 1
  fi
}

# ---- EPUBCheck ------------------------------------------------------
install_epubcheck() {
  if [ -f "$TOOLS/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar" ]; then
    info "EPUBCheck ${EPUBCHECK_VERSION} は導入済みです"
    return 0
  fi
  need_cmd curl "curl をインストールしてください（Debian / Ubuntu: sudo apt-get install -y curl）" || return 1
  need_cmd unzip "unzip をインストールしてください（Debian / Ubuntu: sudo apt-get install -y unzip）" || return 1
  info "EPUBCheck ${EPUBCHECK_VERSION} を tools/ にダウンロードします"
  mkdir -p "$TOOLS"
  local tmp
  tmp="$(mktemp -d)"
  if ! { curl -fsSL -o "$tmp/epubcheck.zip" \
      "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip" \
      && (cd "$TOOLS" && unzip -q -o "$tmp/epubcheck.zip"); }; then
    fail "EPUBCheck のダウンロードに失敗しました"
  fi
  rm -rf "$tmp"
}

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

check_java() {
  if ! command -v java >/dev/null 2>&1; then
    warn "Java が見つかりません。EPUBCheck（make check）には Java 11 以上が必要です"
    warn "  macOS:         brew install openjdk@21"
    warn "  Debian/Ubuntu: sudo apt-get install -y openjdk-21-jre-headless"
    warn "  Windows:       winget install EclipseAdoptium.Temurin.21.JRE"
  elif [ "$(java_major)" -lt 11 ] 2>/dev/null; then
    warn "Java $(java_major) は古すぎます。EPUBCheck には Java 11 以上が必要です"
  elif java -jar "$TOOLS/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar" --version >/dev/null 2>&1; then
    info "EPUBCheck ${EPUBCHECK_VERSION} を確認しました（Java $(java_major)）"
  else
    warn "EPUBCheck を起動できませんでした: java -jar tools/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar --version"
  fi
}

# ---- npm パッケージ（原稿の品質チェック・ペーパーバック PDF の組版に使う）--------
install_npm() {
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    warn "Node.js（npm）が見つかりません。'make lint' と 'make paperback' には Node.js ${MIN_NODE} 以上（推奨 24 LTS）が必要です"
    return 0
  fi
  local v
  v="$(node --version | extract_version)"
  if ! version_ge "$v" "$MIN_NODE"; then
    fail "Node.js ${v} は古すぎます。Node.js ${MIN_NODE} 以上（推奨 24 LTS）を入れてから、もう一度実行してください（nvm なら nvm install && nvm use で .nvmrc のバージョンが入ります）"
    return 1
  fi
  info "npm パッケージ（textlint・Vivliostyle）をインストールします"
  (cd "$ROOT" && npm install --no-fund --no-audit) || fail "npm install に失敗しました"
}

main() {
  install_pandoc
  install_python_deps
  install_epubcheck
  check_java
  install_npm

  if [ ${#FAILED[@]} -gt 0 ]; then
    warn "次の手順が完了していません:"
    local f
    for f in "${FAILED[@]}"; do warn "  - $f"; done
    return 1
  fi
  info "完了しました。'make' でビルド、'make check' でビルドと EPUBCheck による検証、'make paperback' でペーパーバック用 PDF ができます"
}

# source されたとき（テスト）は関数の定義だけを読み込む
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
