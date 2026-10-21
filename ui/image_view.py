"""内置图片预览。

图片附件直接在窗口里解码显示，不写磁盘 —— 资料库内容始终只存在于 .db 里。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core.storage import human_size
from ui.theme import P


class ImagePreview(QDialog):
    """最简单的看图窗：滚轮缩放、拖动平移、双击切原始/适应。"""

    def __init__(self, name: str, image: QImage, size: int = 0,
                 parent: Optional[QWidget] = None,
                 on_save: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle(name or "图片")
        self.setObjectName("ImageView")
        self._pixmap = QPixmap.fromImage(image)
        self._scale = 1.0
        self._fit = True
        self._drag_from: Optional[QPoint] = None
        self._on_save = on_save
        self._info = f"{image.width()} × {image.height()}"
        if size:
            self._info += f" · {human_size(size)}"

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        max_w = int(avail.width() * 0.86) if avail is not None else 1100
        max_h = int(avail.height() * 0.84) if avail is not None else 800
        self._avail = (max_w, max_h)

        self._build_ui(self._info)
        self.resize(min(max_w, max(560, image.width() + 48)),
                    min(max_h, max(420, image.height() + 96)))
        self._apply_fit()

    # ------------------------------------------------------------------ UI

    def _build_ui(self, info: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.area = QScrollArea(self)
        self.area.setObjectName("ImageArea")
        self.area.setWidgetResizable(False)
        self.area.setAlignment(Qt.AlignCenter)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.viewport().setCursor(Qt.OpenHandCursor)

        self.label = QLabel()
        self.label.setObjectName("ImageLabel")
        self.label.setAlignment(Qt.AlignCenter)
        self.area.setWidget(self.label)
        root.addWidget(self.area, 1)

        bar = QWidget()
        bar.setObjectName("ImageBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        self.info_label = QLabel(info)
        self.info_label.setObjectName("ImageInfo")
        row.addWidget(self.info_label)
        row.addStretch(1)

        if self._on_save is not None:
            btn_save = QPushButton("另存为…")
            btn_save.clicked.connect(lambda: self._on_save and self._on_save())
            row.addWidget(btn_save)
        btn_fit = QPushButton("适应窗口")
        btn_fit.clicked.connect(self._apply_fit)
        row.addWidget(btn_fit)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_close)
        root.addWidget(bar)

        self.area.viewport().installEventFilter(self)

        self.setStyleSheet(
            f"#ImageView {{ background: {P['bg']}; }}"
            f"#ImageArea {{ background: {P['bg']}; border: none; }}"
            f"#ImageLabel {{ background: transparent; }}"
            f"#ImageBar {{ background: {P['panel']};"
            f" border-top: 1px solid {P['border']}; }}"
            f"#ImageInfo {{ color: {P['muted']}; }}"
        )

    # --------------------------------------------------------------- 缩放

    def _apply_fit(self) -> None:
        w, h = self._pixmap.width(), self._pixmap.height()
        if not w or not h:
            return
        view_w = max(80, self.area.viewport().width() - 8)
        view_h = max(80, self.area.viewport().height() - 8)
        self._scale = min(view_w / w, view_h / h, 1.0)
        self._fit = True
        self._render()

    def _apply_raw(self) -> None:
        self._scale = 1.0
        self._fit = False
        self._render()

    def _zoom(self, factor: float) -> None:
        self._scale = max(0.05, min(8.0, self._scale * factor))
        self._fit = False
        self._render()

    def _render(self) -> None:
        w = max(1, int(self._pixmap.width() * self._scale))
        h = max(1, int(self._pixmap.height() * self._scale))
        smooth = not (self._scale >= 1.0)
        self.label.setPixmap(self._pixmap.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation if smooth else Qt.FastTransformation))
        self.label.resize(w, h)
        pct = int(round(self._scale * 100))
        self.info_label.setText(f"{self._info} · {pct}%" + ("（适应）" if self._fit else ""))

    # --------------------------------------------------------------- 交互

    def wheelEvent(self, event):  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            self._zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if self._fit:
            self._apply_raw()
        else:
            self._apply_fit()
        event.accept()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.area.viewport():
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_from = event.position().toPoint()
                self.area.viewport().setCursor(Qt.ClosedHandCursor)
                return True
            if event.type() == event.Type.MouseMove and self._drag_from is not None:
                delta = event.position().toPoint() - self._drag_from
                self._drag_from = event.position().toPoint()
                bar = self.area.horizontalScrollBar()
                var = self.area.verticalScrollBar()
                bar.setValue(bar.value() - delta.x())
                var.setValue(var.value() - delta.y())
                return True
            if event.type() == event.Type.MouseButtonRelease and self._drag_from is not None:
                self._drag_from = None
                self.area.viewport().setCursor(Qt.OpenHandCursor)
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self._apply_fit()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom(1.15)
        elif key == Qt.Key_Minus:
            self._zoom(1 / 1.15)
        elif key == Qt.Key_0:
            self._apply_fit()
        elif key == Qt.Key_1:
            self._apply_raw()
        else:
            super().keyPressEvent(event)
