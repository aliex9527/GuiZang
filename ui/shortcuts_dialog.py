"""快捷键一览（F1）。

键位显示走实时键表（view.key_for_action）：用户自定义过改键后，一览里
显示的是**当前生效**的键，而不是出厂默认。未纳入自定义范围的 Qt 内建
编辑键（撤销/剪切/复制等）仍显示固定键名。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPushButton, QTextBrowser,
                               QVBoxLayout)

from ui.theme import P

# 每组条目：(键显示来源, 描述, 动作id可选)
# 键显示来源是动作 id 时用当前键表解析；否则原样显示（内建键/组合说明）。
GROUPS = [
    ("文件", [
        ("new_child", "新建子条目"),
        ("new_sibling_after", "新建同级（后面）"),
        ("new_sibling_before", "新建同级（前面）"),
        ("toggle_star", "收藏 / 取消收藏"),
        ("move_up", "条目上移"),
        ("move_down", "条目下移"),
        ("open_library", "打开资料库"),
        ("focus_search", "快速打开（聚焦搜索）"),
        ("save", "保存"),
        ("backup", "备份资料库到文件"),
        ("add_attachment", "添加附件"),
        ("close_tab", "关闭标签页 / 退出"),
    ]),
    ("编辑", [
        ("_fixed", "撤销", None, "Ctrl+Z"),
        ("_fixed", "重做", None, "Ctrl+Y"),
        ("_fixed", "剪切 / 复制 / 粘贴", None, "Ctrl+X / C / V"),
        ("copy_md", "复制为 Markdown"),
        ("paste_plain", "粘贴为纯文本"),
        ("_fixed", "全选", None, "Ctrl+A"),
        ("find", "查找"),
        ("replace", "替换"),
        ("rename", "重命名条目"),
        ("delete", "删除条目"),
    ]),
    ("标题", [
        ("heading1", "一级标题"),
        ("heading2", "二级标题"),
        ("heading3", "三级标题"),
        ("heading4", "四级标题"),
        ("heading5", "五级标题"),
        ("heading6", "六级标题"),
        ("para", "正文段落"),
        ("heading_level_up", "提升标题级别"),
        ("heading_level_down", "降低标题级别"),
    ]),
    ("段落", [
        ("table", "插入表格"),
        ("code_block", "代码块"),
        ("quote", "引用"),
        ("list_ordered", "有序列表"),
        ("list_unordered", "无序列表"),
        ("task_list", "任务列表"),
        ("task_toggle", "切换任务完成状态"),
        ("indent", "增加缩进"),
        ("outdent", "减少缩进"),
        ("para_above", "在上方插入段落"),
        ("para_below", "在下方插入段落"),
    ]),
    ("格式", [
        ("bold", "加粗"),
        ("italic", "斜体"),
        ("underline", "下划线（落成 <u>…</u>）"),
        ("strike", "删除线"),
        ("inline_code", "行内代码"),
        ("highlight", "高亮"),
        ("link", "超链接"),
        ("image", "插入图像"),
        ("clear_format", "清除格式"),
    ]),
    ("视图", [
        ("source_mode", "源码模式"),
        ("focus_mode", "专注模式"),
        ("typewriter", "打字机模式"),
        ("fullscreen", "全屏"),
        ("zoom_in", "放大"),
        ("zoom_out", "缩小"),
        ("zoom_reset", "实际大小"),
    ]),
    ("帮助", [
        ("shortcuts", "快捷键一览"),
    ]),
]

# 输入法/键位不给快捷键、只能用菜单的项
EXTRA = [
    ("表格行/列操作", "菜单 段落 → 表格"),
    ("水平分割线", "菜单 段落 → 水平分割线"),
]

_PRETTY = {"Up": "↑", "Down": "↓", "Return": "Enter"}


def _pretty(seq: str) -> str:
    for k, v in _PRETTY.items():
        seq = seq.replace(k, v)
    return seq


class ShortcutsDialog(QDialog):
    def __init__(self, view=None, parent=None):
        super().__init__(parent)
        self._view = view
        self.setWindowTitle("快捷键一览")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        view = QTextBrowser(self)
        view.setOpenLinks(False)
        view.setHtml(self._html())
        lay.addWidget(view, 1)

        row = QHBoxLayout()
        b_cfg = QPushButton("自定义快捷键…", self)
        b_cfg.clicked.connect(self._open_settings)
        row.addWidget(b_cfg)
        row.addStretch(1)
        ok = QPushButton("知道了", self)
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    def _key_text(self, item) -> str:
        """条目键位文本：动作 id → 当前键；固定条目 → 原样。"""
        if isinstance(item, str):
            return item                      # 旧式纯键名（兼容）
        if item[0] == "_fixed":
            return item[3]
        aid = item[2] if len(item) > 2 else item[0]
        if self._view is not None:
            seq = self._view.key_for_action(aid)
            return _pretty(seq) if seq else "（未绑定）"
        from ui.keymap import action_by_id
        return _pretty(action_by_id(aid).default)

    def _desc(self, item) -> str:
        if isinstance(item, str):
            return ""
        return item[1]

    def _open_settings(self) -> None:
        if self._view is None:
            return
        from ui.keymap_dialog import KeymapDialog
        self.accept()                        # 先收起一览
        KeymapDialog(self._view, self._view.window()).exec()

    def _html(self) -> str:
        parts = [f"<div style='font-family:\"PingFang SC\",\"Microsoft YaHei UI\",sans-serif;color:{P['text']};'>"]
        for group in GROUPS:
            title, items = group[0], group[1]
            parts.append(
                f"<h3 style='margin:14px 0 6px 0;color:{P['accent']};font-size:13px;'>"
                f"{title}</h3>")
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='4' "
                f"style='border-collapse:collapse;'>")
            for item in items:
                parts.append(
                    "<tr>"
                    f"<td width='42%' style='color:{P['muted']};"
                    f"font-family:Consolas,monospace;font-size:10pt;'>"
                    f"{self._key_text(item)}</td>"
                    f"<td style='color:{P['text']};'>{self._desc(item)}</td>"
                    "</tr>")
            parts.append("</table>")
        parts.append(
            f"<p style='color:{P['muted']};font-size:11px;margin-top:12px;'>"
            "表格行/列操作与水平分割线暂无快捷键，见菜单 段落。</p>")
        parts.append("</div>")
        return "".join(parts)
