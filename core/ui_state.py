"""界面状态存取：全部写进资料库自己的 .db（meta 表）。

以前这些状态散落在注册表（QSettings）和 %APPDATA%/GuiZang/config.json 里，
导致「换台机器打开同一个 .db，界面状态就丢了」，也在系统里留下了一份影子数据。
现在统一进库：一个 .db 走到哪，界面状态跟到哪。

用法刻意做成 QSettings 的子集接口（value / setValue），调用点改动最小：

    st = DbState(db)
    st.setValue("splitter", [250, 1000, 320])
    sizes = st.value("splitter", [], list)
    on = st.value("attach_panel", False, type=bool)
"""

from __future__ import annotations

import base64
import sqlite3
import sys
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import QByteArray

META_PREFIX = "ui."
DEFAULT_NAME = "归藏.db"

_TRUE = {"1", "true", "True", "yes", "on"}
_FALSE = {"0", "false", "False", "no", "off", ""}


def app_dir() -> Path:
    """程序所在目录（打包后是 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def portable_db() -> Path:
    """便携库：程序目录下的 归藏.db。它的 meta 里顺便记住上次打开的库。"""
    return app_dir() / DEFAULT_NAME


def last_library() -> Optional[Path]:
    """上次打开的库路径（记在便携库里，因此系统里不留任何配置文件）。"""
    portable = portable_db()
    if not portable.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{portable}?mode=ro", uri=True, timeout=1.0)
        try:
            row = con.execute(
                "SELECT value FROM meta WHERE key = 'ui.last_library'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        path = Path(row[0]).expanduser()
    except (OSError, ValueError):
        return None
    return path if path.exists() else None


def remember_library(target: Path) -> None:
    """把「当前打开的是哪个库」写进便携库的 meta。

    便携库不存在（用户把 exe 放在只读目录）时就跳过——不额外造文件。
    """
    portable = portable_db()
    try:
        if not portable.exists() or portable.resolve() == Path(target).resolve():
            return
        con = sqlite3.connect(portable, timeout=2.0)
        try:
            con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, "
                        "value TEXT NOT NULL)")
            con.execute(
                "INSERT INTO meta(key, value) VALUES('ui.last_library', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(Path(target)),))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        pass


def _encode(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, QByteArray):
        return "b64:" + bytes(value.toBase64()).decode("ascii")
    if isinstance(value, (bytes, bytearray)):
        return "b64:" + base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple)):
        return ",".join(str(x) for x in value)
    return str(value)


class DbState:
    """把界面状态存进 Database 的 meta 表（键统一加 ui. 前缀）。"""

    def __init__(self, db) -> None:
        self.db = db

    # ---------------------------------------------------------- QSettings 子集
    def value(self, key: str, default: Any = None, type: Optional[type] = None) -> Any:
        raw = self._read(key)
        if raw is None:
            return default
        if type is bool:
            if raw in _TRUE:
                return True
            if raw in _FALSE:
                return False
            return bool(raw)
        if type is int:
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default
        if raw.startswith("b64:"):
            try:
                return QByteArray.fromBase64(raw[4:].encode("ascii"))
            except (ValueError, TypeError):
                return default
        if isinstance(default, (list, tuple)):
            try:
                return [int(x) for x in raw.split(",") if x.strip() != ""]
            except (TypeError, ValueError):
                return default
        return raw

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802 (对齐 QSettings)
        try:
            self.db.set_meta(META_PREFIX + key, _encode(value))
        except Exception:  # noqa: BLE001  库已关闭时静默忽略，别在退出流程里炸
            pass

    def remove(self, key: str) -> None:
        try:
            self.db.set_meta(META_PREFIX + key, "")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 内部
    def _read(self, key: str) -> Optional[str]:
        try:
            raw = self.db.get_meta(META_PREFIX + key, "")
        except Exception:  # noqa: BLE001
            return None
        return raw if raw != "" else None


def splitter_sizes(state: DbState, default: List[int]) -> List[int]:
    """读取分割器尺寸，数量不对就退回默认（列数变化后旧值会错位）。"""
    sizes = state.value("splitter", default, list)
    if isinstance(sizes, list) and len(sizes) == len(default) and all(s >= 0 for s in sizes):
        return sizes
    return default
