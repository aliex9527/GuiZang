"""AST 节点。

刻意做得比 CommonMark 的 AST 扁平：块级节点和行内节点放在同一个模块里，
因为渲染器本来就是一段 ``isinstance`` 分发，拆两个模块只会多写 import。

所有节点都是 dataclass，方便比较与调试（``==`` 能直接比对两棵语法树）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class Node:
    """所有节点的基类。"""

    __slots__ = ()


# ---------------------------------------------------------------- 行内节点


@dataclass
class Text(Node):
    value: str


@dataclass
class Code(Node):
    """行内代码。"""
    value: str


@dataclass
class Html(Node):
    """原样直通的 HTML 片段。"""
    value: str


@dataclass
class SoftBreak(Node):
    """软换行（源码里的单个换行）。"""


@dataclass
class HardBreak(Node):
    """硬换行（行尾两个空格或反斜杠）。"""


@dataclass
class Emphasis(Node):
    children: List[Node]


@dataclass
class Strong(Node):
    children: List[Node]


@dataclass
class Strike(Node):
    children: List[Node]


@dataclass
class Mark(Node):
    """``==高亮==``。"""
    children: List[Node]


@dataclass
class Link(Node):
    dest: str
    title: str = ""
    children: List[Node] = field(default_factory=list)


@dataclass
class Image(Node):
    src: str
    title: str = ""
    alt: str = ""
    width: Optional[int] = None


# ---------------------------------------------------------------- 块级节点


@dataclass
class Paragraph(Node):
    children: List[Node]


@dataclass
class Heading(Node):
    level: int
    children: List[Node]
    ident: Optional[str] = None


@dataclass
class CodeBlock(Node):
    text: str
    info: str = ""


@dataclass
class ThematicBreak(Node):
    """``---`` 分隔线。"""


@dataclass
class BlockQuote(Node):
    children: List[Node]


@dataclass
class ListItem(Node):
    children: List[Node]
    task: Optional[bool] = None   # None=普通项；True=已勾选；False=未勾选


@dataclass
class ListBlock(Node):
    ordered: bool
    items: List[ListItem]
    start: int = 1
    tight: bool = True


@dataclass
class Table(Node):
    headers: List[List[Node]]
    rows: List[List[List[Node]]]
    aligns: List[Optional[str]] = field(default_factory=list)


@dataclass
class HtmlBlock(Node):
    value: str


@dataclass
class Admonition(Node):
    kind: str
    title: str
    children: List[Node]


@dataclass
class Document(Node):
    children: List[Node] = field(default_factory=list)


def walk_document(doc: Document) -> List[Node]:
    """把整棵树拍平成列表，调试和统计用。"""
    out: List[Node] = []
    stack: List[Node] = [doc]
    while stack:
        node = stack.pop()
        out.append(node)
        for name in ("children", "items"):
            kids = getattr(node, name, None)
            if isinstance(kids, list):
                for kid in kids:
                    if isinstance(kid, ListItem):
                        stack.append(kid)
                    elif isinstance(kid, Node):
                        stack.append(kid)
    return out
