"""即时渲染（Typora 式就地排版）的测试。

这里测的是"渲染到位"这件事本身：字号层次、标记是否被抹掉、光标块是否
恢复源码、块级装饰类型、图片行撑高与收起。不测像素，只测量得到的属性。
"""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QTextCursor
    from PySide6.QtWidgets import QApplication

    from ui.live_render import LiveDecor
    from ui.source_edit import MarkdownSource
    from ui.theme import apply_theme
    HAVE_QT = True
except ImportError:          # pragma: no cover - 系统 Python 没有 Qt 时整组跳过
    HAVE_QT = False


def _app():
    return QApplication.instance() or QApplication([])


def _picture(w: int = 400, h: int = 200) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#3366cc"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


@unittest.skipUnless(HAVE_QT, "需要 PySide6（用项目自带 .venv 运行）")
class LiveRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _app()
        apply_theme("light")

    def setUp(self) -> None:
        self.ed = MarkdownSource()
        self.ed.resize(900, 600)

    def tearDown(self) -> None:
        self.ed.deleteLater()

    # ---------------------------------------------------------- 工具

    def _load(self, md: str, cursor_block: int = -1) -> None:
        """载入文本；cursor_block 为 -1 时把光标放到最后一块。

        光标一开始总在第 0 块，所以"没有光标"的用例必须在末尾留一块收尾，
        否则被测块自己就是 active，标记当然看得见。
        """
        self.ed.setPlainText(md)
        self.app.processEvents()
        doc = self.ed.document()
        block = (doc.findBlockByNumber(cursor_block) if cursor_block >= 0
                 else doc.lastBlock())
        self.ed.setTextCursor(QTextCursor(block))
        self.app.processEvents()

    def _size_at(self, block_no: int, index: int):
        block = self.ed.document().findBlockByNumber(block_no)
        for r in block.layout().formats():
            if r.start <= index < r.start + r.length:
                return r.format.fontPointSize()
        return None

    def _height(self, block_no: int) -> float:
        block = self.ed.document().findBlockByNumber(block_no)
        return self.ed.blockBoundingGeometry(block).height()

    # ---------------------------------------------------------- 文本

    def test_rendering_never_changes_text(self):
        md = ("# 标题\n\n**粗** [链接](https://a.b) `代码`\n\n"
              "> 引用\n\n```py\nx = 1\n```\n\n---\n")
        self.ed.setPlainText(md)
        self.app.processEvents()
        self.ed.refresh_decor()
        self.assertEqual(self.ed.toPlainText(), md)

    # ---------------------------------------------------------- 标题

    def test_heading_sizes_are_layered(self):
        self._load("# 一级\n\n## 二级\n\n正文\n", cursor_block=4)
        h1 = self._height(0)
        h2 = self._height(2)
        body = self._height(4)
        self.assertGreater(h1, h2, "一级标题该比二级大")
        self.assertGreater(h2, body, "二级标题该比正文大")

    def test_non_active_markers_are_erased(self):
        self._load("正文 **粗体** 收尾\n\n尾巴\n")
        self.assertLess(self._size_at(0, 3), 1.0, "不在光标的块应把 ** 缩没")

    def test_markers_never_shown(self):
        """光标所在块的标记同样不可见——编辑区里不该出现 `**`。"""
        md = "第一段\n\n正文 **粗体** 收尾\n"
        self._load(md, cursor_block=2)
        idx = self.ed.document().findBlockByNumber(2).text().index("**")
        self.assertLess(self._size_at(2, idx), 1.0, "光标所在块也不该看见标记")

    def test_markers_stay_hidden_after_cursor_move(self):
        md = "上一段 **粗**\n\n下一段\n"
        self._load(md, cursor_block=2)
        idx = self.ed.document().findBlockByNumber(0).text().index("**")
        self.assertLess(self._size_at(0, idx), 1.0)
        # 光标移回第一块，标记依旧不展开
        doc = self.ed.document()
        self.ed.setTextCursor(QTextCursor(doc.findBlockByNumber(0)))
        self.app.processEvents()
        self.assertLess(self._size_at(0, idx), 1.0, "移动光标不该让标记冒出来")

    # ---------------------------------------------------------- 行内

    def test_link_keeps_text_hides_url(self):
        self._load("见 [示例](https://example.com) 完\n\n尾巴\n")
        text = self.ed.document().findBlockByNumber(0).text()
        open_at = text.index("[")
        url_at = text.index("https")
        self.assertLess(self._size_at(0, open_at), 1.0, "方括号该被抹掉")
        self.assertLess(self._size_at(0, url_at), 1.0, "URL 该被抹掉")

    def test_inline_code_uses_monospace(self):
        self._load("一句 `code_here()` 结尾\n\n尾巴\n")
        block = self.ed.document().findBlockByNumber(0)
        idx = block.text().index("code_here")
        for r in block.layout().formats():
            if r.start <= idx < r.start + r.length:
                self.assertEqual(r.format.fontFamilies()[0], self.ed.highlighter._mono)
                return
        self.fail("行内代码没被打上格式")

    # ---------------------------------------------------------- 块级装饰

    def test_decor_kinds(self):
        md = ("正文\n\n> 引用\n\n```py\nx = 1\n```\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n---\n")
        self.ed.setPlainText(md)
        self.app.processEvents()
        self.ed.refresh_decor()
        kinds = set(self.ed.decor._kinds)
        self.assertIn(LiveDecor.QUOTE, kinds)
        self.assertIn(LiveDecor.CODE, kinds)
        self.assertIn(LiveDecor.TABLE_HEAD, kinds)
        self.assertIn(LiveDecor.HR, kinds)

    def test_separator_keeps_line_height(self):
        self._load("上文\n\n---\n\n下文\n", cursor_block=0)
        self.assertGreater(self._height(2), 8, "分隔线行不能塌成 0 高")

    # ---------------------------------------------------------- 图片

    def test_image_row_stays_expanded(self):
        self.ed.image_loader = lambda fid: _picture() if fid == 1 else None
        md = "上文\n\n![图](gzs:///1)\n\n下文\n"
        self.ed.setPlainText(md)
        self.app.processEvents()
        self.ed.refresh_decor()
        self.app.processEvents()

        self.assertIn(2, self.ed.highlighter.img_heights, "独占一行的图片该被识别")
        self.assertGreater(self._height(2), 120, "图片行该被撑高")

        # 光标进入该行也不再收回源码：标记一律不显示，图片始终按图片铺开
        doc = self.ed.document()
        self.ed.setTextCursor(QTextCursor(doc.findBlockByNumber(2)))
        self.app.processEvents()
        self.assertGreater(self._height(2), 120, "光标进入后图片行仍保持展开")

    def test_missing_image_falls_back_to_text(self):
        self.ed.image_loader = lambda fid: None
        self.ed.setPlainText("![图](gzs:///9)\n")
        self.app.processEvents()
        self.ed.refresh_decor()
        self.assertEqual(self.ed.highlighter.img_heights, {})

    # ---------------------------------------------------------- 模式

    def test_source_mode_switches_font_and_layout(self):
        self._load("# 标题\n\n正文\n", cursor_block=2)
        live_h = self._height(0)
        self.ed.set_live(False)
        self.app.processEvents()
        self.assertFalse(self.ed.is_live())
        self.assertAlmostEqual(self._height(0), self._height(2), delta=1.0,
                               msg="源码模式各块行高应一致")
        self.ed.set_live(True)
        self.app.processEvents()
        self.assertAlmostEqual(self._height(0), live_h, delta=2.0,
                               msg="切回即时渲染应恢复标题高度")

    # ---------------------------------------------------------- 健壮性

    def test_long_line_degrades_without_crash(self):
        md = "正文" + "字" * 5000 + "**粗**"
        self.ed.setPlainText(md)
        self.app.processEvents()
        self.ed.refresh_decor()
        self.assertEqual(self.ed.toPlainText(), md)

    def test_unclosed_fence_does_not_crash(self):
        self.ed.setPlainText("```python\nx = 1\ny = 2\n")
        self.app.processEvents()
        self.ed.refresh_decor()
        self.assertEqual(set(self.ed.decor._kinds), {LiveDecor.CODE})


