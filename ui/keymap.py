"""快捷键动作表（数据驱动）。

每个「动作」有一组元数据：唯一 id、中文名、所属分组、默认键。默认键是
Typora（Windows 版）的风格。用户自定义后的键存在库的 meta（DbState 的
``ui.shortcuts``，JSON 格式 ``{action_id: 键序列}``），未自定义的动作回落默认键。

键序列用 QKeySequence 的字符串格式（如 ``"Ctrl+Alt+N"``）。一个动作可以有多
个别名键（``aliases``），别名同样触发该动作、但不出现在设置里单独修改——
用于兼容用户的肌肉记忆（例如删除线既认 Alt+Shift+5 也认 Ctrl+Shift+5）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    group: str
    default: str
    aliases: List[str] = field(default_factory=list)


# 顺序即设置对话框与 F1 一览里的展示顺序。
ACTIONS: List[Action] = [
    # ---- 文件 / 条目
    Action("new_child", "新建子条目", "文件", "Ctrl+Alt+N"),
    Action("new_sibling_after", "新建同级（后面）", "文件", "Ctrl+N"),
    Action("new_sibling_before", "新建同级（前面）", "文件", "Ctrl+Shift+N"),
    Action("open_library", "打开资料库", "文件", "Ctrl+O"),
    Action("focus_search", "快速打开（聚焦搜索）", "文件", "Ctrl+P"),
    Action("save", "保存", "文件", "Ctrl+S"),
    Action("backup", "备份资料库到文件", "文件", "Ctrl+Shift+S"),
    Action("add_attachment", "添加附件", "文件", "Ctrl+Shift+A"),
    Action("toggle_star", "收藏 / 取消收藏", "文件", "Ctrl+D"),
    Action("close_tab", "关闭标签页 / 退出", "文件", "Ctrl+W",
           aliases=["Ctrl+Q"]),
    Action("move_up", "条目上移", "文件", "Ctrl+Alt+Up"),
    Action("move_down", "条目下移", "文件", "Ctrl+Alt+Down"),

    # ---- 编辑
    Action("rename", "重命名条目", "编辑", "F2"),
    Action("delete", "删除条目", "编辑", "Delete"),

    # ---- 标题
    Action("heading1", "一级标题", "标题", "Ctrl+1"),
    Action("heading2", "二级标题", "标题", "Ctrl+2"),
    Action("heading3", "三级标题", "标题", "Ctrl+3"),
    Action("heading4", "四级标题", "标题", "Ctrl+4"),
    Action("heading5", "五级标题", "标题", "Ctrl+5"),
    Action("heading6", "六级标题", "标题", "Ctrl+6"),
    Action("para", "正文段落", "标题", "Ctrl+0"),
    Action("heading_level_up", "提升标题级别", "标题", "Ctrl+="),
    Action("heading_level_down", "降低标题级别", "标题", "Ctrl+-"),

    # ---- 段落 / 块
    Action("table", "插入表格", "段落", "Ctrl+T"),
    Action("code_block", "代码块", "段落", "Ctrl+Shift+K"),
    Action("quote", "引用", "段落", "Ctrl+Shift+Q"),
    Action("list_ordered", "有序列表", "段落", "Ctrl+Shift+["),
    Action("list_unordered", "无序列表", "段落", "Ctrl+Shift+]"),
    Action("task_list", "任务列表", "段落", "Ctrl+Shift+X"),
    Action("task_toggle", "切换任务完成状态", "段落", "Ctrl+Shift+Return"),
    Action("para_above", "在上方插入段落", "段落", "Ctrl+Shift+Up"),
    Action("para_below", "在下方插入段落", "段落", "Ctrl+Shift+Down"),
    Action("indent", "增加缩进", "段落", "Ctrl+]"),
    Action("outdent", "减少缩进", "段落", "Ctrl+["),

    # ---- 行内格式
    Action("bold", "加粗", "格式", "Ctrl+B"),
    Action("italic", "斜体", "格式", "Ctrl+I"),
    Action("underline", "下划线", "格式", "Ctrl+U"),
    Action("strike", "删除线", "格式", "Alt+Shift+5",
           aliases=["Ctrl+Shift+5"]),
    Action("inline_code", "行内代码", "格式", "Ctrl+Shift+`"),
    Action("highlight", "高亮", "格式", "Ctrl+Shift+H"),
    Action("link", "超链接", "格式", "Ctrl+K"),
    Action("image", "插入图像", "格式", "Ctrl+Shift+I"),
    Action("clear_format", "清除格式", "格式", "Ctrl+\\"),
    Action("copy_md", "复制为 Markdown", "格式", "Ctrl+Shift+C"),
    Action("paste_plain", "粘贴为纯文本", "格式", "Ctrl+Shift+V"),

    # ---- 视图
    Action("source_mode", "源码 / 即时渲染切换", "视图", "Ctrl+/"),
    Action("focus_mode", "专注模式", "视图", "F8"),
    Action("typewriter", "打字机模式", "视图", "F9"),
    Action("fullscreen", "全屏", "视图", "F11"),
    Action("zoom_in", "放大", "视图", "Ctrl+Shift+="),
    Action("zoom_out", "缩小", "视图", "Ctrl+Shift+-"),
    Action("zoom_reset", "实际大小", "视图", "Ctrl+Shift+0"),
    Action("find", "查找", "视图", "Ctrl+F"),
    Action("replace", "替换", "视图", "Ctrl+H"),

    # ---- 帮助
    Action("shortcuts", "快捷键一览", "帮助", "F1"),
]


def action_by_id(aid: str) -> Action:
    for a in ACTIONS:
        if a.id == aid:
            return a
    raise KeyError(aid)


def default_key(aid: str) -> str:
    return action_by_id(aid).default
