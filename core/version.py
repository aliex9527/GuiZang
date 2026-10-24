"""版本号读取。

唯一来源是仓库根的 VERSION 文件；打包时被塞进 exe（PyInstaller 解包到
_MEIPASS 目录下），开发运行时直接读仓库根的那个文件。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _candidates():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        yield Path(base) / "VERSION"
    yield Path(__file__).resolve().parent.parent / "VERSION"


def app_version() -> str:
    for path in _candidates():
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text.lstrip("vV")
    return "0.0.0"
