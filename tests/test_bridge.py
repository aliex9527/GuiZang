"""自研引擎接入层测试（需要 PySide6，缺了自动跳过）。

跑法（必须用项目自带的 .venv，系统 Python 里没有 PySide6）：

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
    QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v

这里测的是「归藏真的能用自研引擎跑起来」：开关生不生效、Qt 能吞下输出、
**载入再保存不丢内容**——最后这条是笔记应用最容易出事的地方。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:      # pragma: no cover - 没有 Qt 时整组跳过
    HAVE_QT = False

from ui import md_engine_bridge as bridge   # noqa: E402

SAMPLE = """# 标题

含 **粗体**、~~删除~~、==高亮== 与 [链接](https://example.com)。

> 引用第一行
> 引用第二行

- [ ] 未完成
- [x] 已完成
- 父项
    - 子项

| 项目 | 值 |
| --- | ---: |
| 版本 | 1.0.4 |

```python
x = 1
```
"""


@unittest.skipUnless(HAVE_QT, "需要 PySide6（请用项目的 .venv 运行）")
class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["mdengine-test"])

    def setUp(self):
        os.environ["GUICANG_MD_ENGINE"] = "1"

    def tearDown(self):
        os.environ.pop("GUICANG_MD_ENGINE", None)

    # ------------------------------------------------------------ 开关
    def test_flag_on(self):
        self.assertTrue(bridge.available())
        self.assertTrue(bridge.using_own())

    def test_default_is_own(self):
        os.environ.pop("GUICANG_MD_ENGINE", None)
        self.assertTrue(bridge.using_own())

    def test_flag_values(self):
        for value in ("1", "on", "true", "YES", " mdengine ", ""):
            os.environ["GUICANG_MD_ENGINE"] = value
            self.assertTrue(bridge.using_own(), value)
        for value in ("0", "off", "false", "no"):
            os.environ["GUICANG_MD_ENGINE"] = value
            self.assertFalse(bridge.using_own(), value)

    # ------------------------------------------------------------ 渲染
    def test_switch_actually_changes_engine(self):
        """两条链确实换了实现：删除线一个输出 <s>，一个输出 <del>。"""
        from ui.md_source import markdown_to_html

        os.environ["GUICANG_MD_ENGINE"] = "0"
        old = markdown_to_html("~~x~~")
        os.environ.pop("GUICANG_MD_ENGINE", None)       # 默认即自研引擎
        new = markdown_to_html("~~x~~")
        self.assertIn("<s>", old)
        self.assertIn("<del>", new)

    def test_qt_path_uses_span_not_mark(self):
        """喂 Qt 的两条出口都不能用 <mark>：Qt 富文本不认它，会连标签一起丢掉。"""
        self.assertIn("background-color", bridge.to_qt_html("==x=="))
        self.assertNotIn("<mark>", bridge.to_qt_html("==x=="))
        self.assertIn("background-color", bridge.to_preview_html("==x=="))
        self.assertNotIn("<mark>", bridge.to_preview_html("==x=="))

    def test_task_uses_glyph_not_input(self):
        """Qt 富文本不支持 <input>，任务项必须渲染成字形。"""
        html = bridge.to_qt_html("- [x] done")
        self.assertIn("☑", html)
        self.assertNotIn("<input", html)

    def test_blockquote_has_no_stray_br(self):
        html = bridge.to_qt_html("> a\n> b")
        self.assertIn("<blockquote><p>", html)
        self.assertNotIn("<blockquote><br>", html)
        self.assertIn("<br>", html)          # 行内换行仍要保留

    def test_pre_style_flattened_for_qt(self):
        html = bridge.to_qt_html("```python\nx = 1\n```")
        self.assertIn("<pre style=", html)
        self.assertNotIn("<code", html)       # Qt 只认 pre 的样式，code 壳要剥掉

    def test_preview_keeps_highlight(self):
        html = bridge.to_preview_html("```python\ndef f(): pass\n```")
        self.assertIn("<span style=", html)
        self.assertNotIn('class="highlight"', html)

    # ------------------------------------------------------------ 往返
    def test_qt_roundtrip_keeps_blocks(self):
        from ui.md_source import document_to_markdown, markdown_to_html

        doc = QTextDocument()
        doc.setHtml(markdown_to_html(SAMPLE))
        back = document_to_markdown(doc)

        self.assertIn("# 标题", back)
        self.assertIn("- [ ] 未完成", back)
        self.assertIn("- [x] 已完成", back)
        self.assertIn("    - 子项", back)          # 缩进翻倍会变成 8 空格
        self.assertIn("| 项目 | 值 |", back)
        self.assertIn("```", back)
        self.assertIn("> 引用第一行", back)

    def test_html_to_markdown_roundtrip(self):
        html = bridge.to_qt_html(SAMPLE)
        md = bridge.html_to_markdown(html)
        self.assertIn("**粗体**", md)
        self.assertIn("~~删除~~", md)
        self.assertIn("==高亮==", md)
        self.assertIn("[链接](https://example.com)", md)


@unittest.skipUnless(HAVE_QT, "需要 PySide6（请用项目的 .venv 运行）")
class LivePreviewTest(unittest.TestCase):
    """编辑器实时预览：增量渲染 + 刷新时不跳回顶部。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["mdengine-test"])

    def setUp(self):
        os.environ["GUICANG_MD_ENGINE"] = "1"
        self.live = bridge.live_preview()

    def tearDown(self):
        os.environ.pop("GUICANG_MD_ENGINE", None)

    def test_live_equals_full(self):
        self.assertEqual(bridge.live_preview_html(SAMPLE),
                         bridge.to_preview_html(SAMPLE))

    def test_second_render_reuses_blocks(self):
        long_md = "\n\n".join("第 %d 段。" % i for i in range(30))
        self.live.update(long_md)
        self.live.update(long_md + "\n\n新的一段。")
        stats = self.live.stats
        self.assertEqual(stats.reused, 30, "已有段落都该命中缓存")
        self.assertEqual(stats.rendered, 1)

    # -------------------------------------------------- 编辑器内即时渲染

    @staticmethod
    def _size_at(editor, block_no: int, index: int):
        """取某块某字符位置的实际字号（拿它判断标记是"显示"还是"隐藏"）。"""
        block = editor.edit.document().findBlockByNumber(block_no)
        for r in block.layout().formats():
            if r.start <= index < r.start + r.length:
                return r.format.fontPointSize()
        return None

    def test_editor_renders_in_place(self):
        """即时渲染：编辑区自己就是预览，不再有右侧面板。"""
        from ui.note_editor import NoteEditor

        editor = NoteEditor(lambda b, n: ("gzs:///1", 1), lambda fid: None)
        editor.resize(1000, 640)
        editor.show()
        self.app.processEvents()
        editor.set_node(1, "# 标题\n\n正文段落。\n", "md")
        self.app.processEvents()

        self.assertFalse(editor.preview.isVisible(), "默认不该分屏")
        doc = editor.edit.document()
        head = editor.edit.blockBoundingGeometry(doc.findBlockByNumber(0)).height()
        body = editor.edit.blockBoundingGeometry(doc.findBlockByNumber(2)).height()
        self.assertGreater(head, body * 1.3, "标题该比其他行高出一截")

        editor.edit.insertPlainText("新增内容。")
        editor._refresh_preview()
        self.assertIn("新增内容", editor.edit.toPlainText())
        editor.close()

    def test_markers_hidden_on_every_block(self):
        """标记一律不可见：光标停在哪一块都不露出 ``**``。"""
        from ui.note_editor import NoteEditor
        from PySide6.QtGui import QTextCursor

        editor = NoteEditor(lambda b, n: ("gzs:///1", 1), lambda fid: None)
        editor.resize(1000, 640)
        editor.show()
        self.app.processEvents()
        editor.set_node(1, "# 标题\n\n正文 **粗体** 与 `代码`。\n", "md")
        self.app.processEvents()

        doc = editor.edit.document()
        bold_at = doc.findBlockByNumber(2).text().index("**")

        # 光标在第一块：第二块的 ** 被缩到 1pt 以下
        editor.edit.setTextCursor(QTextCursor(doc.findBlockByNumber(0)))
        self.app.processEvents()
        self.assertLess(self._size_at(editor, 2, bold_at), 1.0)

        # 光标移到第二块：** 仍然不可见（不再回退成源码视图）
        editor.edit.setTextCursor(QTextCursor(doc.findBlockByNumber(2)))
        self.app.processEvents()
        self.assertLess(self._size_at(editor, 2, bold_at), 1.0)
        editor.close()

    def test_source_mode_reveals_everything(self):
        """切成源码模式后，标记全部恢复原样，文本一个字都不变。"""
        from ui.note_editor import NoteEditor
        from PySide6.QtGui import QTextCursor

        editor = NoteEditor(lambda b, n: ("gzs:///1", 1), lambda fid: None)
        editor.resize(1000, 640)
        editor.show()
        self.app.processEvents()
        editor.set_node(1, "## 标题\n\n正文 **粗体**。\n", "md")
        self.app.processEvents()

        before = editor.edit.toPlainText()
        editor.set_source_mode(True)
        self.app.processEvents()
        self.assertTrue(editor.source_only())
        self.assertEqual(editor.edit.toPlainText(), before, "切模式不该改动文本")
        # 源码模式没有标题放大：各块行高一致
        doc = editor.edit.document()
        h0 = editor.edit.blockBoundingGeometry(doc.findBlockByNumber(0)).height()
        h2 = editor.edit.blockBoundingGeometry(doc.findBlockByNumber(2)).height()
        self.assertAlmostEqual(h0, h2, delta=1.0)

        editor.set_source_mode(False)
        self.app.processEvents()
        self.assertFalse(editor.source_only())
        self.assertEqual(editor.edit.toPlainText(), before)
        editor.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
