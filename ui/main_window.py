"""主窗口：多资料库标签页容器。

每个资料库是一个 DatabaseView（分类树 + 编辑器 + 附件），
这里用 QTabWidget 管理多个库，共享菜单栏和状态栏。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMessageBox,
                               QTabBar, QTabWidget, QWidget)

from core.database import Database
from core.ui_state import DbState, remember_library
from ui.database_view import DatabaseView
from ui.icons import app_icon


class MainWindow(QMainWindow):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        # 窗口几何同样存进当前库，不在注册表留痕
        self._db = db
        self.settings = DbState(db)
        self._views: list[DatabaseView] = []

        self.setWindowTitle("归藏 · 个人资料库")
        self.setWindowIcon(app_icon())
        self.resize(1360, 860)
        self.setMinimumSize(980, 620)

        self._build_ui()
        self._build_statusbar()

        # 打开首个资料库
        self._open_db(db)

        # 恢复窗口几何
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabBarAutoHide(False)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_view_at)
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)

        self.lbl_counts = QLabel("", sb)
        sb.addPermanentWidget(self.lbl_counts)

        self.lbl_mode = QLabel("", sb)
        sb.addPermanentWidget(self.lbl_mode)

        self.lbl_saved = QLabel("", sb)
        sb.addPermanentWidget(self.lbl_saved)

        self.lbl_db = QLabel("", sb)
        sb.addPermanentWidget(self.lbl_db)

    # ------------------------------------------------------------ 标签管理

    def _open_db(self, db: Database, select: bool = True) -> DatabaseView:
        view = DatabaseView(db, self.tabs)
        self._views.append(view)

        # 连接信号
        view.status_message.connect(self._on_status)
        view.close_requested.connect(lambda v=view: self._close_view(v))
        view.fullscreen_toggled.connect(self._toggle_fullscreen)
        view.title_changed.connect(self._on_title_changed)
        view.save_state_changed.connect(self._on_save_state)
        view.mode_changed.connect(self._on_mode_changed)
        view.counts_changed.connect(self._on_counts)
        view.db_label_changed.connect(self._on_db_label)
        view.open_library_requested.connect(self._open_library_file)
        view.new_library_requested.connect(self._new_library_file)

        remember_library(db.db_path)

        idx = self.tabs.addTab(view, db.db_path.name)
        self.tabs.setTabToolTip(idx, str(db.db_path))
        if select:
            self.tabs.setCurrentIndex(idx)

        # 立即同步该 view 的状态到状态栏（因为它可能不是当前活动标签）
        self._refresh_statusbar(view)
        return view

    def _current_view(self) -> Optional[DatabaseView]:
        idx = self.tabs.currentIndex()
        if 0 <= idx < len(self._views):
            return self._views[idx]
        return None

    def _on_tab_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._views):
            view = self._views[idx]
            self._rebuild_menus(view)
            self._refresh_statusbar(view)
            self._update_title(view)

    def _rebuild_menus(self, view: DatabaseView) -> None:
        mb = self.menuBar()
        mb.clear()
        view.build_menus(mb)

    def _refresh_statusbar(self, view: DatabaseView) -> None:
        s = view.db.stats()
        self.lbl_counts.setText(
            f"{s['nodes']} 条目 · {s['files']} 附件 · 库 "
            f"{self._human_size(s['db_bytes'])}")
        self.lbl_db.setText(
            f"库文件 · {view.db.db_path.name} · "
            f"{self._human_size(view.db.disk_size())}")
        self.lbl_db.setToolTip(str(view.db.db_path))
        if view.editor.is_dirty():
            self.lbl_saved.setText("有未保存的更改")
            self.lbl_saved.setStyleSheet("color:#b45309;")
        else:
            self.lbl_saved.setText("")
            self.lbl_saved.setStyleSheet("")
        self.lbl_mode.setText("源码模式" if view.editor.edit.md_rules else "")
        self._update_title(view)

    def _update_title(self, view: DatabaseView) -> None:
        self.setWindowTitle(f"{view.db.db_path.name} · 归藏")

    def _on_title_changed(self, _text: str) -> None:
        view = self.sender()
        if view is self._current_view():
            self._update_title(view)

    # ------------------------------------------------------------ 打开/新建

    def _open_library_file(self, path: Path) -> None:
        # 若已打开同路径库，直接切过去
        for i, v in enumerate(self._views):
            if str(v.db.db_path.resolve()) == str(path.resolve()):
                self.tabs.setCurrentIndex(i)
                return
        try:
            new_db = Database(path)
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "无法打开资料库", str(exc))
            return
        self._open_db(new_db)

    def _new_library_file(self, path: Path) -> None:
        try:
            new_db = Database(path)
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "无法创建资料库", str(exc))
            return
        self._open_db(new_db)

    def _close_view_at(self, idx: int) -> None:
        if 0 <= idx < len(self._views):
            self._close_view(self._views[idx])

    def _close_view(self, view: DatabaseView) -> None:
        if len(self._views) <= 1:
            # 至少保留一个标签；关闭最后一个等同退出
            self.close()
            return
        idx = self._views.index(view)
        view.close()
        self.tabs.removeTab(idx)
        self._views.pop(idx)

    # ------------------------------------------------------------ 状态栏回调

    def _on_status(self, msg: str, timeout: int) -> None:
        self.statusBar().showMessage(msg, timeout)

    def _on_save_state(self, dirty: bool) -> None:
        if self.sender() is not self._current_view():
            return
        if dirty:
            self.lbl_saved.setText("有未保存的更改")
            self.lbl_saved.setStyleSheet("color:#b45309;")
        else:
            self.lbl_saved.setText("")
            self.lbl_saved.setStyleSheet("")

    def _on_mode_changed(self, text: str) -> None:
        if self.sender() is not self._current_view():
            return
        self.lbl_mode.setText(text)

    def _on_counts(self, text: str) -> None:
        if self.sender() is not self._current_view():
            return
        self.lbl_counts.setText(text)

    def _on_db_label(self, text: str, path: str) -> None:
        self.lbl_db.setText(text)
        self.lbl_db.setToolTip(path)

    # ------------------------------------------------------------ 全屏/退出

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        view = self._current_view() or (self._views[0] if self._views else None)
        state = DbState(view.db) if view is not None else self.settings
        state.setValue("geometry", self.saveGeometry())
        for v in self._views:
            try:
                v.close()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)

    @staticmethod
    def _human_size(n: int) -> str:
        from core.storage import human_size
        return human_size(n)
