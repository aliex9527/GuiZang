"""mdengine 自测。

跑法（在 归藏-工作区 目录下）：

    python -m unittest discover -s tests -v
    python tests\\test_mdengine.py          # 直接跑也行

断言基本都是「片段包含」而不是整段字符串比对——HTML 里的空行/属性顺序
不属于契约，语义对才是对；少数格式敏感的用例才做精确比对。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdengine import Engine, to_html, to_markdown  # noqa: E402
from mdengine.highlight import highlight_code, languages  # noqa: E402


class HeadingTest(unittest.TestCase):
    def test_atx(self):
        self.assertEqual(to_html("# 标题").strip(), "<h1>标题</h1>")
        self.assertEqual(to_html("### 三级").strip(), "<h3>三级</h3>")

    def test_atx_closing_hashes(self):
        self.assertEqual(to_html("## 标题 ##").strip(), "<h2>标题</h2>")

    def test_seven_hashes_is_text(self):
        html = to_html("####### x")
        self.assertIn("<p>", html)
        self.assertNotIn("<h7", html)

    def test_setext(self):
        self.assertEqual(to_html("标题\n===").strip(), "<h1>标题</h1>")
        self.assertEqual(to_html("标题\n---").strip(), "<h2>标题</h2>")

    def test_heading_id(self):
        html = to_html("# 标题 {#intro}")
        self.assertIn('id="intro"', html)
        self.assertIn("标题", html)


class EmphasisTest(unittest.TestCase):
    def test_strong_and_em(self):
        self.assertEqual(to_html("**粗**").strip(), "<p><strong>粗</strong></p>")
        self.assertEqual(to_html("*斜*").strip(), "<p><em>斜</em></p>")

    def test_triple(self):
        html = to_html("***both***")
        self.assertIn("<em><strong>both</strong></em>", html)

    def test_nested(self):
        html = to_html("**a *b* c**")
        self.assertIn("<strong>a <em>b</em> c</strong>", html)

    def test_underscore_intraword(self):
        html = to_html("snake_case_name")
        self.assertIn("snake_case_name", html)
        self.assertNotIn("<em>", html)

    def test_underscore_emphasis(self):
        self.assertIn("<em>x</em>", to_html("_x_"))

    def test_strike(self):
        self.assertIn("<del>删</del>", to_html("~~删~~"))

    def test_mark(self):
        self.assertIn("<mark>亮</mark>", to_html("==亮=="))

    def test_lone_tilde_is_text(self):
        self.assertIn("~~", to_html("a ~~ b"))

    def test_escape(self):
        html = to_html(r"\*not em\*")
        self.assertIn("*not em*", html)
        self.assertNotIn("<em>", html)

    def test_html_escaped(self):
        html = to_html("1 < 2 & 3 > 2")
        self.assertIn("&lt;", html)
        self.assertIn("&amp;", html)


class CodeTest(unittest.TestCase):
    def test_fence_with_lang(self):
        html = to_html("```python\nprint(1)\n```")
        self.assertIn("<pre", html)
        self.assertIn('class="language-python"', html)
        self.assertIn("print", html)

    def test_fence_content_escaped(self):
        html = to_html("```\nif a < b:\n```")
        self.assertIn("a &lt; b", html)

    def test_fence_info_string_not_leaked(self):
        html = to_html("```js\nlet a = 1\n```")
        self.assertNotIn("```", html)

    def test_inline_code(self):
        self.assertIn("<code>x = 1</code>", to_html("`x = 1`"))

    def test_inline_code_backticks(self):
        html = to_html("`` a`b ``")
        self.assertIn("<code>a`b</code>", html)

    def test_highlight_python_keyword(self):
        html = highlight_code("def f():\n    return 1", "python")
        self.assertIn("def", html)
        self.assertIn("<span", html)

    def test_highlight_unknown_lang_escapes(self):
        html = highlight_code("a < b", "brainfuck")
        self.assertEqual(html, "a &lt; b")

    def test_highlight_languages_listed(self):
        self.assertIn("python", languages())
        self.assertIn("json", languages())


class ListTest(unittest.TestCase):
    def test_bullet(self):
        html = to_html("- a\n- b")
        self.assertIn("<ul>", html)
        self.assertIn("<li>a</li>", html)
        self.assertIn("<li>b</li>", html)

    def test_ordered(self):
        html = to_html("1. a\n2. b")
        self.assertIn("<ol>", html)
        self.assertIn("<li>a</li>", html)

    def test_ordered_start(self):
        self.assertIn('start="3"', to_html("3. a\n4. b"))

    def test_nested(self):
        html = to_html("- a\n    - b")
        self.assertIn("<ul>", html)
        self.assertIn("<li>b</li>", html)
        # 嵌套的第二层必须在这个位置出现，而不是被压平到顶层
        self.assertGreaterEqual(html.count("<ul>"), 2)

    def test_tight_item_with_sublist_has_no_p(self):
        """回归：紧凑列表里「文字 + 子列表」的项曾被包上 <p>，观感比旧路径多一段间距。"""
        html = to_html("- 父项\n    - 子项")
        self.assertIn("<li>父项", html)
        self.assertNotIn("<p>父项</p>", html)

    def test_task_list(self):
        html = to_html("- [ ] todo\n- [x] done")
        self.assertIn('type="checkbox"', html)
        self.assertIn("checked", html)
        self.assertIn("todo", html)

    def test_task_glyph_mode(self):
        html = to_html("- [x] done", task_style="glyph")
        self.assertIn("☑", html)

    def test_loose_list_has_paragraph(self):
        html = to_html("- a\n\n- b")
        self.assertIn("<p>a</p>", html)

    def test_thematic_break_not_list(self):
        html = to_html("- - -")
        self.assertIn("<hr", html)
        self.assertNotIn("<ul>", html)


class BlockTest(unittest.TestCase):
    def test_blockquote(self):
        html = to_html("> 引用")
        self.assertIn("<blockquote>", html)
        self.assertIn("引用", html)

    def test_blockquote_nested(self):
        html = to_html("> a\n> > b")
        self.assertGreaterEqual(html.count("<blockquote>"), 2)

    def test_hr(self):
        self.assertIn("<hr", to_html("---"))

    def test_paragraphs_split(self):
        html = to_html("a\n\nb")
        self.assertEqual(html.count("<p>"), 2)

    def test_indented_code(self):
        html = to_html("    x = 1")
        self.assertIn("<pre", html)
        self.assertIn("x = 1", html)

    def test_admonition(self):
        html = to_html('!!! note "提示"\n    内容')
        self.assertIn("admonition", html)
        self.assertIn("提示", html)
        self.assertIn("内容", html)

    def test_raw_html_passthrough(self):
        html = to_html("<div class=\"x\">\n原生\n</div>")
        self.assertIn('class="x"', html)
        self.assertIn("原生", html)

    def test_empty(self):
        self.assertEqual(to_html(""), "")
        self.assertEqual(to_html("   \n\n"), "")


class LinkTest(unittest.TestCase):
    def test_link(self):
        html = to_html("[官网](https://example.com)")
        self.assertIn('href="https://example.com"', html)
        self.assertIn("官网", html)

    def test_link_title(self):
        html = to_html('[a](https://x.com "标题")')
        self.assertIn('title="标题"', html)

    def test_image(self):
        html = to_html("![图](gzs:///1)")
        self.assertIn('src="gzs:///1"', html)
        self.assertIn('alt="图"', html)

    def test_image_width_attr(self):
        html = to_html("![图](gzs:///1){width=300}")
        self.assertIn('width="300"', html)
        self.assertNotIn("{width", html)

    def test_reference_link(self):
        md = "[官网][a]\n\n[a]: https://example.com"
        html = to_html(md)
        self.assertIn('href="https://example.com"', html)
        self.assertNotIn("[a]:", html)

    def test_autolink(self):
        html = to_html("<https://example.com>")
        self.assertIn('href="https://example.com"', html)

    def test_gzs_url_not_mangled(self):
        html = to_html("[图](gzs:///42)")
        self.assertIn("gzs:///42", html)


class TableTest(unittest.TestCase):
    MD = "| 名 | 值 |\n| --- | ---: |\n| a | 1 |\n| b | 2 |"

    def test_structure(self):
        html = to_html(self.MD)
        self.assertIn("<table>", html)
        self.assertIn("<th>名</th>", html)
        self.assertIn("<td>a</td>", html)

    def test_alignment(self):
        html = to_html(self.MD)
        self.assertIn("text-align:right", html)

    def test_pipe_in_cell_escaped(self):
        html = to_html("| a |\n| --- |\n| x \\| y |")
        self.assertIn("x | y", html)

    def test_table_not_paragraph(self):
        html = to_html(self.MD)
        self.assertNotIn("<p>| 名", html)


class ReverseTest(unittest.TestCase):
    def test_heading(self):
        self.assertEqual(to_markdown("<h1>标题</h1>"), "# 标题\n")

    def test_paragraph_strong(self):
        self.assertEqual(to_markdown("<p>Hello <strong>world</strong></p>"),
                         "Hello **world**\n")

    def test_list(self):
        self.assertEqual(to_markdown("<ul><li>a</li><li>b</li></ul>"), "- a\n- b\n")

    def test_ordered_list(self):
        md = to_markdown("<ol><li>a</li><li>b</li></ol>")
        self.assertIn("1. a", md)
        self.assertIn("2. b", md)

    def test_code_block(self):
        md = to_markdown('<pre><code class="language-python">print(1)</code></pre>')
        self.assertIn("```python", md)
        self.assertIn("print(1)", md)

    def test_link_and_image(self):
        md = to_markdown('<p><a href="https://x.com">点我</a></p>')
        self.assertIn("[点我](https://x.com)", md)
        md = to_markdown('<p><img src="gzs:///1" alt="图"></p>')
        self.assertIn("![图](gzs:///1)", md)

    def test_blockquote(self):
        md = to_markdown("<blockquote><p>引用</p></blockquote>")
        self.assertIn("> 引用", md)

    def test_table(self):
        html = "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
        md = to_markdown(html)
        self.assertIn("| a | b |", md)
        self.assertIn("| 1 | 2 |", md)

    def test_table_row_order_and_no_duplicate_header(self):
        """回归：曾经用栈收集 <tr> 导致行序反转、表头重复。"""
        html = ("<table><thead><tr><th>项目</th><th>内容</th></tr></thead>"
                "<tbody><tr><td>版本号</td><td>1.0.4</td></tr>"
                "<tr><td>平台</td><td>Windows</td></tr></tbody></table>")
        md = to_markdown(html)
        lines = [line for line in md.splitlines() if line.startswith("|")]
        self.assertEqual(lines[0], "| 项目 | 内容 |")
        self.assertEqual(lines[2], "| 版本号 | 1.0.4 |")
        self.assertEqual(lines[3], "| 平台 | Windows |")
        self.assertEqual(md.count("版本号"), 1)

    def test_strike_and_mark(self):
        self.assertIn("~~x~~", to_markdown("<p><del>x</del></p>"))
        self.assertIn("==x==", to_markdown('<p><span style="background-color:#fff59d">x</span></p>'))

    def test_skips_script_style(self):
        md = to_markdown("<p>a</p><script>evil()</script><style>.x{}</style>")
        self.assertNotIn("evil", md)
        self.assertNotIn(".x", md)

    def test_empty(self):
        self.assertEqual(to_markdown(""), "")


class RoundTripTest(unittest.TestCase):
    def test_md_html_md(self):
        md = "# 标题\n\n- a\n- b\n\n正文 **粗** 结尾\n"
        html = to_html(md)
        back = to_markdown(html)
        self.assertIn("# 标题", back)
        self.assertIn("- a", back)
        self.assertIn("**粗**", back)

    def test_idempotent_second_pass(self):
        md = "1. 第一\n2. 第二\n"
        once = to_markdown(to_html(md))
        twice = to_markdown(to_html(once))
        self.assertEqual(once, twice)


class EngineTest(unittest.TestCase):
    def test_reuse(self):
        engine = Engine()
        self.assertIn("<h1>", engine.to_html("# a"))
        self.assertIn("<h2>", engine.to_html("## b"))

    def test_extensions_override(self):
        engine = Engine(extensions=["setext"])
        html = engine.to_html("```\ncode\n```")
        # fenced_code 被关掉，围栏退化成普通段落
        self.assertNotIn("<pre", html)

    def test_nl2br(self):
        self.assertIn("<br>", to_html("a\nb", nl2br=True))
        self.assertNotIn("<br>", to_html("a\nb"))

    def test_highlight_off(self):
        html = to_html("```python\nx = 1\n```", highlight=False)
        self.assertNotIn("<span", html)
        self.assertIn("x = 1", html)

    def test_classes_mode(self):
        html = to_html("```python\ndef f(): pass\n```", noclasses=False)
        self.assertIn('class="tok-', html)


class RobustnessTest(unittest.TestCase):
    """畸形输入不能崩、也不能卡。

    这几条是回归护栏：修之前「一万个 ``[``」要 10 秒（O(n²)），
    「500 层引用」直接 RecursionError。
    """

    BUDGET = 3.0   # 秒；正常工作应在 0.1s 内，留足余量避免 CI 抖动

    def _timed(self, source: str) -> str:
        import time
        start = time.perf_counter()
        html = to_html(source)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, self.BUDGET, "耗时 %.2fs，疑似退化回 O(n²)" % elapsed)
        return html

    def test_unclosed_brackets(self):
        html = self._timed("[" * 10000)
        self.assertIn("[", html)

    def test_unclosed_images(self):
        self._timed("![a](gzs:///1" * 500)

    def test_unclosed_links(self):
        self._timed("[a](http://x" * 500)

    def test_deep_blockquote_no_crash(self):
        html = self._timed(">" * 500 + " x")
        self.assertIn("x", html)

    def test_deep_list_no_crash(self):
        md = "\n".join("    " * i + "- l%d" % i for i in range(120))
        self._timed(md)

    def test_long_url_still_parsed(self):
        url = "https://example.com/" + "a" * 300
        html = to_html("[x](%s)" % url)
        self.assertIn('href="%s"' % url, html)

    def test_star_storm(self):
        self._timed("*a**b***c*" * 2000)

    def test_truncated_document(self):
        md = "# 标题\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n- [ ] x\n\n```py\nprint(1)\n"
        for cut in range(1, len(md), 7):
            to_html(md[:cut])
            to_markdown(to_html(md[:cut]))

    def test_blank_and_whitespace(self):
        for src in ("", " ", "\n\n\n", "   \t  "):
            self.assertEqual(to_html(src), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
