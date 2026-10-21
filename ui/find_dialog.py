"""笔记内查找 / 替换对话框（Ctrl+F / Ctrl+H）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from ui.theme import P


class FindReplaceDialog(QDialog):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor_widget = editor          # NoteEditor
        self.setWindowTitle("查找与替换")
        self.setModal(False)
        self.setMinimumWidth(430)
        self._build_ui()

    @property
    def edit(self):
        return self.editor_widget.edit

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.addWidget(QLabel("查找", self), 0, 0)
        self.find_edit = QLineEdit(self)
        self.find_edit.setPlaceholderText("要查找的文字")
        grid.addWidget(self.find_edit, 0, 1)
        grid.addWidget(QLabel("替换为", self), 1, 0)
        self.repl_edit = QLineEdit(self)
        self.repl_edit.setPlaceholderText("替换成…")
        grid.addWidget(self.repl_edit, 1, 1)
        lay.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in (("查找下一个", self.find_next),
                           ("查找上一个", lambda: self.find_next(True)),
                           ("替换", self.replace_one),
                           ("全部替换", self.replace_all)):
            b = QPushButton(text, self)
            b.setObjectName("Ghost")
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("关闭", self)
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)

        self.status = QLabel("", self)
        self.status.setStyleSheet(f"color:{P['muted']}; font-size:11px;")
        lay.addWidget(self.status)

        self.find_edit.textChanged.connect(lambda _t: self.status.setText(""))

    # ------------------------------------------------------------ 操作

    def _needle(self) -> str:
        return self.find_edit.text()

    def find_next(self, backward: bool = False) -> None:
        needle = self._needle()
        if not needle:
            self.find_edit.setFocus()
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        found = self.edit.document().find(needle, self.edit.textCursor(), flags)
        if found.isNull():
            # 从头/尾再找一遍
            cur = QTextCursor(self.edit.document())
            if backward:
                cur.movePosition(QTextCursor.End)
            found = self.edit.document().find(needle, cur, flags)
        if found.isNull():
            self.status.setText("没有找到")
            return
        self.edit.setTextCursor(found)
        self.edit.setFocus()
        self.status.setText("")

    def replace_one(self) -> None:
        needle = self._needle()
        if not needle:
            return
        cur = self.edit.textCursor()
        if cur.hasSelection() and cur.selectedText() == needle:
            cur.insertText(self.repl_edit.text())
            self.edit.setTextCursor(cur)
        self.find_next()

    def replace_all(self) -> int:
        needle = self._needle()
        if not needle:
            return 0
        repl = self.repl_edit.text()
        doc = self.edit.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        count = 0
        while True:
            found = doc.find(needle, cur)
            if found.isNull():
                break
            found.insertText(repl)
            cur = found
            count += 1
        cur.endEditBlock()
        self.status.setText(f"已替换 {count} 处")
        return count

    def open_for(self, replace: bool = False) -> None:
        cur = self.edit.textCursor()
        if cur.hasSelection():
            self.find_edit.setText(cur.selectedText().replace("\u2029", " "))
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        if replace:
            self.repl_edit.setFocus()
        self.show()
        self.raise_()
        self.activateWindow()
