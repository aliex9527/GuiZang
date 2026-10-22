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


def current() -> str:
    return _current


def is_dark() -> bool:
    return _current == "dark"
