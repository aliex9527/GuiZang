"""附件面板：任意格式文件入库、打开、另存、重命名、删除。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from core.database import Database
from core.storage import ext_of, human_size
from ui.icons import chip_icon
from ui.theme import P


class AttachmentPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._node_id: Optional[int] = None
        self.setObjectName("AttachPanel")
        # 自定义 QWidget 子类必须开这个属性，QSS 才会画背景
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget(self)
        head.setObjectName("EditorHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 8, 10, 8)
        hl.setSpacing(4)

        self.title_label = QLabel("附件", head)
        self.title_label.setObjectName("PanelTitle")
        hl.addWidget(self.title_label)
        hl.addStretch(1)

        self.btn_add = QToolButton(head)
        self.btn_add.setText("添加文件")
        self.btn_add.setToolTip("选择文件加入当前条目，或直接把文件拖进来")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.pick_files)
        hl.addWidget(self.btn_add)

        root.addWidget(head)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["名称", "大小", "添加时间"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(26, 26))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(38)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 62)
        self.table.setColumnWidth(2, 96)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        self.table.installEventFilter(self)

        self.empty_label = QLabel("把文件拖进这里\n任何格式都会存进库", self)
        self.empty_label.setObjectName("EmptyHint")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()

        root.addWidget(self.table, 1)
        root.addWidget(self.empty_label, 1)

    # --------------------------------------------------------------- 数据

    def set_node(self, node_id: Optional[int]) -> None:
        self._node_id = node_id
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        has_node = self._node_id is not None
        self.btn_add.setEnabled(has_node)
        rows = self.db.files_of(self._node_id) if has_node else []
        self.title_label.setText(f"附件 · {len(rows)}" if has_node else "附件")
        for r in rows:
            self._add_row(r)
        if has_node and rows:
            self.table.setVisible(True)
            self.empty_label.setVisible(False)
            self.table.selectRow(0)
        else:
            self.table.setVisible(False)
            self.empty_label.setVisible(True)
            self.empty_label.setText(
                "把文件拖进这里\n任何格式都会存进库" if has_node
                else "选中左侧条目后可添加附件")
        self.changed.emit()

    def _add_row(self, row) -> None:
        i = self.table.rowCount()
        self.table.insertRow(i)

        ext = ext_of(row["name"]).lstrip(".").upper() or "文件"
        name_item = QTableWidgetItem(row["name"])
        name_item.setIcon(chip_icon(row["name"]))
        name_item.setData(Qt.UserRole, row["id"])
        name_item.setToolTip(f"{row['name']}\n{ext} · {human_size(row['size'])}")
        self.table.setItem(i, 0, name_item)

        size_item = QTableWidgetItem(human_size(row["size"]))
        size_item.setForeground(QColor(P["muted"]))
        size_item.setToolTip(human_size(row["size"]))
        self.table.setItem(i, 1, size_item)

        time_item = QTableWidgetItem((row["created_at"] or "")[5:16])
        time_item.setForeground(QColor(P["muted"]))
        self.table.setItem(i, 2, time_item)

    def _selected_ids(self) -> List[int]:
        ids = []
        model = self.table.selectionModel()
        if model is None:
            return ids
        for idx in model.selectedRows():
            item = self.table.item(idx.row(), 0)
            if item is not None:
                ids.append(int(item.data(Qt.UserRole)))
        return ids

    def _current_file_id(self) -> Optional[int]:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return None
        item = self.table.item(min(rows), 0)
        return int(item.data(Qt.UserRole)) if item else None

    # ------------------------------------------------------------ 增删改开

    def pick_files(self) -> None:
        if self._node_id is None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "添加文件", "", "所有文件 (*.*)")
        if files:
            self.add_paths([Path(f) for f in files])

    def add_paths(self, paths: List[Path]) -> int:
        if self._node_id is None:
            return 0
        added, failed = 0, []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in paths:
                try:
                    if not p.is_file():
                        continue
                    name = self.db.unique_attachment_name(self._node_id, p.name)
                    self.db.add_file(self._node_id, p, display_name=name)
                    added += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{p.name}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        if added:
            self.refresh()
            self.status.emit(f"已添加 {added} 个文件")
        if failed:
            QMessageBox.warning(self, "部分文件未能添加", "\n".join(failed[:10]))
        return added

    def open_selected(self) -> None:
        fid = self._current_file_id()
        if fid is None:
            return
        path = self.db.path_of_file(fid)
        if path is None:
            QMessageBox.warning(self, "文件不存在", "附件内容在库里缺失。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def save_as(self) -> None:
        fid = self._current_file_id()
        if fid is None:
            return
        row = self.db.get_file(fid)
        data = self.db.blob_bytes(fid)
        if row is None or data is None:
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存为", row["name"])
        if not target:
            return
        try:
            Path(target).write_bytes(data)
            self.status.emit(f"已另存为 {target}")
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def rename(self) -> None:
        fid = self._current_file_id()
        if fid is None:
            return
        row = self.db.get_file(fid)
        if row is None:
            return
        new_name, ok = QInputDialog.getText(self, "重命名附件", "名称：", text=row["name"])
        if ok and new_name.strip():
            self.db.rename_file(fid, new_name.strip())
            self.refresh()

    def reveal(self) -> None:
        fid = self._current_file_id()
        path = self.db.path_of_file(fid) if fid else None
        if path is None:
            return
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        names = [self.db.get_file(i)["name"] for i in ids if self.db.get_file(i)]
        if QMessageBox.question(
                self, "删除附件",
                f"确定删除 {len(ids)} 个附件？\n\n" + "\n".join(names[:8])
                + ("\n…" if len(names) > 8 else ""),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        for fid in ids:
            self.db.delete_file(fid)
        self.refresh()
        self.status.emit(f"已删除 {len(ids)} 个附件")

    def copy_name(self) -> None:
        fid = self._current_file_id()
        if fid is None:
            return
        row = self.db.get_file(fid)
        if row:
            QGuiApplication.clipboard().setText(row["name"])

    # -------------------------------------------------------------- 交互

    def _show_menu(self, pos) -> None:
        if self.table.rowCount() == 0:
            return
        menu = QMenu(self)
        menu.addAction("打开", self.open_selected)
        menu.addAction("另存为…", self.save_as)
        menu.addAction("重命名…", self.rename)
        menu.addAction("复制名称", self.copy_name)
        menu.addAction("在资源管理器中显示", self.reveal)
        menu.addSeparator()
        menu.addAction("删除", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.table and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.open_selected()
                return True
            if event.key() == Qt.Key_Delete:
                self.delete_selected()
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------------------- 拖放

    def dragEnterEvent(self, event):  # noqa: N802
        if self._node_id is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._node_id is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        if self._node_id is None or not event.mimeData().hasUrls():
            return
        paths: List[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths.extend(sorted([f for f in p.iterdir() if f.is_file()]))
            else:
                paths.append(p)
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
