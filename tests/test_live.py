"""实时预览（``mdengine.live`` / ``mdengine.server``）自测。

跑法（在 归藏-工作区 目录下）：

    python -m unittest discover -s tests -v

这里最重要的一组是 **差分测试**：增量渲染的结果必须和 :meth:`Engine.to_html`
逐字节相同。它跑的是真实语料 + 随机构造的编辑（改字符、删行、插围栏、插引用
定义……），并且在**同一个实例**上连续调用——缓存复用的 bug 只在连续编辑里暴露。

开发时就靠它抓到两个真问题：
1. 早期版本自己用正则扫围栏状态来切块，遇到「``​``` `` 被 HTML 块吞掉」会与
   解析器的判断不一致 → 改成由解析器报告块范围；
2. 列表的「紧凑/松散」会看块**之后**那一行，若只拿块原文做缓存键，同一段文字
   会命中上一轮的紧密版本 → 键里补上后一行。
"""

from __future__ import annotations

import json
import random
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdengine import Engine, LivePreview  # noqa: E402
from mdengine.highlight import style_css  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

SNIPPETS = [
    "普通文字", "- 列表项", "  - 缩进子项", "> 引用", "```python\nx = 1\n```",
    "| a | b |\n| --- | --- |\n| 1 | 2 |", "    indented code", "", "", "",
    "[ref]: https://example.com", "文字 [ref] 引用", "---",
    '!!! note "标题"\n    正文', "```\ncode", "仍 ``` 未完", "~~~\ntilde",
    "# 标题 {#x}", "**粗** `代码`", "1. 一\n2. 二", "> > 双层引用",
    "<div>\nhtml\n</div>", "<div>\n\n```\n", "- a\n\n- b",
]


def _corpus(limit: int = 0):
    files = sorted(ROOT.glob("**/*.md"))
    files = [f for f in files if "dist" not in f.parts][: limit or None]
    return files


def _mutate(text: str, rnd: random.Random) -> str:
    lines = text.split("\n")
    if not lines:
        lines = [""]
    op = rnd.choice(["insert", "delete", "replace", "char", "blank", "dup", "swap"])
    i = rnd.randrange(len(lines))
    if op == "insert":
        lines.insert(i, rnd.choice(SNIPPETS))
    elif op == "delete":
        lines.pop(i)
    elif op == "replace":
        lines[i] = rnd.choice(SNIPPETS)
    elif op == "char":
        line = lines[i]
        j = rnd.randrange(len(line) + 1)
        lines[i] = line[:j] + rnd.choice("ab *`|>-#[]()~<>") + line[j:]
    elif op == "blank":
        lines[i] = lines[i] + "\n"
    elif op == "dup":
        lines.insert(i, lines[i])
    elif len(lines) > 1:
        k = rnd.randrange(len(lines))
        lines[i], lines[k] = lines[k], lines[i]
    return "\n".join(lines)


class DifferentialTest(unittest.TestCase):
    """增量渲染 == 全量渲染。"""

    def test_corpus(self):
        engine = Engine()
        files = _corpus()
        self.assertGreater(len(files), 5, "语料太少，测试没意义")
        for f in files:
            src = f.read_text(encoding="utf-8")
            live = LivePreview(engine)
            self.assertEqual(live.update(src), engine.to_html(src), f.name)

    def test_random_edits(self):
        engine = Engine()
        files = _corpus(limit=8)
        total = 0
        rnd = random.Random(20261029)
        for f in files:
            src = f.read_text(encoding="utf-8")
            live = LivePreview(engine)
            cur = src
            for _ in range(30):
                for _ in range(rnd.randint(1, 3)):
                    cur = _mutate(cur, rnd)
                    total += 1
                    self.assertEqual(live.update(cur), engine.to_html(cur),
                                     "%s 第 %d 次编辑后不一致" % (f.name, total))

    def test_empty_and_blank(self):
        engine = Engine()
        live = LivePreview(engine)
        for text in ("", "   ", "\n\n\n", "\t"):
            self.assertEqual(live.update(text), engine.to_html(text))
            self.assertEqual(live.stats.blocks, 0)


