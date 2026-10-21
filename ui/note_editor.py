"""笔记编辑器（单控件，两种输入方式）。

* 富文本模式：所见即所得，靠工具条排版
* Markdown 模式：同样是所见即所得，但支持 Typora 式输入规则
  —— 打 `# ` 变标题、`- ` 变列表、`**粗**` 自动加粗，标记就地消失

两种模式共用同一个 QTextEdit，内容始终以 HTML 保存，切换不会丢内容。
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QImage, QPalette,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextImageFormat, QTextListFormat, QTextTableFormat)
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMenu, QTextEdit,
                               QVBoxLayout, QWidget)

from ui.markdown_render import md_to_html, preview_css
from ui.theme import P
from ui.fonts import UI_FONT_STACK

GZS_SCHEME = "gzs"
SAVE_DELAY_MS = 700

MONO_STACK = ("Menlo", "Consolas", "Courier New", "monospace")

_IMG_SRC_RE = re.compile(r"gzs:///(\d+)")

# 本地 Typora（GitHub 主题 github.css）实测比例，正文 11pt 视为 1em：
# h1 2.25em / h2 1.75em / h3 1.5em / h4 1.25em / h5 1em / h6 1em（h6 灰 #777）
HEADING_SIZES = {1: 24.75, 2: 19.25, 3: 16.5, 4: 13.75, 5: 11.0, 6: 11.0}
# Typora 行高：h1 1.2 / h2 1.225 / h3 1.43（ProportionalHeight，按百分比）
HEADING_LINE_HEIGHT = {1: 120, 2: 123, 3: 143}
HEADING6_COLOR = QColor("#777777")
_BLANK = r"[ \t\u3000]*$"
_HEADING_RE = re.compile(r"^(#{1,6})[ \t\u3000]+(.*)$")
_OL_RE = re.compile(r"^(\d+)\.[ \t\u3000]+(.*)$")
_BULLET_RE = re.compile(r"^([-*+])[ \t\u3000]+(.*)$")
_QUOTE_RE = re.compile(r"^>[ \t\u3000]?(.*)$")
_FENCE_RE2 = re.compile(r"^```" + _BLANK)
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})" + _BLANK)

_MD_BLOCK_RE = re.compile(
    r"(^|\n)[ \t]{0,3}(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|\|.+\|)")

_TASK_PREFIX_RE = re.compile(r"^([☐☑])\s+")
_TASK_INPUT_RE = re.compile(r"^[-*+][ \t\u3000]+\[([ xX])\][ \t\u3000]+(.*)$")
_URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff\uff0c\u3002\uff1b\uff1a\u201c\u201d\uff08\uff09\u3001\uff1f\uff01]+", re.IGNORECASE)

_INLINE_RULES = [
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), "bold"),
    (re.compile(r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)"), "italic"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), "strike"),
    (re.compile(r"`([^`\n]+)`"), "code"),
    (re.compile(r"==(?=\S)(.+?)(?<=\S)=="), "highlight"),
    (re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)"), "link"),
]


class NoteDocument(QTextDocument):
    """让 <img src="gzs:///12"> 从库内 BLOB 取图。"""

    def __init__(self, resolver: Callable[[int], Optional[bytes]], parent=None):
        super().__init__(parent)
        self._resolver = resolver

    def loadResource(self, type_: int, url: QUrl):  # noqa: N802 - Qt 命名
        if url.scheme() == GZS_SCHEME:
            m = _IMG_SRC_RE.search(url.toString())
            if m:
                data = self._resolver(int(m.group(1)))
                if data:
                    img = QImage.fromData(data)
                    if not img.isNull():
                        return img
            return QImage()
        return super().loadResource(type_, url)


_FG_KEYS = ("note_text", "quote_text", "code_text", "inline_text", "link")
_BG_KEYS = ("code_bg", "quote_bg", "inline_bg")


def remap_theme_colors(doc: QTextDocument) -> bool:
    """把正文里写死的主题色换成当前主题对应的颜色（切主题时用）。"""
    from ui.theme import PALETTES

    fg_map, bg_map = {}, {}
    for pal in PALETTES.values():
        for k in _FG_KEYS:
            fg_map[pal[k].lower()] = k
        for k in _BG_KEYS:
            bg_map[pal[k].lower()] = k
    cur_fg = {k: P[k] for k in _FG_KEYS}
    cur_bg = {k: P[k] for k in _BG_KEYS}

    blocks = []
    chars = []
    block_chars = []
    block = doc.begin()
    while block.isValid():
        bf = block.blockFormat()
        bname = bf.background().color().name().lower()
        if bname in bg_map:
            target = cur_bg[bg_map[bname]]
            if target.lower() != bname:
                nb = QTextBlockFormat(bf)
                nb.setBackground(QColor(target))
                blocks.append((block.position(), nb))
        if block.textList() is not None:
            bcf = block.charFormat()
            want = P["note_text"]
            if bcf.foreground().color().name().lower() != want.lower():
                nb = QTextCharFormat(bcf)
                nb.setForeground(QColor(want))
                block_chars.append((block.position(), nb))
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            if not frag.isValid():
                continue
            cf = frag.charFormat()
            fkey = fg_map.get(cf.foreground().color().name().lower())
            bkey = bg_map.get(cf.background().color().name().lower())
            if not fkey and not bkey:
                continue
            new = QTextCharFormat(cf)
            dirty = False
            if fkey:
                cur = cur_fg[fkey]
                if cur.lower() != cf.foreground().color().name().lower():
                    new.setForeground(QColor(cur))
                    dirty = True
            if bkey:
                cur = cur_bg[bkey]
                if cur.lower() != cf.background().color().name().lower():
                    new.setBackground(QColor(cur))
                    dirty = True
            if dirty:
                chars.append((frag.position(), frag.length(), new))
        block = block.next()

    if not blocks and not chars and not block_chars:
        return False
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    for pos, cf in block_chars:
        c = QTextCursor(doc)
        c.setPosition(pos)
        c.setBlockCharFormat(cf)
    for pos, bf in blocks:
        c = QTextCursor(doc)
        c.setPosition(pos)
        c.setBlockFormat(bf)
    for pos, length, cf in chars:
        c = QTextCursor(doc)
        c.setPosition(pos)
        c.setPosition(pos + length, QTextCursor.KeepAnchor)
        c.setCharFormat(cf)
    cur.endEditBlock()
    return True


class MarkdownEdit(QTextEdit):
    """正文控件：粘贴图片入库，可选 Markdown 输入规则。"""

    linkActivated = Signal(str)
    imageActivated = Signal(int)
    # 正文里的图片被删掉（且没有撤销）时发出，交给资料库删对应附件
    imageRemoved = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_sink: Optional[Callable[[bytes, str], Optional[Tuple[str, int]]]] = None
        # 图片原始像素尺寸查询（fid -> (w, h)），由资料库侧注入
        self.image_size: Optional[Callable[[int], Optional[Tuple[int, int]]]] = None
        # 原图字节查询（fid -> bytes），用于平滑缩放后再交给文档绘制
        self.image_loader: Optional[Callable[[int], Optional[bytes]]] = None
        self._image_cache: dict = {}
        self.file_sink: Optional[Callable[[list], None]] = None
        self.md_rules = True
        self.setAcceptRichText(True)
        self._applying = False
        self.setMouseTracking(True)

        # 窗口宽度变化后重新排版图片（防抖）
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(180)
        self._fit_timer.timeout.connect(self.fit_images)

        # 正文图片追踪：记录文档里出现过的 fid，消失即视为删除
        self._tracking = True
        self._doc_fids: set = set()
        self._auto_fids: set = set()      # 宽度由程序自动决定的图片
        self._pending_removed: dict = {}   # fid -> QTimer，撤销期内可取消
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(350)
        self._scan_timer.timeout.connect(self._scan_images)

        # 停手 220ms 就把光标前已闭合的 Markdown 语法就地渲染
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(220)
        self._live_timer.timeout.connect(self._apply_inline_rules_live)
        self.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------ 图片

    def _image_bytes(self, image: QImage) -> Optional[Tuple[str, int]]:
        if image.isNull() or self.image_sink is None:
            return None
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        buf.close()
        data = bytes(ba)
        if not data:
            return None
        return self.image_sink(data, "截图")

    def _try_image(self, image: QImage) -> bool:
        result = self._image_bytes(image)
        if result is None:
            return False
        url, width = result
        fmt = QTextImageFormat()
        fmt.setName(url)
        # 原始像素宽度，只有超出可视宽度时才缩到刚好放得下
        fmt.setWidth(max(80, min(width, self._avail_width())))
        cur = self.textCursor()
        cur.insertImage(fmt)
        new_fid = self._fid_of(url)
        if new_fid is not None:
            self._auto_fids.add(new_fid)
        self.fit_images()
        return True

    def insertFromMimeData(self, source):  # noqa: N802
        if self.md_rules and source.hasText():
            text = source.text()
            if text and _MD_BLOCK_RE.search(text):
                self.insertHtml(md_to_html(text))
                return
        if source.hasImage():
            data = source.imageData()
            if self._try_image(QImage(data) if data is not None else QImage()):
                return
        if source.hasUrls():
            urls = [u for u in source.urls() if u.isLocalFile()]
            imgs = [u for u in urls if u.toLocalFile().lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))]
            if imgs and len(imgs) == len(urls):
                for u in imgs:
                    self._try_image(QImage(u.toLocalFile()))
                return
            if urls and self.file_sink is not None:
                from pathlib import Path as _P
                self.file_sink([_P(u.toLocalFile()) for u in urls])
                return
        super().insertFromMimeData(source)

    def canInsertFromMimeData(self, source):  # noqa: N802
        return source.hasImage() or super().canInsertFromMimeData(source)

    # ------------------------------------------------------- 图片排版

    def _avail_width(self) -> int:
        """正文可视宽度（扣掉左右页边距与滚动条）。"""
        return max(200, self.viewport().width() - 60)

    @staticmethod
    def _fid_of(name: str) -> Optional[int]:
        m = _IMG_SRC_RE.search(name or "")
        return int(m.group(1)) if m else None

    def _orig_size(self, fmt: QTextImageFormat) -> Optional[Tuple[int, int]]:
        fid = self._fid_of(fmt.name())
        if fid is None or self.image_size is None:
            return None
        return self.image_size(fid)

    def _orig_image(self, fid: int) -> Optional[QImage]:
        """原图（解码一次后缓存），缩放一律从原图出发，避免反复插值损失。"""
        img = self._image_cache.get(fid)
        if img is not None and not img.isNull():
            return img
        data = self.image_loader(fid) if self.image_loader is not None else None
        if not data:
            return None
        img = QImage.fromData(data)
        if img.isNull():
            return None
        self._image_cache[fid] = img
        return img

    def _swap_resource(self, doc, name: str, img: QImage, target: int) -> None:
        """把文档里的图片资源换成精确等于显示尺寸的平滑缩放版。

        QTextDocument 绘制时不做平滑插值，尺寸不匹配就会锯齿失真；
        让资源尺寸 == 显示尺寸，绘制时 1:1，任何缩放比例都清晰。
        """
        if img.isNull() or img.width() <= 0:
            return
        if target >= img.width() * 2:
            return  # 放大超过 2 倍才让文档直接用原图，避免内存浪费
        h = max(1, round(target * img.height() / img.width()))
        scaled = img.scaled(target, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        doc.addResource(QTextDocument.ImageResource, QUrl(name), scaled)

    # --------------------------------------------------- 正文图片与附件同步

    def _collect_fids(self) -> set:
        fids = set()
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    fid = self._fid_of(frag.charFormat().toImageFormat().name())
                    if fid is not None:
                        fids.add(fid)
                it += 1
            block = block.next()
        return fids

    def suspend_tracking(self) -> None:
        """换笔记 / 重载文档期间暂停追踪，否则整篇旧图都会被当成“被删”。"""
        self._tracking = False
        self._doc_fids = set()
        self._auto_fids.clear()
        for timer in self._pending_removed.values():
            timer.stop()
        self._pending_removed.clear()

    def resume_tracking(self) -> None:
        self._doc_fids = self._collect_fids()
        self._tracking = True

    def _scan_images(self) -> None:
        if not self._tracking:
            return
        current = self._collect_fids()
        # 撤销把图撤回来了：取消待删除
        for fid, timer in list(self._pending_removed.items()):
            if fid in current:
                timer.stop()
                del self._pending_removed[fid]
        gone = self._doc_fids - current
        self._doc_fids = current
        for fid in gone:
            self._schedule_drop(fid)

    def _schedule_drop(self, fid: int) -> None:
        """延迟确认删除：留出 Ctrl+Z 的撤销时间。"""
        if fid in self._pending_removed:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(1500)

        def fire() -> None:
            self._pending_removed.pop(fid, None)
            if fid not in self._doc_fids:
                self.imageRemoved.emit(fid)

        timer.timeout.connect(fire)
        self._pending_removed[fid] = timer
        timer.start()

    def fit_images(self, allow_grow: bool = False) -> bool:
        """按当前可视宽度重排正文图片：小图保持原像素，大图缩到刚好放得下。"""
        doc = self.document()
        avail = self._avail_width()
        was_modified = doc.isModified()
        self.blockSignals(True)
        changed = False
        try:
            cursor = QTextCursor(doc)
            block = doc.begin()
            while block.isValid():
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    if frag.isValid() and frag.charFormat().isImageFormat():
                        fmt = frag.charFormat().toImageFormat()
                        name = fmt.name()
                        size = self._orig_size(fmt)
                        fid = self._fid_of(name)
                        orig = self._orig_image(fid) if fid is not None else None
                        if size is None and orig is not None:
                            size = (orig.width(), orig.height())
                        cur_w = int(round(fmt.width())) if fmt.width() > 0 else 0
                        auto_w = min(size[0], avail) if size and size[0] > 0 else cur_w
                        auto = (cur_w <= 0) or (fid in self._auto_fids)
                        if allow_grow and size and size[0] > 0:
                            # 首次载入：历史上被限宽的 640 与满宽值都算自动宽度
                            if cur_w == 640 and size[0] > 640:
                                auto = True
                            elif abs(cur_w - auto_w) <= 2:
                                auto = True
                        if auto and size and size[0] > 0:
                            target = auto_w
                            if fid is not None:
                                self._auto_fids.add(fid)
                        elif cur_w > avail:
                            target = avail
                        else:
                            target = cur_w
                        if target > 0 and target != cur_w:
                            cursor.setPosition(frag.position())
                            cursor.setPosition(frag.position() + frag.length(),
                                               QTextCursor.KeepAnchor)
                            new_fmt = QTextImageFormat(fmt)
                            new_fmt.setWidth(target)
                            if size and size[0] > 0 and size[1] > 0:
                                new_fmt.setHeight(max(1, round(target * size[1] / size[0])))
                            cursor.setCharFormat(new_fmt)
                            changed = True
                        if orig is not None and target > 0:
                            self._swap_resource(doc, name, orig, target)
                    it += 1
                block = block.next()
        finally:
            doc.setModified(was_modified)
            self.blockSignals(False)
        if changed:
            self.viewport().update()
        return changed

    def normalize_headings(self) -> bool:
        """统一标题：纯文本 "# 行" 转真标题，已有标题的字号/间距拉到当前标准。"""
        if not self.md_rules:
            return False
        doc = self.document()
        was_modified = doc.isModified()
        self._applying = True
        self.blockSignals(True)
        changed = False
        try:
            block = doc.begin()
            while block.isValid():
                bf = block.blockFormat()
                text = block.text()
                in_code = bf.background().color().name().lower() == P["code_bg"]
                level = int(bf.headingLevel())
                if not in_code and level == 0 and block.textList() is None and text.startswith("#"):
                    m = _HEADING_RE.match(text)
                    if m:
                        cur = QTextCursor(block)
                        cur.movePosition(QTextCursor.EndOfBlock)
                        self.setTextCursor(cur)
                        if self._apply_heading(len(m.group(1)), m.group(2)):
                            changed = True
                elif not in_code and level > 0:
                    # 已有标题：字号/颜色/行高/段间距按当前标准重排（旧笔记升级）
                    want = HEADING_SIZES.get(level, 11.0)
                    want_color = HEADING6_COLOR if level == 6 else QColor(P["note_text"])
                    it = block.begin()
                    while not it.atEnd():
                        frag = it.fragment()
                        if frag.isValid():
                            cf = frag.charFormat()
                            cur_size = cf.fontPointSize()
                            cur_color = cf.foreground().color()
                            if (cur_size <= 0 or abs(cur_size - want) > 0.05
                                    or cur_color != want_color):
                                c = QTextCursor(block)
                                c.setPosition(frag.position())
                                c.setPosition(frag.position() + frag.length(),
                                              QTextCursor.KeepAnchor)
                                nf = QTextCharFormat(cf)
                                nf.setFontPointSize(want)
                                nf.setFontWeight(QFont.Bold)
                                nf.setForeground(want_color)
                                c.setCharFormat(nf)
                                changed = True
                        it += 1
                    new_bf = self._space(QTextBlockFormat(bf), level=level)
                    if ((round(new_bf.topMargin(), 1), round(new_bf.bottomMargin(), 1)) != (
                            round(bf.topMargin(), 1), round(bf.bottomMargin(), 1))
                            or int(new_bf.lineHeight()) != int(bf.lineHeight())
                            or new_bf.lineHeightType() != bf.lineHeightType()):
                        c = QTextCursor(block)
                        c.setBlockFormat(new_bf)
                        changed = True
                block = block.next()
        finally:
            self.blockSignals(False)
            self._applying = False
            doc.setModified(was_modified)
        if changed:
            self.moveCursor(QTextCursor.Start)
        return changed

    def _image_at(self, pos) -> Optional[int]:
        fmt = self.cursorForPosition(pos).charFormat()
        if fmt.isImageFormat():
            return self._fid_of(fmt.toImageFormat().name())
        return None

    def _image_hit(self, pos):
        """命中图片时返回 (fid, 起始位置, 长度, 图片格式)。"""
        cursor = self.cursorForPosition(pos)
        fmt = cursor.charFormat()
        if not fmt.isImageFormat():
            return None
        img_fmt = fmt.toImageFormat()
        fid = self._fid_of(img_fmt.name())
        if fid is None:
            return None
        return fid, cursor.position(), 1, img_fmt

    def _resize_image(self, start: int, length: int, fmt: QTextImageFormat, width: int) -> None:
        """改正文里这张图的显示宽度，等比缩放并同步高质量资源。"""
        fid = self._fid_of(fmt.name())
        orig = self._orig_image(fid) if fid is not None else None
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.KeepAnchor)
        new_fmt = QTextImageFormat(fmt)
        new_fmt.setWidth(int(max(48, width)))
        if orig is not None and orig.width() > 0:
            new_fmt.setHeight(max(1, round(new_fmt.width() * orig.height() / orig.width())))
            self._swap_resource(doc, fmt.name(), orig, int(new_fmt.width()))
        if fid is not None:
            self._auto_fids.discard(fid)   # 手动定过尺寸，窗口变化时不再自动改
        cursor.setCharFormat(new_fmt)
        self.setFocus()

    def _remove_image(self, start: int, length: int) -> None:
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

    def contextMenuEvent(self, event):  # noqa: N802
        hit = self._image_hit(event.pos())
        if hit is None:
            super().contextMenuEvent(event)
            return
        fid, start, length, fmt = hit
        orig = self._orig_image(fid)
        menu = QMenu(self)
        act_view = menu.addAction("看大图（双击）")
        act_view.triggered.connect(lambda _c=False: self.imageActivated.emit(fid))
        menu.addSeparator()
        if orig is not None:
            ow = orig.width()
            act_raw = menu.addAction(f"原始大小（{ow} px）")
            act_raw.triggered.connect(
                lambda _c=False: self._resize_image(start, length, fmt, ow))
            act_fit = menu.addAction("适应窗口宽度")
            act_fit.triggered.connect(
                lambda _c=False: self._resize_image(start, length, fmt, self._avail_width()))
            menu.addSeparator()
            for pct in (150, 125, 100, 75, 50, 33):
                act = menu.addAction(f"{pct}%")
                act.triggered.connect(
                    lambda _c=False, p=pct: self._resize_image(
                        start, length, fmt, max(48, round(ow * p / 100))))
            menu.addSeparator()
        act_del = menu.addAction("删除图片（同时删除附件）")
        act_del.triggered.connect(lambda _c=False: self._remove_image(start, length))
        menu.exec(event.globalPos())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "_fit_timer", None) is not None:
            self._fit_timer.start()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        fid = self._image_at(event.pos())
        if fid is not None:
            self.imageActivated.emit(fid)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            anchor = self.anchorAt(event.pos())
            if anchor:
                self.linkActivated.emit(anchor)
                event.accept()
                return
        super().mousePressEvent(event)

    # ---------------------------------------------------- Markdown 输入规则

    def flush_pending(self) -> None:
        """把全文里还压着的 Markdown 标记立刻转换掉（保存前调用）。"""
        if not self.md_rules or self._applying:
            return
        self._live_timer.stop()
        orig = self.textCursor()
        bn, off = orig.blockNumber(), orig.positionInBlock()
        block = self.document().begin()
        while block.isValid():
            text = block.text()
            if ("*" in text or "`" in text or "](" in text or "~~" in text
                    or "==" in text or text.lstrip().startswith("#")):
                c = QTextCursor(block)
                c.movePosition(QTextCursor.EndOfBlock)
                self.setTextCursor(c)
                self._apply_inline_rules_live()
            block = block.next()
        target = self.document().findBlockByNumber(bn)
        if target.isValid():
            c = QTextCursor(target)
            c.setPosition(target.position() + min(off, max(0, target.length() - 1)))
            self.setTextCursor(c)

    def _on_text_changed(self) -> None:
        scan = getattr(self, "_scan_timer", None)
        if scan is not None and not self._applying:
            scan.start()
        if self.md_rules and not self._applying:
            self._live_timer.start()

    def _format_for(self, kind: str, url: str = "") -> QTextCharFormat:
        fmt = QTextCharFormat()
        if kind == "bold":
            fmt.setFontWeight(QFont.Bold)
        elif kind == "italic":
            fmt.setFontItalic(True)
        elif kind == "strike":
            fmt.setFontStrikeOut(True)
        elif kind == "code":
            fmt.setFontFamilies(list(MONO_STACK))
            fmt.setFontFixedPitch(True)
            fmt.setBackground(QColor(P["inline_bg"]))
            fmt.setForeground(QColor(P["inline_text"]))
        elif kind == "highlight":
            fmt.setBackground(QColor("#fff59d"))
        elif kind == "link":
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
            fmt.setForeground(QColor(P["link"]))
            fmt.setFontUnderline(True)
        return fmt

    def _apply_inline_rules_live(self) -> None:
        """把光标左侧已经闭合的 Markdown 标记实时转成格式（不等空格）。"""
        if not self.md_rules or self._applying:
            return
        self._applying = True
        try:
            if self._try_block_rule():
                return
            for _ in range(6):
                cur = self.textCursor()
                block = cur.block()
                if block.blockFormat().background().color().name().lower() == P["code_bg"]:
                    break
                text = block.text()
                pos = cur.positionInBlock()
                if pos <= 0 or not text:
                    break
                hit = None
                for pattern, kind in _INLINE_RULES:
                    for m in pattern.finditer(text):
                        if m.end() <= pos:
                            hit = (m, kind)
                            break
                    if hit:
                        break
                if hit is None:
                    break
                m, kind = hit
                fmt = self._format_for(kind, m.group(2) if kind == "link" else "")
                old_abs = cur.position()
                removed = (m.end() - m.start()) - len(m.group(1))
                c = QTextCursor(block)
                c.setPosition(block.position() + m.start())
                c.setPosition(block.position() + m.end(), QTextCursor.KeepAnchor)
                c.insertText(m.group(1), fmt)
                c.setPosition(max(0, old_abs - removed))
                self.setTextCursor(c)
        finally:
            self._applying = False

    def _apply_inline_rules(self) -> None:
        if not self.md_rules or self._applying:
            return
        self._applying = True
        try:
            for _ in range(3):
                cur = self.textCursor()
                block = cur.block()
                pos = cur.positionInBlock()
                text = block.text()
                changed = False
                for pattern, kind in _INLINE_RULES:
                    for m in pattern.finditer(text):
                        if m.end() != pos:
                            continue
                        fmt = self._format_for(kind, m.group(2) if kind == "link" else "")
                        c = QTextCursor(block)
                        c.setPosition(block.position() + m.start())
                        c.setPosition(block.position() + m.end(), QTextCursor.KeepAnchor)
                        c.insertText(m.group(1), fmt)
                        changed = True
                        break
                    if changed:
                        break
                if not changed:
                    break
        finally:
            self._applying = False

    def _autolink(self) -> bool:
        """Typora 自动链接：空格/回车时把光标前的裸 URL 转成可点链接。"""
        cur = self.textCursor()
        block = cur.block()
        if block.blockFormat().background().color().name().lower() == P["code_bg"]:
            return False
        text = block.text()
        pos = cur.positionInBlock()
        start = pos
        while start > 0 and text[start - 1] not in " \t\u3000":
            start -= 1
        word = text[start:pos]
        if len(word) < 8 or not _URL_RE.fullmatch(word):
            return False
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(word)
        fmt.setForeground(QColor(P["link"]))
        fmt.setFontUnderline(True)
        c = QTextCursor(block)
        c.setPosition(block.position() + start)
        c.setPosition(block.position() + pos, QTextCursor.KeepAnchor)
        c.setCharFormat(fmt)
        return True

    _TABLE_SEP_RE = re.compile(r"^:?-{3,}:?$")

    def _try_table_rule(self) -> bool:
        """Typora：整行 |a|b|c| 回车 → 生成 2 行表格，首行为加粗表头。"""
        cur = self.textCursor()
        block = cur.block()
        text = block.text()
        if cur.positionInBlock() != len(text) or not text.startswith("|"):
            return False
        m = re.match(r"^\|(.+)\|[ \t\u3000]*$", text)
        if not m:
            return False
        cells = [c.strip() for c in m.group(1).split("|")]
        if not cells or any(not c for c in cells):
            return False
        if all(self._TABLE_SEP_RE.match(c) for c in cells):
            return False   # |---|---| 分隔行不当表格
        ncols = len(cells)
        c = QTextCursor(block)
        c.beginEditBlock()
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderBrush(QBrush(QColor(P["border"])))
        tf.setBorderStyle(QTextTableFormat.BorderStyle_Solid)
        tf.setCellPadding(6)
        tf.setCellSpacing(0)
        tf.setBorderCollapse(True)
        c.setPosition(block.position())
        c.setPosition(block.position() + max(0, block.length() - 1), QTextCursor.KeepAnchor)
        c.removeSelectedText()
        table = c.insertTable(2, ncols, tf)
        for i, cell in enumerate(cells):
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Bold)
            fmt.setFontPointSize(11.0)
            table.cellAt(0, i).firstCursorPosition().insertText(cell, fmt)
        first = table.cellAt(1, 0).firstCursorPosition()
        c.endEditBlock()
        self.setTextCursor(first)
        return True

    def _clear_block(self) -> Optional[QTextCursor]:
        cur = self.textCursor()
        cur.beginEditBlock()
        block = cur.block()
        cur.setPosition(block.position())
        cur.setPosition(block.position() + max(0, block.length() - 1),
                        QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        return cur

    def _try_block_rule(self) -> bool:
        cur = self.textCursor()
        block = cur.block()
        text = block.text()
        if not text or cur.positionInBlock() != len(text):
            return False
        return self._apply_marker(text)

    def _heading_format(self, level: int) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontPointSize(HEADING_SIZES.get(level, 11.0))
        fmt.setFontWeight(QFont.Bold)
        # Typora github.css: h6 { color: #777 }
        fmt.setForeground(HEADING6_COLOR if level == 6 else QColor(P["note_text"]))
        fmt.setFontFamilies(list(UI_FONT_STACK))
        return fmt

    def _apply_heading(self, level: int, content: str) -> bool:
        """把整行变成标题：去掉 # 记号，正文按标题字号重排（内容不丢）。"""
        cur = self.textCursor()
        block = cur.block()
        c = QTextCursor(block)
        c.beginEditBlock()
        c.setPosition(block.position())
        c.setPosition(block.position() + max(0, block.length() - 1), QTextCursor.KeepAnchor)
        bf = QTextBlockFormat()
        bf.setHeadingLevel(level)
        bf.setLeftMargin(0)
        bf.setIndent(0)
        self._space(bf, level=level)
        c.setBlockFormat(bf)
        c.insertText(content, self._heading_format(level))
        c.endEditBlock()
        c.setPosition(c.block().position() + len(content))
        self.setTextCursor(c)
        return True

    def _apply_marker(self, text: str) -> bool:
        # 代码块内的 # - > 都是正文，不能当标记
        if self.textCursor().blockFormat().background().color().name().lower() == P["code_bg"]:
            return False
        m = _HEADING_RE.match(text)
        if m:
            return self._apply_heading(len(m.group(1)), m.group(2))

        m = _TASK_INPUT_RE.match(text)
        if m:
            # Typora：- [ ] 任务 / - [x] 已完成 → ☐/☑ 前缀任务项
            cur = self._clear_block()
            bf = self._space(cur.blockFormat())
            bf.setHeadingLevel(0)
            cur.setBlockFormat(bf)
            self._reset_inline(cur)
            cur.insertText(("☑ " if m.group(1).lower() == "x" else "☐ ") + m.group(2))
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True

        m = _BULLET_RE.match(text)
        if m:
            cur = self._clear_block()
            lf = QTextListFormat()
            lf.setStyle(QTextListFormat.ListDisc)
            lf.setIndent(1)
            cur.createList(lf)
            bf = self._space(cur.blockFormat(), kind="list")
            bf.setHeadingLevel(0)
            cur.setBlockFormat(bf)
            self._reset_inline(cur)
            if m.group(2):
                cur.insertText(m.group(2))
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True

        m = _OL_RE.match(text)
        if m:
            cur = self._clear_block()
            lf = QTextListFormat()
            lf.setStyle(QTextListFormat.ListDecimal)
            lf.setIndent(1)
            cur.createList(lf)
            bf = self._space(cur.blockFormat(), kind="list")
            bf.setHeadingLevel(0)
            cur.setBlockFormat(bf)
            self._reset_inline(cur)
            if m.group(2):
                cur.insertText(m.group(2))
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True

        m = _QUOTE_RE.match(text)
        if m:
            cur = self._clear_block()
            bf = cur.blockFormat()
            bf.setLeftMargin(20)
            bf.setBackground(QColor(P["quote_bg"]))
            bf.setHeadingLevel(0)
            self._space(bf, kind="quote")
            cur.setBlockFormat(bf)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(P["quote_text"]))
            fmt.setFontPointSize(11.0)
            fmt.setFontFamilies(list(UI_FONT_STACK))
            cur.setCharFormat(fmt)
            if m.group(1):
                cur.insertText(m.group(1), fmt)
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True

        if _HR_RE.match(text):
            cur = self._clear_block()
            cur.insertHtml("<hr/>")
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True

        if _FENCE_RE2.match(text):
            cur = self._clear_block()
            self.apply_code_block(cur)
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True
        return False

    def _leave_block_format(self, from_code: bool) -> None:
        """把当前空行从代码块/引用还原成普通段落。"""
        c = self.textCursor()
        bf = c.blockFormat()
        bf.setBackground(QBrush(Qt.NoBrush))
        bf.setLeftMargin(0)
        bf.setTopMargin(8)
        bf.setBottomMargin(0)
        c.setBlockFormat(bf)
        fmt = QTextCharFormat()
        fmt.setFontFamilies(list(UI_FONT_STACK))
        fmt.setFontFixedPitch(False)
        fmt.setFontPointSize(11.0)
        fmt.setForeground(QColor(P["note_text"]))
        c.setCharFormat(fmt)
        self.setTextCursor(c)
        self.setTextCursor(c)

    def _post_enter(self, st: dict) -> None:
        c = self.textCursor()
        if st.get("code"):
            self.apply_code_block(c, continuation=True)
            self.setTextCursor(c)
            return
        if st.get("heading"):
            bf = c.blockFormat()
            bf.setHeadingLevel(0)
            bf.setLeftMargin(0)
            bf.setIndent(0)
            bf.setTopMargin(8)
            bf.setBottomMargin(0)
            c.setBlockFormat(bf)
            self._reset_inline(c)
            self.setTextCursor(c)
            return
        if st.get("quote") and st.get("empty"):
            bf = c.blockFormat()
            bf.setLeftMargin(0)
            bf.setBackground(QBrush(Qt.NoBrush))
            c.setBlockFormat(self._space(bf))
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(P["note_text"]))
            c.setCharFormat(fmt)
            self.setTextCursor(c)
            return
        self._space_current_block()

    def _space_current_block(self) -> None:
        """回车后延后一帧再调段间距——同步调用会让 QTextEdit 之后的回车失效。"""
        c = self.textCursor()
        if c.block().textList() is not None:
            return
        bf = c.blockFormat()
        new = self._space(bf)
        if (round(new.topMargin(), 1), round(new.bottomMargin(), 1)) != (
                round(bf.topMargin(), 1), round(bf.bottomMargin(), 1)):
            c.setBlockFormat(new)
            self.setTextCursor(c)

    def _space(self, bf, level: int = 0, kind: str = "p"):
        """统一的块间距，让即时排版看起来有呼吸感。"""
        if kind in ("code", "quote"):
            bf.setTopMargin(7)
            bf.setBottomMargin(7)
            return bf
        bottom = 0
        if kind == "list":
            top = 2
        elif level >= 1:
            # Typora github.css：所有标题 margin 上下对称各 1rem（16px）
            top, bottom = 16, 16
            lh = HEADING_LINE_HEIGHT.get(level)
            if lh:
                bf.setLineHeight(lh, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        else:
            top = 8
        bf.setTopMargin(top)
        bf.setBottomMargin(bottom)
        return bf

    def _reset_inline(self, cur: QTextCursor) -> None:
        fmt = QTextCharFormat()
        fmt.setFontPointSize(11.0)
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontItalic(False)
        fmt.setForeground(QColor(P["note_text"]))
        fmt.setFontFamilies(list(UI_FONT_STACK))
        cur.setCharFormat(fmt)

    def apply_code_block(self, cur: QTextCursor, continuation: bool = False) -> None:
        bf = cur.blockFormat()
        bf.setBackground(QColor(P["code_bg"]))
        bf.setLeftMargin(12)
        bf.setHeadingLevel(0)
        bf.setTopMargin(0 if continuation else 7)
        bf.setBottomMargin(0)
        cur.setBlockFormat(bf)
        fmt = QTextCharFormat()
        fmt.setFontFamilies(list(MONO_STACK))
        fmt.setFontFixedPitch(True)
        fmt.setFontPointSize(10.0)
        fmt.setForeground(QColor(P["code_text"]))
        cur.setCharFormat(fmt)

    # ------------------------------------------------------------ 键盘

    def _indent_block(self, delta: int) -> None:
        cur = self.textCursor()
        cur.beginEditBlock()
        lst = cur.currentList()
        if lst is not None:
            fmt = lst.format()
            fmt.setIndent(max(1, min(9, fmt.indent() + delta)))
            lst.setFormat(fmt)
        else:
            bf = cur.blockFormat()
            bf.setIndent(max(0, min(9, bf.indent() + delta)))
            cur.setBlockFormat(bf)
        cur.endEditBlock()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Tab and not event.modifiers():
            self._indent_block(1)
            return
        if event.key() == Qt.Key_Backtab:
            self._indent_block(-1)
            return
        if not self.md_rules:
            super().keyPressEvent(event)
            return

        key = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)

        if key == Qt.Key_Space and not ctrl:
            self._autolink()
            self._apply_inline_rules()
            if self._try_block_rule():
                event.accept()
                return
            super().keyPressEvent(event)
            return

        if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
            self._autolink()
            self._apply_inline_rules()
            cur = self.textCursor()
            block = cur.block()
            bf = block.blockFormat()
            in_code = bf.background().color().name().lower() == P["code_bg"]
            empty = block.text().strip() == ""
            heading = int(bf.headingLevel())
            quote = bf.leftMargin() >= 18 and not in_code

            # 列表交给 Qt：继续列表 / 空项自动退出
            if block.textList() is not None:
                super().keyPressEvent(event)
                QTimer.singleShot(0, self._space_current_block)
                return

            # 空行结束代码块 / 引用：就地转换，不新增行
            if (in_code and empty) or (quote and empty):
                self._leave_block_format(in_code)
                event.accept()
                return

            # Typora：|a|b|c| 整行回车 → 生成表格
            if not in_code and self._try_table_rule():
                event.accept()
                return

            # 其余情况自己插入段落，格式一次到位。
            # 不能先 super() 再改格式——那会让 QTextEdit 之后的回车失效。
            nb = QTextBlockFormat(bf)
            cf = QTextCharFormat(cur.charFormat())
            if in_code:
                nb.setBackground(QColor(P["code_bg"]))
                nb.setLeftMargin(12)
                nb.setTopMargin(0)
                nb.setBottomMargin(0)
                cf.setFontFamilies(list(MONO_STACK))
                cf.setFontFixedPitch(True)
                cf.setFontPointSize(10.0)
                cf.setForeground(QColor(P["code_text"]))
            elif heading:
                nb.setHeadingLevel(0)
                nb.setLeftMargin(0)
                nb.setIndent(0)
                nb.setTopMargin(8)
                nb.setBottomMargin(0)
                cf.setFontFamilies(list(UI_FONT_STACK))
                cf.setFontPointSize(11.0)
                cf.setFontWeight(QFont.Normal)
                cf.setForeground(QColor(P["note_text"]))
            elif quote:
                nb.setTopMargin(7)
                nb.setBottomMargin(7)
            else:
                nb.setTopMargin(8)
                nb.setBottomMargin(0)
                nb.setBackground(QBrush(Qt.NoBrush))
            cur.beginEditBlock()
            cur.insertBlock(nb, cf)
            cur.endEditBlock()
            self.setTextCursor(cur)
            return
            return

        super().keyPressEvent(event)


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

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_DELAY_MS)
        self._timer.timeout.connect(self._emit_save)

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.edit = MarkdownEdit(self)
        self.edit.image_sink = self._image_saver
        self.edit.image_loader = self._resolver
        doc = NoteDocument(self._resolver, self.edit)
        doc.setDefaultStyleSheet(preview_css())
        doc.setDocumentMargin(26)
        doc.setDefaultFont(QFont(UI_FONT_STACK[0], 11))
        self.edit.setDocument(doc)
        self.edit.textChanged.connect(self._on_changed)
        root.addWidget(self.edit, 1)

        self._set_enabled(False)

    # ---------------------------------------------------------------- 模式

    def set_source_mode(self, on: bool) -> None:
        """源码模式：关掉即时渲染，输入的标记原样保留。"""
        self.edit.md_rules = not on
        if on:
            self.edit.setPlaceholderText("# 源码模式\n\n输入原样保留，不自动排版")
        else:
            self.edit.setPlaceholderText(
                "直接写就行 —— # 加空格是标题，- 是列表，> 是引用，``` 是代码块，"
                "**粗体** 和 `代码` 打完立刻生效")

    # --------------------------------------------------------------- 状态

    def _set_enabled(self, ok: bool) -> None:
        self.edit.setReadOnly(not ok)
        if not ok:
            self.edit.clear()

    def set_node(self, node_id: Optional[int], content: str = "", fmt: str = "html") -> None:
        self.flush()
        self._node_id = node_id
        self._loading = True
        # 换文档期间不追踪：否则旧笔记的图会被当成“被删掉”
        self.edit.suspend_tracking()
        try:
            if node_id is None:
                self._set_enabled(False)
                changed = False
            else:
                self._set_enabled(True)
                self.edit.setHtml(content or "")
                self.edit.moveCursor(QTextCursor.Start)
                changed = remap_theme_colors(self.edit.document())
                # 历史笔记里的纯文本 “# 标题” 行：载入时就转成真标题
                if self.edit.normalize_headings():
                    changed = True
                # 载入后按当前窗口宽度重排图片（存的是原始像素宽）
                self.edit.fit_images(allow_grow=True)
        finally:
            self._loading = False
        self.edit.resume_tracking()
        self._dirty = False
        self.dirtyChanged.emit(False)
        if changed:
            self._dirty = True
            self.dirtyChanged.emit(True)
            self._timer.start()

    def flush(self) -> None:
        if self._dirty:
            self._timer.stop()
            self._emit_save()
        else:
            self.edit.flush_pending()

    def copy_as_markdown(self) -> None:
        from ui.markdown_render import html_to_md
        text = html_to_md(self.edit.toHtml())
        QApplication.clipboard().setText(text)

    def paste_plain(self) -> None:
        self.edit.insertPlainText(QApplication.clipboard().text())

    def payload(self) -> Tuple[str, str, str]:
        self.edit.flush_pending()
        html = self.edit.toHtml()
        return "html", html, self.edit.toPlainText()

    def refresh_theme(self) -> None:
        doc = self.edit.document()
        doc.setDefaultStyleSheet(preview_css())
        pal = self.edit.palette()
        for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
            pal.setColor(role, QColor(P["note_text"]))
        pal.setColor(QPalette.Base, QColor(P["panel"]))
        pal.setColor(QPalette.Window, QColor(P["panel"]))
        try:
            pal.setColor(QPalette.PlaceholderText, QColor(P["muted"]))
        except AttributeError:
            pass
        self.edit.setPalette(pal)
        changed = remap_theme_colors(doc)
        self.edit.viewport().update()
        if changed and self._node_id is not None:
            self._dirty = True
            self.dirtyChanged.emit(True)
            self._timer.start()

    def is_dirty(self) -> bool:
        return self._dirty

    def _on_changed(self) -> None:
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self.dirtyChanged.emit(True)
        self._timer.start()

    def _emit_save(self) -> None:
        if not self._dirty or self._node_id is None:
            return
        fmt, content, plain = self.payload()
        self._dirty = False
        self.saveRequested.emit(fmt, content, plain)
        self.dirtyChanged.emit(False)

    # -------------------------------------------------------------- 格式

    def _apply_format(self, fmt: QTextCharFormat, whole_block: bool = False) -> None:
        """有选区就作用于选区；否则作用于整个块或光标所在的词。"""
        edit = self.edit
        cur = edit.textCursor()
        if cur.hasSelection():
            cur.mergeCharFormat(fmt)
            edit.setTextCursor(cur)
            edit.mergeCurrentCharFormat(fmt)
            edit.setFocus()
            return

        block = cur.block()
        if whole_block and block.length() > 1:
            c = QTextCursor(block)
            c.setPosition(block.position())
            c.setPosition(block.position() + block.length() - 1, QTextCursor.KeepAnchor)
            c.mergeCharFormat(fmt)
            edit.setTextCursor(c)
            edit.mergeCurrentCharFormat(fmt)
            edit.setFocus()
            return

        text = block.text()
        pos = cur.positionInBlock()
        inside_word = (0 < pos < len(text)
                       and text[pos - 1].isalnum() and text[pos].isalnum())
        if inside_word:
            word = QTextCursor(cur)
            word.select(QTextCursor.WordUnderCursor)
            if word.hasSelection():
                word.mergeCharFormat(fmt)
                edit.setTextCursor(word)
        edit.mergeCurrentCharFormat(fmt)
        edit.setFocus()

    def _merge(self, fmt: QTextCharFormat) -> None:
        self._apply_format(fmt)

    def toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.edit.fontWeight() > QFont.Normal else QFont.Bold)
        self._merge(fmt)

    def toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.edit.fontItalic())
        self._merge(fmt)

    def toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.edit.fontUnderline())
        self._merge(fmt)

    def toggle_inline_code(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies(list(MONO_STACK))
        fmt.setFontFixedPitch(True)
        fmt.setBackground(QColor(P["inline_bg"]))
        fmt.setForeground(QColor(P["inline_text"]))
        self._merge(fmt)

    def toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.edit.currentCharFormat().fontStrikeOut())
        self._merge(fmt)

    def apply_font_size(self, size: float) -> None:
        if not 6 <= size <= 96:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self._merge(fmt)

    def change_heading_level(self, delta: int) -> None:
        """提升/降低标题级别；普通段落不参与（与 Typora 一致）。"""
        level = int(self.edit.textCursor().blockFormat().headingLevel())
        if level <= 0:
            return
        self.set_heading(max(0, min(6, level + delta)))

    def insert_table(self, rows: int = 3, cols: int = 3) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderBrush(QBrush(QColor(P["border"])))
        fmt.setBorderStyle(QTextTableFormat.BorderStyle_Solid)
        fmt.setCellPadding(6)
        fmt.setCellSpacing(0)
        fmt.setBorderCollapse(True)
        cur.insertTable(max(1, rows), max(1, cols), fmt)
        cur.endEditBlock()
        self.edit.setTextCursor(cur)
        self.edit.setFocus()

    def toggle_task(self) -> None:
        """任务列表项：在块首添加/去掉 ☐ 标记。"""
        cur = self.edit.textCursor()
        block = cur.block()
        text = block.text()
        m = _TASK_PREFIX_RE.match(text)
        cur.beginEditBlock()
        if m:
            cur.setPosition(block.position())
            cur.setPosition(block.position() + m.end(), QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        else:
            cur.setPosition(block.position())
            fmt = QTextCharFormat()
            fmt.setFontPointSize(11.0)
            cur.insertText("☐ ", fmt)
        cur.endEditBlock()
        self.edit.setFocus()

    def toggle_task_state(self) -> None:
        """把 ☐ 和 ☑ 互换。"""
        cur = self.edit.textCursor()
        block = cur.block()
        m = _TASK_PREFIX_RE.match(block.text())
        if not m:
            self.toggle_task()
            return
        cur.setPosition(block.position())
        cur.setPosition(block.position() + len(m.group(1)), QTextCursor.KeepAnchor)
        cur.insertText("☑" if m.group(1) == "☐" else "☐")
        self.edit.setFocus()

    def insert_hr(self) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        if cur.block().text().strip():
            cur.insertBlock()
        cur.insertHtml("<hr/>")
        cur.endEditBlock()

    def insert_paragraph(self, above: bool) -> None:
        cur = self.edit.textCursor()
        block = cur.block()
        cur.beginEditBlock()
        if above:
            pos = block.position()
            cur.setPosition(pos)
            cur.insertBlock()
            cur.setPosition(pos)
        else:
            cur.movePosition(QTextCursor.EndOfBlock)
            cur.insertBlock()
        cur.setCharFormat(QTextCharFormat())
        cur.endEditBlock()
        self.edit.setTextCursor(cur)

    def set_heading(self, level: int) -> None:
        # Typora 行为：光标已是该级标题时再按同一快捷键 → 切回正文
        cur_level = int(self.edit.textCursor().blockFormat().headingLevel())
        if level and cur_level == level:
            level = 0
        self.edit.textCursor().beginEditBlock()
        cur = self.edit.textCursor()
        bf = cur.blockFormat()
        bf.setHeadingLevel(max(0, level))
        bf.setLeftMargin(0 if level else bf.leftMargin())
        bf.setIndent(0)
        if level == 0:
            # 从标题改回正文：清掉标题行高（SingleHeight 忽略该值）
            bf.setLineHeight(0, QTextBlockFormat.LineHeightTypes.SingleHeight.value)
        cur.setBlockFormat(bf)

        fmt = QTextCharFormat()
        fmt.setFontPointSize(HEADING_SIZES.get(level, 11.0))
        fmt.setFontWeight(QFont.Bold if level else QFont.Normal)
        fmt.setForeground(HEADING6_COLOR if level == 6 else QColor(P["note_text"]))
        fmt.setFontFamilies(list(UI_FONT_STACK))
        self._apply_format(fmt, whole_block=True)
        self.edit.textCursor().endEditBlock()

    def _pick_color(self) -> None:
        cur_color = self.edit.currentCharFormat().foreground().color()
        color = QColorDialog.getColor(cur_color if cur_color.isValid() else QColor(P["note_text"]),
                                      self, "选择文字颜色")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self._merge(fmt)

    def _pick_highlight(self) -> None:
        menu = QMenu(self)
        for n, c in [("黄色", "#fff59d"), ("绿色", "#c8f7c5"), ("红色", "#ffd6d6"),
                     ("蓝色", "#cfe3ff"), ("紫色", "#e8d9ff"), ("无", "transparent")]:
            act = menu.addAction(n)
            act.setData(c)
        act = menu.exec(QCursor.pos())
        if act is None:
            return
        c = act.data()
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(Qt.NoBrush) if c == "transparent" else QColor(c))
        self._merge(fmt)

    def toggle_list(self, style) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        lst = cur.currentList()
        if lst is not None and lst.format().style() == style:
            bf = cur.blockFormat()
            bf.setObjectIndex(-1)
            cur.setBlockFormat(bf)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(1)
            cur.createList(fmt)
        cur.endEditBlock()

    def toggle_quote(self) -> None:
        cur = self.edit.textCursor()
        bf = cur.blockFormat()
        if bf.leftMargin() >= 18:
            bf.setLeftMargin(0)
            bf.setBackground(QBrush(Qt.NoBrush))
        else:
            bf.setLeftMargin(20)
            bf.setBackground(QColor(P["quote_bg"]))
        cur.setBlockFormat(bf)

    def clear_format(self) -> None:
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        fmt.setFontStrikeOut(False)
        fmt.setForeground(QColor(P["note_text"]))
        fmt.setBackground(QBrush(Qt.NoBrush))
        fmt.setFontPointSize(11)
        fmt.setAnchor(False)
        cur.setCharFormat(fmt)

    def insert_link(self) -> None:
        cur = self.edit.textCursor()
        text = cur.selectedText() or ""
        url, ok = QInputDialog.getText(self, "插入链接", "地址（http / https）：",
                                       QLineEdit.Normal, "https://")
        if not ok or not url.strip():
            return
        url = url.strip()
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url)
        fmt.setForeground(QColor(P["link"]))
        fmt.setFontUnderline(True)
        cur.insertText(text or url, fmt)

    def insert_code_block(self) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        self.edit.apply_code_block(cur)
        cur.endEditBlock()
        fmt = QTextCharFormat()
        fmt.setFontFamilies(list(MONO_STACK))
        fmt.setFontFixedPitch(True)
        fmt.setFontPointSize(10.0)
        fmt.setForeground(QColor(P["code_text"]))
        self._apply_format(fmt, whole_block=True)

    def insert_image(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "插入图片", "",
            "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)")
        for f in files:
            img = QImage(f)
            if not img.isNull():
                self.edit._try_image(img)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.flush()
            event.accept()
            return
        super().keyPressEvent(event)
