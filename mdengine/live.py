"""实时预览：按块增量渲染。

编辑器里每敲一个字就重排整篇是浪费的：44 KB 语料全量要 39 ms，其中 27 ms 是
块级解析、18 ms 是渲染（代码着色占了渲染的四分之三）。这里做两件事：

1. **行内解析记忆化**（``InlineParser``）：没改动的段落文字一个字都没变，直接命中；
2. **块级渲染缓存**（本模块）：以「顶层块的原文」为键缓存它的 HTML，改哪块重排哪块。

块的行范围由**解析器自己报告**（:meth:`BlockParser.parse_spans`），不猜。早期版本
用正则扫描围栏状态来切块，结果遇到「``​``` `` 被 HTML 块吞掉」「围栏在列表项里被
重新缩进」这类情况就会和解析器判断不一致，增量结果与全量渲染对不上；现在块边界
与解析器同源，拼接结果和 ``Engine.to_html`` 逐字节相等（``tests/test_live.py``
有对全量渲染的差分测试，含随机编辑）。

解析仍是线性的——对一篇 2 KB 的笔记不到 1 ms，够用；真正贵的是渲染，而那部分
被完整缓存掉了。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .block import BlockParser, normalize_source
from .options import Options
from .render import HtmlRenderer

__all__ = ["LivePreview", "RenderStats"]


@dataclass
class RenderStats:
    """一次 :meth:`LivePreview.update` 的统计，供界面显示与测试断言。"""

    ms: float = 0.0
    blocks: int = 0
    rendered: int = 0
    reused: int = 0
    chars: int = 0

    @property
    def ratio(self) -> float:
        """复用率，0~1。"""
        return (self.reused / self.blocks) if self.blocks else 0.0

    def as_dict(self) -> dict:
        return {"ms": round(self.ms, 2), "blocks": self.blocks,
                "rendered": self.rendered, "reused": self.reused,
                "chars": self.chars}


class LivePreview:
    """给编辑器用的增量渲染器。

    Args:
        options: 直接传 :class:`Options`。
        engine: 传 :class:`mdengine.Engine`（取它的 ``options``）。
        post: 每块 HTML 的后处理，例如把引用里的软换行转 ``<br>``。
        anchor: 是否给每块套 ``<div class="md-block" data-line="N">``。
            浏览器里靠它做「预览跟随光标」，``N`` 是该块起始行的下标（从 0 起）。
        cache_size: 缓存多少个块的 HTML（LRU）。

    实例不是线程安全的；多线程使用请自行加锁（内置的实时预览服务就是这么做的）。
    """

    def __init__(self, options: Optional[Options] = None, *,
                 engine: Optional[object] = None,
                 post: Optional[Callable[[str], str]] = None,
                 anchor: bool = False,
                 cache_size: int = 2048) -> None:
        # 第一个位置参数既可以是 Options 也可以是 Engine：LivePreview(engine)
        # 是最顺手的写法，不该因为顺序问题悄悄把 Engine 当选项用。
        if engine is None and options is not None and not hasattr(options, "has"):
            engine, options = options, None
        if options is None and engine is not None:
            options = getattr(engine, "options", None)
        if options is None or not hasattr(options, "has"):
            options = Options()
        self.o = options
        self._post = post
        self._anchor = anchor
        self._parser = BlockParser(self.o)      # 复用：行内缓存挂在这里
        self._renderer = HtmlRenderer(self.o)
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        self._cache_size = max(16, int(cache_size))
        self._refs_sig: Optional[Tuple[Tuple[str, str], ...]] = None
        self._html = ""
        self._stats = RenderStats()

    # ------------------------------------------------------------ 属性
    @property
    def html(self) -> str:
        """最近一次的渲染结果。"""
        return self._html

    @property
    def stats(self) -> RenderStats:
        """最近一次的统计。"""
        return self._stats

    def invalidate(self) -> None:
        """清掉块缓存（换了渲染选项/主题后调用）。"""
        self._cache.clear()
        self._refs_sig = None

    # ------------------------------------------------------------ 渲染
    def update(self, source: str) -> str:
        """重新渲染，返回完整 HTML（与 ``Engine.to_html`` 逐字节一致）。"""
        t0 = time.perf_counter()
        text = normalize_source(source or "")

        if not text.strip():
            self.invalidate()
            self._parser.inline.clear_cache()
            self._html = ""
            self._stats = RenderStats(ms=(time.perf_counter() - t0) * 1000)
            return ""

        doc, spans = self._parser.parse_spans(text)

        # 引用定义变了，任何块的 HTML 都可能失效（[x] 可能指到别的地址）
        sig = tuple(sorted(self._parser.refs.items()))
        if sig != self._refs_sig:
            self._cache.clear()
            self._refs_sig = sig

        lines = text.split("\n")
        total = len(lines)
        pieces = []
        rendered = reused = 0

        for node, (start, end) in zip(doc.children, spans):
            # 键 = 块原文 + 紧跟其后的那一行。后面那行也要进键，是因为列表的
            # 「紧凑 / 松散」会看块外第一行：`- a` 后面若跟着缩进不同的列表项，
            # 这个列表就是松散的（`<li><p>`），同一段块原文能渲染出两种结果。
            after = lines[end] if end < total else ""
            key = "%s\x00%s" % ("\n".join(lines[start:end]), after)
            html = self._cache.get(key)
            if html is None:
                html = self._renderer.block(node)
                if self._post is not None and html:
                    html = self._post(html)
                self._cache[key] = html
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
                rendered += 1
            else:
                self._cache.move_to_end(key)
                reused += 1

            if not html:
                continue
            if self._anchor:
                html = '<div class="md-block" data-line="%d">%s</div>' % (
                    start, html.rstrip("\n"))
            pieces.append(html)

        body = "\n\n".join(pieces)
        out = body + "\n" if body else ""
        self._html = out
        self._stats = RenderStats(ms=(time.perf_counter() - t0) * 1000,
                                  blocks=len(doc.children), rendered=rendered,
                                  reused=reused, chars=len(text))
        return out
