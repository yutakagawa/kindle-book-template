"""テストで共通に使う小さな道具。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def have_pandoc() -> bool:
    """scripts/build.py が使える pandoc（3.1 以上）があるか。"""
    exe = shutil.which("pandoc")
    if not exe:
        return False
    out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
    m = re.search(r"pandoc(?:\.exe)? (\d+)\.(\d+)", out)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (3, 1)


def solid_image(path: Path, color, size=(800, 600), fmt=None, **save_args) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, fmt, **save_args)
    return path


def gps_exif(model: str = "TestPhone 9"):
    """撮影場所（GPS）と機種名を入れた EXIF。"""
    from PIL import Image

    exif = Image.Exif()
    exif[0x0110] = model                     # Model
    gps = exif.get_ifd(0x8825)               # GPS IFD
    gps[1] = "N"                             # GPSLatitudeRef
    gps[2] = (35.0, 39.0, 29.0)              # GPSLatitude
    gps[3] = "E"                             # GPSLongitudeRef
    gps[4] = (139.0, 44.0, 28.0)             # GPSLongitude
    return exif


def write_book(book_dir: Path, yaml_text: str, chapters: dict[str, str]) -> Path:
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    (book_dir / "book.yaml").write_text(yaml_text, encoding="utf-8")
    for name, text in chapters.items():
        (book_dir / "chapters" / name).write_text(text, encoding="utf-8")
    return book_dir
