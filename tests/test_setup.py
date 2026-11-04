"""scripts/setup.sh・Makefile・scripts/use_venv.py のテスト。

docs/review-2026-11.md の 3:
- PEP 668（externally-managed-environment）の Python では pip install --user が失敗し、set -e で途中で止まる
- 古い pandoc（Ubuntu 22.04 の 2.9 など）も「導入済み」と判定される
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

import use_venv

SETUP = ROOT / "scripts" / "setup.sh"
BASH = shutil.which("bash")


def run_setup_function(script: str, env: dict | None = None, path: str | None = None) -> subprocess.CompletedProcess:
    """setup.sh を source して（main は実行しない）、関数を呼ぶ。"""
    full_env = {**os.environ, **(env or {})}
    if path is not None:
        full_env["PATH"] = path
    return subprocess.run([BASH, "-c", f'source "{SETUP}"\n{script}'], capture_output=True, text=True,
                          env=full_env, timeout=600)


def write_stub(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    p.chmod(0o755)
    return p


def link_tools(directory: Path, *names: str) -> None:
    """限られた PATH を作るため、必要なコマンドだけをリンクする。"""
    directory.mkdir(parents=True, exist_ok=True)
    for n in names:
        target = shutil.which(n)
        if target:
            (directory / n).symlink_to(target)


@unittest.skipUnless(BASH, "bash が必要です")
class SetupScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_syntax(self):
        r = subprocess.run([BASH, "-n", str(SETUP)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_sourcing_does_not_run_main(self):
        r = run_setup_function("echo sourced-ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "sourced-ok")

    def test_version_ge(self):
        cases = [("3.1.3", "3.1", True), ("3.1", "3.1", True), ("3.9", "3.1", True), ("3.10", "3.9", True),
                 ("2.9.2.1", "3.1", False), ("3.0.1", "3.1", False), ("22.11.0", "22.12.0", False),
                 ("24.1.0", "22.12.0", True), ("v22.12.0", "22.12.0", True)]
        for a, b, expected in cases:
            r = run_setup_function(f'version_ge "{a}" "{b}" && echo yes || echo no')
            self.assertEqual(r.stdout.strip(), "yes" if expected else "no", f"{a} >= {b}")

    def test_pandoc_status_detects_old_pandoc(self):
        bin_dir = self.dir / "bin"
        link_tools(bin_dir, "grep", "head", "bash", "env")
        stubs = {
            "pandoc 2.9.2.1\nCompiled with pandoc-types 1.20": "old",   # Ubuntu 22.04 の apt
            "pandoc 3.0.1": "old",
            "pandoc 3.1.3\nFeatures: +server": "ok",
            "pandoc.exe 3.9\n": "ok",
        }
        for version_text, expected in stubs.items():
            write_stub(bin_dir, "pandoc", f"printf '%s\\n' '{version_text}'\n")
            r = run_setup_function("pandoc --version | head -1; pandoc_status", path=str(bin_dir))
            first, _, status = r.stdout.strip().rpartition("\n")
            self.assertEqual(first, version_text.splitlines()[0], r.stderr)  # スタブが動いていること
            self.assertEqual(status, expected, version_text)

    def test_pandoc_status_missing(self):
        bin_dir = self.dir / "bin"
        link_tools(bin_dir, "grep", "head")
        r = run_setup_function("pandoc_status", path=str(bin_dir))
        self.assertEqual(r.stdout.strip(), "missing")

    def test_python_deps_go_into_venv_even_when_system_pip_is_blocked(self):
        # システムの python3 は PEP 668 で pip install を拒否する（Ubuntu 24.04・Debian 12・Homebrew）
        real = sys.executable
        stub = write_stub(self.dir / "stub", "python3", f"""
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  echo "error: externally-managed-environment" >&2
  exit 1
