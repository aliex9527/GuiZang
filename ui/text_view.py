"""内置文本预览：文本类附件在窗口里直接读，不写磁盘。"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from core.storage import human_size
from ui.theme import P

# 超过这个体积只显示开头一段，避免一次性占满内存
SOFT_LIMIT = 4 * 1024 * 1024
SHOW_LIMIT = 2 * 1024 * 1024

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1")


def decode_text(data: bytes) -> Tuple[str, str]:
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace"), "utf-8(replace)"


class TextPreview(QDialog):
    def __init__(self, name: str, data: bytes, size: int = 0,
                 parent: Optional[QWidget] = None,
                 on_save: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle(name or "文本")
        self.setObjectName("TextView")
        self._on_save = on_save

        raw = data
        truncated = False
        if len(raw) > SOFT_LIMIT:
            raw = raw[:SHOW_LIMIT]
            truncated = True
        text, self._encoding = decode_text(raw)
        lines = text.count("\n") + 1

        info = f"{name} · {lines} 行 · {human_size(size or len(data))} · {self._encoding}"
        if truncated:
            info += f" · 仅显示前 {human_size(SHOW_LIMIT)}"

        self._build_ui(info)
        self.editor.setPlainText(text)

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        w = int(avail.width() * 0.78) if avail is not None else 1000
        h = int(avail.height() * 0.8) if avail is not None else 720
        self.resize(max(640, min(w, 1200)), max(460, min(h, 900)))

    def _build_ui(self, info: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("TextHead")
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(14, 10, 14, 10)
        self.info_label = QLabel(info)
        self.info_label.setObjectName("TextInfo")
        hrow.addWidget(self.info_label)
        hrow.addStretch(1)
        root.addWidget(head)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("TextBody")
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(10)
        self.editor.setFont(mono)
        root.addWidget(self.editor, 1)

        bar = QWidget()
        bar.setObjectName("TextBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.wrap_box = QCheckBox("自动换行")
        self.wrap_box.toggled.connect(self._toggle_wrap)
        row.addWidget(self.wrap_box)
        row.addStretch(1)
        if self._on_save is not None:
            btn_save = QPushButton("另存为…")
            btn_save.clicked.connect(lambda: self._on_save and self._on_save())
            row.addWidget(btn_save)
        btn_copy = QPushButton("全选复制")
        btn_copy.clicked.connect(self._copy_all)
        row.addWidget(btn_copy)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_close)
        root.addWidget(bar)

        self.setStyleSheet(
            f"#TextView {{ background: {P['panel']}; }}"
            f"#TextHead {{ background: {P['panel']};"
            f" border-bottom: 1px solid {P['border']}; }}"
            f"#TextInfo {{ color: {P['muted']}; }}"
            f"#TextBody {{ background: {P['bg']}; color: {P['text']};"
            f" border: none; padding: 8px;"
            f" selection-background-color: {P['accent']}; }}"
            f"#TextBar {{ background: {P['panel']};"
            f" border-top: 1px solid {P['border']}; }}"
        )

    def _toggle_wrap(self, on: bool) -> None:
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)

    def _copy_all(self) -> None:
        self.editor.selectAll()
        self.editor.copy()
        cursor = self.editor.textCursor()
        cursor.clearSelection()
        self.editor.setTextCursor(cursor)


def preview_text(parent: Optional[QWidget], name: str, data: bytes, size: int = 0,
                 on_save: Optional[Callable[[], None]] = None) -> bool:
    dlg = TextPreview(name, data, size or len(data), parent, on_save)
    dlg.exec()
    return True
