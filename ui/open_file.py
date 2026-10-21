"""统一附件打开入口。

任何附件都不会被释放到临时目录：能在库内预览的（图片、文本）直接在窗口里看，
其余格式只能「另存为」到用户自己指定的位置再打开 —— 数据始终只在 .db 里。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from core.database import Database
from core.storage import TEXT_EXTS, ext_of

# QImage 一次解码的上限，超过就只提示另存为（避免超大图吃光内存）
IMAGE_MAX_BYTES = 128 * 1024 * 1024


def save_attachment(parent: Optional[QWidget], db: Database, file_id: int) -> Optional[str]:
    """另存到用户指定位置；返回保存路径（取消则为 None）。"""
    row = db.get_file(file_id)
    data = db.blob_bytes(file_id)
    if row is None or data is None:
        QMessageBox.warning(parent, "文件不存在", "附件内容在库里缺失。")
        return None
    target, _ = QFileDialog.getSaveFileName(parent, "另存为", row["name"])
    if not target:
        return None
    try:
        Path(target).write_bytes(data)
    except OSError as exc:
        QMessageBox.critical(parent, "保存失败", str(exc))
        return None
    return target


def _offer_save(parent: Optional[QWidget], db: Database, file_id: int, name: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("无法在库内预览")
    box.setIcon(QMessageBox.Information)
    box.setText(f"「{name}」这种格式需要本机对应程序才能打开。")
    box.setInformativeText(
        "归藏的附件全部存在 .db 里，不会释放到临时目录。\n"
        "需要外部程序打开时，请先另存到你自己的目录。")
    btn_save = box.addButton("另存为…", QMessageBox.AcceptRole)
    box.addButton("关闭", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is btn_save:
        save_attachment(parent, db, file_id)


def open_attachment(parent: Optional[QWidget], db: Database, file_id: int,
                    allow_preview: bool = True) -> None:
    row = db.get_file(file_id)
    if row is None:
        QMessageBox.warning(parent, "文件不存在", "这个附件已被删除。")
        return
    data = db.blob_bytes(file_id)
    if data is None:
        QMessageBox.warning(parent, "文件不存在", "附件内容在库里缺失。")
        return

    name = row["name"] or ""
    ext = ext_of(name)
    size = row["size"] or len(data)

    if allow_preview:
        # 图片：能解码就内置预览
        if len(data) <= IMAGE_MAX_BYTES:
            image = QImage.fromData(data)
            if not image.isNull():
                from ui.image_view import ImagePreview
                ImagePreview(name, image, size, parent,
                             on_save=lambda: save_attachment(parent, db, file_id)).exec()
                return
        # 文本 / 代码 / Markdown / CSV 等：内置只读预览
        if ext in TEXT_EXTS:
            from ui.text_view import preview_text
            preview_text(parent, name, data, size,
                         on_save=lambda: save_attachment(parent, db, file_id))
            return

    _offer_save(parent, db, file_id, name or "这个文件")
