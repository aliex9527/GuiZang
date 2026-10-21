"""跨平台字体统一：Windows / macOS / Linux 各用合适的 CJK 字体。"""

from __future__ import annotations

import sys

# 正文/界面用的无衬线中文字体族（按平台返回）
if sys.platform.startswith("win"):
    UI_FONT_FAMILY = "Microsoft YaHei UI"
    UI_FONT_STACK = "Microsoft YaHei UI", "Segoe UI", "PingFang SC", "sans-serif"
elif sys.platform == "darwin":
    UI_FONT_FAMILY = "PingFang SC"
    UI_FONT_STACK = "PingFang SC", "Helvetica Neue", "Microsoft YaHei UI", "sans-serif"
else:
    UI_FONT_FAMILY = "Noto Sans CJK SC"
    UI_FONT_STACK = "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"


def css_stack() -> str:
    """用于 QSS / HTML 里 font-family 的逗号分隔字体栈。"""
    return ", ".join(f'"{f}"' for f in UI_FONT_STACK)
