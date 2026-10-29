"""HTML → Markdown。

两段式：先用 :class:`html.parser.HTMLParser` 建一棵极简 DOM，再递归下降把
它写成 Markdown。比流式状态机好写——列表嵌套、表格单元格这类「需要看上下文」
的情况，在树上就是普通递归。

输出的风格对齐 html2text 的常用配置：``body_width=0``（不折行）、保留链接与
图片、引用前缀只留一个 ``> ``、块之间恰好一个空行。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Union

VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})

SKIP_TAGS = frozenset({"head", "style", "script", "noscript", "title", "meta"})

BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "header", "footer", "aside",
    "figure", "figcaption", "body", "html", "form", "fieldset", "address",
    "details", "summary", "dl", "dt", "dd", "center",
})

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

WS_RE = re.compile(r"[ \t\r\n\u2028\u2029]+")
LANG_RE = re.compile(r"(?:language|lang)-([\w+#.-]+)", re.I)
MULTI_BLANK_RE = re.compile(r"\n{3,}")


class _El:
    """极简 DOM 节点。"""

    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: Optional[Dict[str, str]] = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: List[Union["_El", str]] = []

    def text(self) -> str:
        out: List[str] = []
        for child in self.children:
            out.append(child if isinstance(child, str) else child.text())
        return "".join(out)


class _DomBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("#root")
        self.stack: List[_El] = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(el)
        if tag not in VOID_TAGS:
            self.stack.append(el)

    def handle_startendtag(self, tag: str, attrs) -> None:
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(el)

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _collapse(text: str) -> str:
    """折叠空白，但保留首尾各一个空格（拼接时才不会把词粘在一起）。"""
    flat = WS_RE.sub(" ", text.replace("\u00a0", " "))
    if not flat.strip():
        return " "
    lead = " " if flat.startswith(" ") else ""
    trail = " " if flat.endswith(" ") else ""
    return lead + flat.strip() + trail


def _tidy_inline(text: str) -> str:
    """收尾：压掉连续空格并去掉首尾空白。

    标记内侧的空白已经在 :meth:`_Writer._wrap` 里 ``strip()`` 过了；
    这里再动标记左右的空格会把 ``Hello **world**`` 粘成 ``Hello**world**``，
    所以只做空格折叠。
    """
    return re.sub(r"[ \t]{2,}", " ", text).strip()


class _Writer:
    """DOM → Markdown。"""

    def __init__(self) -> None:
        self.styles: List[str] = []

    # ------------------------------------------------------------ 块级
    def blocks(self, el: _El, depth: int = 0) -> List[str]:
        out: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            if buf:
                text = _tidy_inline("".join(buf))
                if text:
                    out.append(text)
                buf.clear()

        for child in el.children:
            if isinstance(child, str):
                if child.strip():
                    buf.append(_collapse(child))
                continue

            tag = child.tag
            if tag in SKIP_TAGS:
                continue

            if tag == "p":
                flush()
                text = _tidy_inline(self.inline(child))
                if text:
                    out.append(text)
            elif tag in HEADINGS:
                flush()
                text = _tidy_inline(self.inline(child))
                if text:
                    out.append("#" * HEADINGS[tag] + " " + text)
            elif tag in ("ul", "ol", "menu"):
                flush()
                block = self.list_block(child, depth)
                if block:
                    out.append(block)
            elif tag == "pre":
                flush()
                out.append(self.pre_block(child))
            elif tag == "blockquote":
                flush()
                inner = self.blocks(child, depth)
                if inner:
                    body = "\n\n".join(inner)
                    out.append("\n".join(("> " + line) if line.strip() else ">"
                                         for line in body.split("\n")))
            elif tag == "hr":
                flush()
                out.append("---")
            elif tag == "table":
                flush()
                block = self.table_block(child)
                if block:
                    out.append(block)
            elif tag == "br":
                buf.append("  \n")
            elif tag in BLOCK_TAGS:
                flush()
                out.extend(self.blocks(child, depth))
            else:
                buf.append(self.inline_el(child))

        flush()
        return out

    def list_block(self, el: _El, depth: int = 0) -> str:
        ordered = el.tag == "ol"
        pad = "    " * depth
        lines: List[str] = []
        index = 0

        for li in el.children:
            if not isinstance(li, _El) or li.tag != "li":
                continue
            index += 1
            # 传 depth 而不是 depth + 1：嵌套列表的缩进由下面那句
            # ``pad + "    "`` 统一补，两边都加会变成每层 8 空格。
            pieces = self.blocks(li, depth)
            if not pieces:
                continue
            marker = ("%d. " % index) if ordered else "- "
            first, rest = pieces[0], pieces[1:]
            first_lines = first.split("\n")
            lines.append(pad + marker + first_lines[0])
            hang = pad + " " * len(marker)
            for extra in first_lines[1:]:
                lines.append((hang + extra) if extra.strip() else "")
            for piece in rest:
                for line in piece.split("\n"):
                    if not line.strip():
                        lines.append("")
                    else:
                        lines.append(pad + "    " + line)
        return "\n".join(lines)

    def pre_block(self, el: _El) -> str:
        code_el = el
        for child in el.children:
            if isinstance(child, _El) and child.tag == "code":
                code_el = child
                break

        text = code_el.text()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.rstrip("\n")

        lang = ""
        cls = (code_el.attrs.get("class") or el.attrs.get("class") or "")
        m = LANG_RE.search(cls)
        if m:
            lang = m.group(1)

        fence = "```"
        while fence in text:
            fence += "`"
        return "%s%s\n%s\n%s" % (fence, lang, text, fence)

    def table_block(self, el: _El) -> str:
        rows: List[List[str]] = []

        for tr in self._descendants(el, "tr"):
            cells: List[str] = []
            for cell in tr.children:
                if not isinstance(cell, _El) or cell.tag not in ("td", "th"):
                    continue
                text = _tidy_inline(self.inline(cell)).replace("|", "\\|")
                cells.append(text)
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]

        separator = "|" + "|".join([" --- "] * width) + "|"
        out = ["| " + " | ".join(rows[0]) + " |", separator]
        # Markdown 表格必须有表头行，所以不管第一行原本是 th 还是 td，
        # 都把它当表头，剩下的做正文——这样既不会重复也不会丢行。
        for row in rows[1:]:
            out.append("| " + " | ".join(row) + " |")
        return "\n".join(out)

    @staticmethod
    def _descendants(el: _El, tag: str) -> List[_El]:
        """按文档顺序收集后代元素。

        必须保持顺序：表格的行序一旦被打乱，反序列化出来的表头和正文就会错位。
        所以这里是递归而不是用栈（栈会得到逆序）。
        """
        found: List[_El] = []
        for child in el.children:
            if isinstance(child, _El):
                if child.tag == tag:
                    found.append(child)
                else:
                    found.extend(_Writer._descendants(child, tag))
        return found

    # ------------------------------------------------------------ 行内
    def inline(self, el: _El) -> str:
        parts: List[str] = []
        for child in el.children:
            if isinstance(child, str):
                parts.append(_collapse(child))
            else:
                parts.append(self.inline_el(child))
        return _tidy_inline("".join(parts))

    def inline_el(self, el: _El) -> str:
        tag = el.tag
        if tag in SKIP_TAGS:
            return ""
        if tag in ("strong", "b"):
            return self._wrap(el, "**")
        if tag in ("em", "i"):
            return self._wrap(el, "*")
        if tag in ("del", "s", "strike"):
            return self._wrap(el, "~~")
        if tag == "u":
            inner = self.inline(el)
            return "<u>%s</u>" % inner if inner.strip() else ""
        if tag in ("mark",):
            return self._wrap(el, "==")
        if tag == "code":
            return self._code_span(el.text())
        if tag == "br":
            return "  \n"
        if tag == "img":
            return self._image(el)
        if tag == "a":
            return self._link(el)
        if tag == "span":
            return self._span(el)
        if tag in ("ul", "ol", "menu", "p", "div", "pre", "table", "blockquote"):
            # 行内位置出现块级元素：退化成纯文本，避免结构错乱
            return self.inline(el)
        if tag == "input":
            return ""
        return self.inline(el)

    def _wrap(self, el: _El, mark: str) -> str:
        inner = self.inline(el).strip()
        if not inner:
            return ""
        if mark in inner and len(mark) == 2:
            return inner          # 内部已有同样的标记，别嵌套出歧义
        return mark + inner + mark

    @staticmethod
    def _code_span(text: str) -> str:
        if not text:
            return ""
        ticks = "`"
        while ticks in text:
            ticks += "`"
        pad = " " if text.startswith("`") or text.endswith("`") else ""
        return "%s%s%s%s%s" % (ticks, pad, text, pad, ticks)

    def _link(self, el: _El) -> str:
        href = (el.attrs.get("href") or "").strip()
        inner = self.inline(el)
        if not href:
            return inner
        if not inner.strip():
            return "<%s>" % href
        return "[%s](%s)" % (inner, href)

    def _image(self, el: _El) -> str:
        src = (el.attrs.get("src") or "").strip()
        if not src:
            return ""
        alt = el.attrs.get("alt") or ""
        return "![%s](%s)" % (alt.strip(), src)

    def _span(self, el: _El) -> str:
        style = (el.attrs.get("style") or "").lower()
        inner = self.inline(el)
        if not inner.strip():
            return ""
        if "background-color" in style or "background:" in style:
            return "==%s==" % inner.strip()
        if "line-through" in style:
            return "~~%s~~" % inner.strip()
        if "underline" in style:
            return "<u>%s</u>" % inner.strip()
        if "monospace" in style or "consolas" in style or "courier" in style:
            return self._code_span(el.text())
        return inner


def html_to_markdown(html: str) -> str:
    """HTML（片段或整页）→ Markdown 源码。"""
    if not html or not html.strip():
        return ""

    builder = _DomBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # noqa: BLE001 - HTML 再烂也不能把调用方拖崩
        return ""

    writer = _Writer()
    blocks = [b for b in writer.blocks(builder.root) if b.strip()]
    text = "\n\n".join(blocks)
    text = MULTI_BLANK_RE.sub("\n\n", text).strip("\n")
    return text + "\n" if text else ""
