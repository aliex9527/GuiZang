"""主窗口：分类树 + 笔记编辑器 + 附件面板 + 全局搜索。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont,
                           QImage, QKeySequence, QPainter, QPainterPath, QPalette,
                           QPen, QShortcut, QTextListFormat)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QDialog,
                               QDialogButtonBox, QInputDialog, QMenu,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QProgressDialog,
                               QSizePolicy, QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QTextBrowser, QToolBar,
                               QToolButton, QToolTip, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import sqlite3

from core.database import Database
from core.ui_state import DbState, splitter_sizes
from core.storage import human_size
from ui.attachments import AttachmentPanel
from ui.icons import app_icon, file_icon, folder_icon, leaf_icon
from ui.note_editor import NoteEditor
from ui.markdown_render import md_to_html
from ui.search_panel import SearchPanel
from ui.theme import P

ROLE_ID = Qt.UserRole


class InstantToolButton(QToolButton):
    """鼠标一移入就立即显示提示，移出即隐藏，替代 Qt 默认约 700ms 的 tooltip 延迟。"""

    def enterEvent(self, event):
        tip = self.toolTip()
        if tip:
            pos = self.mapToGlobal(QPoint(self.width() // 2, self.height() + 4))
            QToolTip.showText(pos, tip, self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class CategoryItemDelegate(QStyledItemDelegate):
    """选中时只给条目内容区刷蓝条，前面的缩进/虚线区留白（照 myBase 的样子）。

    delegate 拿到的 ``option.rect`` 是**内容区**（缩进之后到视口右边缘），
    而 Qt 画的行底色是整行 —— 所以选中行要先把缩进区刷回面板色、把虚线
    补画一遍，再给内容区上蓝条。
    """

    def __init__(self, tree: "CategoryTree"):
        super().__init__(tree)
        self._tree = tree

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or hovered:
            painter.save()
            if selected:
                gutter = QRect(0, option.rect.top(), option.rect.left(),
                               option.rect.height())
                painter.fillRect(gutter, QColor(P["panel"]))
                self._tree.paint_branch_lines(painter, gutter, index)
            painter.fillRect(option.rect,
                             QColor(P["select_bg"] if selected else P["row_hover"]))
            painter.restore()
        super().paint(painter, option, index)


class CategoryTree(QTreeWidget):
    """myBase 风格的分类树：层级虚线 + 整行实心蓝条 + 展开三角。"""

    structureChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(CategoryItemDelegate(self))
        # delegate 要靠 State_MouseOver 画悬停底，得让 viewport 报鼠标位置
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)

    def dropEvent(self, event):  # noqa: N802
        super().dropEvent(event)
        self.structureChanged.emit()

    def drawBranches(self, painter, rect, index):  # noqa: N802
        """Qt 的 branch 钩子：只画线，不画任何底色。"""
        self.paint_branch_lines(painter, rect, index)

    def paint_branch_lines(self, painter, rect, index) -> None:
        """在 ``rect``（缩进区）里画层级点线和展开三角。

        Qt 默认的 branch 绘制会被样式表接管成"一块实心色"，这里整段接管：
        层级用竖直点线串起来，末级画 └ 拐到条目。选中行的缩进区由 delegate
        刷白后回调本方法补线，所以这里不碰任何填充色。
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        model = self.model()

        chain = [index]
        parent = index.parent()
        while parent.isValid():
            chain.insert(0, parent)
            parent = parent.parent()
        depth = len(chain) - 1

        ind = self.indentation()
        mid = ind // 2
        mid_y = rect.top() + rect.height() // 2
        line = QColor(P["branch"])
        painter.setPen(QPen(line, 1, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for lv in range(depth):
            x = rect.left() + lv * ind + mid
            node = chain[lv]
            if model.rowCount(node.parent()) > node.row() + 1:
                # 这一层后面还有兄弟，竖线贯穿整行
                painter.drawLine(x, rect.top(), x, rect.bottom())
            if lv == depth - 1:
                painter.drawLine(x, rect.top(), x, mid_y)
                painter.drawLine(x, mid_y, x + mid, mid_y)

        if model.rowCount(index) > 0:
            cx = rect.left() + depth * ind + mid
            cy = mid_y
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(line)
            arrow = QPainterPath()
            if self.isExpanded(index):
                arrow.moveTo(cx - 3.5, cy - 2.0)
                arrow.lineTo(cx + 3.5, cy - 2.0)
                arrow.lineTo(cx, cy + 2.5)
            else:
                arrow.moveTo(cx - 2.0, cy - 3.5)
                arrow.lineTo(cx - 2.0, cy + 3.5)
                arrow.lineTo(cx + 2.5, cy)
            arrow.closeSubpath()
            painter.drawPath(arrow)

        painter.restore()


class DatabaseView(QWidget):
    # 与宿主(MainWindow)通信的信号
    status_message = Signal(str, int)      # 临时状态栏消息
    close_requested = Signal()             # 请求关闭本标签
    fullscreen_toggled = Signal()          # 请求切换全屏
    title_changed = Signal(str)            # 窗口标题变化（库名）
    save_state_changed = Signal(bool)      # 保存状态
    mode_changed = Signal(str)             # 模式（源码/即时渲染）
    counts_changed = Signal(str)           # 条目/附件统计文本
    db_label_changed = Signal(str, str)    # (库文件显示文本, 完整路径)
    open_library_requested = Signal(Path)  # 请求打开指定库文件（新标签）
    new_library_requested = Signal(Path)   # 请求新建库文件（新标签）

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._items: Dict[int, QTreeWidgetItem] = {}
        self._current_id: Optional[int] = None
        self._loading_tree = False
        self._syncing_item = False

        # 界面状态存进库本身，不再写注册表
        self.settings = DbState(db)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._run_search)

        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(400)
        self._title_timer.timeout.connect(self._commit_title)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._image_size_cache: dict = {}
        self._build_ui()
        self._build_shortcuts()
        self.editor.edit.cursorPositionChanged.connect(self._sync_para_action)
        self.editor.edit.textChanged.connect(self._sync_para_action)
        self._reload_tree()
        self._restore_state()
        self._update_counts()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左：分类栏；右侧：正文在上、附件在下（附件栏宽度只跟正文区对齐）
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self._build_side())

        self.vsplitter = QSplitter(Qt.Vertical, self)
        self.vsplitter.setChildrenCollapsible(False)
        self.vsplitter.setHandleWidth(1)
        self.vsplitter.addWidget(self._build_editor())
        self.vsplitter.addWidget(self._build_attachments())
        self.vsplitter.setSizes([680, 220])
        self.vsplitter.setStretchFactor(0, 1)

        self.splitter.addWidget(self.vsplitter)
        self.splitter.setSizes([250, 1010])
        self.splitter.setStretchFactor(1, 1)
        self.attachments.setVisible(False)
        outer.addWidget(self.splitter, 1)

        self._set_save_state(False)

    def _build_side(self) -> QWidget:
        wrap = QWidget(self)
        wrap.setObjectName("SidePanel")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        wrap.setMinimumWidth(200)
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_icon_strip(wrap))

        self.search_box = QLineEdit(wrap)
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索标题、正文、附件…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_text)
        search_wrap = QWidget(wrap)
        sl = QVBoxLayout(search_wrap)
        sl.setContentsMargins(8, 4, 8, 8)
        sl.addWidget(self.search_box)
        lay.addWidget(search_wrap)

        self.side_stack = QStackedWidget(wrap)

        self.tree = CategoryTree(wrap)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(15)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(lambda i: self._on_expanded(i, True))
        self.tree.itemCollapsed.connect(lambda i: self._on_expanded(i, False))
        self.tree.structureChanged.connect(self._persist_tree)
        self._sync_tree_palette()

        self.search_panel = SearchPanel(wrap)
        self.search_panel.nodeActivated.connect(self._goto_search_result)

        self.side_stack.addWidget(self.tree)
        self.side_stack.addWidget(self.search_panel)
        lay.addWidget(self.side_stack, 1)
        return wrap

    def _sync_tree_palette(self) -> None:
        """让树的原生绘制（拖放指示、焦点框）也用上我们的选中配色。"""
        pal = self.tree.palette()
        select_bg = QColor(P["select_bg"])
        select_fg = QColor(P["select_fg"])
        for group in (QPalette.Active, QPalette.Inactive):
            pal.setColor(group, QPalette.Highlight, select_bg)
            pal.setColor(group, QPalette.HighlightedText, select_fg)
            pal.setColor(group, QPalette.Base, QColor(P["panel"]))
            pal.setColor(group, QPalette.Window, QColor(P["panel"]))
        self.tree.setPalette(pal)

    def _build_icon_strip(self, parent: QWidget) -> QWidget:
        """侧栏顶部那一排图标：对齐 myBase 大纲工具条的按钮组合。"""
        strip = QWidget(parent)
        strip.setObjectName("IconStrip")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(strip)
        hl.setContentsMargins(5, 5, 5, 3)
        hl.setSpacing(1)

        self._icon_buttons = []

        def add(name, tip, slot=None, sep=False, menu=None):
            if sep:
                line = QWidget(strip)
                line.setFixedWidth(1)
                line.setFixedHeight(16)
                line.setStyleSheet(f"background:{P['border']}; margin:0 4px;")
                hl.addWidget(line)
            b = InstantToolButton(strip)
            b.setObjectName("IconBtn")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(26, 26)
            b.setIconSize(QSize(17, 17))
            if menu is not None:
                b.setMenu(menu)
                b.setPopupMode(QToolButton.InstantPopup)
            elif slot is not None:
                b.clicked.connect(slot)
            hl.addWidget(b)
            self._icon_buttons.append((b, name))
            return b

        # 照 myBase 大纲工具条：关联 | 新建子项 | 前插入 | 后插入 | 上移 | 下移
        rel_menu = QMenu(strip)
        rel_menu.addAction("收藏 / 取消收藏\tCtrl+D", self.toggle_star)
        rel_menu.addSeparator()
        sort_menu = QMenu("排序子条目", rel_menu)
        sort_menu.addAction("按名称 A → Z", lambda: self.sort_nodes("title", False))
        sort_menu.addAction("按名称 Z → A", lambda: self.sort_nodes("title", True))
        sort_menu.addSeparator()
        sort_menu.addAction("按修改时间（新→旧）", lambda: self.sort_nodes("updated"))
        sort_menu.addAction("按创建时间（新→旧）", lambda: self.sort_nodes("created"))
        rel_menu.addMenu(sort_menu)
        rel_menu.addAction("移到顶层", self.move_to_top)
        rel_menu.addSeparator()
        rel_menu.addAction("删除当前条目", self._delete_current)
        add("relation", "条目操作", menu=rel_menu)

        add("new_child", "新建子条目 (Ctrl+Alt+N)", lambda: self.new_node(True), sep=True)
        add("new_before", "在前面新建同级 (Ctrl+Shift+N)", lambda: self.new_node(False, before=True))
        add("new_after", "在后面新建同级 (Ctrl+N)", lambda: self.new_node(False))
        add("move_up", "上移 (Ctrl+Alt+↑)", lambda: self.move_item(-1), sep=True)
        add("move_down", "下移 (Ctrl+Alt+↓)", lambda: self.move_item(1))

        hl.addStretch(1)
        self._apply_icon_theme()
        return strip

    def _apply_icon_theme(self) -> None:
        from ui.icons import svg_icon
        color = P["muted"]
        starred = bool(self._current_id and self.db.is_starred(self._current_id))
        for btn, name in getattr(self, "_icon_buttons", []):
            icon_name = "star_on" if (name == "star" and starred) else name
            btn.setIcon(svg_icon(icon_name, color=color))

    def toggle_star(self) -> None:
        if self._current_id is None:
            self.status_message.emit("先选一个条目", 2500)
            return
        on = not self.db.is_starred(self._current_id)
        self.db.set_starred(self._current_id, on)
        item = self._items.get(self._current_id)
        if item is not None:
            item.setData(0, Qt.UserRole + 1, on)
        self._refresh_icons()
        self._apply_icon_theme()
        self.status_message.emit("已收藏" if on else "已取消收藏", 2500)

    def move_to_top(self) -> None:
        if self._current_id is None:
            return
        self.db.promote_to_top(self._current_id)
        self._reload_tree(select_id=self._current_id)
        self.status_message.emit("已移到顶层", 2000)

    def expand_branch(self, on: bool) -> None:
        if self._current_id is None:
            return
        item = self._items.get(self._current_id)
        if item is None:
            return
        item.setExpanded(on)
        self._set_subtree_expanded(item, on)

    def _set_subtree_expanded(self, item, on: bool) -> None:
        for i in range(item.childCount()):
            ch = item.child(i)
            ch.setExpanded(on)
            self._set_subtree_expanded(ch, on)

    def expand_to_level(self, level: int) -> None:
        for item in self._items.values():
            item.setExpanded(self._depth_of(item) < level - 1)

    def _depth_of(self, item) -> int:
        d = 0
        p = item.parent()
        while p is not None:
            d += 1
            p = p.parent()
        return d

    def auto_number(self) -> None:
        if self._current_id is None:
            self.status_message.emit("先选一个条目", 2500)
            return
        n = self.db.auto_number(self._current_id)
        self._reload_tree(select_id=self._current_id)
        self.status_message.emit(f"已为 {n} 个子条目编号", 3000)

    def duplicate_branch(self) -> None:
        if self._current_id is None:
            return
        new_id = self.db.duplicate_branch(self._current_id)
        if new_id:
            self._reload_tree(select_id=new_id)
            self._update_counts()
            self.status_message.emit("已复制条目（含子分枝与附件）", 3000)

    def show_node_stats(self) -> None:
        if self._current_id is None:
            return
        st = self.db.node_stats(self._current_id)
        if not st:
            return
        QMessageBox.information(
            self, "条目统计",
            f"名称：{st['title']}\n路径：{st['path']}\n\n"
            f"子条目：{st['children']}\n附件：{st['files']}（{human_size(st['bytes'])}）\n"
            f"正文字数：{st['chars']}\n\n"
            f"创建：{st['created']}\n修改：{st['updated']}")

    def move_item(self, delta: int) -> None:
        if self._current_id is None:
            return
        if self.db.move_sibling(self._current_id, delta):
            self._reload_tree(select_id=self._current_id)
            self.status_message.emit("已上移" if delta < 0 else "已下移", 2000)

    def sort_nodes(self, key: str, reverse: bool = False) -> None:
        parent_id = None
        if self._current_id is not None:
            row = self.db.get_node(self._current_id)
            parent_id = row["parent_id"] if row else None
        self.db.reorder_siblings(parent_id, key, reverse)
        self._reload_tree(select_id=self._current_id)
        self.status_message.emit("已重新排序", 2500)

    # ---------------------------------------------------------------- 导航

    _nav: list = []
    _nav_pos: int = -1
    _nav_busy = False

    def _push_nav(self, node_id: int) -> None:
        if self._nav_busy or node_id is None:
            return
        if 0 <= self._nav_pos < len(self._nav) and self._nav[self._nav_pos] == node_id:
            return
        self._nav = self._nav[:self._nav_pos + 1]
        self._nav.append(node_id)
        if len(self._nav) > 60:
            self._nav.pop(0)
        self._nav_pos = len(self._nav) - 1
        self._update_nav_buttons()

    def _nav_go(self, delta: int) -> None:
        pos = self._nav_pos + delta
        if not (0 <= pos < len(self._nav)):
            return
        self._nav_pos = pos
        self._nav_busy = True
        try:
            self._select_node(self._nav[pos])
        finally:
            self._nav_busy = False
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        # 侧栏已移除后退/前进按钮，这里仅在有对应按钮时更新（保留导航历史栈能力）
        back = getattr(self, "btn_back", None)
        forward = getattr(self, "btn_forward", None)
        if back is not None:
            back.setEnabled(self._nav_pos > 0)
        if forward is not None:
            forward.setEnabled(self._nav_pos < len(self._nav) - 1)

    def _filter_by_tag(self, tag: str) -> None:
        self.search_box.setText(tag)

    def _build_editor(self) -> QWidget:
        wrap = QWidget(self)
        wrap.setObjectName("EditorPanel")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget(wrap)
        head.setObjectName("EditorHeader")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(24, 14, 16, 12)
        hl.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.title_edit = QLineEdit(head)
        self.title_edit.setObjectName("TitleEdit")
        self.title_edit.setPlaceholderText("未命名")
        self.title_edit.textChanged.connect(lambda _t: self._title_timer.start())
        self.title_edit.editingFinished.connect(self._commit_title)
        row1.addWidget(self.title_edit, 1)

        self.path_label = QLabel("", head)
        self.path_label.setObjectName("PathLabel")
        row1.addWidget(self.path_label)

        hl.addLayout(row1)
        lay.addWidget(head)

        self.editor = NoteEditor(self._save_image, lambda fid: self.db.blob_bytes(fid), wrap)
        self.editor.edit.file_sink = self._attach_paths
        self.editor.saveRequested.connect(self._save_note)
        self.editor.edit.linkActivated.connect(self._open_link)
        self.editor.edit.image_size = self._image_size
        self.editor.edit.imageActivated.connect(self._open_image)
        self.editor.edit.imageRemoved.connect(self._drop_removed_image)
        self.editor.dirtyChanged.connect(self._set_save_state)
        lay.addWidget(self.editor, 1)

        self.empty_hint = QLabel(
            "左边选一个条目，或按 Ctrl+N 新建一个\n\n"
            "· 任意格式的文件都可以拖进右侧附件区\n"
            "· 顶部搜索框可以搜正文和附件名", wrap)
        self.empty_hint.setObjectName("EmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.hide()
        lay.addWidget(self.empty_hint)
        return wrap

    def _build_attachments(self) -> QWidget:
        self.attachments = AttachmentPanel(self.db, self)
        self.attachments.changed.connect(self._update_counts)
        self.attachments.status.connect(lambda m: self.status_message.emit(m, 4000))
        self.attachments.setMinimumHeight(96)
        return self.attachments

    def _set_db_label(self, size: Optional[int] = None) -> None:
        p = self.db.db_path
        if size is None:
            size = self.db.disk_size()
        self.db_label_changed.emit(
            f"库文件 · {p.name} · {human_size(size)}", str(p))

    def _build_shortcuts(self) -> None:
        for keys, slot in (
            ("Delete", self._delete_current),
            ("F2", self._rename_current),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)

    def build_menus(self, mb) -> None:
        """菜单与快捷键对齐 Typora（Windows 版）。"""
        mb.setNativeMenuBar(False)
        ed = self.editor

        # ---- 文件
        m = mb.addMenu("文件(&F)")
        m.addAction("新建子条目\tCtrl+Alt+N", lambda: self.new_node(True))
        m.addAction("新建同级（后）\tCtrl+N", lambda: self.new_node(False))
        m.addAction("新建同级（前）\tCtrl+Shift+N",
                    lambda: self.new_node(False, before=True))
        m.addSeparator()
        m.addAction("打开资料库…\tCtrl+O", self.open_library)
        m.addAction("快速打开…\tCtrl+P", self._focus_search)
        m.addAction("新建资料库…", self.new_library)
        m.addSeparator()
        m.addAction("保存\tCtrl+S", self.save_now)
        m.addAction("备份资料库到文件…\tCtrl+Shift+S", self.backup)
        m.addAction("精简数据库（压缩并整理）", self.compact_db)
        m.addAction("在资源管理器中显示库文件", self.reveal_db)
        m.addSeparator()
        m.addAction("导出此条目…", lambda: self.export_node(self._current_id)
                    if self._current_id else None)
        m.addAction("添加附件…\tCtrl+Shift+A", self.pick_attachments)
        m.addAction("导入文件夹为分类…", self.import_folder)
        m.addSeparator()
        m.addAction("退出\tCtrl+Q", self.close_requested.emit)

        # ---- 编辑
        m = mb.addMenu("编辑(&E)")
        m.addAction("撤销\tCtrl+Z", ed.edit.undo)
        m.addAction("重做\tCtrl+Y", ed.edit.redo)
        m.addSeparator()
        m.addAction("剪切\tCtrl+X", ed.edit.cut)
        m.addAction("复制\tCtrl+C", ed.edit.copy)
        m.addAction("粘贴\tCtrl+V", ed.edit.paste)
        m.addAction("复制为 Markdown\tCtrl+Shift+C", ed.copy_as_markdown)
        m.addAction("粘贴为纯文本\tCtrl+Shift+V", ed.paste_plain)
        m.addSeparator()
        m.addAction("全选\tCtrl+A", ed.edit.selectAll)
        m.addSeparator()
        m.addAction("查找…\tCtrl+F", lambda: self.show_find(False))
        m.addAction("替换…\tCtrl+H", lambda: self.show_find(True))
        m.addSeparator()
        m.addAction("重命名条目\tF2", self._rename_current)
        m.addAction("删除条目", self._delete_current)

        # ---- 整理（对齐 myBase 的「整理」菜单）
        m = mb.addMenu("整理(&R)")
        m.addAction("添加子项\tCtrl+Alt+N", lambda: self.new_node(True))
        m.addAction("添加项（前面）\tCtrl+Shift+N",
                    lambda: self.new_node(False, before=True))
        m.addAction("添加项（后面）\tCtrl+N", lambda: self.new_node(False))
        m.addSeparator()
        m.addAction("收藏 / 取消收藏\tCtrl+D", self.toggle_star)
        m_move = m.addMenu("移动")
        m_move.addAction("上移\tCtrl+Alt+↑", lambda: self.move_item(-1))
        m_move.addAction("下移\tCtrl+Alt+↓", lambda: self.move_item(1))
        m_move.addAction("移到顶层", self.move_to_top)
        m_sort = m.addMenu("排序子项")
        m_sort.addAction("按名称 A → Z", lambda: self.sort_nodes("title", False))
        m_sort.addAction("按名称 Z → A", lambda: self.sort_nodes("title", True))
        m_sort.addAction("按修改时间（新→旧）", lambda: self.sort_nodes("updated"))
        m_sort.addAction("按创建时间（新→旧）", lambda: self.sort_nodes("created"))
        m_exp = m.addMenu("展开/折叠分枝")
        m_exp.addAction("展开此分枝", lambda: self.expand_branch(True))
        m_exp.addAction("折叠此分枝", lambda: self.expand_branch(False))
        m_exp.addSeparator()
        m_exp.addAction("全部展开", self._expand_all)
        m_exp.addAction("全部折叠", self._collapse_all)
        m_lv = m.addMenu("展开到指定层级")
        for lv in range(1, 6):
            m_lv.addAction(f"第 {lv} 层", lambda _c=False, n=lv: self.expand_to_level(n))
        m.addSeparator()
        m.addAction("自动编号…", self.auto_number)
        m.addAction("复制条目（分枝）", self.duplicate_branch)
        m.addSeparator()
        m.addAction("显示条目统计…", self.show_node_stats)

        # ---- 段落
        m = mb.addMenu("段落(&P)")
        names = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
        for lv in range(1, 7):
            m.addAction(f"{names[lv]}级标题\tCtrl+{lv}",
                        lambda _c=False, n=lv: ed.set_heading(n))
        m.addSeparator()
        self.act_para = m.addAction("段落\tCtrl+0", lambda: ed.set_heading(0))
        self.act_para.setCheckable(True)
        self.act_para.setChecked(True)
        m.addSeparator()
        m.addAction("提升标题级别\tCtrl+=", lambda: ed.change_heading_level(-1))
        m.addAction("降低标题级别\tCtrl+-", lambda: ed.change_heading_level(1))
        m.addSeparator()
        m.addAction("表格\tCtrl+T", self.insert_table)
        m.addAction("代码块\tCtrl+Shift+K", ed.insert_code_block)
        m.addAction("引用\tCtrl+Shift+Q", ed.toggle_quote)
        m.addSeparator()
        m.addAction("有序列表\tCtrl+Shift+[",
                    lambda: ed.toggle_list(QTextListFormat.ListDecimal))
        m.addAction("无序列表\tCtrl+Shift+]",
                    lambda: ed.toggle_list(QTextListFormat.ListDisc))
        m.addAction("任务列表\tCtrl+Shift+X", ed.toggle_task)
        m.addAction("切换任务状态\tCtrl+Shift+Enter", ed.toggle_task_state)
        m.addSeparator()
        m.addAction("增加缩进\tCtrl+]", lambda: ed.edit._indent_block(1))
        m.addAction("减少缩进\tCtrl+[", lambda: ed.edit._indent_block(-1))
        m.addSeparator()
        m.addAction("在上方插入段落\tCtrl+Shift+Up", lambda: ed.insert_paragraph(True))
        m.addAction("在下方插入段落\tCtrl+Shift+Down", lambda: ed.insert_paragraph(False))
        m.addSeparator()
        m.addAction("水平分割线\tCtrl+Shift+-", ed.insert_hr)

        # ---- 格式（只保留 Markdown 有对应语法的项）
        m = mb.addMenu("格式(&O)")
        m.addAction("加粗\tCtrl+B", ed.toggle_bold)
        m.addAction("斜体\tCtrl+I", ed.toggle_italic)
        m.addAction("删除线\tAlt+Shift+5", ed.toggle_strike)
        m.addAction("行内代码\tCtrl+Shift+`", ed.toggle_inline_code)
        m.addSeparator()
        m.addAction("高亮\tCtrl+Shift+H", ed.toggle_highlight)
        m.addAction("超链接\tCtrl+K", ed.insert_link)
        m.addAction("图像\tCtrl+Shift+I", ed.insert_image)
        m.addSeparator()
        m.addAction("清除格式\tCtrl+\\", ed.clear_format)

        # ---- 视图
        m = mb.addMenu("视图(&V)")
        self.act_source = m.addAction("源码模式\tCtrl+/", self.toggle_source_mode)
        self.act_source.setCheckable(True)
        m.addSeparator()
        self.act_focus = m.addAction("专注模式\tF8", self.toggle_focus_mode)
        self.act_focus.setCheckable(True)
        self.act_typewriter = m.addAction("打字机模式\tF9", self.toggle_typewriter)
        self.act_typewriter.setCheckable(True)
        m.addSeparator()
        self.act_side = m.addAction("显示分类栏")
        self.act_side.setCheckable(True)
        self.act_side.setChecked(True)
        self.act_side.triggered.connect(
            lambda c: self.splitter.widget(0).setVisible(c))
        self.act_attach = m.addAction("显示附件栏")
        self.act_attach.setCheckable(True)
        # _restore_state() 可能已经把附件栏恢复了，菜单勾选状态要跟实际可见性一致。
        # 这里用 isHidden()（反映显隐意图）而不是 isVisible()：菜单构建时窗口
        # 往往还没 show()，所有子控件 isVisible() 都是 False。
        self.act_attach.setChecked(not self.attachments.isHidden())
        self.act_attach.triggered.connect(self._toggle_attach_panel)
        m.addSeparator()
        m.addAction("全部展开", self._expand_all)
        m.addAction("全部折叠", self._collapse_all)
        m.addSeparator()
        m.addAction("放大\tCtrl+Shift+=", lambda: self._zoom(1))
        m.addAction("缩小\tCtrl+Shift+-", lambda: self._zoom(-1))
        m.addAction("实际大小\tCtrl+Shift+0", lambda: self._zoom(0))
        m.addSeparator()
        m.addAction("全屏\tF11", self._toggle_fullscreen)

        # ---- 主题
        m_theme = mb.addMenu("主题(&T)")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self._theme_actions = {}
        from ui.theme import LABELS
        for key in ("light", "dark"):
            a = m_theme.addAction(f"{LABELS[key]}主题")
            a.setCheckable(True)
            a.setData(key)
            a.triggered.connect(lambda _c=False, k=key: self.set_theme(k))
            self.theme_group.addAction(a)
            self._theme_actions[key] = a

        # ---- 帮助
        m = mb.addMenu("帮助(&H)")
        m.addAction("使用说明", self._show_guide)
        m.addAction("快捷键一览\tF1", self._show_shortcuts)
        m.addAction("资料库信息", self.show_stats)
        m.addSeparator()
        m.addAction("关于归藏", self._about)

        # 恢复各 checkable 动作的当前状态
        from ui.theme import current as current_theme
        self._sync_theme_checks(current_theme())
        self._sync_para_action()
        if hasattr(self, "act_source"):
            self.act_source.setChecked(bool(self.editor.edit.md_rules))
        if hasattr(self, "act_focus"):
            self.act_focus.setChecked(self._focus_mode)
        if hasattr(self, "act_typewriter"):
            self.act_typewriter.setChecked(self._typewriter)
        if hasattr(self, "act_side"):
            self.act_side.setChecked(not self.splitter.widget(0).isHidden())
        if hasattr(self, "act_attach"):
            self.act_attach.setChecked(not self.attachments.isHidden())

    # ------------------------------------------------------------ 视图动作

    _focus_mode = False
    _typewriter = False

    def _toggle_attach_panel(self, on: bool) -> None:
        panel = self.attachments
        panel.setVisible(on)
        # 菜单项 act_attach 在 build_menus() 里才创建，而 _restore_state()
        # 会在那之前调用本方法恢复上次的面板状态，所以要判空
        if hasattr(self, "act_attach"):
            self.act_attach.setChecked(on)
        if hasattr(self, "settings"):
            self.settings.setValue("attach_panel", on)
        if on:
            sizes = self.vsplitter.sizes()
            if len(sizes) != 2 or sizes[1] < 80:
                total = max(360, self.vsplitter.height())
                self.vsplitter.setSizes([max(200, total - 200), 200])

    def show_attach_panel(self) -> None:
        self._toggle_attach_panel(True)

    def pick_attachments(self) -> None:
        if self._current_id is None:
            self.status_message.emit("先选一个条目，再添加附件", 3000)
            return
        self.attachments.pick_files()
        if self.attachments.table.rowCount():
            self.show_attach_panel()

    def _attach_paths(self, paths) -> None:
        """把拖进正文的文件存成当前条目的附件。"""
        if self._current_id is None:
            self.status_message.emit("先选一个条目，再把文件拖进来", 4000)
            return
        n = self.attachments.add_paths(list(paths))
        if n and not self.attachments.isVisible():
            self.status_message.emit(
                f"已加入 {n} 个附件 · 视图 → 显示附件栏 可查看", 6000)

    def toggle_focus_mode(self) -> None:
        self._focus_mode = not self._focus_mode
        on = self._focus_mode
        self.splitter.widget(0).setVisible(not on)
        self.attachments.setVisible(not on)
        if hasattr(self, "act_side"):
            self.act_side.setChecked(not on)
        if hasattr(self, "act_attach"):
            self.act_attach.setChecked(not on)
        if hasattr(self, "act_focus"):
            self.act_focus.setChecked(on)

    def toggle_typewriter(self) -> None:
        self._typewriter = not self._typewriter
        self.act_typewriter.setChecked(self._typewriter)
        if self._typewriter:
            self.editor.edit.cursorPositionChanged.connect(self._center_cursor)
            self._center_cursor()
        else:
            try:
                self.editor.edit.cursorPositionChanged.disconnect(self._center_cursor)
            except (RuntimeError, TypeError):
                pass

    def _center_cursor(self) -> None:
        if not self._typewriter:
            return
        edit = self.editor.edit
        rect = edit.cursorRect()
        delta = rect.y() - edit.viewport().height() // 2
        sb = edit.verticalScrollBar()
        sb.setValue(sb.value() + delta)

    def insert_table(self) -> None:
        rows, ok = QInputDialog.getInt(self, "插入表格", "行数：", 3, 1, 50)
        if not ok:
            return
        cols, ok = QInputDialog.getInt(self, "插入表格", "列数：", 3, 1, 20)
        if not ok:
            return
        self.editor.insert_table(rows, cols)

    def show_find(self, replace: bool = False) -> None:
        if getattr(self, "_find_dialog", None) is None:
            from ui.find_dialog import FindReplaceDialog
            self._find_dialog = FindReplaceDialog(self.editor, self)
        self._find_dialog.open_for(replace)

    def _show_shortcuts(self) -> None:
        from ui.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    # ------------------------------------------------------- 编辑器快捷键

    def _owns_widget(self, obj) -> bool:
        """判断这个控件上的按键该不该由本视图处理。"""
        if not isinstance(obj, QWidget):
            return False
        if self.isAncestorOf(obj):
            return True
        # 焦点停在库标签栏上时（刚点过标签），当前标签是本视图就也接管
        tabs = getattr(self.window(), "tabs", None)
        return bool(tabs is not None and tabs.currentWidget() is self
                    and tabs.tabBar() is obj)

    def _ensure_body_focus(self) -> None:
        """把键盘焦点交给正文。

        选中条目后焦点可能还停在分类树、库标签栏或标题框上，
        这时按格式快捷键虽然改了文档，光标却不在正文里 —— 用户看到的就是
        "空笔记里按了没反应"。所以正文类快捷键先接管焦点再执行。
        """
        edit = self.editor.edit
        if edit.hasFocus():
            return
        fw = QApplication.focusWidget()
        if fw is not None and (fw is self.search_box
                               or self.search_box.isAncestorOf(fw)):
            return                      # 正在搜索框里打字，不抢
        edit.setFocus()

    def eventFilter(self, obj, event):  # noqa: N802
        if (event.type() == QEvent.KeyPress
                and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None
                and self._owns_widget(obj)):
            if self._handle_shortcut(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_shortcut(self, event) -> bool:
        """Typora 风格快捷键：统一在窗口层处理，不挑焦点。"""
        ed = self.editor
        key = event.key()
        mods = event.modifiers()

        # ---- 无修饰的功能键
        if mods == Qt.NoModifier:
            if key == Qt.Key_F1:
                self._show_shortcuts()
                return True
            if key == Qt.Key_F8:
                self.toggle_focus_mode()
                return True
            if key == Qt.Key_F9:
                self.toggle_typewriter()
                return True
            if key == Qt.Key_F11:
                self._toggle_fullscreen()
                return True
            return False

        # ---- Ctrl+Alt+↑/↓ 移动条目
        if mods & Qt.AltModifier and mods & Qt.ControlModifier:
            if key == Qt.Key_Up:
                self.move_item(-1)
                return True
            if key == Qt.Key_Down:
                self.move_item(1)
                return True
            if key == Qt.Key_N:
                self.new_node(True)
                return True
            return False

        # ---- Alt+Shift+5 删除线
        if mods & Qt.AltModifier:
            if key == Qt.Key_5 and mods & Qt.ShiftModifier:
                self._ensure_body_focus()
                ed.toggle_strike()
                return True
            return False

        if not (mods & Qt.ControlModifier):
            return False

        shift = bool(mods & Qt.ShiftModifier)

        # ---- 标题
        if not shift and Qt.Key_1 <= key <= Qt.Key_6:
            self._ensure_body_focus()
            ed.set_heading(key - Qt.Key_0)
            return True
        if not shift and key == Qt.Key_0:
            self._ensure_body_focus()
            ed.set_heading(0)
            return True

        # ---- 缩放 / 升降级
        if key in (Qt.Key_Equal, Qt.Key_Plus):
            if shift:
                self._zoom(1)
            else:
                self._ensure_body_focus()
                ed.change_heading_level(-1)
            return True
        if key in (Qt.Key_Minus, Qt.Key_Underscore):
            if shift:
                if key == Qt.Key_Minus and mods == (Qt.ControlModifier | Qt.ShiftModifier):
                    self._ensure_body_focus()
                    ed.insert_hr()          # Ctrl+Shift+- 水平分割线
                else:
                    self._zoom(-1)
            else:
                self._ensure_body_focus()
                ed.change_heading_level(1)
            return True

        # ---- 带 Shift 的组合
        if shift:
            if key == Qt.Key_K:
                self._ensure_body_focus()
                ed.insert_code_block()
                return True
            if key == Qt.Key_Q:
                self._ensure_body_focus()
                ed.toggle_quote()
                return True
            if key == Qt.Key_BracketLeft:
                self._ensure_body_focus()
                ed.toggle_list(QTextListFormat.ListDecimal)
                return True
            if key == Qt.Key_BracketRight:
                self._ensure_body_focus()
                ed.toggle_list(QTextListFormat.ListDisc)
                return True
            if key == Qt.Key_X:
                self._ensure_body_focus()
                ed.toggle_task()
                return True
            if key == Qt.Key_H:
                self._ensure_body_focus()
                ed.toggle_highlight()
                return True
            if key == Qt.Key_Return or key == Qt.Key_Enter:
                self._ensure_body_focus()
                ed.toggle_task_state()
                return True
            if key == Qt.Key_Up:
                self._ensure_body_focus()
                ed.insert_paragraph(True)
                return True
            if key == Qt.Key_Down:
                self._ensure_body_focus()
                ed.insert_paragraph(False)
                return True
            if key == Qt.Key_I:
                self._ensure_body_focus()
                ed.insert_image()
                return True
            if key == Qt.Key_QuoteLeft:
                self._ensure_body_focus()
                ed.toggle_inline_code()
                return True
            if key == Qt.Key_C:
                self._ensure_body_focus()
                ed.copy_as_markdown()
                return True
            if key == Qt.Key_V:
                self._ensure_body_focus()
                ed.paste_plain()
                return True
            if key == Qt.Key_S:
                self.backup()
                return True
            if key == Qt.Key_N:
                self.new_node(False, before=True)   # myBase: 新建同级（前面）
                return True
            if key == Qt.Key_A:
                self.pick_attachments()
                return True
            return False

        # ---- Ctrl 单键
        if key == Qt.Key_B:
            self._ensure_body_focus()
            ed.toggle_bold()
            return True
        if key == Qt.Key_I:
            self._ensure_body_focus()
            ed.toggle_italic()
            return True
        if key == Qt.Key_K:
            self._ensure_body_focus()
            ed.insert_link()
            return True
        if key == Qt.Key_T:
            self.insert_table()
            return True
        if key == Qt.Key_Backslash:
            self._ensure_body_focus()
            ed.clear_format()
            return True
        if key == Qt.Key_Slash:
            self.toggle_source_mode()
            return True
        if key == Qt.Key_D:
            self.toggle_star()               # myBase: Ctrl+D 书签/收藏
            return True
        if key == Qt.Key_BracketRight:
            self._ensure_body_focus()
            ed.edit._indent_block(1)
            return True
        if key == Qt.Key_BracketLeft:
            self._ensure_body_focus()
            ed.edit._indent_block(-1)
            return True
        if key == Qt.Key_S:
            self.save_now()
            return True
        if key == Qt.Key_N:
            self.new_node(False)      # myBase: 新建同级（后面）
            return True
        if key == Qt.Key_O:
            self.open_library()
            return True
        if key == Qt.Key_P:
            self._focus_search()
            return True
        if key == Qt.Key_F:
            self.show_find(False)
            return True
        if key == Qt.Key_H:
            self.show_find(True)
            return True
        if key == Qt.Key_W or key == Qt.Key_Q:
            self.close_requested.emit()
            return True
        return False

    # ------------------------------------------------------------ 菜单动作

    def _sync_para_action(self) -> None:
        if not hasattr(self, "act_para"):
            return
        level = int(self.editor.edit.textCursor().blockFormat().headingLevel())
        self.act_para.setChecked(level == 0)

    _zoom_level = 0

    def _zoom(self, delta: int) -> None:
        if delta == 0:
            self.editor.edit.zoomIn(-self._zoom_level)
            self._zoom_level = 0
            return
        step = 1 if delta > 0 else -1
        new = max(-3, min(8, self._zoom_level + step))
        if new != self._zoom_level:
            self.editor.edit.zoomIn(new - self._zoom_level)
            self._zoom_level = new

    def _toggle_fullscreen(self) -> None:
        self.fullscreen_toggled.emit()

    def set_theme(self, name: str) -> None:
        from ui import style, theme
        theme.apply_theme(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(style.qss())
        self.editor.refresh_theme()
        self._apply_icon_theme()
        self.attachments.refresh()
        self.search_panel.list.viewport().update()
        self._sync_tree_palette()
        self._sync_theme_checks(name)
        try:
            self.db.set_meta("ui.theme", theme.current())
        except Exception:  # noqa: BLE001  库已关闭时忽略
            pass

    def _sync_theme_checks(self, name: str) -> None:
        for key, act in getattr(self, "_theme_actions", {}).items():
            act.setChecked(key == name)

    def _show_guide(self) -> None:
        """帮助内容只在这里按需展示，不再往库里塞「使用说明」条目。"""
        from core.database import GUIDE_MD
        from ui.markdown_render import render_preview

        dlg = QDialog(self)
        dlg.setWindowTitle("使用说明")
        dlg.resize(780, 660)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 10)
        view = QTextBrowser(dlg)
        view.setFrameShape(QFrame.NoFrame)
        view.setOpenExternalLinks(True)
        view.setHtml(render_preview(GUIDE_MD))
        lay.addWidget(view, 1)
        box = QDialogButtonBox(QDialogButtonBox.Ok, dlg)
        box.accepted.connect(dlg.accept)
        lay.addWidget(box, 0, Qt.AlignCenter)
        dlg.exec()

    def _about(self) -> None:
        QMessageBox.about(
            self, "关于 归藏",
            "<b>归藏</b> · 个人资料库<br><br>"
            "把任意格式的资料按树形分类收在一起，<br>"
            "整个库就是一个 .db 文件。<br><br>"
            "Python · PySide6 · SQLite<br>"
            f"库文件：{self.db.db_path}")

    # ------------------------------------------------------------------ 树

    def _reload_tree(self, select_id: Optional[int] = None) -> None:
        prev = select_id if select_id is not None else self._current_id
        self._loading_tree = True
        self.tree.clear()
        self._items.clear()
        self._icon_selected_item = None   # 旧 item 已被销毁，别留着下次访问

        rows = self.db.all_nodes()
        by_parent: Dict[Optional[int], list] = defaultdict(list)
        for r in rows:
            by_parent[r["parent_id"]].append(r)

        def build(parent_id: Optional[int], parent_item: Optional[QTreeWidgetItem]) -> None:
            for r in by_parent.get(parent_id, []):
                item = QTreeWidgetItem(parent_item) if parent_item else QTreeWidgetItem(self.tree)
                item.setText(0, r["title"] or "未命名")
                item.setData(0, ROLE_ID, int(r["id"]))
                item.setData(0, Qt.UserRole + 1, bool(r["starred"]))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
                              | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                item.setToolTip(0, r["title"] or "")
                self._items[int(r["id"])] = item
                build(int(r["id"]), item)

        build(None, None)
        self._refresh_icons()
        self._loading_tree = False

        # 恢复展开状态
        self._loading_tree = True
        for r in rows:
            item = self._items.get(int(r["id"]))
            if item is not None:
                item.setExpanded(bool(r["expanded"]))
        self._loading_tree = False

        if prev is not None and prev in self._items:
            self.tree.setCurrentItem(self._items[prev])
            self._select_node(prev, from_tree=True)
        elif self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first)
        else:
            self._show_empty_state()

    def _paint_icon(self, item: QTreeWidgetItem) -> None:
        """选中项用白图标，其余用原色 —— 深蓝底上彩色小图标会糊成一团。"""
        starred = bool(item.data(0, Qt.UserRole + 1))
        on = item.isSelected()
        if item.childCount() > 0:
            item.setIcon(0, folder_icon(36, color="#ffffff" if on else "#f0b429",
                                        starred=starred))
        else:
            item.setIcon(0, leaf_icon(36, color="#ffffff" if on else "#9aa4b8",
                                      starred=starred))

    def _refresh_icons(self) -> None:
        self._syncing_item = True
        try:
            for item in self._items.values():
                self._paint_icon(item)
        finally:
            self._syncing_item = False

    def _persist_tree(self) -> None:
        if self._loading_tree:
            return
        structure = []

        def walk(item: QTreeWidgetItem, parent_id: Optional[int]) -> None:
            for i in range(item.childCount()):
                child = item.child(i)
                cid = child.data(0, ROLE_ID)
                if cid is None:
                    continue
                structure.append((int(cid), parent_id, i))
                walk(child, int(cid))

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            tid = top.data(0, ROLE_ID)
            if tid is None:
                continue
            structure.append((int(tid), None, i))
            walk(top, int(tid))
        self.db.apply_tree(structure)
        self._refresh_icons()

    def _on_expanded(self, item: QTreeWidgetItem, expanded: bool) -> None:
        if self._loading_tree:
            return
        nid = item.data(0, ROLE_ID)
        if nid is not None:
            self.db.update_node(int(nid), expanded=1 if expanded else 0)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading_tree or self._syncing_item or column != 0:
            return
        nid = item.data(0, ROLE_ID)
        if nid is None:
            return
        title = item.text(0).strip() or "未命名"
        self.db.update_node(int(nid), title=title)
        if int(nid) == self._current_id:
            self._syncing_item = True
            self.title_edit.setText(title)
            self._syncing_item = False
            self._update_path(int(nid))

    # ------------------------------------------------------------ 选中与加载

    def _on_tree_selection(self) -> None:
        items = self.tree.selectedItems()
        prev = getattr(self, "_icon_selected_item", None)
        cur = items[0] if items else None
        if prev is not cur:
            self._syncing_item = True
            try:
                for it in (prev, cur):
                    if it is not None:
                        self._paint_icon(it)
            finally:
                self._syncing_item = False
            self._icon_selected_item = cur
        if not items:
            return
        nid = items[0].data(0, ROLE_ID)
        if nid is None or int(nid) == self._current_id:
            return
        self._select_node(int(nid), from_tree=True)

    def _select_node(self, node_id: int, from_tree: bool = False) -> None:
        row = self.db.get_node(node_id)
        if row is None:
            return

        self.editor.set_node(node_id, row["note_text"], row["note_format"])
        self._current_id = node_id

        self._syncing_item = True
        self.title_edit.setText(row["title"] or "")
        self._syncing_item = False
        self._update_path(node_id)
        self.attachments.set_node(node_id)
        # 回到编辑界面：按上次的开关恢复附件栏（空状态时会临时收起）
        if self.settings.value("attach_panel", True, type=bool):
            self.attachments.setVisible(True)
        self.empty_hint.hide()
        self._apply_icon_theme()
        self._push_nav(node_id)
        self._set_save_state(self.editor.is_dirty())

        item = self._items.get(node_id)
        if item is not None and not from_tree:
            self._loading_tree = True
            self.tree.setCurrentItem(item)
            self._loading_tree = False
        self._update_counts()

    def _open_link(self, url: str) -> None:
        m = re.match(r"gzs:///(\d+)", url or "")
        if m:
            from ui.open_file import open_attachment
            open_attachment(self, self.db, int(m.group(1)))
            return
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _update_path(self, node_id: int) -> None:
        path = self.db.path_of(node_id)
        self.path_label.setText(path if " / " in path else "")
        self.path_label.setToolTip(path)

    def _show_empty_state(self) -> None:
        self._current_id = None
        self.editor.set_node(None)
        self.attachments.set_node(None)
        self.attachments.setVisible(False)
        self.title_edit.clear()
        self.path_label.clear()
        self.empty_hint.show()
        self._set_save_state(False)
        self._update_counts()

    def _current_node_title(self) -> str:
        if self._current_id is None:
            return ""
        return self.db.title_of(self._current_id)

    # ---------------------------------------------------------------- 新建

    def new_node(self, child_of_current: bool = True, before: bool = False) -> None:
        parent_id: Optional[int] = None
        ref_index = None
        if self._current_id is not None:
            if child_of_current:
                parent_id = self._current_id
            else:
                row = self.db.get_node(self._current_id)
                parent_id = row["parent_id"] if row else None
                if before:
                    ref_index = self.db.sibling_index(self._current_id)
        node_id = self.db.create_node("新条目", parent_id)
        if ref_index is not None:
            self.db.place_sibling(node_id, ref_index)
        self._reload_tree(select_id=node_id)

        item = self._items.get(node_id)
        if item is not None:
            self.tree.scrollToItem(item)
            self.tree.editItem(item, 0)
        self.title_edit.setFocus()
        self.title_edit.selectAll()
        self.status_message.emit("已新建条目，输入标题即可", 3000)

    def _rename_current(self) -> None:
        if self._current_id is None:
            return
        item = self._items.get(self._current_id)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.editItem(item, 0)

    def _delete_current(self) -> None:
        if self._current_id is None:
            return
        node_id = self._current_id
        sub = len(self.db.descendant_ids(node_id))
        files = len(self.db.files_of(node_id))
        msg = f"确定删除「{self.db.title_of(node_id)}」？"
        if sub or files:
            msg += f"\n\n将一并删除其下 {sub} 个子条目、{files} 个附件。"
        if QMessageBox.question(self, "删除条目", msg,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        parent = self.db.get_node(node_id)
        parent_id = parent["parent_id"] if parent else None
        self._current_id = None
        self.db.delete_node(node_id)
        self._reload_tree(select_id=parent_id)
        self.status_message.emit("已删除", 3000)

    # ---------------------------------------------------------------- 保存

    def save_now(self) -> None:
        if self._current_id is None:
            self.status_message.emit("还没有选中条目", 2500)
            return
        if not self.editor.is_dirty():
            self.status_message.emit("当前条目已是最新", 2500)
            return
        self.editor.flush()
        self.status_message.emit("已保存", 2500)

    def _set_save_state(self, dirty: bool) -> None:
        self.save_state_changed.emit(dirty)

    def _save_note(self, fmt: str, content: str, plain: str) -> None:
        if self._current_id is None:
            return
        self.db.update_node(self._current_id, note_text=content,
                            note_format=fmt, plain=plain)
        self.save_state_changed.emit(False)
        self.status_message.emit(
            "已保存 · " + self.db.get_node(self._current_id)["updated_at"][11:], 2500)

    def _commit_title(self) -> None:
        if self._title_timer.isActive():
            self._title_timer.stop()
        if self._current_id is None or self._syncing_item:
            return
        title = self.title_edit.text().strip() or "未命名"
        row = self.db.get_node(self._current_id)
        if row is None or row["title"] == title:
            return
        self.db.update_node(self._current_id, title=title)
        item = self._items.get(self._current_id)
        if item is not None:
            self._syncing_item = True
            item.setText(0, title)
            item.setToolTip(0, title)
            self._syncing_item = False
        self._update_path(self._current_id)

    # ---------------------------------------------------------------- 模式

    def toggle_source_mode(self) -> None:
        """源码模式：关掉即时渲染，直接看/改 Markdown 原文。"""
        on = self.editor.edit.md_rules
        self.editor.set_source_mode(on)
        if hasattr(self, "act_source"):
            self.act_source.setChecked(on)
        self.mode_changed.emit("源码模式" if on else "")
        self.status_message.emit("已切到源码模式" if on else "已回到即时渲染", 2500)

    # ---------------------------------------------------------------- 搜索

    def _focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _on_search_text(self, text: str) -> None:
        if not text.strip():
            self._search_timer.stop()
            self.side_stack.setCurrentIndex(0)
            return
        self._search_timer.start()

    def _run_search(self) -> None:
        kw = self.search_box.text().strip()
        if not kw:
            return
        self.editor.flush()      # 先落盘，刚写的内容也能被搜到
        results = self.db.search(kw)
        self.search_panel.set_results(results, kw)
        self.side_stack.setCurrentIndex(1)

    def _goto_search_result(self, node_id: int) -> None:
        self.search_box.clear()
        self.side_stack.setCurrentIndex(0)
        item = self._items.get(node_id)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._select_node(node_id)
        self.tree.scrollToItem(item)

    # -------------------------------------------------------------- 上下文

    def _side_menu(self) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("全部展开", self._expand_all)
        menu.addAction("全部折叠", self._collapse_all)
        menu.addSeparator()
        menu.addAction("导入文件夹为分类…", self.import_folder)
        menu.addSeparator()
        menu.addAction("新建资料库…", self.new_library)
        menu.addAction("打开资料库…", self.open_library)
        menu.addAction("备份资料库到文件…", self.backup)
        menu.addAction("在资源管理器中显示库文件", self.reveal_db)
        btn = self.sender()
        pos = btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.cursor().pos()
        menu.exec(pos)

    def _expand_all(self) -> None:
        self.tree.expandAll()
        for nid in self._items:
            self.db.update_node(nid, expanded=1)

    def _collapse_all(self) -> None:
        self.tree.collapseAll()
        for nid in self._items:
            self.db.update_node(nid, expanded=0)

    def _tree_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        nid = item.data(0, ROLE_ID) if item is not None else None
        menu = QMenu(self)
        menu.addAction("新建子条目\tCtrl+Alt+N", lambda: self.new_node(True))
        menu.addAction("新建同级（后）\tCtrl+N", lambda: self.new_node(False))
        menu.addAction("新建同级（前）\tCtrl+Shift+N",
                       lambda: self.new_node(False, before=True))
        if nid is not None:
            menu.addSeparator()
            menu.addAction("收藏 / 取消收藏\tCtrl+D", self.toggle_star)
            menu.addAction("上移\tCtrl+Alt+↑", lambda: self.move_item(-1))
            menu.addAction("下移\tCtrl+Alt+↓", lambda: self.move_item(1))
            menu.addSeparator()
            menu.addAction("重命名\tF2", self._rename_current)
            menu.addAction("添加附件…", lambda: self.attachments.pick_files())
            menu.addAction("导入文件夹到这里…", lambda: self.import_folder(int(nid)))
            menu.addAction("导出此条目…", lambda: self.export_node(int(nid)))
            menu.addSeparator()
            menu.addAction("删除", self._delete_current)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ 导入导出

    def _image_size(self, fid: int):
        """图片原始像素尺寸，用于正文按可视宽度排版。"""
        if fid in self._image_size_cache:
            return self._image_size_cache[fid]
        data = self.db.blob_bytes(fid)
        size = None
        if data:
            img = QImage.fromData(data)
            if not img.isNull():
                size = (img.width(), img.height())
        self._image_size_cache[fid] = size
        return size

    def _drop_removed_image(self, fid: int) -> None:
        """正文里删掉的图片：对应附件记录一起删，附件栏同步消失。"""
        row = self.db.get_file(fid)
        if row is None:
            return
        # 不校验“是否当前条目”：切条目时追踪会被暂停并清空待删队列，
        # 能走到这里的必然是刚在当前正文里被删掉的图
        self.db.delete_file(fid)
        self._image_size_cache.pop(fid, None)
        self.editor.edit._image_cache.pop(fid, None)
        self.attachments.refresh()
        self._update_counts()
        self.status_message.emit("已删除正文中移除的图片", 3000)

    def _open_image(self, fid: int) -> None:
        from ui.open_file import open_attachment
        open_attachment(self, self.db, fid)

    def _save_image(self, data: bytes, name: str):
        if self._current_id is None:
            return None
        fid = self.db.add_bytes(self._current_id, name + ".png" if not name.endswith(".png")
                                else name, data)
        self.attachments.refresh()
        from PySide6.QtGui import QImage
        img = QImage.fromData(data)
        width = img.width() if not img.isNull() else 480
        return f"gzs:///{fid}", width

    def import_folder(self, parent_id: Optional[int] = None) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择要导入的文件夹")
        if not folder:
            return
        root = Path(folder)
        if not root.is_dir():
            return
        total = sum(1 for p in root.rglob("*") if p.is_file())
        if total == 0:
            QMessageBox.information(self, "导入文件夹", "这个文件夹里没有文件。")
            return
        if parent_id is None:
            parent_id = self._current_id if QMessageBox.question(
                self, "导入位置",
                f"共 {total} 个文件。\n\n导入到当前选中的条目下吗？\n"
                "（选「No」则建在顶层）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) == QMessageBox.Yes else None

        progress = QProgressDialog("正在导入…", "取消", 0, total, self)
        progress.setWindowTitle("导入文件夹")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)
        counter = {"n": 0, "files": 0, "cancelled": False}

        def walk(src: Path, pid: Optional[int], depth: int) -> Optional[int]:
            if counter["cancelled"]:
                return None
            node = self.db.create_node(src.name or root.name, pid)
            counter["n"] += 1
            for child in sorted(src.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if counter["cancelled"]:
                    break
                if child.is_dir():
                    if depth < 8:
                        walk(child, node, depth + 1)
                elif child.is_file():
                    try:
                        self.db.add_file(node, child)
                        counter["files"] += 1
                    except OSError:
                        pass
                    counter["n"] += 1
                    progress.setValue(min(counter["n"], total))
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        counter["cancelled"] = True
                        break
            return node

        try:
            new_id = walk(root, parent_id, 0)
        finally:
            progress.close()

        self._reload_tree(select_id=new_id or parent_id)
        self._update_counts()
        self.status_message.emit(
            f"导入完成：{counter['files']} 个文件"
            + ("（已取消）" if counter["cancelled"] else ""), 6000)

    def export_node(self, node_id: int) -> None:
        row = self.db.get_node(node_id)
        if row is None:
            return
        target = QFileDialog.getExistingDirectory(self, "选择导出位置")
        if not target:
            return
        try:
            out = self._export_recursive(node_id, Path(target))
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.status_message.emit(f"已导出到 {out}", 8000)

    def _export_recursive(self, node_id: int, parent_dir: Path) -> Path:
        row = self.db.get_node(node_id)
        title = self._safe_name(row["title"] or "未命名")
        folder = parent_dir / title
        i = 2
        while folder.exists():
            folder = parent_dir / f"{title} ({i})"
            i += 1
        folder.mkdir(parents=True)

        files = self.db.files_of(node_id)
        if files:
            fdir = folder / "附件"
            fdir.mkdir()
            for f in files:
                data = self.db.blob_bytes(f["id"])
                if data is not None:
                    try:
                        (fdir / f["name"]).write_bytes(data)
                    except OSError:
                        pass

        source = row["note_text"] or ""
        # 真源是 Markdown：笔记.md 直接就是源码，笔记.html 由源码渲染
        try:
            (folder / "笔记.md").write_text(source, encoding="utf-8")
        except OSError:
            pass
        body = md_to_html(source) if row["note_format"] == "md" else source
        (folder / "笔记.html").write_text(
            self._standalone_html(row["title"] or "未命名", body), encoding="utf-8")

        for child in self.db.children(node_id):
            self._export_recursive(int(child["id"]), folder)
        return folder

    @staticmethod
    def _safe_name(name: str) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
        return name[:60] or "未命名"

    @staticmethod
    def _standalone_html(title: str, body_html: str) -> str:
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title>"
                "<style>body{font-family:'PingFang SC','Microsoft YaHei UI',sans-serif;"
                "max-width:820px;margin:40px auto;line-height:1.75;color:#1f2430;"
                "padding:0 20px}img{max-width:100%}table{border-collapse:collapse}"
                "th,td{border:1px solid #e3e6ec;padding:6px 10px}</style></head>"
                f"<body>{body_html}</body></html>")

    # ------------------------------------------------------------ 库与备份

    def backup(self) -> None:
        self.editor.flush()
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        default = self.db.db_path.with_name(f"{self.db.db_path.stem}-备份-{stamp}.db")
        target, _ = QFileDialog.getSaveFileName(
            self, "备份资料库", str(default), "归藏资料库 (*.db)")
        if not target:
            return
        try:
            out = self.db.save_copy_to(Path(target))
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.critical(self, "备份失败", str(exc))
            return
        QMessageBox.information(
            self, "备份完成",
            f"已导出完整副本：\n{out}\n\n"
            "这个文件可以单独拷走，随时用「打开资料库」恢复。")

    def compact_db(self) -> None:
        self.editor.flush()
        before = self.db.disk_size()
        if QMessageBox.question(
                self, "精简数据库",
                f"将压缩库内附件并整理数据库文件。\n\n当前大小：{human_size(before)}\n"
                "附件越多、文本类越多，压缩效果越明显；已经压缩过的图片/视频基本压不动。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self.db.compact()
        finally:
            QApplication.restoreOverrideCursor()
        self._update_counts()
        self.status_message.emit(
            f"已精简：{human_size(result['before'])} → {human_size(result['after'])}", 8000)
        QMessageBox.information(
            self, "精简完成",
            f"新压缩附件：{result['packed']} 个\n"
            f"{human_size(result['before'])} → {human_size(result['after'])}")

    def reveal_db(self) -> None:
        path = self.db.db_path
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def new_library(self) -> None:
        default = Path.home() / "Documents" / "我的资料库.db"
        path, _ = QFileDialog.getSaveFileName(
            self, "新建资料库", str(default), "归藏资料库 (*.db)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".db":
            target = target.with_suffix(".db")
        if target.exists() and QMessageBox.question(
                self, "新建资料库",
                f"{target.name} 已存在，要覆盖它吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if target.exists():
            target.unlink()
        self.new_library_requested.emit(target)

    def open_library(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开资料库", "", "归藏资料库 (*.db);;所有文件 (*.*)")
        if path:
            self.open_library_requested.emit(Path(path))

    def _switch_db(self, db_file: Path) -> None:
        # 多库模式下不再替换当前库，改为请求宿主打开新标签
        self.open_library_requested.emit(db_file)

    def show_stats(self) -> None:
        s = self.db.stats()
        tags = self.db.all_tags()
        QMessageBox.information(
            self, "资料库信息",
            f"条目数：{s['nodes']}\n附件数：{s['files']}\n"
            f"附件内容：{human_size(s['bytes'])}\n"
            f"库文件大小：{human_size(s['db_bytes'])}\n"
            f"最近更新：{s['updated'] or '—'}\n\n"
            f"库文件：\n{self.db.db_path}\n\n"
            f"标签（{len(tags)}）：{'、'.join(tags[:20]) or '—'}")

    # ---------------------------------------------------------------- 其他

    def _update_counts(self) -> None:
        s = self.db.stats()
        self.counts_changed.emit(
            f"{s['nodes']} 条目 · {s['files']} 附件 · 库 {human_size(s['db_bytes'])}")
        self._set_db_label(s["db_bytes"])

    def _restore_state(self) -> None:
        # 记下待恢复的分割比例，窗口真正显示后再应用一次：
        # 未 show 时 setSizes 会被后续布局覆盖
        # 默认值写死：窗口未 show 时控件尺寸还没算出来，不能拿当前 sizes 当默认
        self._pending_sizes = (
            splitter_sizes(self.settings, [250, 1010], "splitter"),
            splitter_sizes(self.settings, [680, 220], "vsplitter"),
        )
        self.splitter.setSizes(self._pending_sizes[0])
        self.vsplitter.setSizes(self._pending_sizes[1])

        # 主题也存在库里：同一个 .db 换台机器打开，外观保持一致
        from ui import theme as theme_mod
        saved_theme = self.db.get_meta("ui.theme", "")
        if saved_theme in ("light", "dark") and saved_theme != theme_mod.current():
            self.set_theme(saved_theme)
        else:
            self._sync_theme_checks(theme_mod.current())

        if self.settings.value("attach_panel", True, type=bool):
            self.show_attach_panel()

        last = self.db.get_meta("last_node", "")
        if last.isdigit() and int(last) in self._items:
            self._select_node(int(last))

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        pending = getattr(self, "_pending_sizes", None)
        if pending:
            self._pending_sizes = None
            sizes_h, sizes_v = pending

            def apply_sizes() -> None:
                self.splitter.setSizes(sizes_h)
                self.vsplitter.setSizes(sizes_v)

            QTimer.singleShot(0, apply_sizes)

    def closeEvent(self, event):  # noqa: N802
        try:
            self.editor.flush()
            if self._current_id is not None:
                self.db._set_meta("last_node", str(self._current_id))
            self.settings.setValue("splitter", self.splitter.sizes())
            self.settings.setValue("vsplitter", self.vsplitter.sizes())
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)