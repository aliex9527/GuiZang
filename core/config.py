"""配置文件读写（记住上次打开的资料库）。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    folder = base / "GuiZang"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path.home() / ".guizang.json"
    return folder / "config.json"


def load() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    try:
        config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except OSError:
        pass


def last_db() -> Path | None:
    raw = load().get("db_file")
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.exists() else None


def saved_theme() -> str:
    name = load().get("theme", "light")
    return name if name in ("light", "dark") else "light"


def remember_theme(name: str) -> None:
    data = load()
    data["theme"] = name
    save(data)


def remember_db(path: Path) -> None:
    data = load()
    data["db_file"] = str(path)
    save(data)
