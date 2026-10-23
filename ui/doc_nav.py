"""文档导航条（编辑器右侧的刻度导航，模仿 WorkBuddy 的消息导航条）。

一串竖直排列的小刻度：文档里每个**标题**（# ~ ######）对应一条，越高级
的标题刻度越长。点击刻度直接跳到那个标题；随正文滚动，视口顶部所在的
标题会以高亮圆点指示当前位置；悬停可预览标题文字。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget

from ui.theme import P

_BAR_W = 26            # 整条宽度
_TICK_TOP = 14         # 上下留白
_MIN_GAP = 5           # 刻度最小间距（挤不下时自动压缩并等比抽样）


class DocNav(QWidget):
    """挂在 QTextEdit 右侧的标题刻度导航条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(_BAR_W)
        self._edit: Optional[QTextEdit] = None
        self._headings: List[Tuple[int, int, str]] = []   # (level, block_no, text)
        self._hover = -1
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(200)
        self._refresh.timeout.connect(self.reparse)
        self.setMouseTracking(True)

    # ------------------------------------------------------------ 绑定

    def attach(self, edit: QTextEdit) -> None:
        self._edit = edit
        edit.textChanged.connect(self._on_text_changed)
        sb = edit.verticalScrollBar()
        sb.valueChanged.connect(lambda _v: self.update())
        sb.rangeChanged.connect(lambda _a, _b: self.update())
        edit.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        # 视口尺寸变化时重排刻度
        if obj is self._edit and event.type() in (event.Type.Resize,):
            self.update()
        return False

    def _on_text_changed(self) -> None:
        self._refresh.start()            # 打字过程中 200ms 节流

    # ------------------------------------------------------------ 解析

    def reparse(self) -> None:
        """扫描文档里的标题块（带 200ms 节流，长文档也不卡）。"""
        self._headings = []
        ed = self._edit
        if ed is None:
            self.update()
            return
        doc = ed.document()
        block = doc.firstBlock()
        while block.isValid():
            lv = int(block.blockFormat().headingLevel())
            if lv > 0:
                self._headings.append((lv, block.blockNumber(),
                                       block.text()[:120]))
            block = block.next()
        self.update()

    # ------------------------------------------------------------ 几何

    def _ticks(self) -> List[Tuple[int, int]]:
        """返回 [(y 坐标, 索引)]。刻度等距均分，数量多时自动压缩。"""
        n = len(self._headings)
        if n == 0:
            return []
        h = self.height() - 2 * _TICK_TOP
        if n == 1:
            return [(_TICK_TOP, 0)]
        gap = h / (n - 1)
        return [(int(_TICK_TOP + i * gap), i) for i in range(n)]

    def _index_at(self, y: int) -> int:
        ticks = self._ticks()
        if not ticks:
            return -1
        return min(ticks, key=lambda t: abs(t[0] - y))[1]

    def _current_index(self) -> int:
        """视口顶部对应的标题索引（即滚动位置指示）。"""
        ed = self._edit
        if ed is None or not self._headings:
            return -1
        # 视口顶部在文档坐标里的 y = 滚动条值；用文档布局取各标题的 y
        top = ed.verticalScrollBar().value() + 2
        layout = ed.document().documentLayout()
        idx, best_y = -1, -1
        for i, (_lv, bno, _t) in enumerate(self._headings):
            block = ed.document().findBlockByNumber(bno)
            if not block.isValid():
                continue
            y = int(layout.blockBoundingRect(block).top())
            if y <= top and y > best_y:
                best_y, idx = y, i
        return idx

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._edit is None or not self._headings:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        base = QColor(P["branch"])
        cur = QColor(P["accent"])
        cur_idx = self._current_index()
        ticks = self._ticks()

        for y, i in ticks:
            lv = self._headings[i][0]
            length = {1: 16, 2: 14, 3: 12, 4: 10, 5: 9, 6: 8}.get(lv, 8)
            x2 = w - 6
            x1 = x2 - length
            if i == cur_idx:
                # 当前位置：小圆点 + 高亮刻度
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(cur)
                p.drawEllipse(QRect(x1 - 9, y - 2, 4, 4))
                p.fillRect(x1, y - 1, x2 - x1, 2, cur)
            else:
                color = QColor(P["muted"]) if i == self._hover else base
                p.setPen(QPen(color, 2))
                p.drawLine(x1, y, x2, y)
        p.end()

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._edit is None or event.button() != Qt.MouseButton.LeftButton:
            return
        idx = self._index_at(int(event.position().y()))
        if idx < 0 or idx >= len(self._headings):
            return
        _lv, bno, _t = self._headings[idx]
        doc = self._edit.document()
        block = doc.findBlockByNumber(bno)
        if not block.isValid():
            return
        c = QTextCursor(block)
        self._edit.setTextCursor(c)
        self._edit.ensureCursorVisible()
        self._edit.setFocus()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._index_at(int(event.position().y()))
        if idx != self._hover:
            self._hover = idx
            if 0 <= idx < len(self._headings):
                self.setToolTip(self._headings[idx][2])
            else:
                self.setToolTip("")
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor
                       if idx >= 0 else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.setToolTip("")
        self.update()
        super().leaveEvent(event)
