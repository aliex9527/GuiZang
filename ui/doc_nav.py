"""文档导航条（编辑器右侧的刻度导航，模仿 WorkBuddy 的消息导航条）。

一串竖直排列的小刻度：文档里每个**标题**（# ~ ######）对应一条，越高级
的标题刻度越长。点击刻度直接跳到那个标题；随正文滚动，视口顶部所在的
标题会以高亮圆点指示当前位置；悬停可预览标题文字。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QTextEdit,
                               QVBoxLayout, QWidget)

from ui.theme import P

_BAR_W = 26            # 整条宽度
_TICK_TOP = 14         # 上下留白
_TICK_GAP = 12         # 刻度固定间距（标题少时也紧凑排列，不拉伸出空隙）
_MIN_GAP = 4           # 标题太多挤不下时的最小间距
_HOVER_DELAY = 120     # 悬停多久后弹出预览（毫秒），太快划过不闪
_LIST_MAX = 42         # 预览列表最多显示多少行（超出按当前项开窗）

class _PreviewCard(QFrame):
    """悬停刻度时在导航条左侧弹出的**整列标题列表**（当前行加粗高亮）。"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("NavPreview")
        self.setFixedWidth(360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 8, 8)
        lay.setSpacing(0)

        self._list = QLabel(self)
        self._list.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        self._list.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._list)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"QFrame#NavPreview {{ background:{P['panel']};"
            f" border:1px solid {P['border']}; border-radius:10px; }}"
            f"QFrame#NavPreview QLabel {{ background:transparent; border:none; }}")

    def show_list(self, headings: List[Tuple[int, int, str]], active: int,
                  anchor: QPoint, max_h: int = 780) -> None:
        """渲染整列标题；行距紧凑，无空隙。当前项加粗、横线加粗。"""
        import html as _html

        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            max_h = min(max_h, int(screen.availableGeometry().height() * 0.85))
        # 每行约 19px，按屏幕高度决定最多显示多少行
        row_limit = max(8, min(_LIST_MAX, (max_h - 26) // 19))

        total = len(headings)
        start = 0
        end = total
        if total > row_limit:
            start = max(0, active - row_limit // 2)
            end = min(total, start + row_limit)
            start = max(0, end - row_limit)

        rows: List[str] = []
        rows.append("<table width='100%' cellspacing='0' cellpadding='0'>")
        if start > 0:
            rows.append(
                f"<tr><td align='right' style='padding:1px 4px 1px 0;"
                f"color:{P['muted']};font-size:10px;'>… 上方还有 {start} 个标题</td>"
                f"<td style='color:{P['border']};'> </td></tr>")
        name_max = 26
        for i in range(start, end):
            _lv, _bno, title = headings[i]
            name = (title or "").strip() or "（空标题）"
            if len(name) > name_max:
                name = name[:name_max] + "…"
            name = _html.escape(name)
            if i == active:
                rows.append(
                    f"<tr><td align='right' style='padding:1px 5px 1px 0;"
                    f"color:{P['text']};font-size:12px;font-weight:700;'>{name}</td>"
                    f"<td width='10' style='color:{P['text']};font-size:12px;"
                    f"font-weight:700;'>—</td></tr>")
            else:
                rows.append(
                    f"<tr><td align='right' style='padding:1px 5px 1px 0;"
                    f"color:{P['muted']};font-size:12px;'>{name}</td>"
                    f"<td width='10' style='color:{P['border']};font-size:12px;'>—</td></tr>")
        if end < total:
            rows.append(
                f"<tr><td align='right' style='padding:1px 4px 1px 0;"
                f"color:{P['muted']};font-size:10px;'>… 下方还有 {total - end} 个标题</td>"
                f"<td style='color:{P['border']};'> </td></tr>")
        rows.append("</table>")
        self._list.setText("".join(rows))
        self.adjustSize()

        # 贴在导航条左侧，垂直对齐鼠标；超出屏幕就夹回来
        x = anchor.x() - self.width() - 8
        y = anchor.y() - self.height() // 2
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left() + 6, min(x, geo.right() - self.width() - 6))
            y = max(geo.top() + 6, min(y, geo.bottom() - self.height() - 6))
        self.move(x, y)
        self.show()


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

        # 悬停预览：延迟一点弹出，避免鼠标快速划过时闪一堆卡片
        self._card = _PreviewCard()
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(_HOVER_DELAY)
        self._show_timer.timeout.connect(self._show_preview)
        self.setMouseTracking(True)

    # ------------------------------------------------------------ 绑定

    def attach(self, edit: QTextEdit) -> None:
        self._edit = edit
        edit.textChanged.connect(self._on_text_changed)
        sb = edit.verticalScrollBar()
        sb.valueChanged.connect(lambda _v: (self.update(), self._hide_preview()))
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
        self._hide_preview()             # 标题结构变了，旧预览已失效
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
        """返回 [(y 坐标, 索引)]。

        刻度按**固定间距**紧凑排列（标题少时不铺满整条、不留大空隙），
        整体在竖条里垂直居中；标题多到挤不下时才等比压缩间距。
        """
        n = len(self._headings)
        if n == 0:
            return []
        h = self.height() - 2 * _TICK_TOP
        if n == 1:
            return [(self.height() // 2, 0)]
        gap = float(_TICK_GAP)
        if (n - 1) * gap > h:
            gap = max(float(_MIN_GAP), h / (n - 1))
        total = (n - 1) * gap
        start = _TICK_TOP + max(0.0, (h - total) / 2)
        return [(int(start + i * gap), i) for i in range(n)]

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

    def _show_preview(self) -> None:
        idx = self._hover
        if self._edit is None or not self._headings or not (0 <= idx < len(self._headings)):
            return
        anchor = self.mapToGlobal(QPoint(0, self._ticks()[idx][0]))
        budget = self.height() - 8            # 不超出编辑器可视高度
        if self._edit is not None and self._edit.height() > 0:
            budget = min(budget, self._edit.height() - 8)
        self._card.show_list(self._headings, idx, anchor,
                             max_h=max(260, budget))

    def _hide_preview(self) -> None:
        self._show_timer.stop()
        try:
            self._card.hide()
        except RuntimeError:          # 退出时 C++ 对象已销毁
            pass

    def refresh_theme(self) -> None:
        """主题切换后重刷预览卡片配色。"""
        self._card._apply_style()
        self.update()

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._edit is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._hide_preview()
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
            self.update()
            if idx < 0:
                self._hide_preview()
            elif self._card.isVisible():
                self._show_preview()     # 列表已展开：跟着滑动即时切换高亮行
            else:
                self._show_timer.start() # 首次悬停：延迟弹出，快速划过不闪
        self.setCursor(Qt.CursorShape.PointingHandCursor
                       if idx >= 0 else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self._hide_preview()
        self.update()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_preview()
        super().hideEvent(event)
