"""快捷键自定义设置（编辑 → 自定义快捷键…）。

每个动作一行：动作名 + QKeySequenceEdit 录制框 + 清除 / 恢复默认。
冲突检测：两行录了同一个键时保存会被拦截并高亮提示。自定义结果写进
库 meta（``ui.shortcuts``），未改动的动作不落盘（跟着默认值走）。
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ui.keymap import ACTIONS
from ui.theme import P


class KeymapDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self.setWindowTitle("自定义快捷键")
        self.resize(620, 680)
        self._rows: List[tuple] = []      # (table_row, action_id, editor, btn_clear, btn_reset)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        tip = QLabel("点击「按下新键」框后直接按组合键即可录制；留空表示禁用该快捷键。", self)
        tip.setStyleSheet(f"color:{P['muted']}; font-size:11px;")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        groups = []
        for a in ACTIONS:
            if not groups or groups[-1][0] != a.group:
                groups.append((a.group, []))
            groups[-1][1].append(a)

        table = QTableWidget(self)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["动作", "快捷键", "操作"])
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 180)
        table.setColumnWidth(2, 160)
        table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)

        total = len(ACTIONS) + len(groups)
        table.setRowCount(total)
        row = 0
        for gname, acts in groups:
            it = QTableWidgetItem(gname)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setBackground(Qt.GlobalColor.transparent)
            table.setItem(row, 0, it)
            table.setSpan(row, 0, 1, 3)
            table.setRowHeight(row, 26)
            row += 1
            for a in acts:
                name_it = QTableWidgetItem(a.name)
                name_it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row, 0, name_it)
                table.setRowHeight(row, 30)

                ed = QKeySequenceEditWrap(self, view.key_for_action(a.id))
                table.setCellWidget(row, 1, ed)
                btns = QWidget(self)
                bh = QHBoxLayout(btns)
                bh.setContentsMargins(0, 0, 0, 0)
                bh.setSpacing(4)
                b_clear = QPushButton("清除", btns)
                b_clear.setToolTip("禁用这个快捷键")
                b_clear.clicked.connect(lambda _c=False, e=ed: e.setKeySequence(QKeySequence()))
                b_reset = QPushButton("默认", btns)
                b_reset.setToolTip("恢复默认键位")
                b_reset.clicked.connect(lambda _c=False, e=ed, d=a.default: e.setKeySequence(QKeySequence(d)))
                bh.addWidget(b_clear)
                bh.addWidget(b_reset)
                bh.addStretch(1)
                table.setCellWidget(row, 2, btns)
                self._rows.append((row, a.id, ed))
                row += 1

        self._table = table
        lay.addWidget(table, 1)

        self._conflict_label = QLabel("", self)
        self._conflict_label.setStyleSheet("color:#b45309; font-size:11px;")
        self._conflict_label.setWordWrap(True)
        lay.addWidget(self._conflict_label)

        row_lay = QHBoxLayout()
        b_all_default = QPushButton("全部恢复默认", self)
        b_all_default.clicked.connect(self._reset_all)
        row_lay.addWidget(b_all_default)
        row_lay.addStretch(1)
        b_cancel = QPushButton("取消", self)
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton("保存", self)
        b_ok.setObjectName("Primary")
        b_ok.clicked.connect(self._save)
        row_lay.addWidget(b_cancel)
        row_lay.addWidget(b_ok)
        lay.addLayout(row_lay)

    # ------------------------------------------------------------ 保存

    def _collect(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for _, aid, ed in self._rows:
            seq = ed.keySequence()
            out[aid] = seq.toString(QKeySequence.NativeText) if seq.count() else ""
        return out

    def _find_conflicts(self, mapping: Dict[str, str]) -> List[str]:
        owners: Dict[str, List[str]] = {}
        name_of = {a.id: a.name for a in ACTIONS}
        for aid, seq in mapping.items():
            if seq:
                owners.setdefault(seq, []).append(name_of.get(aid, aid))
        return [f"{'、'.join(names)} 都绑在 {seq}"
                for seq, names in owners.items() if len(names) > 1]

    def _save(self) -> None:
        mapping = self._collect()
        conflicts = self._find_conflicts(mapping)
        if conflicts:
            self._conflict_label.setText("冲突：" + "；".join(conflicts))
            return
        self._view._write_custom_shortcuts(mapping)
        self._view.reload_shortcuts()
        self.accept()

    def _reset_all(self) -> None:
        for _, aid, ed in self._rows:
            for a in ACTIONS:
                if a.id == aid:
                    ed.setKeySequence(QKeySequence(a.default))
        self._conflict_label.setText("")


class QKeySequenceEditWrap(QWidget):
    """QKeySequenceEdit + 展示当前值；包一层免得表格里样式突兀。"""

    def __init__(self, parent=None, initial: str = ""):
        super().__init__(parent)
        from PySide6.QtWidgets import QKeySequenceEdit as _E
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self._ed = _E(self)
        if initial:
            self._ed.setKeySequence(QKeySequence(initial))
        lay.addWidget(self._ed)

    def keySequence(self) -> QKeySequence:
        return self._ed.keySequence()

    def setKeySequence(self, seq: QKeySequence) -> None:
        self._ed.setKeySequence(seq)
