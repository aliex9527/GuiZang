"""统一的 QMessageBox 外观：按钮底色加深、整排按钮水平居中、按钮文字中文。

Qt 自己画的 QMessageBox 有两个毛病：
1. 全局 QSS 里 `QPushButton { background: transparent }`，提示框的按钮因此没有底色，
   跟对话框白底连成一片，看不出按钮边界；
2. 按钮默认右对齐，中文短文案下看着偏。

这里把两件事收在一处：`decorate()` 负责样式与居中，`ask()` / `say()` 系列负责
用自定义中文按钮替换 Qt 内置的 Yes/No/OK。

注意 QMessageBox 的按钮排在内部 QDialogButtonBox 里，`setCenterButtons(True)`
才是官方支持的居中方式（改 QSS 的 text-align 对按钮排版无效）。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox, QWidget

from ui.theme import P


def qss() -> str:
    """消息框按钮样式：比面板深一档的底色，悬停/按下各深一级。"""
    return f"""
    QMessageBox {{
        background: {P["panel"]};
    }}
    QMessageBox QLabel {{
        color: {P["text"]};
    }}
    QMessageBox QPushButton {{
        background: {P["btn_bg"]};
        border: 1px solid {P["border"]};
        border-radius: 6px;
        padding: 5px 16px;
        min-width: 64px;
        color: {P["text"]};
    }}
    QMessageBox QPushButton:hover {{
        background: {P["btn_bg_hover"]};
        border-color: {P["shadow_hover"]};
    }}
    QMessageBox QPushButton:pressed {{
        background: {P["btn_bg_pressed"]};
    }}
    QMessageBox QPushButton:default {{
        border-color: {P["accent_line"]};
    }}
    QMessageBox QPushButton:focus {{
        border-color: {P["accent"]};
        outline: none;
    }}
    """


def decorate(box: QMessageBox) -> None:
    """给一个已经建好按钮的消息框套样式，并把按钮排到正中间。"""
    box.setStyleSheet(qss())
    bb = box.findChild(QDialogButtonBox)
    if bb is not None:
        bb.setCenterButtons(True)


def ask(parent: Optional[QWidget],
        title: str,
        text: str,
        *,
        informative: str = "",
        ok: str = "确定",
        cancel: str = "取消",
        danger: bool = False,
        default_ok: bool = False) -> bool:
    """问一个「确定 / 取消」问题，返回用户是否点了确定。

    danger=True 时图标换成警告、确定键放到右侧并且不做默认键——
    删除类操作不该回车就过。
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    role_ok = (QMessageBox.ButtonRole.DestructiveRole if danger
               else QMessageBox.ButtonRole.AcceptRole)
    btn_ok = box.addButton(ok, role_ok)
    btn_cancel = box.addButton(cancel, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_ok if default_ok and not danger else btn_cancel)
    box.setEscapeButton(btn_cancel)
    if danger:
        # 危险操作里焦点也放在「取消」上：回车、空格都不会误删
        btn_cancel.setFocus()
    decorate(box)
    box.exec()
    return box.clickedButton() is btn_ok


def say(parent: Optional[QWidget],
        title: str,
        text: str,
        *,
        informative: str = "",
        icon: QMessageBox.Icon = QMessageBox.Icon.Information) -> None:
    """只有一个「确定」的提示框（信息 / 警告 / 错误共用）。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(icon)
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    btn = box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(btn)
    box.setEscapeButton(btn)
    decorate(box)
    box.exec()


def info(parent: Optional[QWidget], title: str, text: str,
         *, informative: str = "") -> None:
    say(parent, title, text, informative=informative)


def warn(parent: Optional[QWidget], title: str, text: str,
         *, informative: str = "") -> None:
    say(parent, title, text, informative=informative, icon=QMessageBox.Icon.Warning)


def error(parent: Optional[QWidget], title: str, text: str,
          *, informative: str = "") -> None:
    say(parent, title, text, informative=informative, icon=QMessageBox.Icon.Critical)
