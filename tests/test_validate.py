"""scripts/validate.py（EPUBCheck の結果判定）のテスト。

EPUBCheck の代わりに、決まった JSON レポートを書き出す偽のコマンドを使う。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import validate


def fake_epubcheck(tmp_path: Path, messages: list[dict], write_report: bool = True) -> list[str]:
    """EPUBCheck と同じ引数（<epub> -u --json <report>）を受け取り、レポートを書く偽コマンド。"""
    report = {
        "checker": {"checkerVersion": "9.9.9"},
        "publication": {"ePubVersion": "3.0"},
        "messages": messages,
    }
    script = tmp_path / "fake_epubcheck.py"
    script.write_text(
        "import json, sys\n"
        f"report = {json.dumps(report)!r}\n"
        "args = sys.argv[1:]\n"
        + ("open(args[args.index('--json') + 1], 'w', encoding='utf-8').write(report)\n" if write_report else
           "print('boom', file=sys.stderr); sys.exit(3)\n"),
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def msg(severity: str, mid: str = "RSC-005", locations=None, suggestion=None) -> dict:
    m = {"ID": mid, "severity": severity, "message": f"{severity} のメッセージ",
         "locations": locations if locations is not None else [{"path": "EPUB/text/ch001.xhtml", "line": 3, "column": 5}]}
    if suggestion:
        m["suggestion"] = suggestion
    return m


@pytest.fixture
def epub(tmp_path) -> Path:
    p = tmp_path / "book.epub"
    p.write_bytes(b"PK")
    return p


class TestValidate:
    def test_no_messages(self, tmp_path, epub):
        ok, counts = validate.validate(epub, fake_epubcheck(tmp_path, []), "warning", None)
        assert ok
        assert counts == {s: 0 for s in validate.SEVERITIES}

    @pytest.mark.parametrize("severity, fail_on, expect_ok", [
        ("WARNING", "warning", False),
        ("WARNING", "error", True),
        ("ERROR", "error", False),
        ("FATAL", "fatal", False),
        ("USAGE", "warning", True),
        ("USAGE", "usage", False),
        ("INFO", "info", False),
        ("INFO", "warning", True),
    ])
    def test_threshold(self, tmp_path, epub, severity, fail_on, expect_ok):
        ok, counts = validate.validate(epub, fake_epubcheck(tmp_path, [msg(severity)]), fail_on, None)
        assert ok is expect_ok
        assert counts[severity] == 1

    def test_counts_every_location(self, tmp_path, epub, capsys):
        locs = [{"path": "a.xhtml", "line": 1, "column": 2}, {"path": "b.xhtml", "line": -1, "column": -1}]
        _, counts = validate.validate(epub, fake_epubcheck(tmp_path, [msg("ERROR", locations=locs, suggestion="直す")]),
                                      "fatal", None)
        assert counts["ERROR"] == 2
        out = capsys.readouterr().out
        assert "ERROR(RSC-005): book.epub/a.xhtml(1,2)" in out
        assert "ERROR(RSC-005): book.epub/b.xhtml:" in out  # 行番号が無い位置は省く
        assert "→ 直す" in out

    def test_message_without_locations(self, tmp_path, epub):
        _, counts = validate.validate(epub, fake_epubcheck(tmp_path, [msg("WARNING", locations=[])]), "error", None)
        assert counts["WARNING"] == 1

    def test_saves_report(self, tmp_path, epub):
        report_dir = tmp_path / "reports"
        validate.validate(epub, fake_epubcheck(tmp_path, [msg("INFO")]), "warning", report_dir)
        saved = json.loads((report_dir / "book.epubcheck.json").read_text(encoding="utf-8"))
        assert saved["messages"][0]["severity"] == "INFO"

    def test_missing_epub(self, tmp_path):
        with pytest.raises(validate.ValidationError, match="見つかりません"):
            validate.validate(tmp_path / "none.epub", fake_epubcheck(tmp_path, []), "warning", None)

    def test_epubcheck_crash(self, tmp_path, epub):
        with pytest.raises(validate.ValidationError, match="実行できませんでした"):
            validate.validate(epub, fake_epubcheck(tmp_path, [], write_report=False), "warning", None)


def test_format_location(tmp_path):
    epub = tmp_path / "x.epub"
    assert validate.format_location({}, epub) == "x.epub"
    assert validate.format_location({"path": "a/b.xhtml", "line": 10, "column": 4}, epub) == "x.epub/a/b.xhtml(10,4)"
    assert validate.format_location({"path": "a.css", "line": 0}, epub) == "x.epub/a.css"


class TestFindEpubcheck:
    def test_explicit_jar(self, tmp_path, monkeypatch):
        jar = tmp_path / "epubcheck.jar"
        jar.write_bytes(b"")
        monkeypatch.setattr(validate, "java_command", lambda: "java")
        assert validate.find_epubcheck(str(jar)) == ["java", "-jar", str(jar)]

    def test_env_jar(self, tmp_path, monkeypatch):
        jar = tmp_path / "e.jar"
        jar.write_bytes(b"")
        monkeypatch.setenv("EPUBCHECK_JAR", str(jar))
        monkeypatch.setattr(validate, "java_command", lambda: "java")
        assert validate.find_epubcheck() == ["java", "-jar", str(jar)]

    def test_missing_jar(self, tmp_path):
        with pytest.raises(validate.ValidationError, match="epubcheck.jar"):
            validate.find_epubcheck(str(tmp_path / "none.jar"))

    def test_prefers_newest_local_tools(self, tmp_path, monkeypatch):
        for v in ("4.2.6", "5.3.0", "5.10.0"):
            d = tmp_path / "tools" / f"epubcheck-{v}"
            d.mkdir(parents=True)
            (d / "epubcheck.jar").write_bytes(b"")
        monkeypatch.delenv("EPUBCHECK_JAR", raising=False)
        monkeypatch.setattr(validate, "ROOT", tmp_path)
        monkeypatch.setattr(validate, "java_command", lambda: "java")
        assert validate.find_epubcheck()[-1].endswith("epubcheck-5.10.0/epubcheck.jar")

    def test_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EPUBCHECK_JAR", raising=False)
        monkeypatch.setattr(validate, "ROOT", tmp_path)
        monkeypatch.setattr(validate.shutil, "which", lambda name: None)
        with pytest.raises(validate.ValidationError, match="EPUBCheck が見つかりません"):
            validate.find_epubcheck()


def test_main_exit_codes_and_summary(tmp_path, epub, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(validate, "find_epubcheck", lambda jar=None: fake_epubcheck(tmp_path, [msg("WARNING")]))
    assert validate.main([str(epub), "--fail-on", "error"]) == 0
    assert validate.main([str(epub)]) == 1
    assert validate.main([str(tmp_path / "missing.epub"), "--fail-on", "error"]) == 1
    text = summary.read_text(encoding="utf-8")
    assert text.count("### EPUBCheck") == 3
    assert "| `book.epub` | ✅ | 0 | 0 | 1 | 0 | 0 |" in text
    assert "| `book.epub` | ❌ |" in text


def test_main_without_epubcheck(tmp_path, epub, monkeypatch):
    def missing(jar=None):
        raise validate.ValidationError("無い")
    monkeypatch.setattr(validate, "find_epubcheck", missing)
    assert validate.main([str(epub)]) == 2
