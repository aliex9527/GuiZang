"""主题调色板：浅色 / 深色。

所有颜色都从这里的语义 token 取，切换主题时原地更新 `P`，
各处通过 `P["xxx"]` 读取，因此不需要重新导入模块。
"""

from __future__ import annotations

from typing import Dict

LIGHT: Dict[str, str] = {
    "bg": "#f5f6f8",
    "panel": "#ffffff",
    "border": "#e3e6ec",
    "text": "#1f2430",
    "muted": "#7a8296",
    "accent": "#2b4fd6",
    "accent_soft": "#eef2ff",
    "accent_line": "#c7d2fe",
    "hover": "#f0f2f7",
    "row_hover": "#f6f7fa",
    "subtle": "#f2f4f8",
    "line": "#f2f4f8",
    "tooltip_bg": "#262c3a",
    "tooltip_fg": "#f5f6f8",
    "white": "#ffffff",
    "shadow": "#d3d8e3",
    "shadow_hover": "#b9c1d1",
    # 对话框按钮（保存 / 不保存 / 取消）：比面板深一档，从背景里立起来
    "btn_bg": "#d9dfe9",
    "btn_bg_hover": "#cbd2e0",
    "btn_bg_pressed": "#bcc4d5",
    # 分类树（myBase 风格：整行实心蓝条 + 白字 + 层级虚线）
    "select_bg": "#0078d4",
    "select_fg": "#ffffff",
    "branch": "#c9ced8",
    # 正文
    "note_text": "#1f2430",
    "code_bg": "#f6f8fa",
    "code_text": "#24292f",
    "inline_bg": "#eef1f6",
    "inline_text": "#b02a37",
    "mark_bg": "#fff3a3",
    "mark_text": "#3a2f00",
    "ok": "#2f855a",
    "quote_bg": "#f6f7fb",
    "quote_text": "#57606a",
    "link": "#2b4fd6",
    "table_head_bg": "#f2f4f8",
}

DARK: Dict[str, str] = {
    "bg": "#191c23",
    "panel": "#21252e",
    "border": "#313743",
    "text": "#e4e7ee",
    "muted": "#98a1b3",
    "accent": "#7d99ff",
    "accent_soft": "#2a3350",
    "accent_line": "#3d4a72",
    "hover": "#2a303b",
    "row_hover": "#262c36",
    "subtle": "#1d212a",
    "line": "#272c36",
    "tooltip_bg": "#3b4252",
    "tooltip_fg": "#eceff5",
    "white": "#21252e",
    "shadow": "#3a4150",
    "shadow_hover": "#4a5263",
    # 对话框按钮（保存 / 不保存 / 取消）：比面板深一档，从背景里立起来
    "btn_bg": "#3a4351",
    "btn_bg_hover": "#46505f",
    "btn_bg_pressed": "#525d6f",
    # 分类树（myBase 风格：整行实心蓝条 + 白字 + 层级虚线）
    "select_bg": "#1f6feb",
    "select_fg": "#ffffff",
    "branch": "#3a4150",
    # 正文
    "note_text": "#e4e7ee",
    "code_bg": "#171a21",
    "code_text": "#d7dce6",
    "inline_bg": "#35303c",
    "inline_text": "#ff9f9f",
    "mark_bg": "#4a4220",
    "mark_text": "#f6ecc0",
    "ok": "#7ee0a8",
    "quote_bg": "#242a35",
    "quote_text": "#a3acbe",
    "link": "#8ea8ff",
    "table_head_bg": "#2a303b",
}

PALETTES = {"light": LIGHT, "dark": DARK}
LABELS = {"light": "浅色", "dark": "深色"}

# 原地更新的当前调色板
P: Dict[str, str] = dict(LIGHT)
_current = "light"


def apply_theme(name: str) -> str:
    global _current
    _current = name if name in PALETTES else "light"
    P.clear()
    P.update(PALETTES[_current])
    return _current


def palette():
    """按当前调色板生成一份 QPalette。

    QSS 管不到的地方（标签栏底色、滚动条槽、原生控件、对话框按钮区）
    都从 QPalette 取色。Fusion 默认调色板恒为浅色，深色主题下这些地方
    会白得刺眼，所以切换主题时连调色板一起换。
    """
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    bg = QColor(P["bg"])
    panel = QColor(P["panel"])
    text = QColor(P["text"])
    muted = QColor(P["muted"])
    accent = QColor(P["accent"])

    roles = {
        QPalette.ColorRole.Window: bg,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: panel,
        QPalette.ColorRole.AlternateBase: QColor(P["subtle"]),
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: panel,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.BrightText: QColor(P["select_fg"]),
        QPalette.ColorRole.Highlight: QColor(P["select_bg"]),
        QPalette.ColorRole.HighlightedText: QColor(P["select_fg"]),
        QPalette.ColorRole.ToolTipBase: QColor(P["tooltip_bg"]),
        QPalette.ColorRole.ToolTipText: QColor(P["tooltip_fg"]),
        QPalette.ColorRole.PlaceholderText: muted,
        QPalette.ColorRole.Link: QColor(P["link"]),
        QPalette.ColorRole.LinkVisited: QColor(P["link"]),
        QPalette.ColorRole.Light: QColor(P["hover"]),
        QPalette.ColorRole.Midlight: QColor(P["line"]),
        QPalette.ColorRole.Mid: QColor(P["border"]),
        QPalette.ColorRole.Dark: QColor(P["shadow"]),
        QPalette.ColorRole.Shadow: QColor(P["shadow"]),
    }
    for role, color in roles.items():
        pal.setColor(role, color)

    # 禁用态：灰掉但不消失
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                 QColor(P["subtle"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight,
                 QColor(P["border"]))
    # 菜单栏、标签栏这类控件在深色下也许会被系统画成浅色，钉死
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(P["subtle"]))
    return pal


def current() -> str:
    return _current


def is_dark() -> bool:
    return _current == "dark"