fi
exec "{real}" "$@"
""")
        req = self.dir / "requirements.txt"
        req.write_text("# テストでは何も入れない（オフラインでも動くように）\n", encoding="utf-8")
        venv = self.dir / ".venv"
        r = run_setup_function(
            'install_python_deps; echo "status=$?"; echo "failed=${#FAILED[@]}"',
            env={"PYTHON": str(stub), "VENV": str(venv), "REQUIREMENTS": str(req), "ROOT": str(self.dir)},
        )
        self.assertIn("status=0", r.stdout, r.stderr)
        self.assertIn("failed=0", r.stdout, r.stderr)
        self.assertTrue((venv / "bin" / "python").exists() or (venv / "Scripts" / "python.exe").exists())
        self.assertNotIn("externally-managed-environment", r.stderr)

    def test_failure_does_not_stop_remaining_steps(self):
        # venv が作れない（Debian / Ubuntu で python3-venv が無い）ときも、後の手順に進む
        stub = write_stub(self.dir / "stub", "python3", 'echo "ensurepip is not available" >&2; exit 1\n')
        r = run_setup_function(
            'install_python_deps; echo "after-python"; echo "failed=${#FAILED[@]}"',
            env={"PYTHON": str(stub), "VENV": str(self.dir / ".venv"), "ROOT": str(self.dir)},
        )
        self.assertIn("after-python", r.stdout)
        self.assertIn("failed=1", r.stdout)
        self.assertIn("python3-venv", r.stderr)
        self.assertFalse((self.dir / ".venv").exists(), "作りかけの .venv を残さないこと")

    def test_main_reports_failures_and_exits_nonzero(self):
        r = run_setup_function(
            'install_pandoc() { fail "pandoc-failed"; }\n'
            'install_python_deps() { echo python-step; }\n'
            'install_epubcheck() { echo epubcheck-step; }\n'
            'check_java() { :; }\n'
            'install_npm() { echo npm-step; }\n'
            'main; echo "main=$?"'
        )
        self.assertIn("python-step", r.stdout)
        self.assertIn("epubcheck-step", r.stdout)
        self.assertIn("npm-step", r.stdout)
        self.assertIn("main=1", r.stdout)
        self.assertIn("pandoc-failed", r.stderr)

    def test_setup_does_not_use_pip_user(self):
        code = "\n".join(l for l in SETUP.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("--user", code)
        self.assertNotIn("set -e", code)

    def test_min_versions_match_project(self):
        import json
        import re

        import build

        text = SETUP.read_text(encoding="utf-8")
        self.assertIn(f'MIN_PANDOC="{".".join(map(str, build.MIN_PANDOC))}"', text)
        engines = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
        m = re.search(r'MIN_NODE="([^"]+)"', text)
        self.assertEqual(">=" + m.group(1), engines)


@unittest.skipUnless(shutil.which("make"), "make が必要です")
class MakefileTest(unittest.TestCase):
    def make_n(self, with_venv: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "Makefile", tmp)
            if with_venv:
                py = Path(tmp) / ".venv" / "bin" / "python"
                py.parent.mkdir(parents=True)
                py.write_text("")
            env = {k: v for k, v in os.environ.items() if k != "PYTHON"}
            return subprocess.run(["make", "-n", "build"], cwd=tmp, capture_output=True, text=True, env=env).stdout

    def test_uses_venv_python_when_present(self):
        self.assertIn(".venv/bin/python scripts/build.py --all", self.make_n(True))

    def test_falls_back_to_python3(self):
        self.assertIn("python3 scripts/build.py --all", self.make_n(False))


class UseVenvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_venv(self) -> Path:
        py = self.root / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("")
        return py

    def test_no_venv(self):
        self.assertIsNone(use_venv.should_reexec(self.root, {}, sys.prefix))

    def test_reexec_into_venv(self):
        py = self.make_venv()
        self.assertEqual(use_venv.should_reexec(self.root, {}, "/usr"), py)

    def test_already_in_venv(self):
        self.make_venv()
        self.assertIsNone(use_venv.should_reexec(self.root, {}, str(self.root / ".venv")))

    def test_disabled_by_env(self):
        self.make_venv()
        self.assertIsNone(use_venv.should_reexec(self.root, {"KBT_NO_VENV": "1"}, "/usr"))

    def test_build_runs_with_venv_python(self):
        # python3 scripts/build.py で起動しても .venv の Python で動く
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            shutil.copytree(ROOT / "scripts", fake_root / "scripts")
            venv = fake_root / ".venv"
            r = subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(venv)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                self.skipTest("venv を作れません: " + r.stderr)
            probe = fake_root / "scripts" / "probe.py"
            probe.write_text(
                "import sys\nfrom pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
                "from use_venv import reexec_in_venv\nreexec_in_venv(__file__)\nprint(sys.prefix)\n",
                encoding="utf-8",
            )
            env = {k: v for k, v in os.environ.items() if k != "KBT_NO_VENV"}
            out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env)
            self.assertEqual(Path(out.stdout.strip()).resolve(), venv.resolve(), out.stderr)


if __name__ == "__main__":
    unittest.main()
