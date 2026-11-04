"""テスト共通の設定とフィクスチャ。

scripts/ 以下のスクリプトをモジュールとして import できるようにし、
一時ディレクトリに小さな本（book.yaml + 原稿）を作るヘルパーを用意する。

外部ツール（pandoc・Vivliostyle・Chrome・EPUBCheck・日本語フォント）が必要なテストは、
見つからなければ自動でスキップする（REQUIRE_ALL_TOOLS=1 のときはスキップせず失敗させる。CI 用）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

REQUIRE_ALL = os.environ.get("REQUIRE_ALL_TOOLS") == "1"


def _skip_or_fail(reason: str):
    if REQUIRE_ALL:
        pytest.fail(f"REQUIRE_ALL_TOOLS=1 ですが {reason}")
    pytest.skip(reason)


# ---------------------------------------------------------------------------
# 外部ツールの有無
# ---------------------------------------------------------------------------

def pandoc_path() -> str | None:
    return shutil.which(os.environ.get("PANDOC", "pandoc"))


def vivliostyle_available() -> bool:
    import paperback
    try:
        paperback.find_vivliostyle()
    except paperback.PaperbackError:
        return False
    return True


def browser_path() -> str | None:
    """Vivliostyle に使わせる Chrome / Chromium。"""
    env = os.environ.get("VIVLIOSTYLE_BROWSER")
    if env and Path(env).exists():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    for p in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome")):
        return str(p)
    return None


def japanese_font_available() -> bool:
    import cover
    return cover.find_font("serif", 700) is not None or cover.find_font("sans", 700) is not None


@pytest.fixture
def require_pandoc():
    if not pandoc_path():
        _skip_or_fail("pandoc が見つかりません")


@pytest.fixture
def require_japanese_font():
    if not japanese_font_available():
        _skip_or_fail("日本語フォント（Noto CJK など）が見つかりません")


@pytest.fixture
def require_vivliostyle(require_pandoc):
    if not vivliostyle_available():
        _skip_or_fail("Vivliostyle CLI が見つかりません（npm ci を実行してください）")
    if not browser_path():
        _skip_or_fail("Chrome / Chromium が見つかりません（VIVLIOSTYLE_BROWSER で指定できます）")


@pytest.fixture
def require_epubcheck():
    import validate
    try:
        validate.find_epubcheck(None)
    except validate.ValidationError as e:
        _skip_or_fail(str(e))


# ---------------------------------------------------------------------------
# 一時的な本
# ---------------------------------------------------------------------------

DEFAULT_CHAPTERS = {
    "chapters/01-intro.md": """\
        # はじめに {#sec:intro}

        これはテスト用の本です。[@sec:second]を参照してください。

        ![テストの図](images/figure.png){#fig:test}

        図は[@fig:test]です。
        """,
    "chapters/02-second.md": """\
        # 二つ目の章 {#sec:second}

        本文です。

        ## 節の見出し

        - 箇条書き
        - もう一つ
        """,
}


class BookFactory:
    def __init__(self, base: Path):
        self.base = base
        self.count = 0

    def __call__(self, config: dict | None = None, chapters: dict[str, str] | None = None,
                 images: dict[str, tuple[int, int]] | None = None, name: str | None = None) -> Path:
        """本のディレクトリを作って返す。

        config は book.yaml の内容（既定値に上書き）、chapters は {相対パス: 本文}、
        images は {相対パス: (幅, 高さ)}（その大きさの PNG を作る）。
        """
        self.count += 1
        book = self.base / (name or f"book{self.count}")
        book.mkdir(parents=True)
        cfg = {
            "title": "テストの本",
            "author": [{"name": "試験 太郎", "kana": "シケン タロウ"}],
            "uuid": "12345678-1234-5678-1234-567812345678",
            "language": "ja",
            "layout": {"writing_mode": "horizontal"},
        }
        cfg.update(config or {})
        (book / "book.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        for rel, body in (DEFAULT_CHAPTERS if chapters is None else chapters).items():
            p = book / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(body), encoding="utf-8")
        if images is None:
            images = {"images/figure.png": (800, 400)}
        for rel, size in images.items():
            make_image(book / rel, size)
        return book


@pytest.fixture
def make_book(tmp_path) -> BookFactory:
    return BookFactory(tmp_path / "books")


def make_image(path: Path, size: tuple[int, int], mode: str = "RGB", color=(40, 90, 160), fmt: str | None = None,
               **save_kw) -> Path:
    from PIL import Image, ImageDraw
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new(mode, size, color if mode != "L" else 128)
    if mode in ("RGB", "RGBA"):
        # 図らしく数色だけ使う
        d = ImageDraw.Draw(im)
        d.rectangle((size[0] // 4, size[1] // 4, size[0] // 2, size[1] // 2), fill=(255, 255, 255) + ((255,) if mode == "RGBA" else ()))
    im.save(path, fmt, **save_kw)
    return path


@pytest.fixture
def build_args(tmp_path):
    """build.main がパースする引数と同じ既定値の Namespace（build_book に直接渡す用）。"""
    import argparse

    def _args(**overrides):
        ns = argparse.Namespace(
            books=[], all=False, writing_mode=None, output_dir=str(tmp_path / "dist"), check=False,
            fail_on="warning", report_dir=None, epubcheck_jar=None, no_optimize_images=False,
            paperback=False, browser=browser_path(), keep_html=False,
            pandoc=os.environ.get("PANDOC", "pandoc"), verbose=False,
        )
        for k, v in overrides.items():
            setattr(ns, k, v)
        return ns
    return _args


def run_script(script: str, *args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd or ROOT,
                          capture_output=True, text=True, env={**os.environ, **(env or {})})
