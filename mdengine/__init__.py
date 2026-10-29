"""mdengine —— 零依赖的 Markdown 引擎（自研，双向 + 代码高亮）。

    >>> from mdengine import to_html, to_markdown
    >>> to_html("# 标题\\n\\n**粗** 与 `code`")
    '<h1>标题</h1>\\n\\n<p><strong>粗</strong> 与 <code>code</code></p>\\n'
    >>> to_markdown("<h1>标题</h1>")
    '# 标题\\n'

三个方向都在这里收口：

* :func:`to_html` —— Markdown → HTML
* :func:`to_markdown` —— HTML → Markdown
* :func:`highlight_code` —— 代码着色（内置词法表，不依赖 Pygments）

需要精细控制时用 :class:`Engine`，选项见 :class:`mdengine.options.Options`。
编辑器边打字边预览时用 :class:`LivePreview`（按块增量渲染，见 :mod:`mdengine.live`）。
"""

from __future__ import annotations

from typing import Iterable, Optional

from .block import BlockParser
from .highlight import STYLES, highlight_code, languages
from .html_to_md import html_to_markdown
from .inline import plain_text
from .live import LivePreview, RenderStats
from .nodes import Document, Node
from .options import DEFAULT_EXTENSIONS, Options
from .render import HtmlRenderer, render_document

__version__ = "1.1.0"
__all__ = [
    "Engine", "Options", "DEFAULT_EXTENSIONS",
    "to_html", "to_markdown", "markdown_to_html", "html_to_markdown",
    "highlight_code", "languages", "STYLES",
    "LivePreview", "RenderStats",
    "Document", "Node", "plain_text",
    "__version__",
]


class Engine:
    """可复用的引擎实例。

    一次构造、多次调用：选项只在构造时确定，解析器每次调用新建，
    所以实例是线程安全的（每次 ``to_html`` 之间没有共享可变状态）。

    Args:
        extensions: 覆盖默认扩展集合；``None`` 表示用默认值。
        **kwargs: 透传给 :class:`Options`（``nl2br`` / ``highlight`` /
            ``noclasses`` / ``hl_style`` / ``task_style`` ...）。
    """

    def __init__(self, extensions: Optional[Iterable[str]] = None, **kwargs) -> None:
        self.options = Options.build(extensions, **kwargs)

    # ---------------------------------------------------------------- 解析
    def parse(self, source: str) -> Document:
        """Markdown → AST，需要做自定义渲染或统计时用。"""
        return BlockParser(self.options).parse(source)

    def render(self, document: Document) -> str:
        """AST → HTML。"""
        return HtmlRenderer(self.options).render(document)

    # ---------------------------------------------------------------- 出口
    def to_html(self, source: str) -> str:
        """Markdown → HTML 片段。"""
        if not source or not source.strip():
            return ""
        return self.render(self.parse(source))

    def to_markdown(self, html: str) -> str:
        """HTML → Markdown。"""
        return html_to_markdown(html)

    def live(self, **kwargs) -> LivePreview:
        """基于本引擎的选项建一个增量渲染器（编辑器实时预览用）。

        ``kwargs`` 透传给 :class:`LivePreview`（``post`` / ``anchor`` /
        ``cache_size``）。每次 :meth:`LivePreview.update` 只重排改动的块。
        """
        return LivePreview(self.options, **kwargs)

    # 兼容旧名字
    markdown_to_html = to_html
    html_to_markdown = to_markdown


def to_html(source: str, extensions: Optional[Iterable[str]] = None, **kwargs) -> str:
    """Markdown → HTML 片段（一次性调用）。"""
    return Engine(extensions, **kwargs).to_html(source)


def to_markdown(html: str) -> str:
    """HTML → Markdown（一次性调用）。"""
    return html_to_markdown(html)


# 对齐 Python-Markdown / html2text 的旧入口名，便于平滑替换
markdown_to_html = to_html
__all__.append("render_document")