@unittest.skipUnless(HAVE_QT, "需要 PySide6（用项目自带 .venv 运行）")
class BlockShortcutTest(unittest.TestCase):
    """块级快捷键（Ctrl+1、列表、引用）落笔后光标该停在哪。

    历史 bug：空行按 Ctrl+1 时 `# ` 插进去了，光标却被放回第 0 列，
    接着打的字落在井号**前面**，整行变成「标题# 」，渲染层又把井号藏了
    ——用户看到的就是"按了没反应、输入的不是标题"。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _app()
        apply_theme("light")

    def setUp(self) -> None:
        from ui.note_editor import NoteEditor
        self.ed = NoteEditor(lambda b, m: None, lambda i: None)
        self.ed.resize(900, 600)
        self.ed.set_node(1, "第一行\n\n第三行\n")

    def tearDown(self) -> None:
        self.ed.deleteLater()

    # ---------------------------------------------------------- 工具

    def _put_cursor(self, block_no: int, col: int = 0):
        block = self.ed.edit.document().findBlockByNumber(block_no)
        cur = QTextCursor(block)
        cur.setPosition(block.position() + col)
        self.ed.edit.setTextCursor(cur)
        return cur

    def _height(self, block_no: int) -> float:
        block = self.ed.edit.document().findBlockByNumber(block_no)
        return self.ed.edit.blockBoundingGeometry(block).height()

    # ---------------------------------------------------------- 用例

    def test_heading_on_empty_line_then_type(self):
        self._put_cursor(1)
        self.assertEqual(self.ed.set_heading(1), 1)
        cur = self.ed.edit.textCursor()
        self.assertEqual(cur.block().text(), "# ")
        self.assertEqual(cur.positionInBlock(), 2, "光标该在 `# ` 之后，不能在井号前")

        cur.insertText("标题")
        self.app.processEvents()
        self.assertEqual(cur.block().text(), "# 标题")
        self.assertEqual(self.ed.heading_level(), 1)
        self.assertGreater(self._height(1), self._height(2) + 5,
                           "输入后该立刻按一级标题排版")

    def test_heading_keeps_cursor_inside_text(self):
        self.ed.set_node(1, "abc\n")
        self._put_cursor(0, 1)
        self.ed.set_heading(1)
        cur = self.ed.edit.textCursor()
        self.assertEqual(cur.block().text(), "# abc")
        self.assertEqual(cur.positionInBlock(), 3, "光标该仍在 a 与 bc 之间")

    def test_heading_toggle_back_keeps_cursor(self):
        self.ed.set_node(1, "# abc\n")
        self._put_cursor(0, 5)
        self.ed.set_heading(1)          # 同级再按一次 → 回正文
        cur = self.ed.edit.textCursor()
        self.assertEqual(cur.block().text(), "abc")
        self.assertEqual(cur.positionInBlock(), 3, "去掉前缀后光标该还在行尾")

    def test_list_mark_keeps_cursor_after_prefix(self):
        self.ed.set_node(1, "abc\n")
        self._put_cursor(0, 0)
        self.ed.toggle_list()
        cur = self.ed.edit.textCursor()
        self.assertEqual(cur.block().text(), "- abc")
        self.assertEqual(cur.positionInBlock(), 2, "光标别停在前缀里面")

    def test_quote_keeps_cursor_after_prefix(self):
        self.ed.set_node(1, "abc\n")
        self._put_cursor(0, 2)
        self.ed.toggle_quote()
        cur = self.ed.edit.textCursor()
        self.assertEqual(cur.block().text(), "> abc")
        self.assertEqual(cur.positionInBlock(), 4, "光标该仍在 b 与 c 之间")


if __name__ == "__main__":
    unittest.main(verbosity=2)
