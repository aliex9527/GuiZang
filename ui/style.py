"""统一视觉样式：由主题调色板生成 QSS。"""

from __future__ import annotations

from ui.theme import P


def qss() -> str:
    BG = P["bg"]
    PANEL = P["panel"]
    BORDER = P["border"]
    TEXT = P["text"]
    MUTED = P["muted"]
    ACCENT = P["accent"]
    ACCENT_SOFT = P["accent_soft"]
    ACCENT_LINE = P["accent_line"]
    SELECT_BG = P["select_bg"]
    SELECT_FG = P["select_fg"]
    HOVER = P["hover"]
    ROW_HOVER = P["row_hover"]
    SUBTLE = P["subtle"]
    LINE = P["line"]
    TIP_BG = P["tooltip_bg"]
    TIP_FG = P["tooltip_fg"]
    SHADOW = P["shadow"]
    SHADOW_HOVER = P["shadow_hover"]

    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background: {BG};
}}

/* Python 自定义子类的类名不是 QWidget，类型选择器匹配不到，这里只用对象名 */
#SidePanel, #EditorPanel, #AttachPanel {{
    background: {PANEL};
}}

QWidget#EditorHeader {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}

QLabel#PanelTitle {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 2px;
}}

QLabel#EmptyHint {{
    color: {MUTED};
    font-size: 13px;
}}

QLabel#PathLabel {{
    color: {MUTED};
    font-size: 11px;
}}

/* ---------------------------------------------------------------- 菜单栏 */
QMenuBar {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 5px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}

/* ---------------------------------------------------------------- 工具条 */
QToolBar {{
    background: {PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    spacing: 6px;
}}

QToolBar QToolButton {{
    padding: 4px 7px;
}}

QToolButton, QPushButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT};
}}
QToolButton:hover, QPushButton:hover {{
    background: {HOVER};
}}
QToolButton:pressed, QPushButton:pressed {{
    background: {SUBTLE};
}}
QToolButton:disabled, QPushButton:disabled {{
    color: {MUTED};
}}
QToolButton:checked {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT_LINE};
    color: {ACCENT};
}}
QToolButton#Mini {{
    padding: 3px 7px;
    font-size: 12px;
    color: {MUTED};
}}
QToolButton#Mini:hover {{
    color: {ACCENT};
    background: {ACCENT_SOFT};
}}

QPushButton#Primary {{
    background: {ACCENT};
    color: #ffffff;
    border: 1px solid {ACCENT};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}

QPushButton#Ghost {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 12px;
    background: {PANEL};
}}
QPushButton#Ghost:hover {{
    border-color: {ACCENT_LINE};
    background: {HOVER};
}}

/* ---------------------------------------------------------------- 输入框 */
QLineEdit {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit#TitleEdit {{
    border: none;
    background: transparent;
    font-size: 19px;
    font-weight: 700;
    padding: 2px 0;
}}
QLineEdit#TitleEdit:focus {{
    border-bottom: 1px solid {ACCENT};
    border-radius: 0;
}}
QLineEdit#SearchBox {{
    border-radius: 15px;
    padding: 5px 12px;
    background: {SUBTLE};
    border: 1px solid transparent;
}}
QLineEdit#SearchBox:focus {{
    background: {PANEL};
    border-color: {ACCENT};
}}

/* ------------------------------------------------------------ 图标条 */
#IconStrip {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QToolButton#IconBtn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}}
QToolButton#IconBtn:hover {{
    background: {HOVER};
}}
QToolButton#IconBtn:pressed {{
    background: {SUBTLE};
}}
QToolButton#IconBtn:disabled {{
    background: transparent;
}}

/* ---------------------------------------------------------------- 分类树 */
QTreeWidget {{
    background: {PANEL};
    border: none;
    outline: none;
    /* 装饰区（缩进/分支线）由 CategoryTree.drawBranches 自绘：
       这里关掉样式自带的"装饰区跟随选中"，避免系统色抢在我们上面涂一层。 */
    show-decoration-selected: 0;
}}
QTreeWidget::item {{
    height: 30px;
    padding: 1px 2px;
    border-radius: 0;
    color: {TEXT};
    background: transparent;
}}
QTreeWidget::item:hover {{
    /* 悬停底色同样由 delegate 画在内容区，避免和选中条宽度不一致 */
    background: transparent;
}}
QTreeWidget::item:selected {{
    /* 蓝条由 CategoryItemDelegate 只刷条目内容区，这里不设底色 */
    background: transparent;
    color: {SELECT_FG};
}}
QTreeWidget::branch {{
    background: transparent;
}}
QTreeWidget::branch:has-children:closed {{
    image: none;
}}
QTreeWidget::branch:has-children:open {{
    image: none;
}}

/* ---------------------------------------------------------------- 表格 */
QTableWidget {{
    background: {PANEL};
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QTableWidget::item {{
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid {LINE};
}}
QTableWidget::item:hover {{
    background: {ROW_HOVER};
}}
QTableWidget::item:selected {{
    background: {ACCENT_SOFT};
}}
QHeaderView::section {{
    background: {PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    color: {MUTED};
    font-size: 11px;
    font-weight: 700;
    padding: 6px 6px;
    text-align: left;
}}

/* ---------------------------------------------------------------- 列表 */
QListWidget {{
    background: {PANEL};
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 7px 8px;
    border-radius: 6px;
    color: {TEXT};
}}
QListWidget::item:hover {{
    background: {ROW_HOVER};
}}
QListWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};
}}

/* ---------------------------------------------------------------- 文本 */
QTextEdit, QPlainTextEdit {{
    background: {PANEL};
    border: none;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QTextBrowser {{
    background: {PANEL};
    border: none;
}}

/* ---------------------------------------------------------------- 菜单 */
QMenu {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 26px 6px 22px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QMenu::item:disabled {{
    color: {MUTED};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
    margin-left: 6px;
}}

/* ---------------------------------------------------------------- 分割条 */
QSplitter::handle {{
    background: {BORDER};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ---------------------------------------------------------------- 滚动条 */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {SHADOW};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {SHADOW_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {SHADOW};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------------------------------------------------------------- 状态栏 */
QStatusBar {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
    color: {MUTED};
    font-size: 11px;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    padding: 0 10px;
}}

QToolTip {{
    background: {TIP_BG};
    color: {TIP_FG};
    border: none;
    border-radius: 5px;
    padding: 4px 8px;
}}

QComboBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
}}
QComboBox:hover {{
    border-color: {ACCENT_LINE};
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    outline: none;
}}

QCheckBox {{
    spacing: 6px;
}}
"""
