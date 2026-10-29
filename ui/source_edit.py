"""Markdown 编辑区：单栏就地渲染（Typora 式），不再分屏。

文档里始终只有 **Markdown 源码**，不经过 ``QTextDocument`` 富文本往返：
排版是给字符打格式 + 在文字下面铺一层装饰画出来的，见 :mod:`ui.live_render`。

* 平时看到的是排版后的正文：标题放大、粗斜体生效、图片内嵌；
* 光标所在块临时露出原始标记（``**``、``#``、链接目标），改完立刻收回；
* 想通篇看源码时按"源码模式"切到等宽视图，文本一个字都不变。

因为从不改写正文，「富文本 → Markdown」的反序列化整条链路不需要存在，
存盘存的就是用户写下的原文。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QKeyEvent, QPainter, QPalette,
                           QTextCursor)
from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser

from ui.fonts import UI_FONT_STACK
from ui.live_render import MAX_IMAGE_H, ImageRow, LiveDecor, LiveHighlighter
from ui.theme import P

GZS_SCHEME = "gzs"
MONO_FALLBACK = ("Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo",
                 "Courier New", "monospace")

INDENT = "    "                      # 一级缩进（与 mdengine 的嵌套判定一致）

# 即时渲染的正文用比例字体：Markdown 渲染出来是给人读的，等宽反而生硬。
# 13pt 在 96dpi 下约 17px，和预览里的正文接近。
BODY_POINT_SIZE = 13
MONO_POINT_SIZE = 11

_IMG_RE = re.compile(r"!\[([^\]]*)\]\((gzs:///\d+)\)")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])([ \t]+)(\[[ xX]\][ \t]+)?")
_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
# 独占一行的图片才内嵌显示；行内夹杂图片的仍然按文字处理
_IMG_ONLY_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)(?:\{[^}]*\})?\s*$")


# ------------------------------------------------------------------ 源码编辑区


class MarkdownSource(QPlainTextEdit):
    """Markdown 源码输入区。

    只做"打字顺手"这件事：列表自动续行、Tab 缩进、图片拖放/粘贴、
    Ctrl+点击打开链接。渲染交给 :class:`MarkdownPreview`。
    """

    linkActivated = Signal(str)
    imageActivated = Signal(int)
    imageRemoved = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.image_sink: Optional[Callable[[bytes, str], Optional[Tuple[str, int]]]] = None
        self.file_sink: Optional[Callable[[List[str]], None]] = None
        self.image_size: Optional[Callable[[int], object]] = None
        self.image_loader: Optional[Callable[[int], Optional[bytes]]] = None
        self._image_cache: dict = {}
        self._live = True             # True = Typora 式即时渲染
        self._text_left = 0           # 正文左边界（图片要跟它对齐）

        mono = QFont()
        mono.setFamilies(list(MONO_FALLBACK))
        mono.setPointSize(MONO_POINT_SIZE)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono_font = mono

        body = QFont()
        body.setFamilies(list(UI_FONT_STACK))
        body.setPointSize(BODY_POINT_SIZE)
        body.setStyleHint(QFont.StyleHint.SansSerif)
        self._body_font = body

        self.setFont(body)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText(
            "直接写 Markdown，标记会随写随变成排版：\n\n"
            "# 一级标题      - 列表      > 引用      ``` 代码块\n"
            "**粗体**  *斜体*  `行内代码`  ==高亮==  ~~删除线~~\n\n"
            "标记本身不会显示，图片可以直接拖进来或粘贴")
        self.highlighter = LiveHighlighter(self.document(), body)
        self.decor = LiveDecor(self)
        # 没有「活动块」这回事：标记字符一律不显示，光标停在哪段都不露原文。
        # active 仍要留着并设成 -1，装饰层用它判断图片行要不要收起、铺图片。
        self.highlighter.active = -1
        # 块级底色记的是行位置，文本一变就得重建。放到 0ms 定时器里做，
        # 避免在高亮器正在重排文档的时候动 extraSelections（会重入）。
        self._decor_timer = QTimer(self)
        self._decor_timer.setSingleShot(True)
        self._decor_timer.setInterval(30)
        self._decor_timer.timeout.connect(self.refresh_decor)
        self.textChanged.connect(self._decor_timer.start)
        self.setAcceptDrops(True)

        # 块级装饰（代码块底色、引用竖线、分隔线）要在文字**之前**画到视口上。
        # 父类的 paintEvent 会先用 palette 的 Base 铺满视口，把 Base 设成透明
        # 后这一步不产生像素，我们画的层才留得住。
        self.viewport().setAutoFillBackground(False)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        self.setPalette(pal)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), QColor(P["panel"]))
        if self._live:
            self.decor.paint(painter, event.rect())
        painter.end()
        super().paintEvent(event)

    # ------------------------------------------------------------ 外观

    def apply_theme(self) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor(P["note_text"]))
        # Base 保持透明：背景由 paintEvent 自己填，父类不能盖掉装饰层
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Window, QColor(P["panel"]))
        try:
            pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(P["muted"]))
        except AttributeError:
            pass
        self.setPalette(pal)
        self.highlighter.apply_theme()
        self.decor.refresh()
        self.viewport().update()

    # ------------------------------------------------------------ 即时渲染

    def is_live(self) -> bool:
        """当前是否 Typora 式即时渲染（False = 纯源码）。"""
        return self._live

    def set_live(self, on: bool) -> None:
        """切换即时渲染 / 纯源码。

        两种模式的文档内容完全相同，只是"标记字符是否隐藏"和字体不同，
        所以切换不会改动文本、不会丢光标、也不需要重新载入。
        """
        on = bool(on)
        if on == self._live:
            return
        self._live = on
        self.highlighter.render = on
        self.decor.enabled = on
        self.highlighter.active = -1
        self._apply_font()
        self.highlighter.rehighlight()
        self.decor.refresh()

    def refresh_decor(self) -> None:
        """重建块级装饰与内嵌图片。文本变化后调用（节流由外层负责）。"""
        if not self._live:
            return
        self._sync_images()
        self.decor.refresh()

    def _sync_images(self) -> None:
        """扫出"独占一行的图片"，算好显示尺寸交给渲染层。

        只有这类图片能内嵌：行内混着文字的图片没法在不改文档的前提下
        撑高行高，仍然按淡色文字显示。
        """
        rows = {}
        # 绝大多数笔记没有内嵌图片：全文里连 gzs:/// 都没有时直接跳过，
        # 省掉每 30ms 一次的全篇正则扫描（18KB/637 块约 12ms）。
        if self.image_loader is not None and "gzs://" in self.toPlainText():
            # 正文左边界：视口坐标里第一个字符落下的位置。图片从同一个 x 起，
            # 否则会贴到控件最左边，和上下文字错开一截。
            probe = QTextCursor(self.document())
            probe.movePosition(QTextCursor.MoveOperation.Start)
            self._text_left = max(0, self.cursorRect(probe).left())
            avail = max(160, self.viewport().width() - self._text_left - 16)
            block = self.document().begin()
            while block.isValid():
                m = _IMG_ONLY_RE.match(block.text())
                if m:
                    fid = re.match(r"gzs:///(\d+)", m.group(2))
                    image = self._picture(int(fid.group(1))) if fid else None
                    if image is not None:
                        w, h = max(1, image.width()), max(1, image.height())
                        scale = min(1.0, avail / w, MAX_IMAGE_H / h)
                        rows[block.blockNumber()] = ImageRow(
                            image, max(1, int(w * scale)), max(1, int(h * scale)))
                block = block.next()

        old = self.highlighter.img_heights
        heights = {no: row.line_h for no, row in rows.items()}
        changed = [no for no in set(heights) | set(old)
                   if heights.get(no) != old.get(no)]
        self.highlighter.img_heights = heights
        self.decor.images = rows
        if changed:
            doc = self.document()
            for no in changed:
                block = doc.findBlockByNumber(no)
                if block.isValid():
                    self.highlighter.rehighlightBlock(block)

    def _picture(self, fid: int) -> Optional[QImage]:
        """按 fid 取图并缓存；加载失败缓存 None，免得反复重试。"""
        if fid in self._image_cache:
            return self._image_cache[fid]
        image = None
        data = self.image_loader(fid) if self.image_loader is not None else None
        if data:
            candidate = QImage()
            if candidate.loadFromData(data):
                image = candidate
        self._image_cache[fid] = image
        return image

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        # 宽度变了，图片的等比缩放也要重算
        if self._live:
            self._decor_timer.start()

    def _apply_font(self) -> None:
        font = self._body_font if self._live else self._mono_font
        if self.font() != font:
            self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        # 源码模式的高亮器也要用等宽字体：否则它会把每段文字重新设回比例字体
        # （字符格式优先于控件字体），源码模式就白切了。
        self.highlighter.set_body_font(font)

    # ------------------------------------------------------------ 图片

    def _save_image(self, img: QImage, name: str = "image") -> Optional[str]:
        """把 QImage 交给外层落库，返回写进 Markdown 的地址。"""
        if self.image_sink is None or img.isNull():
            return None
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(buf.data())
        buf.close()
        got = self.image_sink(data, name)
        if not got:
            return None
        url = got[0] if isinstance(got, (tuple, list)) else str(got)
        return url

    def insert_image_file(self, path: str) -> None:
        """插入一张本地图片：先落库，再写 Markdown 图片语法。"""
        img = QImage(path)
        if img.isNull():
            return
        from pathlib import Path

        url = self._save_image(img, Path(path).stem or "image")
        if not url:
            return
        cur = self.textCursor()
        cur.insertText("![%s](%s)" % (Path(path).name, url))

    def _fid_on_line(self, pos: int) -> Optional[Tuple[int, int, int]]:
        """光标所在行里的图片：返回 (起点, 长度, fid)。"""
        cur = QTextCursor(self.document())
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cur.position()
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cur.selectedText()
        for m in _IMG_RE.finditer(text):
            if start + m.start() <= pos <= start + m.end():
                return start + m.start(), m.end() - m.start(), int(m.group(2))
        return None

    # ------------------------------------------------------------ 输入行为

    def _indent_block(self, delta: int) -> None:
        """整行缩进/反缩进（工具栏与 Tab 共用）。"""
        cur = self.textCursor()
        start, end = cur.selectionStart(), cur.selectionEnd()
        cur.beginEditBlock()
        doc = self.document()
        first = doc.findBlock(start).blockNumber()
        last = doc.findBlock(max(start, end - 1)).blockNumber()
        positions = []
        for no in range(first, last + 1):
            block = doc.findBlockByNumber(no)
            positions.append(block.position())
        for pos in positions:
            c = QTextCursor(doc)
            c.setPosition(pos)
            if delta > 0:
                c.insertText(INDENT)
            else:
                line = doc.findBlockByNumber(doc.findBlock(pos).blockNumber()).text()
                strip = len(line) - len(line.lstrip(" \t"))
                take = min(strip, 4)
                if take:
                    c.setPosition(pos + take, QTextCursor.MoveMode.KeepAnchor)
                    c.removeSelectedText()
        cur.endEditBlock()
        self.setTextCursor(cur)

    def _continue_list(self) -> bool:
        """回车时续写列表 / 引用 / 任务项；空项则结束列表。"""
        cur = self.textCursor()
        if cur.hasSelection():
            return False
        block = cur.block()
        text = block.text()
        m = _LIST_RE.match(text)
        pos_in_block = cur.positionInBlock()
        if not m or pos_in_block < m.end():
            return False
        indent, marker, _sp, task = m.group(1), m.group(2), m.group(3), m.group(4)
        body = text[m.end():]
        if not body.strip():
            # 空列表项：回车把它清成普通段落
            c = QTextCursor(block)
            c.setPosition(block.position())
            c.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
            return True
        if marker[0].isdigit():
            n = int(re.match(r"\d+", marker).group(0))
            nxt = "%d." % (n + 1)
        else:
            nxt = marker
        prefix = indent + nxt + " " + ("[ ] " if task else "")
        cur.insertText("\n" + prefix)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt 命名
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (mods & Qt.KeyboardModifier.ShiftModifier):
            if self._continue_list():
                event.accept()
                return
        if key == Qt.Key.Key_Tab and not (mods & Qt.KeyboardModifier.ControlModifier):
            self._indent_block(1)
            event.accept()
            return
        if key == Qt.Key.Key_Backtab:
            self._indent_block(-1)
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 剪贴板

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source.hasImage() and self.image_sink is not None:
            img = QImage(source.imageData())
            url = self._save_image(img, "image")
            if url:
                self.textCursor().insertText("![](%s)" % url)
                return
        if source.hasUrls() and self.image_sink is not None:
            urls = [u for u in source.urls() if u.isLocalFile()]
            images = [u for u in urls if u.toLocalFile().lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"))]
            if images:
                for u in images:
                    self.insert_image_file(u.toLocalFile())
                return
            if urls and self.file_sink is not None:
                self.file_sink([u.toLocalFile() for u in urls])
                return
        # 其余一律按纯文本插入：外部富文本的颜色/字体不会混进 Markdown
        self.insertPlainText(source.text())

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            hit = self._link_at(self.cursorForPosition(event.position().toPoint()).position())
            if hit:
                self.linkActivated.emit(hit)
                event.accept()
                return
        super().mousePressEvent(event)

    def _link_at(self, pos: int) -> Optional[str]:
        cur = QTextCursor(self.document())
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start = cur.position()
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cur.selectedText()
        for m in re.finditer(r"\]\(([^)\s]+)\)", text):
            if start + m.start() <= pos <= start + m.end():
                return m.group(1)
        return None

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        hit = self._fid_on_line(self.cursorForPosition(event.pos()).position())
        menu = self.createStandardContextMenu()
        if hit:
            start, length, fid = hit
            act_open = menu.addAction("打开图片")
            act_del = menu.addAction("从正文移除图片")
            menu.addSeparator()
            chosen = menu.exec(event.globalPos())
            if chosen is act_open:
                self.imageActivated.emit(fid)
                return
            if chosen is act_del:
                cur = QTextCursor(self.document())
                cur.setPosition(start)
                cur.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                self.imageRemoved.emit(fid)
                return
            return
        menu.exec(event.globalPos())


# ---------------------------------------------------------------------- 预览


class MarkdownPreview(QTextBrowser):
    """右侧预览：``mdengine`` 渲染出的 HTML 直接显示。"""

    def __init__(self, resolver: Callable[[int], Optional[bytes]], parent=None) -> None:
        super().__init__(parent)
        self._resolver = resolver
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().setDocumentMargin(26)
        self._last_html: Optional[str] = None
        self._last_css: Optional[str] = None

    def loadResource(self, type_: int, url: QUrl):  # noqa: N802
        m = re.match(r"gzs:///(\d+)", url.toString())
        if m:
            data = self._resolver(int(m.group(1)))
            if data:
                img = QImage()
                if img.loadFromData(data):
                    return img
        return super().loadResource(type_, url)

    def set_html(self, html: str, css: str) -> None:
        # 内容与样式都没变就别重排：光标移动、保存后回填都会调到这里，
        # 白白 setHtml 一次会把图片重新解码、把滚动位置冲掉。
        if html == self._last_html and css == self._last_css:
            return
        self._last_html, self._last_css = html, css
        self.document().setDefaultStyleSheet(css)
        self.setHtml(html or "")

    def apply_theme(self, css: str) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(P["panel"]))
        pal.setColor(QPalette.ColorRole.Text, QColor(P["note_text"]))
        self.setPalette(pal)
        self._last_css = css
        self.document().setDefaultStyleSheet(css)
        self.viewport().update()
