"""リポジトリ直下の .venv（bash scripts/setup.sh が作る Python の仮想環境）を使って起動し直す。

python3 scripts/build.py のようにシステムの Python で起動しても、PyYAML・Pillow が入っている
.venv の Python で実行されるようにする（PEP 668 の環境では、システムの Python には pip で
パッケージを入れられないため、setup.sh は .venv に入れる）。

KBT_NO_VENV=1 を設定すると起動し直さない。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def venv_python(root: Path = ROOT) -> Path | None:
    for candidate in (root / ".venv" / "bin" / "python", root / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


def should_reexec(root: Path = ROOT, environ=os.environ, prefix: str = sys.prefix) -> Path | None:
    """起動し直すべきなら .venv の Python のパスを返す。"""
    if environ.get("KBT_NO_VENV"):
        return None
    py = venv_python(root)
    if py is None:
        return None
    venv_dir = (root / ".venv").resolve()
    if Path(prefix).resolve() == venv_dir:
        return None  # すでに .venv の Python で動いている
    return py


def reexec_in_venv(script: str) -> None:
    """.venv があり、まだその Python で動いていなければ、同じ引数で起動し直す（戻らない）。"""
    py = should_reexec()
    if py is None:
        return
    env = {**os.environ, "KBT_NO_VENV": "1"}  # 念のため、起動し直しを繰り返さない
    args = [str(py), str(Path(script).resolve()), *sys.argv[1:]]
    if os.name == "nt":
        import subprocess
        sys.exit(subprocess.run(args, env=env).returncode)
    os.execve(str(py), args, env)
