"""笔记编辑器：单栏就地渲染的 Markdown 编辑区。

排版发生在编辑区内部（:mod:`ui.live_render`），没有右侧预览栏：

* 保存回去的永远是用户写下的原文，存盘不会重排格式；
* 高亮、代码块语言、表格对齐、列表内代码块这些"往返损耗"不再存在；
* 「源码模式」把整篇切回等宽源码，适合调表格、对齐嵌套列表。

分屏预览控件仍保留在 :class:`ui.source_edit.MarkdownPreview` 里（默认隐藏），
但 ``_refresh_preview`` 在即时渲染下只重建块级装饰，不再渲染 HTML。

对外接口（信号、方法名）与旧富文本编辑器保持一致，主界面无需改调用方式。
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor, QTextDocument, QTextListFormat
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog,
                               QLineEdit, QSplitter, QVBoxLayout, QWidget)

from ui.markdown_render import md_to_html, preview_css
from ui.md_source import document_to_markdown      # 仅供历史富文本笔记一次性迁移
from ui.source_edit import MarkdownPreview, MarkdownSource
from ui.theme import P

_HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})[ \t]+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+][ \t]+(\[[ xX]\][ \t]+)?(.*)$")
_OL_RE = re.compile(r"^(\s*)\d+[.)][ \t]+(\[[ xX]\][ \t]+)?(.*)$")
_QUOTE_RE = re.compile(r"^(\s*)>[ \t]?(.*)$")
_TASK_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])[ \t]+(\[[ xX]\])[ \t]+")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

_INLINE_PAIRS = ("**", "~~", "==", "`", "<u>", "</u>")


def _plain_of(md: str) -> str:
    """Markdown → 近似纯文本（只给搜索用，不做完整解析）。"""
    text = md or ""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\|?[\s:|-]+\|?\s*$", " ", text, flags=re.M)
    text = re.sub(r"[*_~=`|]", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class NoteEditor(QWidget):
    saveRequested = Signal(str, str, str)   # fmt, content, plain
    dirtyChanged = Signal(bool)

    def __init__(self,
                 image_saver: Callable[[bytes, str], Optional[Tuple[str, int]]],
                 resolver: Callable[[int], Optional[bytes]],
                 parent=None):
        super().__init__(parent)
        self._image_saver = image_saver
        self._resolver = resolver
        self._loading = False
        self._dirty = False
        self._node_id: Optional[int] = None
        self._source_only = False

        # 预览刷新节流：打字时不要每键都重排整篇。必须在连信号之前建好，
        # 否则构建期的一次 textChanged 就会碰到还不存在的属性。
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        # 180 → 110 ms：增量渲染让单次重排便宜了一个量级（长笔记 39ms → 12ms），
        # 可以把等用户停手的时间缩短，跟手感更接近即时。
        self._preview_timer.setInterval(110)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.split = QSplitter(Qt.Orientation.Horizontal, self)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(4)
        self.split.setStyleSheet("QSplitter::handle { background: %s; }" % P["border"])

        self.edit = MarkdownSource(self)
        self.edit.image_sink = self._image_saver
        self.edit.image_loader = self._resolver
        self.edit.textChanged.connect(self._on_changed)
        self.edit.textChanged.connect(self._schedule_preview)
        self.split.addWidget(self.edit)

        # 默认不分屏：排版就在编辑区里就地完成（Typora 式）。
        # 预览控件留着，供需要时切回左右对照；平时隐藏，省掉一次 HTML 渲染。
        self.preview = MarkdownPreview(self._resolver, self)
        self.preview.anchorClicked.connect(self._on_preview_link)
        self.split.addWidget(self.preview)
        self.preview.hide()

        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setSizes([1200, 0])

        # 预览 CSS 每次刷新都重新格式化的开销没必要付，缓存到主题切换时再更新
        self._css = preview_css()
        self.edit.apply_theme()
        self.preview.apply_theme(self._css)

        # 右侧标题导航条：跟着源码里的 # 标题走
        from ui.doc_nav import DocNav
        self.doc_nav = DocNav(self)
        self.doc_nav.attach(self.edit)

        # 编辑区和导航条摆在同一行：导航条固定 26px，贴在右边、上下通高。
        # 以前是浮层，靠手工算坐标，改成单栏后就没人算它了，结果缩在左上角；
        # 放进布局后窗口怎么缩放都跟着走，不用再管 resizeEvent。
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.split, 1)
        row.addWidget(self.doc_nav)
        root.addLayout(row)
        root.setContentsMargins(0, 0, 0, 0)

        self._set_enabled(False)

    def _on_preview_link(self, url) -> None:
        text = url.toString() if hasattr(url, "toString") else str(url)
        self.edit.linkActivated.emit(text)

    # ---------------------------------------------------------------- 模式

    def source_only(self) -> bool:
        """当前是否「只看源码」（预览收起）。"""
        return self._source_only

    def set_source_mode(self, on: bool) -> None:
        """源码模式：所有标记原样显示，不再就地渲染。

        注意不是"收起预览"——现在没有预览栏了。开启后编辑区退回等宽的纯
        源码视图，适合改表格、调嵌套列表这类靠标记对齐的活。
        """
        self._source_only = bool(on)
        self.edit.set_live(not self._source_only)
        if not self._source_only:
            self._refresh_preview()

    # --------------------------------------------------------------- 状态

    def _set_enabled(self, ok: bool) -> None:
        self.edit.setReadOnly(not ok)
        if not ok:
            self.edit.clear()
            self.preview.set_html("", self._css)

    def set_node(self, node_id: Optional[int], content: str = "", fmt: str = "md") -> None:
        # 切条目前的保存/丢弃由 DatabaseView.confirm_unsaved() 决定，这里只装载。
        self._node_id = node_id
        self._loading = True
        changed = False
        try:
            if node_id is None:
                self._set_enabled(False)
            else:
                self._set_enabled(True)
                text = content or ""
                if fmt != "md" and text.strip():
                    # 历史富文本笔记：一次性转成 Markdown 后再进入源码编辑
                    doc = QTextDocument()
                    doc.setHtml(text)
                    text = document_to_markdown(doc)
                    changed = True
                self.edit.setPlainText(text)
                cur = self.edit.textCursor()
                cur.setPosition(0)
                self.edit.setTextCursor(cur)
        finally:
            self._loading = False
        self._refresh_preview()
        self._dirty = False
        self.dirtyChanged.emit(False)
        if changed:
            self._dirty = True          # 迁移结果要静默写回，不该挂"未保存"
            self._emit_save()

    def flush(self) -> None:
        if self._dirty:
            self._emit_save()

    def discard(self) -> None:
        self._dirty = False
        self.dirtyChanged.emit(False)

    def is_dirty(self) -> bool:
        return self._dirty

    def payload(self) -> Tuple[str, str, str]:
        md = self.edit.toPlainText()
        return "md", md, _plain_of(md)

    def copy_as_markdown(self) -> None:
        cur = self.edit.textCursor()
        text = cur.selectedText().replace("\u2029", "\n") if cur.hasSelection() \
            else self.edit.toPlainText()
        QApplication.clipboard().setText(text)

    def paste_plain(self) -> None:
        self.edit.insertPlainText(QApplication.clipboard().text())

    def refresh_theme(self) -> None:
        self.edit.apply_theme()
        self.update_preview_theme()

    def update_preview_theme(self) -> None:
        self._css = preview_css()
        self.preview.apply_theme(self._css)
        self._refresh_preview()

    def _on_changed(self) -> None:
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self.dirtyChanged.emit(True)

    def _schedule_preview(self) -> None:
        if self._loading or self._source_only:
            return
        self._preview_timer.start()

    def _refresh_preview(self) -> None:
        if self._source_only:
            return
        if self.edit.is_live():
            # 即时渲染：排版由高亮器逐块维护，这里只需要重建块级底色
            # （代码块/引用的整行背景依赖块的位置，文本一变就失效）。
            self.edit.refresh_decor()
            return
        src = self.edit.toPlainText()
        bar = self.preview.verticalScrollBar()
        old_max = bar.maximum()
        keep = (bar.value() / old_max) if old_max > 0 else 0.0
        try:
            html = md_to_html(src)
        except Exception:  # noqa: BLE001 - 渲染失败不影响继续写
            html = ""
        self.preview.set_html(html, self._css)
        # setHtml 会把滚动条打回顶部，边写边预览时正文会"跳走"。
        # 按比例还原（预览的块高与源码行数不成正比，比例是够用的近似）。
        if bar.maximum() > 0:
            bar.setValue(int(round(keep * bar.maximum())))

    def _emit_save(self) -> None:
        if not self._dirty or self._node_id is None:
            return
        fmt, content, plain = self.payload()
        self._dirty = False
        self.saveRequested.emit(fmt, content, plain)
        self.dirtyChanged.emit(False)

    # -------------------------------------------------------- 选区与行

    def _selection(self) -> str:
        return self.edit.textCursor().selectedText().replace("\u2029", "\n")

    def _line_span(self, cur: QTextCursor) -> Tuple[int, int, str]:
        """当前行：返回 (起点, 长度, 文本)。"""
        c = QTextCursor(cur)
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = c.position()
        line = cur.block().text()
        return start, len(line), line

    def _replace_line(self, start: int, length: int, text: str) -> None:
        """整行重写，并把光标按"光标之后还剩几个字符"映射回新行。

        前缀长度会变（``# ``、``> ``、``- `` 之类），所以不能把旧列号直接
        套回去：空行上按 Ctrl+1 时旧列号是 0，光标会停在 ``#`` **前面**，
        接着打的字插进标记之前，整行变成「标题# 」——井号又被渲染层藏起来，
        看上去就是"按了没反应、输入的不是标题"。取最小值时留出前缀长度，
        也顺手保证光标不会停在前缀内部。
        """
        col = self.edit.textCursor().position() - start
        head = len(text) - len(text.lstrip())
        tail = max(0, length - col)                       # 光标右边还剩多少字符
        new_col = max(head, min(len(text), len(text) - tail))
        cur = QTextCursor(self.edit.document())
        cur.setPosition(start)
        cur.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(text)
        cur.setPosition(start + new_col)
        self.edit.setTextCursor(cur)

    def _wrap(self, mark: str, close: Optional[str] = None) -> None:
        """给选区套/去一对标记；没有选区就在光标处插入成对标记。"""
        close = close if close is not None else mark
        cur = self.edit.textCursor()
        if cur.hasSelection():
            text = self.edit.toPlainText()
            s, e = cur.selectionStart(), cur.selectionEnd()
            # 选区常常正好是"标记内部的内容"（上一次套完留下的选区），
            # 这时把两侧标记也纳入，才能判断该去掉而不是再套一层。
            if (s >= len(mark) and e + len(close) <= len(text)
                    and text[s - len(mark):s] == mark
                    and text[e:e + len(close)] == close):
                s, e = s - len(mark), e + len(close)
                cur.setPosition(s)
                cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            sel = cur.selectedText().replace("\u2029", "\n")
            if sel.startswith(mark) and sel.endswith(close) and len(sel) >= len(mark) + len(close):
                inner = sel[len(mark):len(sel) - len(close)]
                cur.insertText(inner)
                self._select(s, len(inner))
            else:
                cur.insertText(mark + sel + close)
                self._select(s + len(mark), len(sel))
            return
        pos = cur.position()
        cur.insertText(mark + close)
        cur.setPosition(pos + len(mark))
        self.edit.setTextCursor(cur)

    def _select(self, start: int, length: int) -> None:
        c = self.edit.textCursor()
        c.setPosition(start)
        c.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self.edit.setTextCursor(c)

    def _selection_wrapped(self, mark: str, close: Optional[str] = None) -> bool:
        """选区（连同紧挨着的标记）或光标所在词是否被这对标记包着。"""
        close = close if close is not None else mark
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            return self._mark_around_cursor(mark)
        text = self.edit.toPlainText()
        s, e = cur.selectionStart(), cur.selectionEnd()
        if (s >= len(mark) and e + len(close) <= len(text)
                and text[s - len(mark):s] == mark
                and text[e:e + len(close)] == close):
            return True
        sel = cur.selectedText()
        return (len(sel) >= len(mark) + len(close)
                and sel.startswith(mark) and sel.endswith(close))

    def _mark_around_cursor(self, mark: str) -> bool:
        cur = self.edit.textCursor()
        line = cur.block().text()
        pos = cur.positionInBlock()
        for m in re.finditer(re.escape(mark) + r"(?=\S)(.+?)(?<=\S)" + re.escape(mark), line):
            if m.start() <= pos <= m.end():
                return True
        return False

    # -------------------------------------------------------------- 格式

    def toggle_bold(self) -> None:
        self._wrap("**")

    def toggle_italic(self) -> None:
        self._wrap("*")

    def toggle_underline(self) -> None:
        """Markdown 没有下划线，按 Typora 的做法落成内联 HTML <u>…</u>。"""
        self._wrap("<u>", "</u>")

    def toggle_strike(self) -> None:
        self._wrap("~~")

    def toggle_highlight(self) -> None:
        self._wrap("==")

    def toggle_inline_code(self) -> None:
        self._wrap("`")

    def marked_highlight(self) -> bool:
        return self._selection_wrapped("==")

    def fmt_state(self) -> Dict[str, bool]:
        """当前光标/选区的行内格式状态，供工具栏反馈使用。"""
        bold = self._selection_wrapped("**")
        return {
            "bold": bold,
            "italic": self._selection_wrapped("*") and not bold,
            "underline": self._selection_wrapped("<u>"),
            "strike": self._selection_wrapped("~~"),
            "highlight": self._selection_wrapped("=="),
            "code": self._selection_wrapped("`"),
        }

    def clear_format(self) -> None:
        """去掉选区两端的 Markdown 行内标记。"""
        cur = self.edit.textCursor()
        if cur.hasSelection():
            sel = cur.selectedText().replace("\u2029", "\n")
            for mark in _INLINE_PAIRS:
                while sel.startswith(mark) and sel.endswith(mark) and len(sel) > len(mark) * 2:
                    sel = sel[len(mark):len(sel) - len(mark)]
            sel = re.sub(r"^#{1,6}[ \t]+", "", sel)
            cur.insertText(sel)
            self.edit.setTextCursor(cur)
            return
        # 没有选区就清整行前缀
        start, length, line = self._line_span(cur)
        self._replace_line(start, length, re.sub(r"^(\s*)(#{1,6}|>|[-*+]|\d+[.)])[ \t]+", r"\1", line))

    # -------------------------------------------------------------- 标题

    def heading_level(self) -> int:
        _s, _l, line = self._line_span(self.edit.textCursor())
        m = _HEADING_RE.match(line)
        return len(m.group(2)) if m else 0

    def set_heading(self, level: int, toggle: bool = True) -> int:
        level = max(0, min(6, int(level)))
        cur = self.edit.textCursor()
        start, length, line = self._line_span(cur)
        current = self.heading_level()
        if toggle and level and current == level:
            level = 0
        body = _HEADING_RE.sub(r"\3", line) if current else line
        body = re.sub(r"^(\s*)(?:[-*+]|\d+[.)])[ \t]+", r"\1", body)   # 先脱离列表
        body = body.lstrip()
        new = ("%s %s" % ("#" * level, body)) if level else body
        # 光标由 _replace_line 统一换算，这里不要再自己 setPosition，
        # 否则空行上会把光标放回 `#` 前面（打字变成「标题# 」）
        self._replace_line(start, length, new)
        return level

    def change_heading_level(self, delta: int) -> None:
        level = self.heading_level()
        if level <= 0:
            return
        self.set_heading(max(1, min(6, level + delta)), toggle=False)

    # -------------------------------------------------------------- 块级

    def toggle_quote(self) -> None:
        cur = self.edit.textCursor()
        start, length, line = self._line_span(cur)
        m = _QUOTE_RE.match(line)
        if m:
            self._replace_line(start, length, m.group(1) + m.group(2))
        else:
            self._replace_line(start, length, "> " + line)

    def toggle_list(self, style=None) -> None:
        """无序 / 有序列表切换；style 传 QTextListFormat.ListDecimal 表示有序。"""
        ordered = style in (QTextListFormat.Style.ListDecimal,
                            QTextListFormat.Style.ListLowerAlpha,
                            QTextListFormat.Style.ListUpperAlpha)
        cur = self.edit.textCursor()
        start, length, line = self._line_span(cur)
        bullet = _BULLET_RE.match(line)
        num = _OL_RE.match(line)
        if bullet and not ordered:
            self._replace_line(start, length, bullet.group(1) + (bullet.group(2) or "") + bullet.group(3))
        elif num and ordered:
            self._replace_line(start, length, num.group(1) + (num.group(2) or "") + num.group(3))
        else:
            body = (bullet.group(1) + (bullet.group(2) or "") + bullet.group(3)) if bullet else \
                   (num.group(1) + (num.group(2) or "") + num.group(3)) if num else line
            prefix = "1. " if ordered else "- "
            self._replace_line(start, length, prefix + body)

    def toggle_task(self) -> None:
        cur = self.edit.textCursor()
        start, length, line = self._line_span(cur)
        m = _TASK_RE.match(line)
        if m:
            # 去掉 [ ] 标记，保留列表符号
            kept = m.group(1) + m.group(2) + " " + line[m.end():]
            self._replace_line(start, length, kept)
        else:
            body = line
            b = _BULLET_RE.match(line)
            if b:
                body = b.group(1) + b.group(3)
            self._replace_line(start, length, "- [ ] " + body)

    def toggle_task_state(self) -> None:
        cur = self.edit.textCursor()
        start, length, line = self._line_span(cur)
        m = _TASK_RE.match(line)
        if not m:
            self.toggle_task()
            return
        mark = "x" if m.group(3).lower() != "[x]" else " "
        new = line[:m.start(3)] + "[%s]" % mark + line[m.end(3):]
        self._replace_line(start, length, new)

    def insert_hr(self) -> None:
        cur = self.edit.textCursor()
        cur.insertText("\n\n---\n\n")

    def insert_paragraph(self, above: bool) -> None:
        cur = self.edit.textCursor()
        start, _length, _line = self._line_span(cur)
        pos = start if above else start + len(cur.block().text())
        c = QTextCursor(self.edit.document())
        c.setPosition(pos)
        c.insertText("\n")
        c.setPosition(pos if above else pos + 1)
        self.edit.setTextCursor(c)

    def insert_table(self, rows: int = 3, cols: int = 3) -> None:
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        head = "| " + " | ".join("列%d" % (i + 1) for i in range(cols)) + " |"
        sep = "| " + " | ".join(["---"] * cols) + " |"
        body = ["| " + " | ".join([" "] * cols) + " |" for _ in range(max(0, rows - 1))]
        text = "\n".join([head, sep] + body)
        cur = self.edit.textCursor()
        lead = "" if cur.atBlockStart() and not cur.block().text().strip() else "\n\n"
        cur.insertText(lead + text + "\n")
        self.edit.setFocus()

    def insert_link(self) -> None:
        cur = self.edit.textCursor()
        text = cur.selectedText().replace("\u2029", " ") if cur.hasSelection() else ""
        url, ok = QInputDialog.getText(self, "插入链接", "地址（http / https）：",
                                       QLineEdit.EchoMode.Normal, "https://")
        if not ok or not url.strip():
            return
        url = url.strip()
        cur.insertText("[%s](%s)" % (text or url, url))
        self.edit.setTextCursor(cur)

    def insert_code_block(self) -> None:
        cur = self.edit.textCursor()
        sel = cur.selectedText().replace("\u2029", "\n") if cur.hasSelection() else ""
        if sel:
            cur.insertText("```\n%s\n```" % sel)
        else:
            cur.insertText("```\n\n```")
            pos = cur.position() - 4
            c = self.edit.textCursor()
            c.setPosition(pos)
            self.edit.setTextCursor(c)
        self.edit.setFocus()

    def insert_image(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "插入图片", "",
            "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)")
        for f in files:
            self.edit.insert_image_file(f)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.flush()
            event.accept()
            return
        super().keyPressEvent(event)
