"""引擎选项。

所有开关集中在这里，默认值对齐归藏实际用到的那一套
（Python-Markdown 的 ``extra`` + ``sane_lists`` + ``nl2br`` + ``codehilite``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Set

# 默认打开的扩展。想精简的调用方传 extensions=... 覆盖即可。
DEFAULT_EXTENSIONS: FrozenSet[str] = frozenset({
    "setext",      # === / --- 下划线式标题
    "fenced_code",  # ``` 围栏代码块
    "indented_code",  # 4 空格缩进代码块
    "tables",      # 管道表格
    "attr_list",   # ![a](b){width=300} / # 标题 {#id}
    "tasklist",    # - [ ] / - [x]
    "strike",      # ~~删除~~
    "mark",        # ==高亮==
    "admonition",  # !!! note "标题"
    "codehilite",  # 代码着色
    "html",        # 原样 HTML 直通
    "autolink",    # <https://example.com>
})


@dataclass
class Options:
    """渲染选项。

    Attributes:
        extensions: 打开的语法扩展集合，见 :data:`DEFAULT_EXTENSIONS`。
        nl2br: 单个换行也当成 ``<br>``（Python-Markdown 的 nl2br 语义）。
        highlight: 是否给代码块着色。
        noclasses: 着色时写内联 ``style`` 而不是 ``class``（归藏预览需要）。
        hl_style: 配色方案名，见 :mod:`mdengine.highlight` 的 ``STYLES``。
        softbreak: 软换行输出，``"\\n"``（默认）或 ``"<br />\\n"``。
        xhtml: 空元素是否写成 ``<hr />``。
        task_style: 任务项渲染方式，``"input"`` 输出复选框，``"glyph"`` 输出 ☐/☑。
        mark_style: ``==高亮==`` 的渲染方式。``"tag"`` 输出 ``<mark>``（浏览器/预览），
            ``"span"`` 输出带底色 ``style`` 的 ``<span>``——Qt 富文本不认 ``<mark>``，
            会把标签整个丢掉、高亮在保存时消失，所以编辑器这条路必须用 ``"span"``。
    """

    extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_EXTENSIONS))
    nl2br: bool = False
    highlight: bool = True
    noclasses: bool = True
    hl_style: str = "friendly"
    softbreak: str = "\n"
    xhtml: bool = False
    task_style: str = "input"
    mark_style: str = "tag"

    @classmethod
    def build(cls, extensions: Iterable[str] | None = None, **kwargs) -> "Options":
        opts = cls(**kwargs)
        if extensions is not None:
            opts.extensions = set(extensions)
        return opts

    def has(self, name: str) -> bool:
        """该扩展是否打开。"""
        return name in self.extensions

    def enable(self, name: str) -> "Options":
        self.extensions.add(name)
        return self

    def disable(self, name: str) -> "Options":
        self.extensions.discard(name)
        return self
