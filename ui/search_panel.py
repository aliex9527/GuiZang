"""搜索结果面板。"""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ui.theme import P


class ResultDelegate(QStyledItemDelegate):
    """两行式结果：主标题 + 灰色副标题。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 54)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            painter.setBrush(QColor(P["accent_soft"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 7, 7)
        elif hovered:
            painter.setBrush(QColor(P["row_hover"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 7, 7)

        title = index.data(Qt.DisplayRole) or ""
        sub = index.data(Qt.UserRole + 1) or ""
        badge = index.data(Qt.UserRole + 2) or ""

        inner = rect.adjusted(12, 8, -12, -8)
        fm = QFontMetrics(option.font)

        badge_w = 0
        if badge:
            bf = QFont(option.font)
            bf.setPixelSize(10)
            bf.setBold(True)
            bfm = QFontMetrics(bf)
            badge_w = bfm.horizontalAdvance(badge) + 12
            painter.setFont(bf)
            bp = QRect(inner.right() - badge_w, inner.top() + 1, badge_w, 16)
            painter.setBrush(QColor(P["accent_soft"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bp, 8, 8)
            painter.setPen(QColor(P["accent"]))
            painter.drawText(bp, Qt.AlignCenter, badge)

        tf = QFont(option.font)
        tf.setPixelSize(13)
        tf.setBold(True)
        painter.setFont(tf)
        painter.setPen(QColor(P["accent"] if selected else P["text"]))
        t_fm = QFontMetrics(tf)
        t_rect = QRect(inner.left(), inner.top(), inner.width() - badge_w - 8, 18)
        painter.drawText(t_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         t_fm.elidedText(title, Qt.ElideRight, t_rect.width()))

        sf = QFont(option.font)
        sf.setPixelSize(11)
        painter.setFont(sf)
        painter.setPen(QColor(P["muted"]))
        s_fm = QFontMetrics(sf)
        s_rect = QRect(inner.left(), inner.top() + 20, inner.width(), 16)
        painter.drawText(s_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         s_fm.elidedText(sub, Qt.ElideRight, s_rect.width()))
        painter.restore()


class SearchPanel(QWidget):
    nodeActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.list = QListWidget(self)
        self.list.setItemDelegate(ResultDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(1)
        self.list.itemDoubleClicked.connect(self._activate)
        self.list.itemActivated.connect(self._activate)
        lay.addWidget(self.list, 1)

        self.empty = QLabel("没有找到匹配的内容", self)
        self.empty.setObjectName("EmptyHint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        lay.addWidget(self.empty, 1)

    def clear(self) -> None:
        self.list.clear()

    def set_results(self, results: List[Dict[str, Any]], keyword: str) -> None:
        self.list.clear()
        for r in results:
            item = QListWidgetItem(r["title"] or "未命名")
            sub = r.get("path") or ""
            snip = (r.get("snippet") or "").strip()
            if snip:
                sub = f"{sub}   ·   {snip}"
            item.setData(Qt.UserRole, int(r["id"]))
            item.setData(Qt.UserRole + 1, sub)
            item.setData(Qt.UserRole + 2, r.get("hit") or "")
            item.setToolTip(sub)
            self.list.addItem(item)
        self.empty.setVisible(not results)
        self.list.setVisible(bool(results))
        if results:
            self.list.setCurrentRow(0)

    def _activate(self, item: QListWidgetItem) -> None:
        node_id = item.data(Qt.UserRole)
        if node_id is not None:
            self.nodeActivated.emit(int(node_id))
