"""行内解析：一行文本 → 行内 AST。

实现思路是 CommonMark 的两段式：

1. **扫描**（:meth:`InlineParser._tokenize`）把文本切成「文本片段 / 代码 /
   链接 / 图片 / 自动链接 / HTML / 强调分隔符」这些原子，遇到 ``*`` ``_``
   ``~`` ``=`` 的连续串时记成一个分隔符原子，并算出它能不能开通/闭合。
2. **配对**（:meth:`InlineParser._emphasis`）在分隔符序列上做「闭合符向前找
   开通符」，命中就套一层节点。相比一堆正则替换，这样嵌套
   ``**a *b* c**``、``***x***`` 才能正确成型。

约定：
* ``_`` 遵循 CommonMark 的「词内不强调」规则，``snake_case_name`` 不会被拆。
* ``~~`` 与 ``==`` 只认成对的两个字符，单个 ``~`` / ``=`` 一律当普通文本。
"""

from __future__ import annotations

import re
import string
import unicodedata
from typing import Dict, List, Optional, Tuple

from . import nodes as nd

# CommonMark 允许用反斜杠转义的字符就是 ASCII 标点
ESCAPABLE = frozenset(string.punctuation)

AUTOLINK_RE = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\s]*)>")
EMAIL_RE = re.compile(r"<([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})>")
HTML_TAG_RE = re.compile(
    r"<!--[\s\S]*?-->|</?[A-Za-z][\w:.\-]*(?:\s+[^<>]*?)?/?>"
)
ATTR_RE = re.compile(r"\{([^{}]*)\}")
_TITLE_CLOSE = {'"': '"', "'": "'", "(": ")"}

# 链接标签的最大扫描长度。Markdown 里超过两千字的「链接文字」没有实际意义，
# 但一行一万个未闭合的 ``[`` 是真实会遇到的事故输入。
MAX_LABEL = 2000

# 链接目标（URL）的长度上限。要单独设一个远小于 MAX_LABEL 的值：URL 里没有
# 空白也没有换行，未闭合的 ``(`` 会让扫描一路吃到上限，连续出现时就是 O(n²)——
# 实测「未闭合图片 ×500」在 2000 的窗口下仍要 310ms，压到 512 后降到 40ms 级。
MAX_DEST = 512


def is_punct(ch: str) -> bool:
    """CommonMark 口径的「标点」：Unicode 的 P* 与 S* 两类。"""
    if not ch:
        return False
    return unicodedata.category(ch)[0] in ("P", "S")


def normalize_label(label: str) -> str:
    """引用标签归一化：折叠空白 + 大小写不敏感。"""
    return " ".join(label.split()).lower()


class _Delim:
    """强调分隔符原子。"""

    __slots__ = ("ch", "count", "can_open", "can_close")

    def __init__(self, ch: str, count: int, can_open: bool, can_close: bool) -> None:
        self.ch = ch
        self.count = count
        self.can_open = can_open
        self.can_close = can_close

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "_Delim(%r, %d, %s, %s)" % (self.ch, self.count, self.can_open, self.can_close)


