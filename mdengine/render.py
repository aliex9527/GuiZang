"""AST → HTML。

每个块级节点输出一段自带换行的 HTML，块与块之间用空行分隔，方便人读与 diff。
所有文本都过 :func:`html.escape`，只有 :class:`nodes.Html` / ``HtmlBlock``
是原样直通的——这是「信任输入」的唯一入口。
"""

from __future__ import annotations

from html import escape as _esc
from typing import List, Optional

from . import nodes as nd
from .highlight import highlight_code
from .options import Options

_ALIGN_STYLE = {
    "left": ' style="text-align:left"',
    "center": ' style="text-align:center"',
    "right": ' style="text-align:right"',
}

# `==高亮==` 的底色。与 ``ui/md_source.HIGHLIGHT_BG`` 必须保持一致——
# 反序列化靠这个色值把 span 认回 `==…==`。
MARK_BG = "#fff59d"


def _attr(value: str) -> str:
    """属性值转义：只转义会破坏标记的三个字符。"""
    return _esc(value, quote=True).replace("&#x27;", "'")


class HtmlRenderer:
    """把 Document 渲染成 HTML 片段。"""

    def __init__(self, options: Optional[Options] = None) -> None:
        self.o = options or Options()

    # ------------------------------------------------------------ 对外
    def render(self, doc: nd.Document) -> str:
        blocks = [self.block(child) for child in doc.children]
        body = "\n\n".join(b for b in blocks if b)
        if not body:
            return ""
        return body + "\n"

    # ------------------------------------------------------------ 块级
    def block(self, node: nd.Node) -> str:
        if isinstance(node, nd.Paragraph):
            return "<p>%s</p>" % self.inline(node.children)
        if isinstance(node, nd.Heading):
            ident = ' id="%s"' % _attr(node.ident) if node.ident else ""
            return "<h%d%s>%s</h%d>" % (node.level, ident, self.inline(node.children), node.level)
        if isinstance(node, nd.CodeBlock):
            return self.code_block(node)
        if isinstance(node, nd.ThematicBreak):
            return "<hr />" if self.o.xhtml else "<hr>"
        if isinstance(node, nd.BlockQuote):
            inner = "\n\n".join(self.block(c) for c in node.children)
            return "<blockquote>\n%s\n</blockquote>" % inner
        if isinstance(node, nd.ListBlock):
            return self.list_block(node)
        if isinstance(node, nd.Table):
            return self.table(node)
        if isinstance(node, nd.HtmlBlock):
            return node.value
        if isinstance(node, nd.Admonition):
            inner = "\n\n".join(self.block(c) for c in node.children)
            return ('<div class="admonition %s">\n<p class="admonition-title">%s</p>\n%s\n</div>'
                    % (_attr(node.kind), _esc(node.title), inner))
        return ""

    def code_block(self, node: nd.CodeBlock) -> str:
        lang = (node.info or "").strip()
        if lang.startswith("{"):
            lang = lang.strip("{}").strip()
        if lang:
            lang = lang.split()[0].lstrip(".")

        if self.o.highlight and self.o.has("codehilite"):
            inner = highlight_code(node.text, lang, self.o.hl_style, self.o.noclasses)
            cls = ' class="language-%s"' % _attr(lang) if lang else ""
            return '<pre class="highlight"><code%s>%s</code></pre>' % (cls, inner)

        cls = ' class="language-%s"' % _attr(lang) if lang else ""
        return "<pre><code%s>%s</code></pre>" % (cls, _esc(node.text))

    def list_block(self, node: nd.ListBlock) -> str:
        tag = "ol" if node.ordered else "ul"
        start = ""
        if node.ordered and node.start != 1:
            start = ' start="%d"' % node.start
        items = [self.list_item(item, node.tight) for item in node.items]
        return "<%s%s>\n%s\n</%s>" % (tag, start, "\n".join(items), tag)

    def list_item(self, item: nd.ListItem, tight: bool) -> str:
        box = ""
        if item.task is not None:
            if self.o.task_style == "glyph":
                box = "☑ " if item.task else "☐ "
            else:
                box = ('<input type="checkbox" disabled%s> '
                       % (" checked" if item.task else ""))

        children = item.children

        if tight:
            # 紧凑列表里段落不包 <p>——哪怕是「文字 + 子列表」这种多项的项。
            # 包了的话 Qt 会在列表项里多出一层段距，和 Python-Markdown 的观感不一致。
            parts: List[str] = []
            for child in children:
                if isinstance(child, nd.Paragraph):
                    parts.append(self.inline(child.children))
                else:
                    parts.append(self.block(child))
            parts = [p for p in parts if p]
            if box:
                if parts:
                    parts[0] = box + parts[0]
                else:
                    parts.append(box.strip())
            return "<li>%s</li>" % "\n".join(parts)

        body = "\n".join(self.block(c) for c in children)
        if box:
            if body.startswith("<p>"):
                body = "<p>" + box + body[3:]
            else:
                body = box + body
        return "<li>\n%s\n</li>" % body

    def table(self, node: nd.Table) -> str:
        parts: List[str] = ["<table>", "<thead>", "<tr>"]
        for idx, head in enumerate(node.headers):
            align = node.aligns[idx] if idx < len(node.aligns) else None
            parts.append("<th%s>%s</th>" % (_ALIGN_STYLE.get(align or "", ""),
                                            self.inline(head)))
        parts += ["</tr>", "</thead>"]

        if node.rows:
            parts.append("<tbody>")
            for row in node.rows:
                parts.append("<tr>")
                for idx, cell in enumerate(row):
                    align = node.aligns[idx] if idx < len(node.aligns) else None
                    parts.append("<td%s>%s</td>" % (_ALIGN_STYLE.get(align or "", ""),
                                                    self.inline(cell)))
                parts.append("</tr>")
            parts.append("</tbody>")
        parts.append("</table>")
        return "\n".join(parts)

    # ------------------------------------------------------------ 行内
    def inline(self, nodes: List[nd.Node]) -> str:
        return "".join(self.inline_node(n) for n in nodes)

    def inline_node(self, node: nd.Node) -> str:
        if isinstance(node, nd.Text):
            return _esc(node.value)
        if isinstance(node, nd.Code):
            return "<code>%s</code>" % _esc(node.value)
        if isinstance(node, nd.Html):
            return node.value
        if isinstance(node, nd.SoftBreak):
            return self.o.softbreak
        if isinstance(node, nd.HardBreak):
            return "<br />\n" if self.o.xhtml else "<br>\n"
        if isinstance(node, nd.Strong):
            return "<strong>%s</strong>" % self.inline(node.children)
        if isinstance(node, nd.Emphasis):
            return "<em>%s</em>" % self.inline(node.children)
        if isinstance(node, nd.Strike):
            return "<del>%s</del>" % self.inline(node.children)
        if isinstance(node, nd.Mark):
            inner = self.inline(node.children)
            # Qt 富文本不认 <mark>，会连标签一起丢掉（高亮在存盘时消失），
            # 所以编辑器那条路用带底色的 span，反序列化按色值认回来。
            if getattr(self.o, "mark_style", "tag") == "span":
                return '<span style="background-color:%s;">%s</span>' % (MARK_BG, inner)
            return "<mark>%s</mark>" % inner
        if isinstance(node, nd.Link):
            title = ' title="%s"' % _attr(node.title) if node.title else ""
            return '<a href="%s"%s>%s</a>' % (_attr(node.dest), title,
                                              self.inline(node.children))
        if isinstance(node, nd.Image):
            title = ' title="%s"' % _attr(node.title) if node.title else ""
            width = ' width="%d"' % node.width if node.width else ""
            return '<img src="%s" alt="%s"%s%s>' % (_attr(node.src), _attr(node.alt),
                                                    title, width)
        return ""


def render_document(doc: nd.Document, options: Optional[Options] = None) -> str:
    """便捷函数：Document → HTML。"""
    return HtmlRenderer(options).render(doc)
