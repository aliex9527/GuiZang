"""Windows 深色标题栏。

QSS 只管客户区，窗口顶上那条标题栏（含右上角最小化/关闭按钮）由系统
绘制，默认永远是白的。Windows 10 1809 起提供了
``DWMWA_USE_IMMERSIVE_DARK_MODE`` 这个 DWM 属性，打开后系统会把标题栏
画成深色、标题文字改白。

这里做三件事：
- ``apply_to(widget)`` 给单个窗口设置（按当前主题决定开或关）；
- ``install(app)`` 装一个全局事件过滤器，任何顶层窗口一显示就自动套用，
  对话框不用逐个改；
- ``refresh_all()`` 切主题时把已经开着的窗口重刷一遍。

非 Windows 平台全部是空操作，调用方不必判断系统。
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

# 1809+ 用 20，更早的预览版是 19
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
# Win11 才支持：边框 / 标题栏 / 标题文字，让系统栏和客户区同色
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

_WM_SETREDRAW = 0x000B
_WM_NCACTIVATE = 0x0086
_RDW_INVALIDATE = 0x0001
_RDW_FRAME = 0x0400
_RDW_UPDATENOW = 0x0100


def supported() -> bool:
    return sys.platform.startswith("win")


def _colorref(hex_color: str) -> int:
    """#RRGGBB → Windows 的 COLORREF（0x00BBGGRR）。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 0
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def _set_int(dwm, hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return dwm.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd), ctypes.c_int(attr),
        ctypes.byref(v), ctypes.sizeof(v)) == 0


def apply_to(widget: QWidget, dark: bool | None = None) -> bool:
    """把窗口标题栏设成深色/浅色，返回是否成功。

    ``dark=None`` 时跟随当前主题。
    """
    if not supported() or widget is None:
        return False
    if dark is None:
        from ui import theme
        dark = theme.is_dark()

    try:
        hwnd = int(widget.winId())
    except (RuntimeError, TypeError):       # C++ 对象已销毁
        return False
    if not hwnd:
        return False

    dwm = ctypes.windll.dwmapi
    ok = False
    for attr in (_DWMWA_USE_IMMERSIVE_DARK_MODE,
                 _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
        if _set_int(dwm, hwnd, attr, 1 if dark else 0):
            ok = True
            break
    if not ok:
        return False

    # Win10 的深色标题栏是纯黑，没法改色；Win11 可以，顺手让它和界面同色，
    # 不支持时返回错误码，忽略即可（Win10 就是这种情况）。
    from ui import theme
    _set_int(dwm, hwnd, _DWMWA_CAPTION_COLOR, _colorref(theme.P["panel"]))
    _set_int(dwm, hwnd, _DWMWA_TEXT_COLOR, _colorref(theme.P["text"]))
    _set_int(dwm, hwnd, _DWMWA_BORDER_COLOR, _colorref(theme.P["border"]))

    _repaint_frame(hwnd)
    return True


def _repaint_frame(hwnd: int) -> None:
    """让标题栏按新的 DWM 属性重画一次。

    只改属性、再 SetWindowPos(SWP_FRAMECHANGED) 在 Windows 10 上不够——
    非客户区不会重画，标题栏仍然白着。实测有效的是给窗口发一对
    WM_NCACTIVATE：先发「激活」再发真实状态，两次状态不同才会重绘边框，
    末态仍是窗口本来的激活状态。中途关掉重绘避免闪一下。
    """
    user32 = ctypes.windll.user32
    active = 1 if user32.GetActiveWindow() == hwnd else 0
    user32.SendMessageW(ctypes.c_void_p(hwnd), _WM_SETREDRAW, 0, 0)
    user32.SendMessageW(ctypes.c_void_p(hwnd), _WM_NCACTIVATE, 1 - active, 0)
    user32.SendMessageW(ctypes.c_void_p(hwnd), _WM_NCACTIVATE, active, 0)
    user32.SendMessageW(ctypes.c_void_p(hwnd), _WM_SETREDRAW, 1, 0)
    user32.RedrawWindow(ctypes.c_void_p(hwnd), None, None,
                        _RDW_FRAME | _RDW_INVALIDATE | _RDW_UPDATENOW)


class _TitleBarFilter(QObject):
    """顶层窗口一显示就给标题栏上色，覆盖所有对话框。"""

    def eventFilter(self, obj, event):  # noqa: N802  Qt 命名
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget):
            try:
                if obj.isWindow():
                    apply_to(obj)
            except RuntimeError:
                pass
        return False


_filter: _TitleBarFilter | None = None
_filter_app: int | None = None


def install(app: QApplication | None = None) -> None:
    """装一次即可；重复调用无副作用。"""
    global _filter, _filter_app
    if not supported():
        return
    app = app or QApplication.instance()
    if app is None:
        return
    # 换了一个 QApplication（单元测试里常见）就重装，否则沿用已有的
    if _filter is not None and _filter_app == id(app):
        return
    _filter = _TitleBarFilter(app)
    _filter_app = id(app)
    app.installEventFilter(_filter)


def refresh_all() -> None:
    """主题切换后把所有已显示的窗口重刷一遍。"""
    if not supported():
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            if w.isWindow() and w.isVisible():
                apply_to(w)
        except RuntimeError:
            continue
