#!/usr/bin/env python3
"""Markdown 原稿から Kindle (KDP) 用の EPUB3 を生成するビルドスクリプト。

使い方:
    python3 scripts/build.py books/horizontal-sample          # 1 冊ビルド
    python3 scripts/build.py --all                            # books/ 以下を全部ビルド
    python3 scripts/build.py books/my-book --check            # ビルド後に EPUBCheck で検証（警告以上で失敗）
    python3 scripts/build.py books/my-book --writing-mode horizontal   # 設定を一時的に上書き
    python3 scripts/build.py books/my-book --no-optimize-images        # 画像を最適化せずに使う
    python3 scripts/build.py books/my-book --paperback                 # KDP ペーパーバック用の本文 PDF を作る

出力先は dist/<本のディレクトリ名>.epub（book.yaml の output で変更可）。
画像は Kindle 向けに最適化した版を dist/.image-cache/<本のディレクトリ名>/ に作って使う（scripts/images.py）。
--paperback では dist/<本のディレクトリ名>-paperback.pdf を作る（scripts/paperback.py）。
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

if __name__ == "__main__":
    # bash scripts/setup.sh が作った .venv があれば、その Python（PyYAML・Pillow 入り）で起動し直す
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from use_venv import reexec_in_venv
    reexec_in_venv(__file__)

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要です: bash scripts/setup.sh を実行してください（.venv に入ります）")

ROOT = Path(__file__).resolve().parent.parent
FILTERS = ROOT / "filters"
STYLES = ROOT / "styles"
MIN_PANDOC = (3, 1)

# 縦書き時のコードブロック・表の表示方式
VERTICAL_BLOCK_MODES = ("sideways", "horizontal", "vertical")


class BuildError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[build] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# pandoc
# ---------------------------------------------------------------------------

def pandoc_version(pandoc: str) -> tuple[int, ...]:
    try:
        out = subprocess.run([pandoc, "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        raise BuildError(
            "pandoc が見つかりません。README の「セットアップ」を参照してインストールしてください。"
        )
    m = re.search(r"pandoc(?:\.exe)? (\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        raise BuildError(f"pandoc のバージョンを判定できません: {out.splitlines()[0]}")
    ver = tuple(int(x) for x in m.groups() if x is not None)
    if ver < MIN_PANDOC:
        raise BuildError(f"pandoc {'.'.join(map(str, MIN_PANDOC))} 以上が必要です（現在 {'.'.join(map(str, ver))}）")
    return ver


# ---------------------------------------------------------------------------
# 設定ファイル
# ---------------------------------------------------------------------------

def load_config(book_dir: Path) -> dict:
    path = book_dir / "book.yaml"
    if not path.exists():
        raise BuildError(f"{path} がありません")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise BuildError(f"{path} の形式が正しくありません")
    return cfg


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalize_people(value, role: str) -> list[dict]:
    people = []
    for p in as_list(value):
        if isinstance(p, str):
            p = {"name": p}
        if not p.get("name"):
            continue
        entry = {"text": p["name"], "role": p.get("role", role)}
        if p.get("kana"):
            entry["file-as"] = p["kana"]
        people.append(entry)
    return people


def normalize_isbn(isbn: str) -> str:
    digits = re.sub(r"[^0-9Xx]", "", isbn)
    if len(digits) not in (10, 13):
        raise BuildError(f"ISBN の桁数が正しくありません: {isbn}")
    return digits.upper()


def build_metadata(cfg: dict, book_dir: Path, writing_mode: str, warnings: list[str]) -> dict:
    title = cfg.get("title")
    if not title:
        raise BuildError("book.yaml に title がありません")
    authors = normalize_people(cfg.get("author"), "aut")
    if not authors:
        raise BuildError("book.yaml に author がありません")

    title_entries = [{"type": "main", "text": title}]
    if cfg.get("title_kana"):
        title_entries[0]["file-as"] = cfg["title_kana"]
    if cfg.get("subtitle"):
        title_entries.append({"type": "subtitle", "text": cfg["subtitle"]})

    # 識別子: ISBN があれば ISBN、なければ固定の UUID（KDP では ISBN は不要。ASIN が自動で割り当てられる）
    identifiers = []
    if cfg.get("isbn"):
        identifiers.append({"scheme": "ISBN-13" if len(normalize_isbn(str(cfg["isbn"]))) == 13 else "ISBN-10",
                            "text": "urn:isbn:" + normalize_isbn(str(cfg["isbn"]))})
    book_uuid = cfg.get("uuid")
    if not book_uuid:
        # 毎回変わると別の本として扱われるので、タイトルと著者から決定的に作る
        seed = f"{title}/{authors[0]['text']}"
        book_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "kindle-book-template:" + seed))
        warnings.append(
            f"book.yaml に uuid がないため {book_uuid} を使いました。この値を book.yaml の uuid に書いておくと安全です"
        )
    else:
        try:
            book_uuid = str(uuid.UUID(str(book_uuid)))
        except ValueError:
            raise BuildError(f"uuid の形式が正しくありません: {book_uuid}")
    if not identifiers:
        identifiers.append({"scheme": "UUID", "text": "urn:uuid:" + book_uuid})

    layout = cfg.get("layout") or {}
    vertical = layout.get("vertical") or {}
    code_mode = vertical.get("code_blocks", "sideways")
    table_mode = vertical.get("tables", "sideways")
    for name, mode in (("code_blocks", code_mode), ("tables", table_mode)):
        if mode not in VERTICAL_BLOCK_MODES:
            raise BuildError(f"layout.vertical.{name} は {', '.join(VERTICAL_BLOCK_MODES)} のいずれかです: {mode}")

    meta: dict = {
        "title": title_entries,
        "creator": authors + normalize_people(cfg.get("contributors"), "ctb"),
        "identifier": identifiers,
        "lang": cfg.get("language", "ja"),
        "page-progression-direction": "rtl" if writing_mode == "vertical" else "ltr",
        "toc-title": layout.get("toc_title", "目次"),
    }
    # 扉ページ（title_page.xhtml）は title（main / subtitle）と creator から作られる。
    # pandoc の author / subtitle も設定すると、扉に著者名と副題が重複して出るため設定しない。

    for key in ("publisher", "rights", "description"):
        if cfg.get(key):
            meta[key] = str(cfg[key]).strip()
    if cfg.get("date"):
        meta["date"] = str(cfg["date"])
    if cfg.get("keywords"):
        meta["subject"] = [str(k) for k in as_list(cfg["keywords"])]

    cover = cfg.get("cover")
    if cover:
        cover_path = (book_dir / cover).resolve()
        if not cover_path.exists():
            raise BuildError(f"表紙画像が見つかりません: {cover_path}")
        meta["cover-image"] = str(cover_path)
        check_cover(cover_path, warnings)
    else:
        warnings.append("cover が未設定です。KDP では表紙画像（推奨 1600×2560px の JPEG）を別途アップロードしてください")

    # Lua フィルタへ渡す設定
    meta["kbt"] = {
        "writing_mode": writing_mode,
        "number_chapters": bool(layout.get("number_chapters", True)),
        "chapter_label": layout.get("chapter_label", "第{n}章"),
        "appendix_label": layout.get("appendix_label", "付録{n}"),
        "figure_label": layout.get("figure_label", "図{c}.{n}"),
        "table_label": layout.get("table_label", "表{c}.{n}"),
        "listing_label": layout.get("listing_label", "リスト{c}.{n}"),
        "caption_separator": layout.get("caption_separator", "　"),
        "tcy_digits": str(vertical.get("tcy_digits", 2)),
        "vertical_code": code_mode,
        "vertical_table": table_mode,
    }
    return meta


def check_cover(path: Path, warnings: list[str]) -> None:
    """KDP の推奨（高さ:幅 = 1.6:1、理想 2560×1600px、JPEG/TIFF、RGB）に沿っているか軽く確認する。"""
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        warnings.append(f"表紙は JPEG を推奨します: {path.name}")
    try:
        from PIL import Image  # 任意依存
    except ImportError:
        return
    with Image.open(path) as im:
        w, h = im.size
        if im.mode not in ("RGB", "L"):
            warnings.append(f"表紙のカラーモードは RGB を推奨します（現在 {im.mode}）")
    if w < 625 or h < 1000:
        warnings.append(f"表紙が小さすぎます（{w}×{h}px）。KDP の推奨は 1600×2560px です")
    elif abs(h / w - 1.6) > 0.05:
        warnings.append(f"表紙の縦横比が 1.6:1 から離れています（{w}×{h}px）")


# ---------------------------------------------------------------------------
# ビルド
# ---------------------------------------------------------------------------

def build_book(book_dir: Path, args) -> Path:
    book_dir = book_dir.resolve()
    cfg = load_config(book_dir)
    layout = cfg.get("layout") or {}
    writing_mode = args.writing_mode or layout.get("writing_mode", "horizontal")
    if writing_mode not in ("vertical", "horizontal"):
        raise BuildError(f"layout.writing_mode は vertical か horizontal です: {writing_mode}")

    chapters = [book_dir / c for c in as_list(cfg.get("chapters"))]
    if not chapters:
        chapters = sorted((book_dir / "chapters").glob("*.md"))
    if not chapters:
        raise BuildError("原稿（chapters）がありません")
    for c in chapters:
        if not c.exists():
            raise BuildError(f"原稿が見つかりません: {c}")

    warnings: list[str] = []
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.paperback:
        return build_paperback(book_dir, cfg, chapters, writing_mode, out_dir, args, warnings)
    out_name = cfg.get("output") or f"{book_dir.name}.epub"
    if args.writing_mode and not cfg.get("output"):
        out_name = f"{book_dir.name}-{writing_mode}.epub"
    output = out_dir / out_name

    # cover_design があれば表紙を生成し（dist/<名前>-cover.jpg）、EPUB の表紙として使う
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    from cover import CoverError, design_enabled, generate_book_cover
    if design_enabled(cfg):
        try:
            cover_path = generate_book_cover(book_dir, cfg, output.with_name(output.stem + "-cover.jpg"),
                                             writing_mode, warnings)
        except CoverError as e:
            raise BuildError(f"表紙を生成できません: {e}")
        log(f"表紙を生成しました: {cover_path.name}")
        cfg = {**cfg, "cover": str(cover_path)}

    meta = build_metadata(cfg, book_dir, writing_mode, warnings)
    optimize_images(book_dir, cfg, meta, out_dir, args, warnings)

    ver = pandoc_version(args.pandoc)

    css = [STYLES / "base.css", STYLES / f"{writing_mode}.css"]
    for extra in as_list(cfg.get("css")):
        p = book_dir / extra
        if not p.exists():
            raise BuildError(f"CSS が見つかりません: {p}")
        css.append(p)

    with tempfile.TemporaryDirectory() as tmp:
        meta_file = Path(tmp) / "metadata.yaml"
        # JSON は YAML としても有効。日本語をそのまま書き出す
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = pandoc_common_args(args.pandoc, ver, book_dir, layout) + [
            "--to", "epub3",
            "--metadata-file", str(meta_file),
            "--split-level", "1",
            "--epub-title-page=true",
            "-o", str(output),
        ]
        for c in css:
            cmd += ["--css", str(c)]
        for font in as_list(cfg.get("fonts")):
            cmd += ["--epub-embed-font", str(book_dir / font)]
        cmd += [str(c) for c in chapters]

        log(f"{book_dir.name}: {writing_mode} でビルドします（pandoc {'.'.join(map(str, ver))}）")
        if args.verbose:
            log(" ".join(cmd))
        result = subprocess.run(cmd, cwd=book_dir, capture_output=True, text=True)
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
            raise BuildError(f"pandoc が失敗しました（終了コード {result.returncode}）")

    cover_page = layout.get("cover_page", False)
    if not isinstance(cover_page, bool):
        raise BuildError(f"layout.cover_page は true か false です: {cover_page}")
    postprocess(output, writing_mode, cover_page=cover_page,
                accessibility=cfg.get("accessibility") or {}, warnings=warnings)
    for w in warnings:
        log("警告: " + w)
    log(f"出力: {output.relative_to(Path.cwd()) if output.is_relative_to(Path.cwd()) else output}")

    if args.check:
        run_epubcheck(output, args)
    return output


def pandoc_common_args(pandoc: str, ver: tuple[int, ...], book_dir: Path, layout: dict) -> list[str]:
    """EPUB とペーパーバックで共通の pandoc の引数（入力形式・目次・ハイライト・Lua フィルタ）。"""
    theme = layout.get("highlight_style") or str(STYLES / "kindle.theme")
    if theme.endswith(".theme") and not Path(theme).is_absolute():
        candidate = book_dir / theme
        theme = str(candidate if candidate.exists() else ROOT / theme)
    highlight_flag = "--syntax-highlighting" if ver >= (3, 8) else "--highlight-style"
    return [
        pandoc,
        "--from", "markdown+east_asian_line_breaks+ascii_identifiers+bracketed_spans+fenced_divs+footnotes+pipe_tables+grid_tables+implicit_figures+link_attributes",
        "--toc", "--toc-depth", str(layout.get("toc_depth", 2)),
        f"{highlight_flag}={theme}",
        "--resource-path", os.pathsep.join([str(book_dir), str(book_dir / "images")]),
        "--lua-filter", str(FILTERS / "images.lua"),
        "--lua-filter", str(FILTERS / "linebreaks.lua"),
        "--lua-filter", str(FILTERS / "crossref.lua"),
        "--lua-filter", str(FILTERS / "admonition.lua"),
        "--lua-filter", str(FILTERS / "ruby.lua"),
        "--lua-filter", str(FILTERS / "vertical.lua"),
    ]


def build_paperback(book_dir: Path, cfg: dict, chapters: list[Path], writing_mode: str, out_dir: Path,
                    args, warnings: list[str]) -> Path:
    """KDP ペーパーバック用の本文 PDF を作る（詳細は scripts/paperback.py）。"""
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import paperback

    pb = cfg.get("paperback") or {}
    out_name = (pb.get("output") if isinstance(pb, dict) else None) or f"{book_dir.name}-paperback.pdf"
    if args.writing_mode and not (isinstance(pb, dict) and pb.get("output")):
        out_name = f"{book_dir.name}-{writing_mode}-paperback.pdf"
    output = out_dir / out_name
    # 表紙は PDF に入れない（KDP では本文と表紙を別々の PDF でアップロードする）
    meta = build_metadata({k: v for k, v in cfg.items() if k != "cover"}, book_dir, writing_mode,
                          [])  # EPUB の表紙・識別子の警告は紙の本には関係ないので捨てる
    ver = pandoc_version(args.pandoc)
    log(f"{book_dir.name}: {writing_mode} でペーパーバック用 PDF を作ります（pandoc {'.'.join(map(str, ver))}）")
    try:
        paperback.build_paperback(book_dir, cfg, meta, chapters, writing_mode, output, args,
                                  pandoc_common_args(args.pandoc, ver, book_dir, cfg.get("layout") or {}), warnings)
    except paperback.PaperbackError as e:
        raise BuildError(str(e))
    for w in warnings:
        log("警告: " + w)
    log(f"出力: {output.relative_to(Path.cwd()) if output.is_relative_to(Path.cwd()) else output}")
    return output


def optimize_images(book_dir: Path, cfg: dict, meta: dict, out_dir: Path, args, warnings: list[str]) -> None:
    """原稿の画像を Kindle 向けに最適化し、pandoc がその版を使うよう meta を書き換える。"""
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import images

    images_cfg = cfg.get("images") or {}
    if args.no_optimize_images or (isinstance(images_cfg, dict) and images_cfg.get("optimize") is False):
        log("画像の最適化は無効です（元画像をそのまま使います）")
        warn_gps_images(book_dir, out_dir, warnings)
        return
    try:
        import PIL  # noqa: F401
    except ImportError:
        warnings.append("Pillow が無いため画像を最適化していません（pip install -r requirements.txt）")
        warn_gps_images(book_dir, out_dir, warnings)
        return

    cover = Path(meta["cover-image"]) if meta.get("cover-image") else None
    try:
        report = images.optimize_book_images(book_dir, cfg, out_dir / ".image-cache", cover)
    except ValueError as e:
        raise BuildError(str(e))
    if not report.results:
        return
    meta["kbt"]["images"] = report.mapping
    if report.cover:
        meta["cover-image"] = str(report.cover)
    log(f"画像の最適化（{len(report.results)} 枚）:")
    for line in images.format_report(report.results):
        log("  " + line)
    warnings.extend(report.warnings)


def warn_gps_images(book_dir: Path, out_dir: Path, warnings: list[str]) -> None:
    """最適化しない（メタデータを消さない）ときに、位置情報付きの写真があれば警告する。"""
    import images

    for rel in images.find_gps_images(book_dir, skip=[out_dir]):
        warnings.append(
            f"{rel} に撮影場所（GPS 位置情報）が入っています。このまま EPUB に入り、読者に配布されます。"
            "画像の最適化を有効にするか、画像編集ソフトで位置情報を削除してください"
        )


def postprocess(epub: Path, writing_mode: str, cover_page: bool = False,
                accessibility: dict | None = None, warnings: list[str] | None = None) -> None:
    """pandoc の出力 EPUB を Kindle 向けに微調整する。

    - OPF に primary-writing-mode を追加（Kindle Publishing Guidelines の日本語縦書きの指定方法）
    - nav の landmarks に bodymatter（本文の開始位置）を追加。
      Kindle はこれを「最初から読む」位置として使う（Kindle Publishing Guidelines の推奨）
    - HTML の表紙ページ（pandoc が作る cover.xhtml）を取り除く（cover_page が False のとき）。
      Kindle Publishing Guidelines は、表紙画像に加えて HTML の表紙ページを本文に入れないよう求めている
      （表紙が 2 回出る・変換に失敗することがある）。表紙画像（cover-image）はそのまま残す
    - アクセシビリティのメタデータ（EPUB Accessibility 1.1 / schema.org）を OPF に追加
    - mimetype をアーカイブ先頭に無圧縮で格納（EPUB OCF の要件）
    """
    pwm = "vertical-rl" if writing_mode == "vertical" else "horizontal-lr"
    if warnings is None:
        warnings = []
    with zipfile.ZipFile(epub) as zin:
        infos = zin.infolist()
        contents = {i.filename: zin.read(i.filename) for i in infos}

    opf_name = next(n for n in contents if n.endswith(".opf"))
    opf = contents[opf_name].decode("utf-8")
    opf_dir = posixpath.dirname(opf_name)

    removed: set[str] = set()
    if not cover_page:
        opf, cover_href = remove_cover_page(opf)
        if cover_href:
            removed.add(posixpath.normpath(posixpath.join(opf_dir, cover_href)))
            for name in list(contents):
                if name.endswith("nav.xhtml"):
                    contents[name] = remove_cover_landmark(contents[name].decode("utf-8")).encode("utf-8")

    # 本文の XHTML（表紙ページ・目次は除く。表紙画像は本文の画像として数えない）
    xhtml = [contents[n].decode("utf-8") for n in contents
             if n.endswith(".xhtml") and n not in removed and not n.endswith(("nav.xhtml", "/cover.xhtml"))]
    opf = add_accessibility_metadata(opf, xhtml, accessibility or {}, warnings)
    if "primary-writing-mode" not in opf:
        opf = opf.replace(
            "</metadata>",
            f'  <meta name="primary-writing-mode" content="{pwm}" />\n  </metadata>',
            1,
        )
    contents[opf_name] = opf.encode("utf-8")

    tmp = epub.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(zipfile.ZipInfo("mimetype"), contents["mimetype"], compress_type=zipfile.ZIP_STORED)
        for info in infos:
            name = info.filename
            if name == "mimetype" or name in removed:
                continue
            data = contents[name]
            if name.endswith("nav.xhtml"):
                data = add_bodymatter_landmark(data.decode("utf-8")).encode("utf-8")
            out = zipfile.ZipInfo(name, date_time=info.date_time)
            out.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(out, data)
    tmp.replace(epub)


def remove_cover_page(opf: str) -> tuple[str, str | None]:
    """OPF から HTML の表紙ページ（manifest・spine・guide）を取り除き、(新しい OPF, 表紙ページの href) を返す。

    表紙ページは、spine の先頭にあって表紙画像（properties="cover-image"）だけを表示するページ
    （pandoc では id="cover_xhtml"）。表紙画像の item と <meta name="cover"> は残す。
    """
    m = re.search(r'<item\b[^>]*\bid="cover_xhtml"[^>]*/>', opf)
    if not m:
        return opf, None
    href = re.search(r'\bhref="([^"]+)"', m.group(0)).group(1)
    opf = opf.replace(m.group(0), "", 1)
    opf = re.sub(r'[ \t]*<itemref\b[^>]*\bidref="cover_xhtml"[^>]*/>[ \t]*\n?', "", opf)
    opf = re.sub(r'[ \t]*<reference\b[^>]*\bhref="' + re.escape(href) + r'"[^>]*/>[ \t]*\n?', "", opf)
    # 中身が無くなった guide は消す（guide には reference が 1 つ以上必要）
    opf = re.sub(r'[ \t]*<guide>\s*</guide>[ \t]*\n?', "", opf)
    opf = re.sub(r'\n[ \t]*\n', "\n", opf)
    return opf, href


def remove_cover_landmark(nav: str) -> str:
    return re.sub(r'\s*<li>\s*<a [^>]*epub:type="cover"[^>]*>.*?</a>\s*</li>', "", nav, flags=re.S)


# アクセシビリティのメタデータ（book.yaml の accessibility で上書きできる）
A11Y_KEYS = {
    "access_modes": "schema:accessMode",
    "access_mode_sufficient": "schema:accessModeSufficient",
    "features": "schema:accessibilityFeature",
    "hazards": "schema:accessibilityHazard",
    "summary": "schema:accessibilitySummary",
    "conforms_to": "dcterms:conformsTo",
    "certified_by": "a11y:certifiedBy",
}


def add_accessibility_metadata(opf: str, xhtml: list[str], cfg: dict, warnings: list[str]) -> str:
    """EPUB Accessibility 1.1 のメタデータを OPF に加える。

    既定値は EPUB の中身から決める（画像があるか・代替テキストがあるか・ルビがあるか）。
    欧州アクセシビリティ法（EAA）の対象となる EU のストアでの販売で求められる情報。
    適合（dcterms:conformsTo）は自動では宣言しない（確認した人が book.yaml で指定する）。
    """
    if "schema:accessMode" in opf:
        return opf
    if not isinstance(cfg, dict):
        raise BuildError("book.yaml の accessibility は key: value の形式で書いてください")
    unknown = set(cfg) - set(A11Y_KEYS)
    if unknown:
        raise BuildError(f"accessibility に不明な設定があります: {', '.join(sorted(unknown))}")

    body = "\n".join(xhtml)
    imgs = re.findall(r"<img\b[^>]*>", body)
    no_alt = [i for i in imgs if not re.search(r'\balt="[^"]*\S[^"]*"', i)]
    has_visual = bool(imgs) or "<svg" in body
    if no_alt:
        warnings.append(
            f"代替テキスト（alt）の無い画像が {len(no_alt)} 枚あります。"
            "読み上げで内容が伝わるように、![説明](images/x.png) の形で説明を書いてください"
        )

    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if imgs and not no_alt:
        features.append("alternativeText")
    if "<ruby" in body:
        features.append("rubyAnnotations")

    values = {
        "access_modes": ["textual"] + (["visual"] if has_visual else []),
        "access_mode_sufficient": ["textual"] if not no_alt else ["textual,visual"],
        "features": features,
        "hazards": ["none"],
        "summary": [
            "目次と見出しによるナビゲーションを備えたリフロー型の電子書籍です。文字の大きさや書体は端末で変更できます。"
            + ("画像には代替テキストを付けています。" if imgs and not no_alt else "")
            + ("一部の画像には代替テキストがありません。" if no_alt else "")
        ],
        "conforms_to": [],
        "certified_by": [],
    }
    for key, value in cfg.items():
        values[key] = [str(v) for v in as_list(value)]

    lines = []
    for key, prop in A11Y_KEYS.items():
        for v in values[key]:
            lines.append(f'    <meta property="{prop}">{xml_escape(v.strip())}</meta>\n')
    return re.sub(r"([ \t]*)</metadata>", lambda m: "".join(lines) + m.group(1) + "</metadata>", opf, count=1)


def add_bodymatter_landmark(nav: str) -> str:
    if 'epub:type="bodymatter"' in nav:
        return nav
    # 目次の最初の項目（= 最初の章）を本文の開始位置とする
    m = re.search(r'<nav epub:type="toc".*?<a href="([^"#]+)', nav, re.S)
    if not m:
        return nav
    item = f'<li>\n      <a href="{m.group(1)}" epub:type="bodymatter">Start of Content</a>\n    </li>\n  '
    return re.sub(r'(<nav epub:type="landmarks"[^>]*>\s*<ol>\s*)', lambda mm: mm.group(1) + item, nav, count=1)


def run_epubcheck(epub: Path, args) -> None:
    """scripts/validate.py で検証する。警告以上（--fail-on で変更可）があれば失敗にする。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate

    try:
        cmd = validate.find_epubcheck(args.epubcheck_jar)
        ok, _ = validate.validate(epub, cmd, args.fail_on, Path(args.report_dir) if args.report_dir else None)
    except validate.ValidationError as e:
        raise BuildError(str(e))
    if not ok:
        raise BuildError(f"EPUBCheck で {args.fail_on} 以上のメッセージが見つかりました: {epub.name}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Markdown 原稿から KDP 用 EPUB3（--paperback でペーパーバック用 PDF）を生成します")
    parser.add_argument("books", nargs="*", help="本のディレクトリ（book.yaml がある場所）")
    parser.add_argument("--all", action="store_true", help="books/ 以下の全ての本をビルド")
    parser.add_argument("--writing-mode", choices=["vertical", "horizontal"], help="book.yaml の layout.writing_mode を一時的に上書き")
    parser.add_argument("-o", "--output-dir", default=str(ROOT / "dist"), help="出力ディレクトリ（既定: dist）")
    parser.add_argument("--check", action="store_true", help="ビルド後に EPUBCheck で検証（警告以上で失敗）")
    parser.add_argument("--fail-on", choices=["fatal", "error", "warning", "info", "usage"], default="warning",
                        help="--check で失敗にする重大度（既定: warning）")
    parser.add_argument("--report-dir", help="--check の JSON レポートを保存するディレクトリ")
    parser.add_argument("--epubcheck-jar", help="epubcheck.jar のパス（EPUBCHECK_JAR 環境変数でも可）")
    parser.add_argument("--no-optimize-images", action="store_true", help="画像を最適化せず元画像をそのまま使う")
    parser.add_argument("--paperback", action="store_true",
                        help="EPUB の代わりに KDP ペーパーバック用の本文 PDF を作る（判型などは book.yaml の paperback）")
    parser.add_argument("--browser", help="--paperback で使う Chrome / Chromium の実行ファイル（VIVLIOSTYLE_BROWSER 環境変数でも可）")
    parser.add_argument("--keep-html", action="store_true", help="--paperback の組版用 HTML を dist/.paperback/ に残す")
    parser.add_argument("--pandoc", default=os.environ.get("PANDOC", "pandoc"), help="pandoc の実行ファイル")
    parser.add_argument("-v", "--verbose", action="store_true", help="pandoc のコマンドラインを表示")
    args = parser.parse_args(argv)

    books = [Path(b) for b in args.books]
    if args.all:
        books += sorted(p.parent for p in (ROOT / "books").glob("*/book.yaml"))
    if not books:
        parser.print_help()
        return 2

    failed = 0
    for b in books:
        try:
            build_book(b, args)
        except BuildError as e:
            log(f"エラー（{b}）: {e}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
