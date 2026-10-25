"""首次启动的欢迎框：先让用户选「创建资料库」或「打开已有资料库」。

以前是默默在程序目录建一个空库，用户既没被告知、也不知道笔记存在哪。
现在第一次打开先问一句，选完才继续启动；关掉窗口就退出程序。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from core.ui_state import default_library_path
from ui import msgbox
from ui.icons import app_icon
from ui.theme import P


class WelcomeDialog(QDialog):
    """返回值放在 `choice`：选中/创建的库路径；取消则为 None。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.choice: Optional[Path] = None
        self.setWindowTitle("归藏")
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setSizeGripEnabled(False)
        self._build()
        self.setStyleSheet(self._qss())
        self.setFixedWidth(480)
        self.adjustSize()

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        card = QFrame(self)
        card.setObjectName("WelcomeCard")
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(14)
        icon = QLabel(card)
        icon.setPixmap(app_icon().pixmap(46, 46))
        icon.setFixedSize(46, 46)
        head.addWidget(icon, 0, Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("归藏", card)
        title.setObjectName("WelcomeTitle")
        sub = QLabel("个人资料库", card)
        sub.setObjectName("WelcomeSub")
        titles.addWidget(title)
        titles.addWidget(sub)
        titles.addStretch(1)
        head.addLayout(titles, 1)

        lay.addLayout(head)
        lay.addSpacing(4)

        desc = QLabel(
            "整个资料库就是一个 .db 文件，笔记和附件都在里面。\n"
            "放在本地硬盘、U 盘或网盘同步目录都行，一个文件带走全部数据。",
            card)
        desc.setObjectName("WelcomeDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addSpacing(6)

        btn_create = QPushButton("创建资料库", card)
        btn_create.setObjectName("Primary")
        btn_create.setMinimumHeight(42)
        btn_create.setCursor(Qt.PointingHandCursor)
        btn_create.clicked.connect(self._create)
        lay.addWidget(btn_create)

        btn_open = QPushButton("打开已有资料库", card)
        btn_open.setObjectName("Ghost")
        btn_open.setMinimumHeight(42)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self._open)
        lay.addWidget(btn_open)

        tip = QLabel("创建会在你选的位置新建一个空库；打开会读取已有的 .db 文件。",
                     card)
        tip.setObjectName("WelcomeTip")
        tip.setWordWrap(True)
        lay.addWidget(tip)

    @staticmethod
    def _qss() -> str:
        return f"""
        #WelcomeCard {{
            background: {P["panel"]};
            border: 1px solid {P["border"]};
            border-radius: 12px;
        }}
        #WelcomeTitle {{
            font-size: 22px;
            font-weight: 700;
            color: {P["text"]};
        }}
        #WelcomeSub {{
            font-size: 12px;
            color: {P["muted"]};
        }}
        #WelcomeDesc {{
            font-size: 13px;
            color: {P["text"]};
            line-height: 150%;
        }}
        #WelcomeTip {{
            font-size: 12px;
            color: {P["muted"]};
        }}
        QPushButton#Primary {{
            background: {P["accent"]};
            border: 1px solid {P["accent"]};
            border-radius: 8px;
            color: {P["white"]};
            font-size: 14px;
            font-weight: 600;
        }}
        QPushButton#Primary:hover {{
            background: {P["accent"]};
            border-color: {P["accent"]};
        }}
        QPushButton#Ghost {{
            background: {P["btn_bg"]};
            border: 1px solid {P["border"]};
            border-radius: 8px;
            color: {P["text"]};
            font-size: 14px;
        }}
        QPushButton#Ghost:hover {{
            background: {P["btn_bg_hover"]};
            border-color: {P["shadow_hover"]};
        }}
        QPushButton#Ghost:pressed {{
            background: {P["btn_bg_pressed"]};
        }}
        """

    # -------------------------------------------------------------- 交互

    def _create(self) -> None:
        default = default_library_path()
        while True:
            path, _ = QFileDialog.getSaveFileName(
                self, "创建资料库", str(default), "归藏资料库 (*.db)")
            if not path:
                return
            target = Path(path)
            if target.suffix.lower() != ".db":
                target = target.with_suffix(".db")
            if not target.exists():
                break
            # 已有文件不能当新库，避免手一滑把旧笔记盖掉
            msgbox.warn(self, "创建资料库", f"{target.name} 已经存在。",
                        informative="换个文件名；要打开这个库请用「打开已有资料库」。")
        self.choice = target
        self.accept()

    def _open(self) -> None:
        default = default_library_path()
        path, _ = QFileDialog.getOpenFileName(
            self, "打开资料库", str(default.parent), "归藏资料库 (*.db)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".db":
            msgbox.warn(self, "打开资料库", "请选择 .db 格式的资料库文件。")
            return
        self.choice = target
        self.accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        screen = self.screen()
        if screen is not None:
            geo = self.frameGeometry()
            geo.moveCenter(screen.availableGeometry().center())
            self.move(geo.topLeft())
