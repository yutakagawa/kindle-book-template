#!/usr/bin/env python3
"""EPUBCheck で EPUB を検証し、結果を見やすくまとめる。

使い方:
    python3 scripts/validate.py dist/*.epub                 # 検証（警告以上があれば終了コード 1）
    python3 scripts/validate.py dist/*.epub --fail-on error # エラー以上だけで失敗にする
    python3 scripts/validate.py dist/*.epub --report-dir dist/reports   # JSON レポートを保存

EPUBCheck 本体はそのままでは「警告」があっても終了コード 0 を返すため、
このスクリプトは JSON レポートを読み、指定した重大度以上のメッセージがあれば失敗にする。

EPUBCheck は次の順に探す:
    1. --epubcheck-jar / 環境変数 EPUBCHECK_JAR
    2. tools/epubcheck-*/epubcheck.jar（scripts/setup.sh が展開したもの）
    3. PATH 上の epubcheck コマンド（Homebrew など）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# EPUBCheck の重大度（重い順）
SEVERITIES = ("FATAL", "ERROR", "WARNING", "INFO", "USAGE")
FAIL_ON_CHOICES = ("fatal", "error", "warning", "info", "usage")


class ValidationError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[epubcheck] {msg}", file=sys.stderr)


def find_epubcheck(jar: str | None = None) -> list[str]:
    jar = jar or os.environ.get("EPUBCHECK_JAR")
    if jar:
        if not Path(jar).is_file():
            raise ValidationError(f"epubcheck.jar が見つかりません: {jar}")
        return [java_command(), "-jar", jar]
    local = sorted((ROOT / "tools").glob("epubcheck*/epubcheck.jar"), key=_version_key)
    if local:
        return [java_command(), "-jar", str(local[-1])]
    exe = shutil.which("epubcheck")
    if exe:
        return [exe]
    raise ValidationError(
        "EPUBCheck が見つかりません。bash scripts/setup.sh を実行するか、"
        "環境変数 EPUBCHECK_JAR に epubcheck.jar のパスを設定してください"
    )


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", path.parent.name)) or (0,)


def java_command() -> str:
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if candidate.exists():
            return str(candidate)
    java = shutil.which("java")
    if not java:
        raise ValidationError("Java が見つかりません。EPUBCheck には Java 11 以上が必要です（README の「セットアップ」参照）")
    return java


def run_epubcheck(epub: Path, cmd: list[str], report_dir: Path | None) -> dict:
    """EPUBCheck を実行して JSON レポートを返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        # -u: USAGE（非推奨の書き方など）まで報告させる。失敗にするかどうかは --fail-on で決める
        proc = subprocess.run(
            cmd + [str(epub), "-u", "--json", str(report)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if not report.exists():
            sys.stderr.write(proc.stdout + proc.stderr)
            raise ValidationError(f"EPUBCheck を実行できませんでした（終了コード {proc.returncode}）: {epub}")
        data = json.loads(report.read_text(encoding="utf-8"))
        if report_dir:
            report_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(report, report_dir / f"{epub.stem}.epubcheck.json")
    return data


def format_location(loc: dict, epub: Path) -> str:
    path = loc.get("path") or ""
    line, col = loc.get("line", -1), loc.get("column", -1)
    s = f"{epub.name}/{path}" if path else epub.name
    if line and line > 0:
        s += f"({line},{col})"
    return s


def validate(epub: Path, cmd: list[str], fail_on: str, report_dir: Path | None) -> tuple[bool, dict[str, int]]:
    if not epub.is_file():
        raise ValidationError(f"EPUB が見つかりません: {epub}")
    log(f"検証: {epub}")
    data = run_epubcheck(epub, cmd, report_dir)
    checker = data.get("checker", {})
    pub = data.get("publication", {})
    counts = {s: 0 for s in SEVERITIES}
    threshold = SEVERITIES.index(fail_on.upper())
    failed = False
    for msg in data.get("messages", []):
        sev = msg.get("severity", "ERROR")
        locations = msg.get("locations") or [{}]
        counts[sev] = counts.get(sev, 0) + len(locations)
        if sev in SEVERITIES and SEVERITIES.index(sev) <= threshold:
            failed = True
        text = msg.get("message", "")
        for loc in locations:
            print(f"  {sev}({msg.get('ID')}): {format_location(loc, epub)}: {text}")
        if msg.get("suggestion"):
            print(f"    → {msg['suggestion']}")
    summary = " / ".join(f"{counts[s]} {s.lower()}" for s in SEVERITIES)
    log(f"  EPUBCheck {checker.get('checkerVersion', '?')}・EPUB {pub.get('ePubVersion', '?')}: {summary}")
    if failed:
        log(f"  ✗ {fail_on} 以上のメッセージがあります")
    else:
        log("  ✓ 問題ありません")
    return not failed, counts


def write_github_summary(rows: list[tuple[Path, bool, dict[str, int]]]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["| EPUB | 結果 | " + " | ".join(s.lower() for s in SEVERITIES) + " |",
             "|:--|:--:|" + "--:|" * len(SEVERITIES)]
    for epub, ok, counts in rows:
        lines.append(f"| `{epub.name}` | {'✅' if ok else '❌'} | " + " | ".join(str(counts[s]) for s in SEVERITIES) + " |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("### EPUBCheck\n\n" + "\n".join(lines) + "\n\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EPUBCheck で EPUB を検証します")
    parser.add_argument("epubs", nargs="+", help="検証する EPUB ファイル")
    parser.add_argument("--fail-on", choices=FAIL_ON_CHOICES, default="warning",
                        help="この重大度以上のメッセージがあれば失敗にする（既定: warning）")
    parser.add_argument("--report-dir", help="EPUBCheck の JSON レポートを保存するディレクトリ")
    parser.add_argument("--epubcheck-jar", help="epubcheck.jar のパス（EPUBCHECK_JAR 環境変数でも可）")
    args = parser.parse_args(argv)

    try:
        cmd = find_epubcheck(args.epubcheck_jar)
    except ValidationError as e:
        log(f"エラー: {e}")
        return 2
    report_dir = Path(args.report_dir) if args.report_dir else None
    rows = []
    for e in args.epubs:
        epub = Path(e)
        try:
            ok, counts = validate(epub, cmd, args.fail_on, report_dir)
        except ValidationError as err:
            log(f"エラー: {err}")
            ok, counts = False, {s: 0 for s in SEVERITIES}
        rows.append((epub, ok, counts))
    write_github_summary(rows)
    bad = [r[0].name for r in rows if not r[1]]
    if bad:
        log(f"失敗: {', '.join(bad)}")
        return 1
    log(f"{len(rows)} 件すべて問題ありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
