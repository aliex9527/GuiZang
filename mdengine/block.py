"""块级解析：文本行 → 块级 AST。

整体是一个「逐行前进 + 遇到块起始就递归」的循环，没有做完整的 CommonMark
状态机——目标是把归藏实际会遇到的写法都吃对，而不是通过 spec 测试集。

支持的块：ATX / Setext 标题、段落、围栏与缩进代码块、引用（可嵌套）、
有序/无序/任务列表（可嵌套、紧凑与松散）、管道表格、分隔线、admonition、
原样 HTML 块、链接引用定义。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import nodes as nd
from .inline import InlineParser, normalize_label
from .options import Options

ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
ATX_TRAIL_RE = re.compile(r"[ \t]+#+[ \t]*$")
FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`\n]*)$")
HR_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
LIST_RE = re.compile(r"^( {0,3})([-+*]|\d{1,9}[.)])([ \t]+|$)(.*)$")
QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
ADMON_RE = re.compile(r"^ {0,3}!!!\s*([\w\-]+)(?:\s+\"([^\"]*)\")?\s*$")
TASK_RE = re.compile(r"^\[([ xX])\](?:[ \t]+|$)")
TABLE_SEP_RE = re.compile(
    r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
)
REF_RE = re.compile(
    r"^ {0,3}\[([^\]]+)\]:[ \t]*(?:<([^>]*)>|(\S+))"
    r"(?:[ \t]*(?:\"([^\"]*)\"|'([^']*)'|\(([^)]*)\)))?[ \t]*$"
)
ATTR_TAIL_RE = re.compile(r"\s*\{([^{}]*)\}\s*$")

# 原样 HTML 块：只有这些标签能被识别成块级，避免 <https://x> 这类被误吞
HTML_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "iframe", "li", "main", "nav", "ol",
    "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "ul", "script", "style", "video", "audio", "canvas", "svg",
})
HTML_START_RE = re.compile(r"^ {0,3}(?:<!--|<\?|<![A-Za-z])")
HTML_TAG_START_RE = re.compile(r"^ {0,3}</?([A-Za-z][\w:\-]*)")

# 递归深度上限。编辑器里粘进来一段 500 层嵌套引用是真实可能的事故，
# 与其让 Python 抛 RecursionError 把界面带崩，不如在超深处降级成纯文本。
MAX_NESTING = 64


def normalize_source(source: str) -> str:
    """统一换行：CRLF / CR / U+2028 / U+2029 一律折成 ``\\n``，并去掉 BOM。"""
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def split_row(line: str) -> List[str]:
    """按未转义的 ``|`` 切表格行。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]

    cells: List[str] = []
    cur: List[str] = []
    escaped = False
    for ch in s:
        if escaped:
            cur.append(ch)
            escaped = False
            continue
        if ch == "\\":
            cur.append(ch)
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