class CacheBehaviourTest(unittest.TestCase):
    def test_only_changed_block_rerendered(self):
        engine = Engine()
        live = LivePreview(engine)
        src = "# 一\n\n第一段。\n\n第二段。\n\n第三段。"
        live.update(src)
        self.assertEqual(live.stats.rendered, 4)

        live.update(src.replace("第二段", "第二段改过"))
        self.assertEqual(live.stats.rendered, 1, "只该重排改动的那一块")
        self.assertEqual(live.stats.reused, 3)

    def test_typing_at_end_reuses_everything_but_last(self):
        engine = Engine()
        live = LivePreview(engine)
        # 用段落而不是列表项：空行分隔的列表项会合成一个松散列表（整块变化）
        src = "\n\n".join(["第 %d 段。" % i for i in range(20)])
        live.update(src)
        self.assertEqual(live.stats.blocks, 20)
        live.update(src + "\n\n续写。")
        self.assertEqual(live.stats.reused, 20, "已有段落都该命中缓存")
        self.assertEqual(live.stats.rendered, 1)

    def test_ref_definition_change_invalidates(self):
        engine = Engine()
        live = LivePreview(engine)
        a = "见 [文档]。\n\n[文档]: https://a.example"
        b = "见 [文档]。\n\n[文档]: https://b.example"
        self.assertIn("https://a.example", live.update(a))
        self.assertIn("https://b.example", live.update(b))
        self.assertEqual(live.update(b), engine.to_html(b))

    def test_ref_can_be_removed(self):
        engine = Engine()
        live = LivePreview(engine)
        live.update("见 [文档]。\n\n[文档]: https://a.example")
        gone = live.update("见 [文档]。")
        self.assertNotIn("<a ", gone)
        self.assertEqual(gone, engine.to_html("见 [文档]。"))

    def test_repeated_paragraph_rendered_once(self):
        engine = Engine()
        live = LivePreview(engine)
        src = "同样的段落。\n\n同样的段落。\n\n同样的段落。"
        html = live.update(src)
        self.assertEqual(live.stats.rendered, 1, "相同文本应共用一份渲染结果")
        self.assertEqual(html.count("<p>同样的段落。</p>"), 3)

    def test_invalidate(self):
        engine = Engine()
        live = LivePreview(engine)
        live.update("一段话")
        live.invalidate()
        live.update("一段话")
        self.assertEqual(live.stats.rendered, 1)


class AnchorTest(unittest.TestCase):
    def test_data_line_matches_source(self):
        live = LivePreview(Engine(), anchor=True)
        src = "# 标题\n\n第一段\n\n- 一\n- 二\n\n```py\nx = 1\n```"
        html = live.update(src)
        self.assertIn('data-line="0"', html)     # 标题在第 0 行
        self.assertIn('data-line="2"', html)     # 第一段在第 2 行
        self.assertIn('data-line="4"', html)     # 列表在第 4 行
        self.assertIn('data-line="7"', html)     # 代码块在第 7 行
        self.assertEqual(html.count('class="md-block"'), 4)

    def test_anchor_still_equals_full_render_after_unwrap(self):
        engine = Engine()
        src = "# 标题\n\n段落一。\n\n段落二。"
        plain = engine.to_html(src)
        wrapped = LivePreview(engine, anchor=True).update(src)
        unwrapped = re.sub(r'<div class="md-block" data-line="\d+">(.*?)</div>',
                           r"\1", wrapped, flags=re.S)
        self.assertEqual(unwrapped.rstrip("\n") + "\n", plain)


class PostHookTest(unittest.TestCase):
    def test_post_applied_per_block(self):
        live = LivePreview(Engine(), post=lambda h: h.upper())
        html = live.update("abc\n\ndef")
        self.assertIn("<P>ABC</P>", html)
        self.assertIn("<P>DEF</P>", html)


class StyleCssTest(unittest.TestCase):
    def test_contains_tokens(self):
        css = style_css("friendly")
        self.assertIn(".tok-kw", css)
        self.assertIn(".tok-str", css)
        self.assertIn("color:", css)


class ServerTest(unittest.TestCase):
    """真起一个服务，走 HTTP。"""

    @classmethod
    def setUpClass(cls):
        import tempfile

        from mdengine.server import make_server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.file = Path(cls.tmp.name) / "note.md"
        cls.file.write_text("# 你好\n\n正文。\n", encoding="utf-8")
        cls.httpd, cls.base = make_server(str(cls.file), port=0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path.lstrip("/"), timeout=5) as res:
            return res.status, res.read().decode("utf-8")

    def _post(self, path: str, body: str):
        req = urllib.request.Request(self.base + path.lstrip("/"),
                                     data=body.encode("utf-8"), method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read().decode("utf-8")

    def test_index_has_editor(self):
        status, html = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn('id="src"', html)
        self.assertIn('id="preview"', html)
        self.assertIn("你好", html)          # 初始内容注入了
        self.assertIn(".tok-kw", html)       # 配色 CSS 注入了

    def test_render_returns_html_and_stats(self):
        status, body = self._post("/render", "# 标题\n\n**粗**")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("<h1>标题</h1>", data["html"])
        self.assertIn("<strong>粗</strong>", data["html"])
        self.assertIn("blocks", data["stats"])

    def test_render_twice_reports_reuse(self):
        self._post("/render", "# 标题\n\n段落 A\n\n段落 B")
        _, body = self._post("/render", "# 标题\n\n段落 A 改\n\n段落 B")
        stats = json.loads(body)["stats"]
        self.assertEqual(stats["rendered"], 1)
        self.assertEqual(stats["reused"], 2)

    def test_save_writes_file(self):
        status, body = self._post("/save", "# 改过了\n")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "# 改过了\n")
        self.assertFalse((self.file.parent / "note.md.tmp").exists())

    def test_reload(self):
        # 自己写文件，不依赖别的用例先跑（用例顺序是会变的）
        self.file.write_text("# 磁盘上的内容\n", encoding="utf-8")
        _, body = self._get("/reload")
        self.assertEqual(json.loads(body)["source"], "# 磁盘上的内容\n")

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_save_without_file(self):
        from mdengine.server import make_server
        httpd, base = make_server(None, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(base + "save", data=b"x", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 409)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
