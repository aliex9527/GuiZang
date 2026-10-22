"""快捷键一览（F1）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPushButton, QTextBrowser,
                               QVBoxLayout)

from ui.theme import P

GROUPS = [
    ("文件", [
        ("Ctrl+Alt+N", "新建子条目"),
        ("Ctrl+N", "新建同级（后面）"),
        ("Ctrl+Shift+N", "新建同级（前面）"),
        ("Ctrl+D", "收藏 / 取消收藏"),
        ("Ctrl+Alt+↑ / ↓", "条目上移 / 下移"),
        ("Ctrl+O", "打开资料库"),
        ("Ctrl+P", "快速打开（聚焦搜索）"),
        ("Ctrl+S", "保存"),
        ("Ctrl+Shift+S", "备份资料库到文件"),
        ("Ctrl+Shift+A", "添加附件"),
        ("Ctrl+W / Ctrl+Q", "退出"),
    ]),
    ("编辑", [
        ("Ctrl+Z / Ctrl+Y", "撤销 / 重做"),
        ("Ctrl+X / C / V", "剪切 / 复制 / 粘贴"),
        ("Ctrl+Shift+C", "复制为 Markdown"),
        ("Ctrl+Shift+V", "粘贴为纯文本"),
        ("Ctrl+A", "全选"),
        ("Ctrl+F", "查找"),
        ("Ctrl+H", "替换"),
        ("F2", "重命名条目"),
        ("Delete", "删除条目"),
    ]),
    ("段落", [
        ("Ctrl+1 ~ Ctrl+6", "一 ~ 六级标题"),
        ("Ctrl+0", "正文段落"),
        ("Ctrl+=", "提升标题级别"),
        ("Ctrl+-", "降低标题级别"),
        ("Ctrl+T", "插入表格"),
        ("Ctrl+Shift+K", "代码块"),
        ("Ctrl+Shift+Q", "引用"),
        ("Ctrl+Shift+[", "有序列表"),
        ("Ctrl+Shift+]", "无序列表"),
        ("Ctrl+Shift+X", "任务列表"),
        ("Ctrl+Shift+Enter", "切换任务完成状态"),
        ("Ctrl+] / Ctrl+[", "增加 / 减少缩进"),
        ("Ctrl+Shift+↑ / ↓", "在上方 / 下方插入段落"),
        ("Ctrl+Shift+-", "水平分割线"),
    ]),
    ("格式", [
        ("Ctrl+B", "加粗"),
        ("Ctrl+I", "斜体"),
        ("Alt+Shift+5", "删除线（也认 Ctrl+Shift+5）"),
        ("Ctrl+Shift+`", "行内代码"),
        ("Ctrl+Shift+H", "高亮"),
        ("Ctrl+K", "超链接"),
        ("Ctrl+Shift+I", "插入图像"),
        ("Ctrl+\\", "清除格式"),
    ]),
    ("视图", [
        ("Ctrl+/", "源码模式"),
        ("F8", "专注模式"),
        ("F9", "打字机模式"),
        ("F11", "全屏"),
        ("Ctrl+Shift+=", "放大"),
        ("Ctrl+Shift+-", "缩小"),
        ("Ctrl+Shift+0", "实际大小"),
    ]),
    ("帮助", [
        ("F1", "快捷键一览"),
    ]),
]

# 输入法/键位不给快捷键、只能用菜单的项
EXTRA = [
    ("表格行/列操作", "菜单 段落 → 表格"),
    ("任务状态切换", "Ctrl+Shift+Enter 或菜单"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键一览")
        self.resize(560, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        view = QTextBrowser(self)
        view.setOpenLinks(False)
        view.setHtml(self._html())
        lay.addWidget(view, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("知道了", self)
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    @staticmethod
    def _html() -> str:
        parts = [f"<div style='font-family:\"PingFang SC\",\"Microsoft YaHei UI\",sans-serif;color:{P['text']};'>"]
        for title, items in GROUPS:
            parts.append(
                f"<h3 style='margin:14px 0 6px 0;color:{P['accent']};font-size:13px;'>"
                f"{title}</h3>")
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='4' "
                f"style='border-collapse:collapse;'>")
            for keys, desc in items:
                parts.append(
                    "<tr>"
                    f"<td width='42%' style='color:{P['muted']};"
                    f"font-family:Consolas,monospace;font-size:10pt;'>{keys}</td>"
                    f"<td style='color:{P['text']};'>{desc}</td>"
                    "</tr>")
            parts.append("</table>")
        parts.append("</div>")
        return "".join(parts)
