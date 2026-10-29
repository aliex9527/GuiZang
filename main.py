"""归藏 · 个人资料库 —— 程序入口。

整个资料库就是一个 .db 文件。

用法：
    python main.py [--db <文件.db>]
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

DEFAULT_NAME = "归藏.db"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _normalize(raw: str | Path) -> Path:
    p = Path(raw).expanduser()
    if p.is_dir():
        return p / DEFAULT_NAME
    if p.suffix.lower() != ".db":
        return p.with_suffix(".db")
    return p


def resolve_db_file(argv: list[str]) -> Path:
    for i, arg in enumerate(argv):
        if arg in ("--db", "--data", "-d") and i + 1 < len(argv):
            return _normalize(argv[i + 1])
        if arg.startswith(("--db=", "--data=")):
            return _normalize(arg.split("=", 1)[1])

    env = os.environ.get("GUIZANG_DB")
    if env:
        return _normalize(env)

    # 「上次打开的库」记在便携库（程序目录下的 归藏.db）的 meta 里，
    # 因此系统里不再需要任何配置文件。
    from core.ui_state import last_library
    last = last_library()
    if last is not None:
        return _normalize(last)

    portable = app_root() / DEFAULT_NAME
    if _writable(app_root()) and not (portable.exists() and not os.access(portable, os.W_OK)):
        return portable

    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".local" / "share"
    folder = base / "GuiZang"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / DEFAULT_NAME


def migrate_legacy(target: Path) -> bool:
    """旧版本用 GuiZangData/ 目录存库，这里把它的数据搬成单文件。"""
    if target.exists():
        return False
    legacy = app_root() / "GuiZangData"
    old_db = legacy / "guizang.db"
    if not old_db.exists():
        return False
    from core.database import Database
    try:
        old = Database(old_db)          # 打开时会顺手把 files/ 收进 BLOB
        old.save_copy_to(target)
        old.close()
    except Exception:  # noqa: BLE001
        return False
    shutil.rmtree(legacy, ignore_errors=True)
    return True


def _explicit_db_arg(argv: list[str]) -> bool:
    """命令行/环境变量是否已经把库定死了（那就跳过首次欢迎框）。"""
    if os.environ.get("GUIZANG_DB"):
        return True
    for arg in argv:
        if arg in ("--db", "--data", "-d"):
            return True
        if arg.startswith(("--db=", "--data=")):
            return True
    return False


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from core.database import Database
    from core.storage import clear_cache
    from ui import style
    from ui.icons import app_icon
    from ui.main_window import MainWindow

    # 高分屏：不做整数倍取整，150% 的缩放比下字体仍按真实像素渲染，
    # 界面不会先按 100% 画完再被系统拉伸，截图文字才清晰。
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    QApplication.setApplicationName("GuiZang")
    QApplication.setOrganizationName("GuiZang")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui.fonts import UI_FONT_FAMILY
    app.setFont(QFont(UI_FONT_FAMILY, 9))

    clear_cache()

    from core.ui_state import is_first_run
    from PySide6.QtWidgets import QDialog

    # 顶层窗口一显示就把标题栏调成当前主题色，对话框不用逐个处理
    from ui import win_dark
    win_dark.install(app)

    if not _explicit_db_arg(sys.argv[1:]) and is_first_run():
        # 首次启动：硬盘上还没有任何库，先让用户选「创建」还是「打开」。
        # 这里得先把外观铺上——主题通常从库里读，此刻还没有库，用浅色打底。
        from ui import msgbox
        from ui.welcome import WelcomeDialog
        style.apply(app, "light")
        app.setWindowIcon(app_icon())
        db = None
        while db is None:
            dlg = WelcomeDialog()
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice is None:
                return 0                       # 关掉欢迎框 = 先不建库，直接退出
            target = dlg.choice
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                db = Database(target)
            except (OSError, sqlite3.Error) as exc:
                msgbox.error(None, "无法打开资料库", f"{target}\n\n{exc}")
    else:
        db_file = resolve_db_file(sys.argv[1:])
        db_file.parent.mkdir(parents=True, exist_ok=True)
        if db_file == app_root() / DEFAULT_NAME:
            migrate_legacy(db_file)
        db = Database(db_file)

    # 历史笔记存的是 HTML；这里一次性转成 Markdown 源码，此后库里只有 Markdown
    from ui.md_source import migrate_html_notes
    migrate_html_notes(db)
    # 主题跟着库走（存在 meta 里），不再读 %APPDATA%/GuiZang/config.json
    style.apply(app, db.get_meta("ui.theme", "light"))
    app.setWindowIcon(app_icon())

    window = MainWindow(db)
    window.show()
    code = app.exec()
    # 退出时再清一次：临时释放出来的附件文件不留痕
    clear_cache()
    return code


if __name__ == "__main__":
    sys.exit(main())
