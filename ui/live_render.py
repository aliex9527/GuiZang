"""Typora 式即时渲染：在同一个编辑区里隐藏标记、就地排版。

和「源码 + 右侧预览」的分屏方案相比，这里**不重建文档、不替换字符**——
那会毁掉光标位置、输入法和撤销栈。做法是只给字符**打格式**：

* 标记字符（``#``、``**``、反引号、链接目标）缩到 0.1pt 并染成背景色，
  视觉上消失，但仍可正常选中、删除、用方向键走过去；
* 标题放大加粗、粗斜体真正生效、行内代码换等宽并加底色；
* 代码块、引用、表格这类块级底色由 :class:`LiveDecor` 用
  ``ExtraSelection`` 的整行宽度画出来（``QSyntaxHighlighter`` 只能改字符格式）。

两份数据只有一份真相：``toPlainText()`` 永远是用户写下的原文，存盘链路不用改。

标记字符**一律不显示**：光标停在哪一段都一样，不会突然露出 `#`、`**`、反引号。
要看原始标记就切「源码模式」（那条路走 :meth:`_paint_source`）。这样标题的字号
也不会随光标进出而跳动，上下文不会上下晃。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtCore import QRect
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QImage,
                           QPainter, QPen, QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtWidgets import QTextEdit

from ui.theme import P

# 标记隐藏后的字号：再小就取整成 0，占位会变成 1px 宽
_HIDDEN_SIZE = 0.1

# 标题相对正文的字号倍数（h1..h6）
HEAD_SCALE = (1.85, 1.55, 1.30, 1.16, 1.04, 1.0)

# 超长行不做渲染：单行几千字符时正则扫描会拖慢输入，退回源码着色
MAX_RENDER_LINE = 4000

# 内联图片的最大显示尺寸（超出按比例缩）
MAX_IMAGE_W = 620
MAX_IMAGE_H = 460


class ImageRow:
    """一张"独占一行"的图片：源图 + 计算好的显示尺寸。"""

    __slots__ = ("image", "draw_w", "draw_h", "line_h")

    def __init__(self, image: QImage, draw_w: int, draw_h: int) -> None:
        self.image = image
        self.draw_w = draw_w
        self.draw_h = draw_h
        self.line_h = draw_h + 20      # 行高留出上下空隙


def _brush_none() -> QBrush:
    return QBrush(Qt.BrushStyle.NoBrush)


def _mono_family() -> str:
    """等宽字体族：优先用系统等宽，拿不到就退回 Qt 的固定字体。"""
    for name in ("Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo",
                 "DejaVu Sans Mono", "Courier New"):
        if name in QFontDatabase.families():
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def _srgb(color: str) -> QColor:
    return QColor(color)


class LiveHighlighter(QSyntaxHighlighter):
    """Typora 式即时渲染。

    Args:
        document: 目标 ``QTextDocument``。
        body_font: 正文字体（字号作为基准，标题按 :data:`HEAD_SCALE` 放大）。
    """

    FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})[ \t]*(\S*)[ \t]*$")
    ATX = re.compile(r"^(\s{0,3})(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)[ \t]*$")
    ATX_SIMPLE = re.compile(r"^(\s{0,3})(#{1,6})[ \t]+(.*)$")
    QUOTE = re.compile(r"^(\s{0,3})((?:>[ \t]?)+)(.*)$")
    HR = re.compile(r"^\s{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
    TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
    TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
    LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])([ \t]+)")
    TASK = re.compile(r"^(\s*)([-*+]|\d+[.)])([ \t]+)(\[[ xX]\])")
    REF_DEF = re.compile(r"^\s{0,3}\[[^\]\n]+\]:[ \t]*\S+")

    def __init__(self, document, body_font: QFont) -> None:
        super().__init__(document)
        self._body = QFont(body_font)
        self._mono = _mono_family()
        self.render = True          # False → 纯源码着色
        self.active = -1            # 恒为 -1：标记不随光标显示，装饰层用它判断图片行
        # 块号 → 图片行的目标行高（像素）。由 MarkdownSource 扫图后填，
        # 高亮器只负责把行撑到那么高，图片本身由 LiveDecor 画。
        self.img_heights: Dict[int, float] = {}
        self._stack: List["QTextCharFormat"] = []
        self.apply_theme()

    # ------------------------------------------------------------ 主题

    def set_body_font(self, font: QFont) -> None:
        self._body = QFont(font)
        self.apply_theme()

    def apply_theme(self) -> None:
        self._bg = _srgb(P["panel"])
        size = (self._body.pointSizeF() if self._body.pointSizeF() > 0
                else float(self._body.pointSize()))
        self._size = size
        base = QTextCharFormat()
        base.setFontPointSize(size)
        base.setForeground(_srgb(P["note_text"]))
        base.setFontFamilies(list(self._body.families()) or ["sans-serif"])
        self.f_base = base

        # 隐藏：字号极小 + 全透明前景。用 alpha=0 而不是"背景色"——背景色只在
        # 纯色底上等效，一旦下面有图片或色块就会露出来。
        self.f_hidden = self._plain()
        self.f_hidden.setFontPointSize(_HIDDEN_SIZE)
        self.f_hidden.setForeground(QColor(0, 0, 0, 0))
        self.f_hidden.setBackground(_brush_none())

        self.f_head = self._plain()
        self.f_head.setForeground(_srgb(P["note_text"]))
        self.f_head.setFontWeight(QFont.Weight.Bold)

        self.f_bold = self._plain()
        self.f_bold.setFontWeight(QFont.Weight.Bold)

        self.f_italic = self._plain()
        self.f_italic.setFontItalic(True)

        self.f_strike = self._plain()
        self.f_strike.setFontStrikeOut(True)
        self.f_strike.setForeground(_srgb(P["muted"]))

        self.f_markbg = self._plain()
        self.f_markbg.setBackground(_srgb(P.get("mark_bg", "#fff3a3")))
        self.f_markbg.setForeground(_srgb(P.get("mark_text", P["note_text"])))

        self.f_code = self._plain()
        self.f_code.setFontFamilies([self._mono])
        self.f_code.setFontPointSize(size * 0.92)
        self.f_code.setBackground(_srgb(P["inline_bg"]))
        self.f_code.setForeground(_srgb(P.get("inline_text", P["code_text"])))

        self.f_code_line = self._plain()
        self.f_code_line.setFontFamilies([self._mono])
        self.f_code_line.setFontPointSize(size * 0.92)
        self.f_code_line.setForeground(_srgb(P["code_text"]))

        self.f_link = self._plain()
        self.f_link.setForeground(_srgb(P["link"]))
        self.f_link.setFontUnderline(True)

        self.f_quote = self._plain()
        self.f_quote.setForeground(_srgb(P["quote_text"]))

        self.f_quote_mark = self._plain()
        self.f_quote_mark.setForeground(_srgb(P["accent_line"]))
        self.f_quote_mark.setFontWeight(QFont.Weight.Bold)

        self.f_dim = self._plain()
        self.f_dim.setForeground(_srgb(P["muted"]))

        # 幽灵：全透明，看不见但保留行高（分隔线的横线要画在这一行中间，
        # 行高塌了位置就错了；图片行也靠它撑起高度）
        self.f_ghost = self._plain()
        self.f_ghost.setForeground(QColor(0, 0, 0, 0))
        self.f_ghost.setFontPointSize(size * 0.9)

        self.f_indent = self._plain()
        self.f_indent.setFontFamilies([self._mono])

        # 源码着色用（render=False 时）
        self.f_src_marker = self._plain()
        self.f_src_marker.setForeground(_srgb(P["accent"]))
        self.f_src = self._plain()
        self.f_src.setForeground(_srgb(P["note_text"]))
        self.f_src_code = self._plain()
        self.f_src_code.setForeground(_srgb(P["quote_text"]))
        self.rehighlight()

    def _plain(self) -> QTextCharFormat:
        """以正文格式为底的空白格式。"""
        f = QTextCharFormat(self.f_base) if hasattr(self, "f_base") else QTextCharFormat()
        return f

    def _merge(self, base: QTextCharFormat, extra: QTextCharFormat) -> QTextCharFormat:
        f = QTextCharFormat(base)
        f.merge(extra)
        return f

    def _marker(self) -> QTextCharFormat:
        """行内标记（``**``、反引号、``~~``、``==``、``[](…)``）的格式：一律不可见。"""
        return self.f_hidden

    # ------------------------------------------------------------ 主入口

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        if not self.render:
            self._paint_source(text)
            return

        no = self.currentBlock().blockNumber()

        if len(text) > MAX_RENDER_LINE:
            self.setCurrentBlockState(0)
            self.setFormat(0, len(text), self.f_base)
            return

        prev = self.previousBlockState()
        fence = self.FENCE.match(text)

        # ---- 围栏代码块：``` 隐藏，语言名留成小标签
        if fence:
            opening = prev != 1
            self.setCurrentBlockState(1 if opening else 0)
            self._paint_fence(fence)
            return
        if prev == 1:
            self.setCurrentBlockState(1)
            self.setFormat(0, len(text), self.f_code_line)
            return
        self.setCurrentBlockState(0)

        # ---- 独占一行的图片：整行抹掉，用行首字符把行高撑到图片大小
        target = self.img_heights.get(no)
        if target:
            self._paint_image_row(text, target)
            return

        # ---- 分隔线：--- 擦成透明（保留行高），横线由 LiveDecor 画（真正贯通整行）
        if self.HR.match(text):
            self.setFormat(0, len(text), self.f_ghost)
            return

        # ---- 标题
        m = self.ATX.match(text) or self.ATX_SIMPLE.match(text)
        if m:
            level = len(m.group(2))
            body_start = m.start(3)
            head = QTextCharFormat(self.f_base)
            head.merge(self.f_head)
            head.setFontPointSize(self._size * HEAD_SCALE[level - 1])
            length = len(text) - body_start
            if length > 0:
                self.setFormat(body_start, length, head)
                self._inline(text, body_start, len(text), head)
            # 井号一律藏掉：标题行前面不该看见 `#`（光标停在标题上时也一样）。
            # 只藏视觉，字符还在文本里——源码模式、选中复制都照旧拿得到。
            self.setFormat(0, body_start, self.f_hidden)
            return

        # ---- 引用
        m = self.QUOTE.match(text)
        if m:
            # 竖线已经由装饰层画在行首，> 擦成透明
            self.setFormat(m.start(2), len(m.group(2)), self.f_ghost)
            body_start = m.end(2)
            body = text[body_start:]
            self.setFormat(body_start, len(body), self.f_quote)
            self._inline(text, body_start, len(text), self.f_quote)
            return

        # ---- 表格分隔行：| :--- | :---: | 这一行对读者没有意义，整行擦掉。
        # 用 ghost 而不是 hidden：0.1pt 会让行高塌掉，表头和数据行就贴在一起了。
        if self.TABLE_ROW.match(text) and self.TABLE_SEP.match(text):
            self.setFormat(0, len(text), self.f_ghost)
            return

        # ---- 表格行：竖线淡化，内容等宽便于对齐
        if self.TABLE_ROW.match(text):
            nxt = self.currentBlock().next()
            is_head = (nxt.isValid()
                       and self.TABLE_SEP.match(nxt.text())
                       and not self.TABLE_ROW.match(nxt.text()))
            cells = QTextCharFormat(self.f_base)
            cells.setFontFamilies([self._mono])
            cells.setFontPointSize(self._size * 0.92)
            if is_head:
                cells.setFontWeight(QFont.Weight.Bold)
            self.setFormat(0, len(text), cells)
            self._table_pipes(text)
            self._inline(text, 0, len(text), cells)
            return

        # ---- 引用定义行：[label]: url 不是正文，压暗
        if self.REF_DEF.match(text):
            self.setFormat(0, len(text), self.f_dim)
            return

        # ---- 段落正文（先铺底再描行内，顺序反了会把行内格式盖掉）
        self.setFormat(0, len(text), self.f_base)
        self._inline(text, 0, len(text), self.f_base)

        # ---- 列表 / 任务项的标记最后描：位置与正文重叠，必须后写
        task = self.TASK.match(text)
        if task:
            self._paint_list(text, task, task=True)
        else:
            self._paint_list(text, self.LIST.match(text), task=False)

    # ------------------------------------------------------------ 块级

    def _paint_fence(self, m: re.Match) -> None:
        text = self.currentBlock().text()
        lang = m.group(2)
        start, end = m.start(1), m.end(1)
        # 三个反引号一律擦掉。用 ghost（全透明、但保留 0.9 倍字号的宽度和行高），
        # 不能用 hidden 的 0.1pt：行高会塌成 0，那一行点不进去、光标也看不见。
        self.setFormat(start, end - start, self.f_ghost)
        if lang:
            lab = QTextCharFormat(self.f_base)
            lab.setFontPointSize(self._size * 0.72)
            lab.setForeground(_srgb(P["muted"]))
            lab.setFontFamilies([self._mono])
            self.setFormat(m.start(2), len(lang), lab)
        # 围栏行整行用代码底色，和下面的代码连成一片
        rest = len(text) - end
        if rest > 0:
            self.setFormat(end, rest, self.f_code_line)

    def _paint_image_row(self, text: str, line_h: float) -> None:
        """把图片行整行抹成背景色，只让第一个字符把行高撑起来。"""
        self.setFormat(0, len(text), self.f_ghost)
        if text:
            lift = QTextCharFormat(self.f_ghost)
            lift.setFontPointSize(self._size_for_height(line_h))
            self.setFormat(0, 1, lift)

    def _size_for_height(self, px: float) -> float:
        """反算"要让行高达到 px 像素，字号该是多大"。

        行高与字号在 Qt 里是线性的，量一次比例就够，不必迭代。
        """
        probe = QFont(self._body)
        probe.setPointSizeF(20.0)
        h = QFontMetricsF(probe).height()
        return max(1.0, 20.0 * px / max(h, 1.0))

    def _paint_list(self, text: str, m: Optional[re.Match], task: bool) -> None:
        if not m:
            return
        # 行首缩进用等宽字体：比例字体下 4 个空格只有 ~10px，层级看不出来
        indent_end = m.start(2)
        if indent_end > 0:
            self.setFormat(0, indent_end, self.f_indent)
        bullet = m.group(2)
        if bullet[0].isdigit():
            # 有序编号是内容（成品渲染也是 1. 2. 3.），保留，压成中性灰
            self.setFormat(m.start(2), len(bullet), self.f_dim)
        else:
            # 无序的 - * + 擦成全透明。宽度必须留着，否则圆点没地方画、
            # 文字也会整体左移，和有序列表错开。
            self.setFormat(m.start(2), len(bullet), self.f_ghost)
        if task:
            box = m.group(4)          # "[x]" / "[ ]"
            done = box[1] in "xX"
            bracket = QTextCharFormat(self.f_base)
            bracket.setForeground(_srgb(P["accent_line"]))
            self.setFormat(m.start(4), 1, bracket)
            self.setFormat(m.end(4) - 1, 1, bracket)
            inside = QTextCharFormat(self.f_base)
            inside.setForeground(_srgb(P["ok"] if done else P["muted"]))
            if done:
                inside.setFontWeight(QFont.Weight.Bold)
            self.setFormat(m.start(4) + 1, 1, inside)

    def _table_pipes(self, text: str) -> None:
        """表格竖线压暗，让内容区看起来是"格子"而不是"一堆管道"。"""
        dim = QTextCharFormat(self.f_base)
        dim.setForeground(_srgb(P["accent_line"]))
        for i, ch in enumerate(text):
            if ch == "|":
                self.setFormat(i, 1, dim)

    # ------------------------------------------------------------ 行内

    def _inline(self, text: str, lo: int, hi: int, base: QTextCharFormat) -> None:
        """扫描 ``[lo, hi)`` 里的行内语法。

        ``base`` 是外层已应用的格式（标题的字号、粗体内部的加粗），递归时
        往里合并，而不是从头算，否则 ``**a `b` c**`` 里的 ``b`` 会掉回正文字号。
        """
        i = lo
        while i < hi:
            ch = text[i]

            if ch == "\\" and i + 1 < hi:
                i += 2
                continue

            if ch == "`":
                run = 1
                while i + run < hi and text[i + run] == "`":
                    run += 1
                close = text.find("`" * run, i + run, hi)
                if close < 0:
                    i += run
                    continue
                self.setFormat(i, run, self._marker())
                self.setFormat(close, run, self._marker())
                self.setFormat(i + run, close - i - run, self._merge(base, self.f_code))
                i = close + run
                continue

            if text.startswith("**", i) or text.startswith("__", i):
                tok = text[i:i + 2]
                close = self._find_close(text, i + 2, hi, tok)
                if close > i:
                    self.setFormat(i, 2, self._marker())
                    self.setFormat(close, 2, self._marker())
                    inner = self._merge(base, self.f_bold)
                    self.setFormat(i + 2, close - i - 2, inner)
                    self._inline(text, i + 2, close, inner)
                    i = close + 2
                    continue
                i += 2
                continue

            if ch == "*":
                close = self._find_close(text, i + 1, hi, "*", single=True)
                if close > i:
                    self.setFormat(i, 1, self._marker())
                    self.setFormat(close, 1, self._marker())
                    inner = self._merge(base, self.f_italic)
                    self.setFormat(i + 1, close - i - 1, inner)
                    self._inline(text, i + 1, close, inner)
                    i = close + 1
                    continue
                i += 1
                continue

            if text.startswith("~~", i) or text.startswith("==", i):
                tok = text[i:i + 2]
                close = text.find(tok, i + 2, hi)
                if close > i:
                    self.setFormat(i, 2, self._marker())
                    self.setFormat(close, 2, self._marker())
                    inner = self._merge(base, self.f_strike if tok == "~~" else self.f_markbg)
                    self.setFormat(i + 2, close - i - 2, inner)
                    self._inline(text, i + 2, close, inner)
                    i = close + 2
                    continue
                i += 2
                continue

            # 图片：保留一段淡色小字当作占位（缩略图由外层浮层负责）
            if text.startswith("![", i):
                m = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]*)\)").match(text, i, hi)
                if m:
                    fm = QTextCharFormat(base)
                    fm.setForeground(_srgb(P["accent_line"]))
                    self.setFormat(m.start(), m.end() - m.start(), fm)
                    i = m.end()
                    continue
                i += 2
                continue

            # 链接：[文字](url) → 只留文字，带下划线
            if ch == "[":
                m = re.compile(r"\[([^\]\n]*)\]\(([^)\s]*)\)").match(text, i, hi)
                if m:
                    self.setFormat(m.start(), 1, self._marker())
                    self.setFormat(m.start(1), m.end(1) - m.start(1),
                                   self._merge(base, self.f_link))
                    self.setFormat(m.end(1), m.end() - m.end(1), self._marker())
                    i = m.end()
                    continue
                i += 1
                continue

            # 自动链接 <https://...>
            if ch == "<":
                m = re.compile(r"<(https?://[^>\s]+)>").match(text, i, hi)
                if m:
                    self.setFormat(m.start(), 1, self._marker())
                    self.setFormat(m.start(1), m.end(1) - m.start(1),
                                   self._merge(base, self.f_link))
                    self.setFormat(m.end() - 1, 1, self._marker())
                    i = m.end()
                    continue
                i += 1
                continue

            i += 1

    @staticmethod
    def _find_close(text: str, lo: int, hi: int, tok: str, single: bool = False) -> int:
        """找成对标记的闭合位置；闭合符前面是空白时跳过（``a * b * c``）。"""
        j = lo
        while j < hi:
            k = text.find(tok, j, hi)
            if k < 0:
                return -1
            if single:
                if text.startswith("**", k):
                    j = k + 2
                    continue
            if k > lo and not text[k - 1].isspace():
                return k
            j = k + 1
        return -1

    # ------------------------------------------------------------ 源码模式

    def _paint_source(self, text: str) -> None:
        """纯源码模式：保留原来的语法着色（不隐藏任何字符）。"""
        if self.FENCE.match(text):
            self.setCurrentBlockState(0 if self.previousBlockState() == 1 else 1)
            self.setFormat(0, len(text), self.f_src_code)
            return
        if self.previousBlockState() == 1:
            self.setCurrentBlockState(1)
            self.setFormat(0, len(text), self.f_src_code)
            return
        self.setCurrentBlockState(0)

        if self.ATX.match(text) or self.ATX_SIMPLE.match(text):
            self.setFormat(0, len(text), self.f_head)
        elif self.QUOTE.match(text):
            self.setFormat(0, len(text), self.f_quote)
        else:
            m = self.LIST.match(text)
            if m:
                self.setFormat(m.start(2), m.end(2) - m.start(2), self.f_src_marker)

        for pattern, f in (
            (r"\*\*(?=\S)(.+?)(?<=\S)\*\*", self.f_bold),
            (r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)", self.f_italic),
            (r"~~(?=\S)(.+?)(?<=\S)~~", self.f_strike),
            (r"==(?=\S)(.+?)(?<=\S)==", self.f_markbg),
            (r"`[^`\n]+`", self.f_code),
            (r"!?\[[^\]\n]*\]\([^)\n]*\)", self.f_link),
            (r"<https?://[^>\s]+>", self.f_link),
        ):
            for mm in re.finditer(pattern, text):
                self.setFormat(mm.start(), len(mm.group(0)), f)


class LiveDecor:
    """块级装饰层：代码块底色、引用竖线、分隔横线、表头底色。

    这些都不能用 ``QTextCharFormat`` 表达（字符格式改不了行宽），而
    ``ExtraSelection`` 只能画整行背景、画不了竖线和边框。所以统一在
    :meth:`MarkdownSource.paintEvent` 里、``super().paintEvent()`` **之前**
    直接画到视口上——文字与选区由父类随后覆盖上来。

    前提是把 palette 的 Base 设成全透明：父类开画时会用 ``Base`` 填满视口，
    Base 透明时这个填充不产生任何像素，先画的层才不会被盖掉。
    """

    CODE = 1
    QUOTE = 2
    TABLE_HEAD = 3
    HR = 4
    BULLET = 5          # 无序列表的 - 已擦掉，这里补画一个圆点

    def __init__(self, edit: QTextEdit) -> None:
        self.edit = edit
        self.enabled = True
        self._kinds: List[int] = []
        self.images: Dict[int, "ImageRow"] = {}

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        """重算每个顶层块的装饰类型。

        只存下标（块序号）不存 ``QTextBlock``：编辑后块对象会失效，序号
        在下次刷新前一直有效，足够铺一帧。
        """
        if not self.enabled:
            self._kinds = []
            self.edit.viewport().update()
            return

        kinds: List[int] = []
        in_fence = False
        for block in self._blocks(self.edit.document()):
            text = block.text()
            kind = 0
            if LiveHighlighter.FENCE.match(text):
                in_fence = not in_fence
                kind = self.CODE
            elif in_fence:
                kind = self.CODE
            elif LiveHighlighter.QUOTE.match(text):
                kind = self.QUOTE
            elif LiveHighlighter.HR.match(text):
                kind = self.HR
            elif LiveHighlighter.LIST.match(text):
                # 无序列表的符号在正文里被擦成透明了，这里标记一下好补圆点；
                # 有序列表的 1. 2. 3. 是内容，照常显示，不用管。
                # 任务项自己有 [ ]，再补个圆点就成了两个符号，跳过。
                lm = LiveHighlighter.LIST.match(text)
                if (not lm.group(2)[0].isdigit()
                        and not LiveHighlighter.TASK.match(text)):
                    kind = self.BULLET
            elif LiveHighlighter.TABLE_ROW.match(text):
                nxt = block.next()
                if LiveHighlighter.TABLE_SEP.match(text):
                    kind = 0
                elif nxt.isValid() and LiveHighlighter.TABLE_SEP.match(nxt.text()):
                    kind = self.TABLE_HEAD        # 表格首行是表头
                elif in_fence is False and LiveHighlighter.TABLE_SEP.match(text):
                    kind = 0
            kinds.append(kind)
        self._kinds = kinds

    @staticmethod
    def _blocks(doc):
        block = doc.begin()
        while block.isValid():
            yield block
            block = block.next()

    # ------------------------------------------------------------ 绘制

    def paint(self, painter: "QPainter", rect) -> None:
        if not self.enabled or not self._kinds:
            return

        edit = self.edit
        offset = edit.contentOffset()
        bottom = rect.bottom()

        # 从第一个可见块开始：从文档头遍历的话，2000 块的笔记每帧要算
        # 2000 次 blockBoundingGeometry，滚动会掉到 15ms 一帧。
        active = getattr(edit, "highlighter", None)
        active = getattr(active, "active", -1) if active else -1

        block = edit.firstVisibleBlock()
        while block.isValid():
            no = block.blockNumber()
            kind = self._kinds[no] if 0 <= no < len(self._kinds) else 0
            row = self.images.get(no)
            if kind or (row is not None and no != active):
                geo = edit.blockBoundingGeometry(block).translated(offset)
                if geo.top() > bottom:
                    break
                if row is not None and no != active:
                    # 光标进入这一行时收起图片、显示 ![..](..) 原文，否则
                    # 撑高的行会让光标变成一根几百像素高的竖条。
                    self._draw_image(painter, geo, row)
                elif kind:
                    self._draw(painter, geo, kind, block)
            block = block.next()

    def _draw(self, painter: "QPainter", geo, kind: int, block) -> None:
        left = geo.left()
        right = self.edit.viewport().width() - 2
        y0 = int(geo.top())
        h = int(geo.height()) + 1

        if kind == self.CODE:
            painter.fillRect(int(left) - 6, y0, int(right - left) + 12, h,
                             _srgb(P["code_bg"]))
        elif kind == self.QUOTE:
            painter.fillRect(int(left) - 6, y0, int(right - left) + 12, h,
                             _srgb(P["quote_bg"]))
            # 竖线是引用最明显的识别符：底色可有可无，这条线不能少。
            # x 必须夹在视口内——正文左边界为 0 时画在 -6 会整条看不见。
            bar = _srgb(P["muted"])
            bar.setAlpha(225)
            painter.fillRect(max(2, int(left) - 6), y0, 3, h, bar)
        elif kind == self.TABLE_HEAD:
            painter.fillRect(int(left) - 6, y0, int(right - left) + 12, h,
                             _srgb(P["table_head_bg"]))
        elif kind == self.HR:
            y = y0 + h // 2
            pen = QPen(_srgb(P["accent_line"]), 1)
            painter.setPen(pen)
            painter.drawLine(int(left), y, int(right), y)
        elif kind == self.BULLET:
            self._draw_bullet(painter, geo, block)

    def _draw_bullet(self, painter: "QPainter", geo, block) -> None:
        """补画无序列表的圆点。

        ``- `` 被擦成全透明但保留宽度，这里按 ``-`` 的实际位置放一个点，
        看起来就是渲染后的 ``• 项目``，而不是 ``- 项目``。
        """
        m = LiveHighlighter.LIST.match(block.text())
        layout = block.layout()
        if not m or layout is None or layout.lineCount() == 0:
            return
        x, _y = layout.lineAt(0).cursorToX(m.start(2))
        r = 2.5
        cx = geo.left() + x + r + 1          # - 的占位中心偏右一点，避开破折号左缘
        cy = geo.top() + geo.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_srgb(P["accent"]))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

    def _draw_image(self, painter: "QPainter", geo, row: "ImageRow") -> None:
        avail_h = max(8, int(geo.height()) - 8)
        h = min(row.draw_h, avail_h)
        w = max(1, int(row.draw_w * h / max(1, row.draw_h)))
        x = max(int(geo.left()), getattr(self.edit, "_text_left", 0))
        y = int(geo.top()) + max(4, (int(geo.height()) - h) // 2)
        painter.drawImage(QRect(x, y, w, h), row.image)

