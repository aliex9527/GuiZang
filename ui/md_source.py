"""Markdown 真源：库里只存 Markdown 源码，富文本只是显示层。

两个方向：

* :func:`markdown_to_html` —— Markdown → HTML 片段，喂给 ``QTextEdit.setHtml``。
  故意只开 ``extra`` + ``sane_lists``：不要 ``nl2br``（软换行变 <br>，往返会多出空行）、
  不要 ``codehilite``（染色 span 会污染反序列化）。
* :func:`document_to_markdown` —— ``QTextDocument.toHtml()`` → Markdown。

为什么不直接遍历 QTextDocument：``<hr/>`` 只存在于导出的 HTML 里（块对象上看不出
任何痕迹）；反过来 ``<pre>`` 会被 Qt 拆成"每行一个带底色的 <p>"，标签也就没了。
所以序列化按"HTML 标签 + 块级样式"两路信息一起判断。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

import markdown
from PySide6.QtGui import QTextDocument, QTextFormat

# 图片"用户手动指定过宽度"的标记。带这个标记才往 Markdown 里写 {width=N}；
# 否则宽度只是按窗口自动排版的临时结果，写进源码会随窗口大小漂移。
MANUAL_WIDTH_PROP = int(QTextFormat.Property.UserProperty.value) + 1

HIGHLIGHT_BG = "#fff59d"

_TASK_OUT = re.compile(r"^([\u2610\u2611])\s+(.*)$")
_HL_RE = re.compile(r"==(?=\S)(.+?)(?<=\S)==")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_FENCE_SPLIT_RE = re.compile(r"(```.*?(?:```|\Z))", re.S)
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_QUOTE_MARGIN_RE = re.compile(r"margin-left:\s*(\d+)px")
_WEIGHT_RE = re.compile(r"font-weight:\s*(\d{3})")
_MONO_HINT = ("monospace", "consolas", "courier", "menlo", "cascadia")
# 亮色/暗色主题下代码块与引用的背景色（迁移历史数据时要都认）
_KNOWN_BLOCK_BG = {
    "code_bg": ("#f6f8fa", "#171a21"),
    "quote_bg": ("#f6f7fb", "#242a35"),
}

# ---------------------------------------------------------------- Markdown → HTML


def _replace_marks(seg: str) -> str:
    seg = _HL_RE.sub(lambda m: '<span style="background-color:%s;">%s</span>'
                     % (HIGHLIGHT_BG, m.group(1)), seg)
    return _STRIKE_RE.sub(lambda m: "<s>%s</s>" % m.group(1), seg)


def _inline_outside_code(seg: str) -> str:
    """只在行内代码之外替换，`...` 里的 == 和 ~~ 保持原样。"""
    out: List[str] = []
    last = 0
    for m in _CODE_SPAN_RE.finditer(seg):
        out.append(_replace_marks(seg[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_replace_marks(seg[last:]))
    return "".join(out)


def _task_line(line: str) -> str:
    """`- [ ] x` → `- ☐ x`：Qt 富文本没有复选框，用字形当勾选框。"""
    return re.sub(r"^(\s*)[-*+]\s+\[([ xX])\]\s+",
                  lambda m: "%s- %s " % (m.group(1),
                                         "\u2611" if m.group(2).lower() == "x" else "\u2610"),
                  line)


def _normalize_indent(seg: str) -> str:
    """2 空格缩进的列表转成 4 空格/层。

    Python-Markdown 的嵌套判定是 4 空格，2 空格会被压平成同级。
    归藏自己产出的源码本来就是 4 空格，这里只兜住"从别处粘进来的
    Typora 风格 2 空格缩进"，且仅当通篇没有 4 空格缩进时才动手。
    """
    lines = seg.split("\n")
    indents = set()
    for line in lines:
        m = re.match(r"^( +)([-*+]|\d+\.)[ \t]", line)
        if m:
            indents.add(len(m.group(1)))
    if not indents or any(n % 4 == 0 for n in indents):
        return seg
    out: List[str] = []
    for line in lines:
        m = re.match(r"^( +)([-*+]|\d+\.)[ \t]", line)
        if m:
            level = max(1, (len(m.group(1)) + 1) // 2)
            line = " " * (level * 4) + line[len(m.group(1)):]
        out.append(line)
    return "\n".join(out)


def _preprocess(source: str) -> str:
    """==高亮== / ~~删除~~ → HTML；围栏代码块内一律不动；任务项 → ☐/☑。"""
    parts = _FENCE_SPLIT_RE.split(source)
    for i, seg in enumerate(parts):
        if i % 2 == 0:   # 偶数段是普通文本，奇数段是围栏代码块
            seg = _normalize_indent(seg)
            parts[i] = "\n".join(_task_line(_inline_outside_code(line))
                                 for line in seg.split("\n"))
    return "".join(parts)


def _style_blocks(html: str) -> str:
    """给代码块补底色与等宽，让它在编辑器里就是代码块的样子。"""
    from ui.theme import P

    style = ("margin:12px 0px; padding:8px; white-space:pre-wrap; "
             "font-family:'Consolas'; font-size:10pt; background-color:%s; color:%s;"
             % (P["code_bg"], P["code_text"]))
    html = re.sub(r"<pre[^>]*>", '<pre style="%s">' % style, html)
    # markdown 输出 <pre><code class="...">，Qt 只认 pre 的样式，把 code 壳剥掉
    html = re.sub(r'(<pre style="[^"]*">)\s*<code[^>]*>', r"\1", html)
    return html.replace("</code></pre>", "</pre>")


def _fix_blockquote_breaks(html: str) -> str:
    """引用里的软换行在 Qt 里会被压成空格，先转成 <br> 才能保留分行。"""
    def repl(m: re.Match) -> str:
        return "<blockquote>" + m.group(1).replace("\n", "<br>") + "</blockquote>"

    return re.sub(r"<blockquote>(.*?)</blockquote>", repl, html, flags=re.S)


def markdown_to_html(source: str) -> str:
    """Markdown 源码 → 可塞进 QTextDocument 的 HTML 片段。"""
    if not source or not source.strip():
        return ""
    engine = markdown.Markdown(extensions=["extra", "sane_lists"], output_format="html")
    try:
        html = engine.convert(_preprocess(source))
    except Exception:  # noqa: BLE001 - 渲染失败退回纯文本，绝不让编辑器崩
        from html import escape

        html = "<pre>" + escape(source) + "</pre>"
    return _style_blocks(_fix_blockquote_breaks(html))


# ---------------------------------------------------------------- HTML → Markdown

_SPAN_TOKEN = {"bold": "**", "italic": "*", "strike": "~~", "mark": "==", "code": "`"}


class _HtmlToMd(HTMLParser):
    """把 Qt ``toHtml()`` 的输出还原成 Markdown。

    模型：一个"当前块缓冲"+ 一个行内标记栈。块结束时按块类型加前缀，
    行内遇到 span/a/img 时流式写标记，栈保证嵌套能正确闭合。
    """

    _HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self, manual_widths: Optional[Dict[str, int]] = None) -> None:
        super().__init__(convert_charrefs=True)
        self.manual_widths = manual_widths or {}
        self.blocks: List[Tuple[str, str, int]] = []   # (kind, text, depth)
        self.buf: List[str] = []
        self.kind: str = "p"
        self.in_pre = False
        self.pre_lines: List[str] = []
        self.list_stack: List[Dict] = []          # [{"ordered": bool, "n": int}]
        self.table: Optional[Dict] = None
        self.cell: List[str] = []
        self.span_stack: List[List[str]] = []
        self.href: Optional[str] = None
        self.skip_depth = 0                       # <head>/<style> 里的内容不要
        self.li_index = 0

    # -------------------------------------------------------------- 基础

    @property
    def in_flow(self) -> bool:
        return self.kind in ("p", "li", "li-ol", "quote", "code") or self._in_heading()

    def _flush(self) -> None:
        text = "".join(self.buf)
        self.buf = []
        if self.skip_depth or self.in_pre:
            return
        if not text.strip():
            # 空段落直接忽略：段间空行由 _assemble 统一补。
            # 代码块例外——用户代码里的空行必须留住。
            if self.kind == "code":
                self.blocks.append(("code", "", 0))
            return
        self.blocks.append((self.kind, text.rstrip(), self._depth()))

    def _in_heading(self) -> bool:
        return self.kind.startswith("h")

    def _depth(self) -> int:
        """列表嵌套层级（列表项之外一律 0）。"""
        if self.kind in ("li", "li-ol") and self.list_stack:
            return max(0, int(self.list_stack[-1].get("indent", 1)) - 1)
        return 0

    def _is_block_style(self, key: str, style: str) -> bool:
        """块级样式匹配。

        历史 HTML 里的底色是按"当时用的主题"写下的，所以除了当前主题色，
        还要认其他主题的同一色值，否则暗色主题保存的笔记迁移时认不出代码块。
        """
        from ui.theme import P

        candidates = {str(P[key]).lower()}
        candidates.update(_KNOWN_BLOCK_BG.get(key, ()))
        return any(c and c in style for c in candidates)

    # -------------------------------------------------------------- 标签

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("head", "style", "script"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        a = dict(attrs)
        style = (a.get("style") or "").lower()

        if self.table is not None and tag not in ("tr", "td", "th", "table"):
            return   # 表格内部只收纯文本

        if tag in self._HEADINGS:
            self._flush()
            self.kind = "h%d" % self._HEADINGS[tag]
            return
        if tag == "p":
            self._flush()
            if self._is_block_style("code_bg", style):
                self.kind = "code"
            elif self._is_quote_para(style):
                self.kind = "quote"
            else:
                self.kind = "p"
            return
        if tag in ("ul", "ol"):
            self._flush()
            # Qt 不用嵌套标签表示层级，而是给列表打 -qt-list-indent: N（N 从 1 起）
            m = re.search(r"-qt-list-indent:\s*(\d+)", style)
            indent = int(m.group(1)) if m else len(self.list_stack) + 1
            self.list_stack.append({"ordered": tag == "ol", "n": 0, "indent": indent})
            return
        if tag == "li":
            self._flush()
            if self.list_stack and self.list_stack[-1]["ordered"]:
                self.list_stack[-1]["n"] += 1
                self.li_index = self.list_stack[-1]["n"]
                self.kind = "li-ol"
            else:
                self.kind = "li"
            return
        if tag == "pre":
            self._flush()
            self.in_pre = True
            self.pre_lines = []
            return
        if tag == "hr":
            self._flush()
            self.blocks.append(("hr", "", 0))
            return
        if tag == "blockquote":
            self._flush()
            self.kind = "quote"
            return
        if tag == "table":
            self._flush()
            self.table = {"rows": []}
            return
        if tag == "tr" and self.table is not None:
            self.table["rows"].append([])
            return
        if tag in ("td", "th") and self.table is not None:
            self.cell = []
            return
        if tag == "br":
            self.buf.append("  \n")
            return
        if tag == "img":
            self.buf.append(self._img_md(a))
            return
        if tag == "a":
            self.href = a.get("href") or ""
            self.buf.append("[")
            return
        # 代码块内与标题内都不需要行内标记：内容本身已经是最终形态
        if self.kind == "code" or self._in_heading():
            return
        if tag in ("b", "strong"):
            self.buf.append("**")
        elif tag in ("i", "em"):
            self.buf.append("*")
        elif tag in ("s", "strike", "del"):
            self.buf.append("~~")
        elif tag == "code":
            self.buf.append("`")
        elif tag == "span":
            kinds = self._span_kinds(style)
            self.span_stack.append(kinds)
            for k in kinds:
                self.buf.append(_SPAN_TOKEN[k])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("head", "style", "script"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if self.table is not None and tag not in ("tr", "td", "th", "table"):
            return

        if tag in self._HEADINGS or tag in ("p", "li"):
            self._flush()
            self.kind = "p"
            return
        if tag in ("ul", "ol"):
            self._flush()
            if self.list_stack:
                self.list_stack.pop()
            return
        if tag == "pre":
            self.in_pre = False
            body = "\n".join(self.pre_lines).rstrip("\n")
            self.blocks.append(("pre", body, 0))
            self.pre_lines = []
            self.kind = "p"
            return
        if tag == "blockquote":
            self._flush()
            self.kind = "p"
            return
        if tag == "table":
            self._flush()
            if self.table:
                self.blocks.append(("table", self._table_md(self.table), 0))
            self.table = None
            return
        if tag == "tr" and self.table is not None:
            return
        if tag in ("td", "th") and self.table is not None:
            if self.table["rows"]:
                text = "".join(self.cell).strip().replace("\n", " ").replace("|", "\\|")
                self.table["rows"][-1].append(text)
            self.cell = []
            return
        if tag == "a":
            self.buf.append("](%s)" % (self.href or ""))
            self.href = None
            return
        if self.kind == "code" or self._in_heading():
            return
        if tag in ("b", "strong"):
            self.buf.append("**")
        elif tag in ("i", "em"):
            self.buf.append("*")
        elif tag in ("s", "strike", "del"):
            self.buf.append("~~")
        elif tag == "code":
            self.buf.append("`")
        elif tag == "span":
            kinds = self.span_stack.pop() if self.span_stack else []
            for k in reversed(kinds):
                self.buf.append(_SPAN_TOKEN[k])

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_pre:
            self.pre_lines.append(data)
            return
        if self.table is not None:
            self.cell.append(data)
            return
        text = data.replace("\u2028", "\n").replace("\u00a0", " ")
        if self.in_flow:
            text = text.replace("\n", " ")
        self.buf.append(text)

    # -------------------------------------------------------------- 细节

    def _is_quote_para(self, style: str) -> bool:
        if self._is_block_style("quote_bg", style):
            return True
        m = _QUOTE_MARGIN_RE.search(style)
        return bool(m and int(m.group(1)) >= 18)

    def _span_kinds(self, style: str) -> List[str]:
        """按固定顺序开标记；闭合时反序弹回，保证嵌套合法。"""
        kinds: List[str] = []
        if HIGHLIGHT_BG in style:
            kinds.append("mark")
        if "line-through" in style:
            kinds.append("strike")
        if "font-style:italic" in style:
            kinds.append("italic")
        m = _WEIGHT_RE.search(style)
        if (int(m.group(1)) if m else 400) >= 600:
            kinds.append("bold")
        if any(h in style for h in _MONO_HINT):
            kinds.append("code")
        return kinds

    def _img_md(self, a: Dict) -> str:
        src = a.get("src") or ""
        alt = a.get("alt") or ""
        md = "![%s](%s)" % (alt, src)
        # 只有用户手动定过宽度的图才写 {width=N}；自动排版出来的宽度是临时的，
        # 写进源码会随窗口大小漂移，每次保存都变一次。
        w = self.manual_widths.get(src, 0)
        if w > 0:
            md += "{width=%d}" % w
        return md

    def _table_md(self, table: Dict) -> str:
        rows = [r for r in table["rows"] if r]
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |",
                 "|" + "|".join([" --- "] * width) + "|"]
        for r in rows[1:]:
            lines.append("| " + " | ".join(r) + " |")
        return "\n".join(lines)

    # -------------------------------------------------------------- 出口

    def result(self) -> str:
        self._flush()
        return _assemble(self.blocks)


def _assemble(blocks: List[Tuple[str, str]]) -> str:
    """块序列 → Markdown 文本，处理空行、列表紧凑与连续代码行的合并。"""
    lines: List[str] = []
    i = 0
    total = len(blocks)
    prev_li: Optional[str] = None
    prev_depth = 0

    def gap() -> None:
        if lines and lines[-1] != "":
            lines.append("")

    while i < total:
        kind, text, depth = blocks[i]
        i += 1
        if kind not in ("li", "li-ol", "blank"):
            prev_li = None

        if kind == "blank":
            gap()
            continue
        if kind == "hr":
            gap()
            lines.extend(["---", ""])
            continue
        if kind in ("li", "li-ol"):
            # 同层级里无序/有序切换必须空一行，否则 Markdown 会把它们并成一个列表；
            # 换层级属于嵌套，不能空行。
            if prev_li is not None and prev_li != kind and prev_depth == depth:
                gap()
            prev_li, prev_depth = kind, depth
            body = text.strip()
            pad = "    " * depth
            m = _TASK_OUT.match(body)
            if m:
                lines.append("%s- [%s] %s" % (pad, "x" if m.group(1) == "\u2611" else " ", m.group(2)))
            elif kind == "li-ol":
                lines.append("%s%d. %s" % (pad, _next_ol(lines, pad), body))
            else:
                lines.append("%s- %s" % (pad, body))
            continue
        if kind == "code":
            # Qt 把代码块拆成"每行一个带底色的 <p>"，这里合并回一个围栏
            body = [text]
            while i < total and blocks[i][0] == "code":
                body.append(blocks[i][1])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            gap()
            lines.append("```")
            lines.extend(body)
            lines.extend(["```", ""])
            continue
        if kind == "pre":
            gap()
            lines.append("```")
            lines.extend(text.split("\n"))
            lines.extend(["```", ""])
            continue
        if kind == "table":
            gap()
            lines.extend(text.split("\n"))
            lines.append("")
            continue
        if kind.startswith("h"):
            gap()
            lines.extend(["#" * int(kind[1:]) + " " + text.strip(), ""])
            continue
        if kind == "quote":
            gap()
            for line in text.split("\n"):
                line = line.strip()      # 引用前缀只需一个 "> "
                lines.append("> " + line if line else ">")
            lines.append("")
            continue
        body = text.strip("\n")
        if not body.strip():
            continue
        gap()
        lines.extend(body.split("\n"))
        lines.append("")

    md = _MULTI_BLANK_RE.sub("\n\n", "\n".join(lines)).strip("\n")
    return md + "\n" if md else ""


def _next_ol(lines: List[str], pad: str) -> int:
    """同层级的有序列表项自动递增；换层级或遇到其它内容就从 1 重新开始。"""
    for line in reversed(lines):
        if not line.strip():
            continue
        m = re.match(r"^(\s*)(\d+)\. ", line)
        if m:
            if m.group(1) == pad:
                return int(m.group(2)) + 1
            continue          # 更深/更浅的层级跳过，继续往上找
        if re.match(r"^(\s*)[-*+] ", line):
            continue          # 中间夹了无序项也跳过
        break
    return 1


def _manual_widths(doc: QTextDocument) -> Dict[str, int]:
    """收集"用户手动定过宽度"的图片：只有这些才写回 Markdown。"""
    found: Dict[str, int] = {}
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                cf = frag.charFormat()
                if cf.isImageFormat() and cf.hasProperty(MANUAL_WIDTH_PROP):
                    name = cf.toImageFormat().name()
                    if name:
                        found[name] = int(round(cf.toImageFormat().width()))
            it += 1
        block = block.next()
    return found


def document_to_markdown(doc: QTextDocument) -> str:
    """QTextDocument → Markdown 源码。"""
    try:
        parser = _HtmlToMd(_manual_widths(doc))
        parser.feed(doc.toHtml())
        parser.close()
    except Exception:  # noqa: BLE001 - 反序列化失败时退回纯文本，不丢内容
        return (doc.toPlainText() or "").strip() + "\n"
    return parser.result()


# ---------------------------------------------------------------- 历史数据迁移

_IMG_SIZE_ATTR_RE = re.compile(r'(<img\b[^>]*?)\s(?:width|height)="[^"]*"')


def _drop_img_size(html: str) -> str:
    """迁移时去掉图片的 width/height。

    历史 HTML 里的宽度是"当时窗口下自动排出来的"，留着会被当成用户手动尺寸，
    换台机器就锁死在旧宽度上。去掉后交给 fit_images 按当前窗口重排。
    """
    return _IMG_SIZE_ATTR_RE.sub(r"\1", html)


def migrate_html_notes(db) -> int:
    """把 note_format != 'md' 的历史笔记转成 Markdown 源码，返回转换条数。

    幂等：转换后 note_format 变 'md'，下次打开不会再处理。
    """
    try:
        rows = db.conn.execute(
            "SELECT id, note_text FROM nodes WHERE COALESCE(note_format, '') <> 'md'"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return 0
    done = 0
    for row in rows:
        node_id, html = row[0], (row[1] or "")
        if not html.strip():
            db.update_node(node_id, note_text="", note_format="md")
            continue
        try:
            doc = QTextDocument()
            doc.setHtml(_drop_img_size(html))
            md = document_to_markdown(doc)
        except Exception:  # noqa: BLE001 - 转不了就留着原样，不破坏数据
            continue
        db.update_node(node_id, note_text=md, note_format="md")
        done += 1
    return done
