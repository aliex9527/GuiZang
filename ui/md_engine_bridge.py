"""自研引擎 mdengine 与归藏的接入点（默认启用）。

自研 ``mdengine`` 是默认渲染引擎；第三方 ``markdown`` / ``html2text`` 保留为
兜底与对照，可用环境变量关掉自研引擎退回旧路径：

    Windows:  set GUICANG_MD_ENGINE=0  &&  python main.py
    macOS/Linux: GUICANG_MD_ENGINE=0 python main.py

两个出口分别对应归藏的两条渲染链：

* :func:`to_qt_html` —— 喂 ``QTextEdit.setHtml``：不要行内换行、不要着色，
  并且按 Qt 的脾气把 ``<pre>`` 的样式压平（见 ``ui.md_source._style_blocks``）。
* :func:`to_preview_html` —— 预览/导出：要着色（内联 style），别的与上面一致。

引擎不可用（没装、被裁掉）时 :func:`using_own` 恒为 False，老路径照跑。
"""

from __future__ import annotations

import os
import re

try:  # 引擎是仓库内的包，正常情况下一定在
    import mdengine
except Exception:  # noqa: BLE001 - 任何导入失败都退回第三方库，不能让界面起不来
    mdengine = None

ENV_NAME = "GUICANG_MD_ENGINE"
# 显式关掉自研引擎、退回第三方库的取值；其余（含空值）一律走自研引擎。
_FALSY = {"0", "off", "false", "no", "thirdparty", "third_party", "old"}

# Qt 这条路不需要着色（染色 span 会污染「HTML → Markdown」的反序列化），
# 但需要表格、任务项、高亮这些语法扩展。
QT_EXTENSIONS = {
    "setext", "fenced_code", "indented_code", "tables", "attr_list",
    "tasklist", "strike", "mark", "admonition", "html", "autolink",
}


def available() -> bool:
    """自研引擎是否可用。"""
    return mdengine is not None


def using_own() -> bool:
    """当前是否走自研引擎。

    引擎可用时**默认启用**；设 ``GUICANG_MD_ENGINE=0/off/false/no`` 可退回第三方库。
    """
    if mdengine is None:
        return False
    val = os.environ.get(ENV_NAME, "").strip().lower()
    if val in _FALSY:
        return False
    return True


def _quote_breaks(html: str) -> str:
    """引用内的软换行转 ``<br>``，但不要给 ``<p>`` 外侧添乱。

    第三方库输出的引用里是「裸文字 + 换行」，Qt 会把换行压成空格，所以要转
    ``<br>``；自研引擎输出的是 ``<p>`` 包着的块，只在块内部转，块与块之间
    什么都不加，否则引用里会多出空行。
    """
    def repl(m: re.Match) -> str:
        # 先 strip：捕获到的内容首尾是 "…>\n<p>" 这种，换行前面没有 ">"，
        # 不剥掉的话下面那条折叠规则匹配不到，结果会在 <p> 外面留下 <br>。
        inner = m.group(1).strip()
        inner = re.sub(r">\s*\n\s*<", "><", inner)
        return "<blockquote>" + inner.replace("\n", "<br>") + "</blockquote>"

    return re.sub(r"<blockquote>(.*?)</blockquote>", repl, html, flags=re.S)


def to_qt_html(source: str) -> str:
    """Markdown → 可塞进 QTextDocument 的 HTML。"""
    from ui.md_source import _style_blocks

    # task_style="glyph" 不能省：Qt 富文本不支持 <input>，用 input 画勾选框会被
    # 整体丢掉，保存时任务标记就消失了（旧路径同样是用 ☐/☑ 字形）。
    # mark_style="span" 同理：Qt 不认 <mark>，会连标签一起丢，`==高亮==` 存盘即丢。
    engine = mdengine.Engine(extensions=QT_EXTENSIONS, highlight=False,
                             task_style="glyph", mark_style="span")
    return _style_blocks(_quote_breaks(engine.to_html(source)))


def to_preview_html(source: str) -> str:
    """Markdown → 预览/导出用的 HTML（带代码着色）。"""
    html = _preview_engine().to_html(source)
    # 预览的 CSS 里 pre 已经给了底色，这里只把 Qt 不认的 class 清掉
    return _strip_pre_class(html)


# --------------------------------------------------------------- 预览引擎
# 引擎构造一次就够：它只存选项，解析器每次调用新建。以前每条笔记、每次刷新
# 都新建一个 Engine，白付了一遍选项构造的钱。

_PREVIEW_OPTIONS = dict(
    extensions=QT_EXTENSIONS | {"codehilite"},
    highlight=True, noclasses=True, hl_style="friendly",
    task_style="glyph", mark_style="span",
)

_engine_cache: dict = {}
_live_cache: dict = {}


def _preview_engine():
    eng = _engine_cache.get("preview")
    if eng is None:
        eng = mdengine.Engine(**_PREVIEW_OPTIONS)
        _engine_cache["preview"] = eng
    return eng


def _strip_pre_class(html: str) -> str:
    return re.sub(r'<pre class="highlight">', "<pre>", html)


def live_preview() -> "mdengine.LivePreview":
    """编辑器预览用的增量渲染器（进程内单例）。

    与 :func:`to_preview_html` 输出完全一致，但只重排改动过的块——打字时
    不用把整篇重新解析渲染一遍。缓存键是块原文，跨笔记复用没有副作用。
    """
    live = _live_cache.get("preview")
    if live is None:
        live = _preview_engine().live(post=_strip_pre_class)
        _live_cache["preview"] = live
    return live


def live_preview_html(source: str) -> str:
    """Markdown → 预览 HTML，走增量渲染。"""
    return live_preview().update(source)


def preview_stats() -> dict:
    """最近一次增量渲染的统计（块数/复用数/耗时），调试与自测用。"""
    live = _live_cache.get("preview")
    return live.stats.as_dict() if live is not None else {}


def html_to_markdown(html: str) -> str:
    """HTML → Markdown。"""
    return mdengine.to_markdown(html)