class BlockParser:
    """块级解析器。实例可复用，但每次 :meth:`parse` 会重置引用表。"""

    def __init__(self, options: Optional[Options] = None) -> None:
        self.o = options or Options()
        self.refs: Dict[str, Tuple[str, str]] = {}
        self.inline = InlineParser(self.o, self.refs)
        self._refs_sig: Optional[Tuple[Tuple[str, str], ...]] = None

    # ------------------------------------------------------------ 对外
    def parse(self, source: str,
              seed_refs: Optional[Dict[str, Tuple[str, str]]] = None) -> nd.Document:
        """解析整篇文档。

        Args:
            source: Markdown 原文。
            seed_refs: 预置的引用定义表。单独解析一段文字时用它补齐文档级
                定义；整篇解析不需要传。
        """
        return self.parse_spans(source, seed_refs)[0]

    def parse_spans(self, source: str,
                    seed_refs: Optional[Dict[str, Tuple[str, str]]] = None
                    ) -> Tuple[nd.Document, List[Tuple[int, int]]]:
        """解析整篇文档，并报告每个顶层块占用的行范围。

        Returns:
            ``(document, spans)``，``spans[i]`` 是 ``document.children[i]`` 的
            ``(起始行, 结束行)``，行号对齐 ``source`` 按 ``\\n`` 切分的下标
            （结束行不含）。引用定义行被替换成空行，行号依然对得上。
        """
        if not source:
            return nd.Document([]), []
        lines = self._extract_refs(normalize_source(source).split("\n"),
                                   seed=seed_refs)
        # 引用定义变了，行内缓存里的 [x] 可能指向旧地址（甚至从链接退化成文字）
        sig = tuple(sorted(self.refs.items()))
        if sig != self._refs_sig:
            self.inline.clear_cache()
            self._refs_sig = sig

        spans: List[Tuple[int, int]] = []
        doc = nd.Document(self._blocks(lines, 0, spans))
        return doc, spans

    def collect_refs(self, source: str) -> Dict[str, Tuple[str, str]]:
        """只抽取全篇的引用定义表，不建 AST。"""
        self._extract_refs(normalize_source(source).split("\n"))
        return dict(self.refs)

    # ------------------------------------------------------------ 预处理
    def _extract_refs(self, lines: List[str],
                      seed: Optional[Dict[str, Tuple[str, str]]] = None) -> List[str]:
        """拎出 ``[label]: url "title"`` 定义，其余行原样保留。

        ``seed`` 是整篇的引用表（增量渲染用）。注意这里是对 ``self.refs``
        **原地** clear/update：``InlineParser`` 持有的是同一个 dict 对象。
        """
        self.refs.clear()
        if seed:
            self.refs.update(seed)
        out: List[str] = []
        fence: Optional[str] = None
        for line in lines:
            fm = FENCE_RE.match(line)
            if fence is not None:
                out.append(line)
                if (fm and fm.group(2)[0] == fence[0]
                        and len(fm.group(2)) >= len(fence)
                        and not fm.group(3).strip()):
                    fence = None
                continue
            if fm:
                fence = fm.group(2)
                out.append(line)
                continue
            m = REF_RE.match(line)
            if m:
                key = normalize_label(m.group(1))
                if key and key not in self.refs:
                    dest = m.group(2) or m.group(3) or ""
                    title = m.group(4) or m.group(5) or m.group(6) or ""
                    self.refs[key] = (dest, title)
                out.append("")
                continue
            out.append(line)
        return out

    # ------------------------------------------------------------ 主循环
    def _blocks(self, lines: List[str], depth: int = 0,
                spans: Optional[List[Tuple[int, int]]] = None) -> List[nd.Node]:
        """逐行切块。

        Args:
            spans: 传一个空列表进来时，按顺序追加每个顶层块的 ``(起始行, 结束行)``
                （结束行不含）。增量渲染靠它把块映射回原文，别处不用传。
        """
        if depth > MAX_NESTING:
            text = "\n".join(lines).strip("\n")
            if not text.strip():
                return []
            return [nd.Paragraph([nd.Text(text)])]

        out: List[nd.Node] = []
        i, n = 0, len(lines)
        while i < n:
            start = i
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            node: nd.Node
            m = ATX_RE.match(line)
            fm = FENCE_RE.match(line)
            am = ADMON_RE.match(line) if self.o.has("admonition") else None

            if m:                                       # ATX 标题
                raw = (m.group(2) or "").strip()
                raw = ATX_TRAIL_RE.sub("", raw).strip()
                ident = None
                if self.o.has("attr_list"):
                    at = ATTR_TAIL_RE.search(raw)
                    if at:
                        ident = self._attr_id(at.group(1))
                        raw = raw[:at.start()].strip()
                node = nd.Heading(len(m.group(1)), self.inline.parse(raw), ident)
                i += 1

            elif fm and self.o.has("fenced_code"):      # 围栏代码块
                node, i = self._fenced(lines, i, fm)

            # 分隔线（要在列表之前判断：`- - -` 是分隔线不是列表）
            elif HR_RE.match(line):
                node, i = nd.ThematicBreak(), i + 1

            elif QUOTE_RE.match(line):                  # 引用
                node, i = self._quote(lines, i, depth)

            elif am:                                    # admonition
                node, i = self._admonition(lines, i, am, depth)

            elif self.o.has("indented_code") and line.startswith("    "):
                node, i = self._indented(lines, i)

            elif LIST_RE.match(line):                   # 列表
                node, i = self._list(lines, i, depth)

            elif (self.o.has("tables") and "|" in line
                  and self._is_table_start(lines, i)):  # 表格
                node, i = self._table(lines, i)

            elif self.o.has("html") and self._is_html_start(line):
                node, i = self._html_block(lines, i)

            else:                                       # 段落（含 Setext 提升）
                node, i = self._paragraph(lines, i)

            out.append(node)
            if spans is not None:
                spans.append((start, i))

        return out

    # ------------------------------------------------------------ 逐个块
    def _fenced(self, lines: List[str], i: int, fm: re.Match):
        indent = len(fm.group(1))
        fence = fm.group(2)
        info = fm.group(3).strip()
        close_re = re.compile(r"^ {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*$")
        i += 1
        body: List[str] = []
        while i < len(lines):
            if close_re.match(lines[i]):
                i += 1
                break
            raw = lines[i]
            strip_n = min(indent, len(raw) - len(raw.lstrip(" ")))
            body.append(raw[strip_n:])
            i += 1
        return nd.CodeBlock("\n".join(body), info), i

    def _indented(self, lines: List[str], i: int):
        body: List[str] = []
        while i < len(lines):
            raw = lines[i]
            if not raw.strip():
                body.append("")
                i += 1
                continue
            if not raw.startswith("    "):
                break
            body.append(raw[4:])
            i += 1
        while body and not body[-1].strip():
            body.pop()
        return nd.CodeBlock("\n".join(body), ""), i

    def _quote(self, lines: List[str], i: int, depth: int):
        buf: List[str] = []
        n = len(lines)
        while i < n:
            m = QUOTE_RE.match(lines[i])
            if m:
                buf.append(m.group(1))
                i += 1
                continue
            # 懒续行：引用内部的普通文字行
            if (lines[i].strip() and buf and buf[-1].strip()
                    and not self._interrupts(lines[i])):
                buf.append(lines[i])
                i += 1
                continue
            break
        return nd.BlockQuote(self._blocks(buf, depth + 1)), i

    def _admonition(self, lines: List[str], i: int, m: re.Match, depth: int):
        kind = m.group(1).lower()
        title = m.group(2) or kind.capitalize()
        i += 1
        buf: List[str] = []
        n = len(lines)
        while i < n:
            raw = lines[i]
            if not raw.strip():
                buf.append("")
                i += 1
                continue
            if raw.startswith("    "):
                buf.append(raw[4:])
                i += 1
                continue
            break
        return nd.Admonition(kind, title, self._blocks(buf, depth + 1)), i

    def _list(self, lines: List[str], i: int, depth: int):
        first = LIST_RE.match(lines[i])
        marker0 = first.group(2)
        ordered = marker0[0].isdigit()
        start = int(re.match(r"\d+", marker0).group()) if ordered else 1
        base_indent = len(first.group(1))
        items: List[nd.ListItem] = []
        loose = False
        n = len(lines)

        while i < n:
            m = LIST_RE.match(lines[i])
            if not m:
                break
            if m.group(2)[0].isdigit() != ordered:
                break
            if len(m.group(1)) != base_indent:
                break

            marker = m.group(2)
            spaces = m.group(3) or ""
            pad = len(spaces) if 0 < len(spaces) <= 4 else 1
            if not spaces:
                pad = 1
            content_indent = base_indent + len(marker) + pad

            cur: List[str] = [m.group(4)]
            i += 1
            pending_blank = 0

            while i < n:
                raw = lines[i]
                if not raw.strip():
                    cur.append("")
                    pending_blank += 1
                    i += 1
                    continue
                indent = len(raw) - len(raw.lstrip(" "))
                if indent >= content_indent:
                    if pending_blank:
                        loose = True
                    cur.append(raw[content_indent:])
                    pending_blank = 0
                    i += 1
                    continue
                if LIST_RE.match(raw):
                    break
                if indent == 0 and not pending_blank and not self._interrupts(raw):
                    cur.append(raw)      # 懒续行
                    i += 1
                    continue
                break

            trailing_blank = pending_blank > 0
            while cur and not cur[-1].strip():
                cur.pop()

            task: Optional[bool] = None
            if self.o.has("tasklist") and cur:
                tm = TASK_RE.match(cur[0])
                if tm:
                    task = tm.group(1).lower() == "x"
                    rest = cur[0][tm.end():]
                    cur = ([rest] + cur[1:]) if rest or len(cur) > 1 else [""]

            items.append(nd.ListItem(self._blocks(cur, depth + 1), task))
            if trailing_blank and i < n and LIST_RE.match(lines[i]):
                loose = True

        return nd.ListBlock(ordered, items, start, tight=not loose), i

    def _is_table_start(self, lines: List[str], i: int) -> bool:
        if i + 1 >= len(lines):
            return False
        sep = lines[i + 1]
        if "|" not in sep and "|" not in lines[i]:
            return False
        if not TABLE_SEP_RE.match(sep):
            return False
        return "|" in lines[i] and ("|" in sep or len(split_row(lines[i])) == len(split_row(sep)))

    def _table(self, lines: List[str], i: int):
        heads = [self.inline.parse(c) for c in split_row(lines[i])]
        aligns: List[Optional[str]] = []
        for cell in split_row(lines[i + 1]):
            cell = cell.strip()
            if cell.startswith(":") and cell.endswith(":"):
                aligns.append("center")
            elif cell.endswith(":"):
                aligns.append("right")
            elif cell.startswith(":"):
                aligns.append("left")
            else:
                aligns.append(None)

        width = len(heads)
        while len(aligns) < width:
            aligns.append(None)

        i += 2
        rows: List[List[List[nd.Node]]] = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            cells = split_row(lines[i])
            parsed = [self.inline.parse(c) for c in cells[:width]]
            while len(parsed) < width:
                parsed.append([])
            rows.append(parsed)
            i += 1

        return nd.Table(heads, rows, aligns[:width]), i

    def _html_block(self, lines: List[str], i: int):
        buf: List[str] = []
        n = len(lines)
        while i < n and lines[i].strip():
            buf.append(lines[i])
            i += 1
        return nd.HtmlBlock("\n".join(buf)), i

    def _paragraph(self, lines: List[str], i: int):
        buf: List[str] = [lines[i]]
        i += 1
        level = 0
        n = len(lines)

        while i < n:
            raw = lines[i]
            if not raw.strip():
                break
            sm = SETEXT_RE.match(raw)
            if sm and self.o.has("setext"):
                level = 1 if sm.group(1)[0] == "=" else 2
                i += 1
                break
            if self._interrupts(raw):
                break
            if self.o.has("tables") and "|" in raw and self._is_table_start(lines, i):
                break
            buf.append(raw)
            i += 1

        text = "\n".join(buf)
        if level:
            return nd.Heading(level, self.inline.parse(text)), i
        return nd.Paragraph(self.inline.parse(text)), i

    # ------------------------------------------------------------ 判定
    def _interrupts(self, line: str) -> bool:
        """这一行能否打断正在收集的段落。"""
        if ATX_RE.match(line):
            return True
        if HR_RE.match(line):
            return True
        if QUOTE_RE.match(line):
            return True
        fm = FENCE_RE.match(line)
        if fm and self.o.has("fenced_code"):
            return True
        if self.o.has("admonition") and ADMON_RE.match(line):
            return True
        m = LIST_RE.match(line)
        if m:
            marker = m.group(2)
            if marker[0].isdigit():
                # 有序列表只有从 1 开始才能打断段落（CommonMark 规则）
                return int(re.match(r"\d+", marker).group()) == 1
            return bool(m.group(4).strip())
        if self.o.has("html") and self._is_html_start(line):
            return True
        return False

    @staticmethod
    def _is_html_start(line: str) -> bool:
        if HTML_START_RE.match(line):
            return True
        m = HTML_TAG_START_RE.match(line)
        return bool(m and m.group(1).lower() in HTML_BLOCK_TAGS)

    @staticmethod
    def _attr_id(attrs: str) -> Optional[str]:
        for token in attrs.split():
            if token.startswith("#"):
                return token[1:]
        return None
