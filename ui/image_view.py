"""内置图片预览。

图片附件直接在窗口里解码显示，不写磁盘 —— 资料库内容始终只存在于 .db 里。
默认按 1:1 原始像素显示（1 图像像素 = 1 屏幕物理像素），缩小时才做平滑处理，
放大时不会退化成最近邻插值，避免文字发糊。
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
    """看图窗：默认 1:1，Ctrl+滚轮缩放、拖动平移、双击切 1:1/适应。"""

    def __init__(self, name: str, image: QImage, size: int = 0,
                 parent: Optional[QWidget] = None,
                 on_save: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle(name or "图片")
        self.setObjectName("ImageView")
        self._pixmap = QPixmap.fromImage(image)
        self._scale = 1.0
        self._fit = False
        self._drag_from: Optional[QPoint] = None
        self._on_save = on_save
        self._info = f"{image.width()} × {image.height()}"
        if size:
            self._info += f" · {human_size(size)}"

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        self._screen_w = avail.width() if avail is not None else 1920
        self._screen_h = avail.height() if avail is not None else 1080
        self._max_w = int(self._screen_w * 0.94)
        self._max_h = int(self._screen_h * 0.9)

        self._build_ui(self._info)
        w = min(self._max_w, max(560, image.width() + 40))
        h = min(self._max_h, max(420, image.height() + 96))
        self.resize(w, h)
        # 打开即 1:1，图片比屏幕还大时才退一步适应窗口
        self._scale = 1.0
        self._render()
        self._fit_if_needed()

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
        self.area.viewport().setMouseTracking(True)

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
        btn_raw = QPushButton("1:1")
        btn_raw.setToolTip("按原始像素显示（快捷键 1）")
        btn_raw.clicked.connect(self._apply_raw)
        row.addWidget(btn_raw)
        btn_fit = QPushButton("适应窗口")
        btn_fit.setToolTip("缩放到完整可见（快捷键 0）")
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

    def _dpr(self) -> float:
        dpr = self.devicePixelRatioF()
        if not dpr or dpr <= 0:
            screen = QGuiApplication.primaryScreen()
            dpr = screen.devicePixelRatio() if screen is not None else 1.0
        return dpr or 1.0

    def _fit_scale(self) -> float:
        dpr = self._dpr()
        view_w = max(80, self.area.viewport().width() - 6) * dpr
        view_h = max(80, self.area.viewport().height() - 6) * dpr
        return min(view_w / max(1, self._pixmap.width()),
                   view_h / max(1, self._pixmap.height()), 1.0)

    def _fit_if_needed(self) -> None:
        """比屏幕还大的图先适应一次；屏幕放得下的图保持 1:1，宁可滚动也不缩字。"""
        limit_w = max(self._screen_w, 1280)
        limit_h = max(self._screen_h, 800)
        if self._pixmap.width() > limit_w or self._pixmap.height() > limit_h:
            self._apply_fit()

    def _apply_fit(self) -> None:
        if self._pixmap.isNull():
            return
        self._scale = self._fit_scale() or 1.0
        self._fit = True
        self._render()

    def _apply_raw(self) -> None:
        self._scale = 1.0
        self._fit = False
        self._render()

    def _zoom(self, factor: float, anchor: Optional[QPoint] = None) -> None:
        old = self._scale
        self._scale = max(0.05, min(8.0, self._scale * factor))
        if abs(self._scale - old) < 1e-6:
            return
        self._fit = False
        self._render()
        if anchor is not None:
            ratio = self._scale / old
            for bar, pos in ((self.area.horizontalScrollBar(), anchor.x()),
                             (self.area.verticalScrollBar(), anchor.y())):
                bar.setValue(int((bar.value() + pos) * ratio - pos))

    def _render(self) -> None:
        dpr = self._dpr()
        target_w = max(1, int(round(self._pixmap.width() * self._scale)))
        target_h = max(1, int(round(self._pixmap.height() * self._scale)))
        pm = self._pixmap
        if target_w != pm.width() or target_h != pm.height():
            # 放大用平滑，避免像素块；缩到 1/4 以下才退回快速插值
            mode = Qt.FastTransformation if self._scale < 0.25 else Qt.SmoothTransformation
            pm = pm.scaled(target_w, target_h, Qt.IgnoreAspectRatio, mode)
        pm.setDevicePixelRatio(dpr)
        self.label.setPixmap(pm)
        self.label.resize(max(1, int(round(target_w / dpr))),
                          max(1, int(round(target_h / dpr))))
        pct = int(round(self._scale * 100))
        suffix = "（适应窗口）" if self._fit else ""
        self.info_label.setText(f"{self._info} · {pct}%{suffix}")

    # --------------------------------------------------------------- 交互

    def wheelEvent(self, event):  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            pos = self.area.viewport().mapFrom(self, event.position().toPoint())
            self._zoom(1.25 if event.angleDelta().y() > 0 else 1 / 1.25, pos)
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

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._fit_if_needed()
        self._render()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom(1.25)
        elif key == Qt.Key_Minus:
            self._zoom(1 / 1.25)
        elif key == Qt.Key_0:
            self._apply_fit()
        elif key == Qt.Key_1:
            self._apply_raw()
        else:
            super().keyPressEvent(event)
