"""os_open.py — open a folder (or highlight a file) in the system file manager.

The backend runs on the user's own PC (desktop app), so this opens Explorer /
Finder / the Linux file manager on that machine.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _spawn(args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_folder(folder: Path) -> None:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(str(folder))
    if sys.platform.startswith("win"):
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        _spawn(["open", str(folder)])
    else:
        _spawn(["xdg-open", str(folder)])


def reveal_file(path: Path) -> None:
    """Open the containing folder with the file selected where the OS supports it."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if sys.platform.startswith("win"):
        _spawn(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        _spawn(["open", "-R", str(path)])
    else:
        _spawn(["xdg-open", str(path.parent)])