class InlineParser:
    """行内解析器。

    Args:
        options: 引擎选项。
        refs: 引用式链接表，``{归一化标签: (目标, 标题)}``，由块级解析器填充。
    """

    def __init__(self, options, refs: Optional[Dict[str, Tuple[str, str]]] = None,
                 cache_size: int = 4096) -> None:
        self.o = options
        self.refs = refs if refs is not None else {}
        # 行内解析占了整篇解析六成时间，而编辑器里没改动的段落文字一个字都没变。
        # 按原文做记忆化，宽表格/长列表的重复单元格也能一起省掉。
        self._cache: Dict[str, List[nd.Node]] = {}
        self._cache_size = max(64, int(cache_size))

    # ------------------------------------------------------------ 对外
    def parse(self, text: str) -> List[nd.Node]:
        """解析一段行内文本。

        返回的节点列表视为**只读**：同一段文字第二次解析会直接命中缓存、拿到
        同一个列表对象（渲染器不改 AST，所以安全）。引用定义变了要调
        :meth:`clear_cache`，否则 ``[x]`` 会拿旧的解析结果。
        """
        if not text:
            return []
        hit = self._cache.get(text)
        if hit is not None:
            return hit
        nodes = self._emphasis(self._tokenize(text))
        if len(self._cache) >= self._cache_size:
            self._cache.clear()
        self._cache[text] = nodes
        return nodes

    def clear_cache(self) -> None:
        """清掉行内解析缓存（引用表变化、选项变化时）。"""
        self._cache.clear()

    # ------------------------------------------------------------ 扫描
    def _tokenize(self, text: str) -> list:
        atoms: list = []
        buf: List[str] = []

        def flush() -> None:
            if buf:
                atoms.append(nd.Text("".join(buf)))
                buf.clear()

        i, n = 0, len(text)
        while i < n:
            ch = text[i]

            # 反斜杠转义
            if ch == "\\":
                nxt = text[i + 1] if i + 1 < n else ""
                if nxt and nxt in ESCAPABLE:
                    buf.append(nxt)
                    i += 2
                    continue
                if nxt == "\n":
                    flush()
                    atoms.append(nd.HardBreak())
                    i += 2
                    continue
                buf.append(ch)
                i += 1
                continue

            # 行内代码
            if ch == "`":
                run = 1
                while i + run < n and text[i + run] == "`":
                    run += 1
                end = self._find_backticks(text, i + run, run)
                if end is None:
                    buf.append(text[i:i + run])
                    i += run
                    continue
                flush()
                raw = text[i + run:end].replace("\n", " ")
                if len(raw) > 2 and raw[0] == " " and raw[-1] == " " and raw.strip():
                    raw = raw[1:-1]
                atoms.append(nd.Code(raw))
                i = end + run
                continue

            # 图片 / 链接
            if ch == "!" and i + 1 < n and text[i + 1] == "[":
                node, nxt = self._link(text, i + 1, image=True)
                if node is not None:
                    flush()
                    atoms.append(node)
                    i = nxt
                    continue
                buf.append(ch)
                i += 1
                continue
            if ch == "[":
                node, nxt = self._link(text, i, image=False)
                if node is not None:
                    flush()
                    atoms.append(node)
                    i = nxt
                    continue
                buf.append(ch)
                i += 1
                continue

            # 尖括号：自动链接 / 原样 HTML
            if ch == "<":
                node, nxt = self._angle(text, i)
                if node is not None:
                    flush()
                    atoms.append(node)
                    i = nxt
                    continue
                buf.append(ch)
                i += 1
                continue

            # 强调类分隔符
            if ch in "*_~=":
                run = 1
                while i + run < n and text[i + run] == ch:
                    run += 1
                if ch in "~=" and run != 2:
                    buf.append(text[i:i + run])
                    i += run
                    continue
                can_open, can_close = self._flanking(text, i, run, ch)
                flush()
                atoms.append(_Delim(ch, run, can_open, can_close))
                i += run
                continue

            # 换行
            if ch == "\n":
                hard = self.o.nl2br
                if buf:
                    joined = "".join(buf)
                    trimmed = joined.rstrip(" ")
                    if len(joined) - len(trimmed) >= 2:
                        hard = True
                    buf.clear()
                    if trimmed:
                        buf.append(trimmed)
                flush()
                atoms.append(nd.HardBreak() if hard else nd.SoftBreak())
                i += 1
                continue

            buf.append(ch)
            i += 1

        flush()
        return atoms

    # ------------------------------------------------------------ 细节：代码
    @staticmethod
    def _find_backticks(text: str, start: int, run: int) -> Optional[int]:
        """找到长度恰好 ``run`` 的反引号串的起始位置。"""
        i, n = start, len(text)
        while i < n:
            if text[i] != "`":
                i += 1
                continue
            j = i
            while j < n and text[j] == "`":
                j += 1
            if j - i == run:
                return i
            i = j
        return None

    # ------------------------------------------------------------ 细节：强调
    def _flanking(self, text: str, start: int, run: int, ch: str) -> Tuple[bool, bool]:
        prev = text[start - 1] if start > 0 else ""
        nxt = text[start + run] if start + run < len(text) else ""

        prev_ws = (not prev) or prev.isspace()
        next_ws = (not nxt) or nxt.isspace()
        prev_punct = is_punct(prev)
        next_punct = is_punct(nxt)

        left = (not next_ws) and ((not next_punct) or prev_ws or prev_punct)
        right = (not prev_ws) and ((not prev_punct) or next_ws or next_punct)

        if ch == "_":
            can_open = left and ((not right) or prev_punct)
            can_close = right and ((not left) or next_punct)
        else:
            can_open, can_close = left, right
        return can_open, can_close

    @staticmethod
    def _rule_of_three(opener: _Delim, closer: _Delim) -> bool:
        """CommonMark 的「三的倍数」规则：返回 True 表示不允许配对。"""
        if opener.ch not in "*_":
            return False
        if not (opener.can_close or closer.can_open):
            return False
        total = opener.count + closer.count
        if total % 3 != 0:
            return False
        return not (opener.count % 3 == 0 and closer.count % 3 == 0)

    def _emphasis(self, atoms: list) -> List[nd.Node]:
        # openers_bottom 是 CommonMark 参考实现里的剪枝：某种「闭合符类型」
        # 往前找失败一次之后，更靠前的分隔符不会再变成可配对的开通符
        # （它们只会被消耗，不会凭空多出来），所以下次直接跳过那一段。
        # 没有它，`*a**b***c*` 重复两千遍就是 O(n²)。
        openers_bottom: Dict[Tuple[str, bool, int], int] = {}

        i = 0
        guard = 0
        while i < len(atoms):
            guard += 1
            if guard > 200000:  # pragma: no cover - 极端输入的保险丝
                break
            cur = atoms[i]
            if not isinstance(cur, _Delim) or not cur.can_close or cur.count == 0:
                i += 1
                continue

            key = (cur.ch, cur.can_open, cur.count % 3)
            floor = openers_bottom.get(key, -1)

            opener_index = -1
            j = i - 1
            while j > floor:
                cand = atoms[j]
                if (isinstance(cand, _Delim) and cand.ch == cur.ch
                        and cand.can_open and cand.count > 0
                        and not self._rule_of_three(cand, cur)):
                    opener_index = j
                    break
                j -= 1

            if opener_index < 0:
                openers_bottom[key] = i - 1
                i += 1
                continue

            opener = atoms[opener_index]
            if cur.ch in "~=":
                use = 2
            else:
                use = 2 if (opener.count >= 2 and cur.count >= 2) else 1

            inner = [self._freeze(x) for x in atoms[opener_index + 1:i]]
            wrapped = self._wrap(cur.ch, use, inner)

            opener.count -= use
            cur.count -= use

            replacement: list = []
            if opener.count > 0:
                replacement.append(opener)
            replacement.append(wrapped)
            if cur.count > 0:
                replacement.append(cur)
            atoms[opener_index:i + 1] = replacement

            if cur.count > 0:
                i = opener_index + len(replacement) - 1
            else:
                i = opener_index + len(replacement)

        out: List[nd.Node] = []
        for atom in atoms:
            if isinstance(atom, _Delim):
                if atom.count > 0:
                    out.append(nd.Text(atom.ch * atom.count))
            else:
                out.append(atom)
        return out

    @staticmethod
    def _freeze(atom) -> nd.Node:
        """把尚未配对的分隔符固化成文本（被包进强调节点后不再参与配对）。"""
        if isinstance(atom, _Delim):
            return nd.Text(atom.ch * atom.count)
        return atom

    @staticmethod
    def _wrap(ch: str, use: int, inner: List[nd.Node]) -> nd.Node:
        if ch == "~":
            return nd.Strike(inner)
        if ch == "=":
            return nd.Mark(inner)
        return nd.Strong(inner) if use == 2 else nd.Emphasis(inner)

    # ------------------------------------------------------------ 细节：链接
    def _link(self, text: str, i: int, image: bool):
        """``[label](dest "title")`` / ``[label][ref]`` / ``[label]``。

        ``i`` 指向 ``[``。返回 ``(节点或 None, 新的扫描位置)``。

        这里有两条性能护栏，都是为了「一行里塞一万个 ``[``」这种输入不把
        编辑器卡死：先用 ``str.find`` 确认窗口里确实有 ``]``（C 层扫描，
        便宜），再给标签长度封顶。没有护栏时每个 ``[`` 都要扫到行尾，
        退化成 O(n²)——实测一万个 ``[`` 要 10 秒。
        """
        n = len(text)
        limit = min(n, i + MAX_LABEL)
        if text.find("]", i, limit) < 0:
            return None, i

        depth = 0
        j = i
        while j < limit:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                run = 1
                while j + run < n and text[j + run] == "`":
                    run += 1
                end = self._find_backticks(text, j + run, run)
                j = (end + run) if end is not None else (j + run)
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= limit:
            return None, i

        label = text[i + 1:j]
        k = j + 1

        # 行内形式 (dest "title")
        if k < n and text[k] == "(":
            dest, title, end = self._dest(text, k)
            if end is not None:
                return self._make_link(dest, title, label, image, text, end)

        # 引用形式 [label][ref] / [label][]
        if k < n and text[k] == "[":
            e = k + 1
            while e < n and text[e] != "]":
                if text[e] == "\\":
                    e += 1
                e += 1
            if e < n:
                rid = text[k + 1:e].strip() or label
                hit = self.refs.get(normalize_label(rid))
                if hit is not None:
                    return self._make_link(hit[0], hit[1], label, image, text, e + 1)

        # 快捷形式 [label]
        hit = self.refs.get(normalize_label(label))
        if hit is not None:
            return self._make_link(hit[0], hit[1], label, image, text, j + 1)

        return None, i

    def _make_link(self, dest: str, title: str, label: str, image: bool,
                   text: str, end: int):
        if image:
            node: nd.Node = nd.Image(self._unescape(dest), self._unescape(title),
                                     alt=self._plain(label))
            if self.o.has("attr_list"):
                m = ATTR_RE.match(text, end)
                if m:
                    width = self._parse_width(m.group(1))
                    if width:
                        node.width = width
                    end = m.end()
            return node, end
        return nd.Link(self._unescape(dest), self._unescape(title), self.parse(label)), end

    def _dest(self, text: str, k: int):
        """解析 ``(...)`` 里的目标与标题，返回 ``(dest, title, end)``。

        同样封顶：目标串不可能有几千字长，而未闭合的 ``(`` 如果一路扫到文末，
        连续出现时就是 O(n²)。
        """
        p, n = k + 1, min(len(text), k + MAX_DEST)
        while p < n and text[p] in " \t\n":
            p += 1

        if p < n and text[p] == "<":
            q = text.find(">", p)
            if q < 0:
                return "", "", None
            dest = text[p + 1:q]
            p = q + 1
        else:
            start = p
            depth = 0
            while p < n:
                ch = text[p]
                if ch == "\\":
                    p += 2
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        break
                    depth -= 1
                elif ch in " \t\n":
                    break
                p += 1
            dest = text[start:p]

        while p < n and text[p] in " \t\n":
            p += 1

        title = ""
        if p < n and text[p] in _TITLE_CLOSE:
            quote = text[p]
            close = _TITLE_CLOSE[quote]
            e = p + 1
            while e < n and text[e] != close:
                if text[e] == "\\":
                    e += 1
                e += 1
            if e >= n:
                return "", "", None
            title = text[p + 1:e]
            p = e + 1
            while p < n and text[p] in " \t\n":
                p += 1

        if p < n and text[p] == ")":
            return dest, title, p + 1
        return "", "", None

    @staticmethod
    def _parse_width(attrs: str) -> Optional[int]:
        for token in attrs.split():
            if token.startswith("width="):
                raw = token[6:].strip('"\'')
                if raw.isdigit():
                    return int(raw)
            if token.isdigit():
                return int(token)
        return None

    @staticmethod
    def _unescape(value: str) -> str:
        """去掉反斜杠转义，剩下原样的 URL（``gzs:///1`` 不能被改写）。"""
        return re.sub(r"\\([%s])" % re.escape(string.punctuation), r"\1", value)

    def _plain(self, text: str) -> str:
        """把一段 Markdown 压成纯文本，图片 alt 用。"""
        flat = re.sub(r"\s+", " ", text)
        flat = re.sub(r"[*_~=`]", "", flat)
        flat = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", flat)
        return flat.strip()

    # ------------------------------------------------------------ 细节：尖括号
    def _angle(self, text: str, i: int):
        if self.o.has("autolink"):
            m = AUTOLINK_RE.match(text, i)
            if m:
                url = m.group(1)
                return nd.Link(url, "", [nd.Text(url)]), m.end()
            m = EMAIL_RE.match(text, i)
            if m:
                mail = m.group(1)
                return nd.Link("mailto:" + mail, "", [nd.Text(mail)]), m.end()
        if self.o.has("html"):
            m = HTML_TAG_RE.match(text, i)
            if m:
                return nd.Html(m.group(0)), m.end()
        return None, i

def plain_text(nodes: List[nd.Node]) -> str:
    """取一段行内节点的纯文本（生成目录、图片 alt 用）。"""
    out: List[str] = []
    for node in nodes:
        if isinstance(node, nd.Text):
            out.append(node.value)
        elif isinstance(node, nd.Code):
            out.append(node.value)
        elif isinstance(node, (nd.Emphasis, nd.Strong, nd.Strike, nd.Mark)):
            out.append(plain_text(node.children))
        elif isinstance(node, (nd.Link,)):
            out.append(plain_text(node.children))
        elif isinstance(node, nd.Image):
            out.append(node.alt)
        elif isinstance(node, (nd.SoftBreak, nd.HardBreak)):
            out.append(" ")
    return "".join(out)
