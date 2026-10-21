"""Markdown ⇄ HTML 转换，供编辑器预览与导出复用。"""

from __future__ import annotations

import re
from typing import List

import html2text
import markdown

_TASK_RE = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+", re.M)
_FENCE_RE = re.compile(r"<pre>", re.I)
_HL_RE = re.compile(r"==(?=\S)(.+?)(?<=\S)==")
_CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
_FENCE_SPLIT_RE = re.compile(r"(```.*?(?:```|\Z))", re.S)

def preview_css() -> str:
    """编辑器正文（以及预览）使用的 CSS，随主题变化。"""
    from ui.theme import P
    return f"""
body {{ font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 11pt;
       color: {P['note_text']}; }}
p {{ margin: 0 0 8px 0; line-height: 1.7; }}
h1 {{ font-size: 24.75pt; font-weight: 700; line-height: 1.2; margin: 16px 0; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
h2 {{ font-size: 19.25pt; font-weight: 700; line-height: 1.225; margin: 16px 0; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
h3 {{ font-size: 16.5pt; font-weight: 700; line-height: 1.43; margin: 16px 0; }}
h4 {{ font-size: 13.75pt; font-weight: 700; margin: 16px 0; }}
h5 {{ font-size: 11pt; font-weight: 700; margin: 16px 0; }}
h6 {{ font-size: 11pt; font-weight: 700; margin: 16px 0; color: #777; }}
ul, ol {{ margin: 4px 0 10px 0; }}
li {{ margin: 2px 0; line-height: 1.65; }}
code {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 10pt;
        background-color: {P['inline_bg']}; color: {P['inline_text']}; }}
pre {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 10pt;
       background-color: {P['code_bg']}; color: {P['code_text']}; }}
blockquote {{ color: {P['quote_text']}; background-color: {P['quote_bg']}; margin: 8px 0; }}
a {{ color: {P['link']}; text-decoration: none; }}
hr {{ color: {P['border']}; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
th {{ background-color: {P['table_head_bg']}; font-weight: 700; }}
th, td {{ border: 1px solid {P['border']}; }}
img {{ max-width: 100%; }}
strong {{ font-weight: 700; }}
mark {{ background-color: #fff59d; color: {P['note_text']}; padding: 0 2px; }}
"""


def _md_engine() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=["extra", "sane_lists", "nl2br", "admonition", "codehilite"],
        extension_configs={
            "codehilite": {
                "noclasses": True,
                "pygments_style": "friendly",
                "guess_lang": False,
                "cssclass": "highlight",
            }
        },
        output_format="html",
    )


def _preprocess_task_lists(source: str) -> str:
    def repl(m: re.Match) -> str:
        indent, mark = m.group(1), m.group(2)
        return f"{indent}- {'☑' if mark.lower() == 'x' else '☐'} "
    return _TASK_RE.sub(repl, source)


def _hl_outside_code(seg: str) -> str:
    """把 ==高亮== 换成 <mark>，跳过行内代码 `...`。"""
    out, last = [], 0
    for m in _CODE_SPAN_RE.finditer(seg):
        out.append(_HL_RE.sub(r"<mark>\1</mark>", seg[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_HL_RE.sub(r"<mark>\1</mark>", seg[last:]))
    return "".join(out)


def _preprocess_highlight(source: str) -> str:
    """==高亮== → <mark>；围栏代码块（```）内不动。"""
    parts = _FENCE_SPLIT_RE.split(source)
    for i, seg in enumerate(parts):
        if i % 2 == 0:  # 偶数段是普通文本，奇数段是围栏代码块
            parts[i] = "\n".join(_hl_outside_code(line) for line in seg.split("\n"))
    return "".join(parts)


def md_to_html(source: str) -> str:
    """Markdown 源码 → HTML 片段（已内联代码高亮配色）。"""
    if not source or not source.strip():
        return ""
    try:
        engine = _md_engine()
        html = engine.convert(_preprocess_task_lists(_preprocess_highlight(source)))
    except Exception:  # noqa: BLE001 - 渲染失败时退回纯文本，避免编辑器崩
        from html import escape
        html = "<pre>" + escape(source) + "</pre>"
    from ui.theme import P
    html = html.replace('<div class="highlight">', "<div>")
    html = _FENCE_RE.sub(f'<pre style="background-color:{P["code_bg"]};">', html)
    return html


def html_to_md(html: str) -> str:
    """富文本 HTML → Markdown，保留链接与 gzs 内嵌图片。"""
    if not html or not html.strip():
        return ""
    conv = html2text.HTML2Text(baseurl="")
    conv.body_width = 0
    conv.ignore_links = False
    conv.ignore_images = False
    conv.ignore_emphasis = False
    conv.single_line_break = False
    conv.protect_links = True
    conv.unicode_snob = True
    try:
        md = conv.handle(html)
    except Exception:  # noqa: BLE001
        return ""
    md = md.replace("\\_", "_").replace("\\*", "*")
    md = re.sub(r"^(\s*)[*+-]\s+", lambda m: ("  " * (len(m.group(1)) // 2)) + "- ", md, flags=re.M)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md + "\n"


def render_preview(source: str) -> str:
    return md_to_html(source)
