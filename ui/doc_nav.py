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
_MIN_GAP = 5           # 刻度最小间距（挤不下时自动压缩并等比抽样）
_HOVER_DELAY = 120     # 悬停多久后弹出预览（毫秒），太快划过不闪

_LEVEL_NAMES = {1: "一级标题", 2: "二级标题", 3: "三级标题",
                4: "四级标题", 5: "五级标题", 6: "六级标题"}


class _PreviewCard(QFrame):
    """悬停刻度时在导航条左侧弹出的详情卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("NavPreview")
        self.setFixedWidth(330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 12)
        lay.setSpacing(6)

        self._badge = QLabel(self)
        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._body = QLabel(self)
        self._body.setWordWrap(True)
        self._meta = QLabel(self)
        lay.addWidget(self._badge)
        lay.addWidget(self._title)
        lay.addWidget(self._body)
        lay.addWidget(self._meta)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"QFrame#NavPreview {{ background:{P['panel']};"
            f" border:1px solid {P['border']}; border-radius:8px; }}"
            f"QFrame#NavPreview QLabel {{ background:transparent; border:none; }}")
        self._badge.setStyleSheet(
            f"color:{P['accent']}; font-size:11px; font-weight:600;")
        self._title.setStyleSheet(
            f"color:{P['text']}; font-size:13px; font-weight:600;")
        self._body.setStyleSheet(
            f"color:{P['text']}; font-size:11px;")
        self._meta.setStyleSheet(
            f"color:{P['muted']}; font-size:10px;")

    def show_for(self, level: int, title: str, snippet: str,
                 meta: str, anchor: QPoint) -> None:
        self._badge.setText(f"H{level} · {_LEVEL_NAMES.get(level, '标题')}")
        self._title.setText(title.strip() or "（空标题）")
        self._body.setText(snippet or "（此标题下暂无正文）")
        self._body.setVisible(True)
        self._meta.setText(meta)
        self.adjustSize()

        # 贴在导航条左侧，垂直对齐鼠标；超出屏幕就夹回来
        x = anchor.x() - self.width() - 10
        y = anchor.y() - self.height() // 2
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
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

    def _section_info(self, idx: int, max_lines: int = 3,
                      max_chars: int = 200) -> Tuple[str, str]:
        """取某标题下的正文摘要与统计：返回 (摘要, "本节 N 段 · 约 M 字")。"""
        ed = self._edit
        if ed is None or not (0 <= idx < len(self._headings)):
            return "", ""
        doc = ed.document()
        block = doc.findBlockByNumber(self._headings[idx][1]).next()
        lines: List[str] = []
        chars = 0
        paras = 0
        while block.isValid():
            if int(block.blockFormat().headingLevel()) > 0:
                break                        # 到下一个标题为止
            text = block.text().strip()
            if text:
                paras += 1
                chars += len(text)
                if len(lines) < max_lines and sum(map(len, lines)) < max_chars:
                    lines.append(text)
            block = block.next()
        snippet = " ".join(lines)
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "…"
        if chars > 1200:
            size = f"约 {chars / 1000:.1f}k 字"
        else:
            size = f"约 {chars} 字"
        return snippet, f"本节 {paras} 段 · {size}"

    def _show_preview(self) -> None:
        idx = self._hover
        if self._edit is None or not (0 <= idx < len(self._headings)):
            return
        level, _bno, title = self._headings[idx]
        snippet, meta = self._section_info(idx)
        anchor = self.mapToGlobal(QPoint(0, self._ticks()[idx][0]))
        self._card.show_for(level, title, snippet, meta, anchor)

    def _hide_preview(self) -> None:
        self._show_timer.stop()
        self._card.hide()

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
            if idx >= 0:
                self._show_timer.start()     # 延迟弹出，快速划过不闪
            else:
                self._hide_preview()
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
