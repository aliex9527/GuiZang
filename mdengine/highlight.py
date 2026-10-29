"""轻量语法高亮。

不追求 Pygments 的词法精度，只做「够用且不会崩」的着色：

* 每种语言是一张 ``(token, 正则)`` 的有序表，按顺序在当前位置尝试匹配，
  先命中先着色。顺序即优先级，所以「注释/字符串」永远排在最前面。
* 匹配失败就吞一个字符当普通文本，保证线性推进、不会回溯爆炸。
* 未知语言直接转义输出，不报错。

配色内置 ``friendly``（Pygments friendly 的近似）、``github``、``monokai``
三套，够覆盖归藏的亮/暗主题。
"""

from __future__ import annotations

import re
from html import escape
from typing import Dict, List, Optional, Sequence, Tuple

# token → (颜色, 附加样式)
STYLES: Dict[str, Dict[str, Tuple[str, str]]] = {
    "friendly": {
        "kw": ("#007020", "font-weight:600"),
        "str": ("#4070a0", ""),
        "num": ("#40a070", ""),
        "com": ("#60a0b0", "font-style:italic"),
        "fn": ("#06287e", ""),
        "cls": ("#0e84b5", "font-weight:600"),
        "op": ("#666666", ""),
        "punct": ("#666666", ""),
        "tag": ("#062873", "font-weight:600"),
        "attr": ("#4070a0", ""),
        "builtin": ("#007020", ""),
        "decorator": ("#555555", ""),
        "key": ("#007020", "font-weight:600"),
        "bool": ("#40a070", ""),
        "ins": ("#1a7f37", ""),
        "del": ("#cf222e", ""),
        "hdr": ("#005cc5", "font-weight:600"),
    },
    "github": {
        "kw": ("#d73a49", ""),
        "str": ("#032f62", ""),
        "num": ("#005cc5", ""),
        "com": ("#6a737d", "font-style:italic"),
        "fn": ("#6f42c1", ""),
        "cls": ("#6f42c1", "font-weight:600"),
        "op": ("#d73a49", ""),
        "punct": ("#24292e", ""),
        "tag": ("#22863a", ""),
        "attr": ("#6f42c1", ""),
        "builtin": ("#005cc5", ""),
        "decorator": ("#6f42c1", ""),
        "key": ("#005cc5", ""),
        "bool": ("#005cc5", ""),
        "ins": ("#22863a", ""),
        "del": ("#b31d28", ""),
        "hdr": ("#005cc5", "font-weight:600"),
    },
    "monokai": {
        "kw": ("#f92672", ""),
        "str": ("#e6db74", ""),
        "num": ("#ae81ff", ""),
        "com": ("#75715e", "font-style:italic"),
        "fn": ("#a6e22e", ""),
        "cls": ("#66d9ef", ""),
        "op": ("#f92672", ""),
        "punct": ("#f8f8f2", ""),
        "tag": ("#f92672", ""),
        "attr": ("#a6e22e", ""),
        "builtin": ("#66d9ef", ""),
        "decorator": ("#a6e22e", ""),
        "key": ("#66d9ef", ""),
        "bool": ("#ae81ff", ""),
        "ins": ("#a6e22e", ""),
        "del": ("#f92672", ""),
        "hdr": ("#e6db74", "font-weight:600"),
    },
}

# ---------------------------------------------------------------- 词法规则

_PY = [
    ("com", r"#[^\n]*"),
    ("str", r"(?i:[rubf]{0,2})(?:'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\")"),
    ("decorator", r"@[\w.]+"),
    ("kw", r"\b(?:def|class|return|yield|if|elif|else|for|while|break|continue|pass|try|except|finally|raise|with|as|import|from|lambda|global|nonlocal|assert|del|in|is|not|and|or|async|await|match|case|None|True|False)\b"),
    ("bool", r"\b(?:True|False|None)\b"),
    ("num", r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?j?)\b"),
    ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
    ("cls", r"\b[A-Z][A-Za-z0-9_]*\b"),
    ("builtin", r"\b(?:self|cls|print|len|range|str|int|float|list|dict|set|tuple|open|super|type|isinstance|enumerate|zip|map|filter|sorted|sum|min|max|any|all)\b"),
    ("op", r"[+\-*/%=<>!&|^~@]+"),
    ("punct", r"[\(\)\[\]\{\},.:;]"),
]

_JS = [
    ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
    ("str", r"`(?:\\[\s\S]|[^`\\])*`|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\""),
    ("kw", r"\b(?:var|let|const|function|class|extends|new|delete|typeof|instanceof|return|if|else|for|while|do|switch|case|break|continue|try|catch|finally|throw|async|await|yield|import|export|from|default|in|of|this|super|void|null|undefined|true|false)\b"),
    ("bool", r"\b(?:true|false|null|undefined|NaN)\b"),
    ("num", r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b"),
    ("fn", r"\b[A-Za-z_$][\w$]*(?=\s*\()"),
    ("cls", r"\b[A-Z][A-Za-z0-9_$]*\b"),
    ("op", r"[+\-*/%=<>!&|^~?]+"),
    ("punct", r"[\(\)\[\]\{\},.:;]"),
]

_JSON = [
    ("key", r"\"(?:\\.|[^\"\\])*\"(?=\s*:)"),
    ("str", r"\"(?:\\.|[^\"\\])*\""),
    ("num", r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
    ("bool", r"\b(?:true|false|null)\b"),
    ("punct", r"[{}\[\],:]"),
]

_YAML = [
    ("com", r"#[^\n]*"),
    ("key", r"(?m)^[ \t-]*[\w.\-/]+(?=\s*:)"),
    ("str", r"'(?:''|[^'])*'|\"(?:\\.|[^\"\\])*\""),
    ("bool", r"\b(?:true|false|null|yes|no|on|off|True|False|Null)\b"),
    ("num", r"\b-?\d+(?:\.\d+)?\b"),
    ("punct", r"[:\[\]{},|>&*!%@`]"),
]

_HTML = [
    ("com", r"<!--[\s\S]*?-->"),
    ("str", r"\"[^\"]*\"|'[^']*'"),
    ("tag", r"</?[A-Za-z][\w:\-]*"),
    ("attr", r"\b[A-Za-z_:][\w:.\-]*(?=\s*=)"),
    ("punct", r"[<>/=]"),
]

_CSS = [
    ("com", r"/\*[\s\S]*?\*/"),
    ("str", r"\"[^\"]*\"|'[^']*'"),
    ("kw", r"@[\w\-]+"),
    ("attr", r"[-a-zA-Z]+(?=\s*:)"),
    ("num", r"#[0-9a-fA-F]{3,8}\b|\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg|pt)?\b"),
    ("fn", r"\b[a-z\-]+(?=\()"),
    ("punct", r"[{}:;,>~+]"),
]

_SH = [
    ("com", r"#[^\n]*"),
    ("str", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("kw", r"\b(?:if|then|else|elif|fi|for|while|do|done|case|esac|function|return|in|export|local|readonly|source|alias|set|unset|shift|exit)\b"),
    ("builtin", r"\$\{?[\w@#?*$!-]+\}?|\b(?:echo|cd|ls|cat|grep|sed|awk|find|mkdir|rm|cp|mv|chmod|curl|git|python|pip|npm|node|make)\b"),
    ("num", r"\b\d+\b"),
    ("op", r"[|&;<>()]+"),
]

_SQL = [
    ("com", r"--[^\n]*|/\*[\s\S]*?\*/"),
    ("str", r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\""),
    ("kw", r"\b(?i:select|from|where|insert|into|values|update|set|delete|create|table|alter|drop|index|join|left|right|inner|outer|on|group|by|order|having|limit|offset|union|all|distinct|as|and|or|not|null|is|in|exists|case|when|then|else|end|primary|key|foreign|references|default|int|integer|text|varchar|datetime|boolean)\b"),
    ("num", r"\b\d+(?:\.\d+)?\b"),
    ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
    ("op", r"[+\-*/%=<>!]+"),
    ("punct", r"[(),.;]"),
]

_C = [
    ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
    ("str", r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\""),
    ("hdr", r"(?m)^[ \t]*#[ \t]*\w+.*$"),
    ("kw", r"\b(?:auto|break|case|char|const|continue|default|do|double|else|enum|extern|float|for|goto|if|inline|int|long|register|return|short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|volatile|while|class|public|private|protected|new|delete|namespace|template|using|try|catch|throw|package|import|interface|extends|implements|func|var|let|fn|impl|trait|pub|use|mod|match|loop|mut|package|go|defer|chan|select|type|range)\b"),
    ("bool", r"\b(?:true|false|nullptr|NULL|None|True|False|nil)\b"),
    ("num", r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?[fFlLuU]*)\b"),
    ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
    ("cls", r"\b[A-Z][A-Za-z0-9_]*\b"),
    ("op", r"[+\-*/%=<>!&|^~?:]+"),
    ("punct", r"[\(\)\[\]\{\},;.]"),
]

_DIFF = [
    ("hdr", r"(?m)^(?:diff|index|---|\+\+\+|@@).*$"),
    ("ins", r"(?m)^\+.*$"),
    ("del", r"(?m)^-.*$"),
]

_INI = [
    ("com", r"[#;][^\n]*"),
    ("hdr", r"(?m)^\[[^\]\n]*\]"),
    ("key", r"(?m)^[\w.\-]+(?=\s*=)"),
    ("str", r"\"[^\"]*\"|'[^']*'"),
    ("bool", r"\b(?:true|false|yes|no|on|off)\b"),
    ("num", r"\b-?\d+(?:\.\d+)?\b"),
    ("op", r"="),
]

_SPECS: Dict[str, Sequence[Tuple[str, str]]] = {
    "python": _PY, "py": _PY, "python3": _PY,
    "javascript": _JS, "js": _JS, "jsx": _JS, "typescript": _JS, "ts": _JS, "tsx": _JS,
    "json": _JSON, "json5": _JSON,
    "yaml": _YAML, "yml": _YAML, "toml": _INI, "ini": _INI, "conf": _INI, "cfg": _INI,
    "html": _HTML, "xml": _HTML, "svg": _HTML, "vue": _HTML, "htm": _HTML,
    "css": _CSS, "scss": _CSS, "less": _CSS,
    "bash": _SH, "sh": _SH, "shell": _SH, "zsh": _SH, "console": _SH,
    "sql": _SQL, "mysql": _SQL, "postgresql": _SQL, "sqlite": _SQL,
    "c": _C, "h": _C, "cpp": _C, "c++": _C, "cc": _C, "hpp": _C, "java": _C,
    "cs": _C, "csharp": _C, "go": _C, "golang": _C, "rust": _C, "rs": _C,
    "kotlin": _C, "kt": _C, "swift": _C, "php": _C, "scala": _C, "dart": _C,
    "objc": _C, "zig": _C,
    "diff": _DIFF, "patch": _DIFF,
}

_ALIASES = {
    "text": "", "plain": "", "plaintext": "", "txt": "", "": "",
    "golang": "go",
}


def languages() -> List[str]:
    """已支持的语言名（去重排序）。"""
    return sorted({name for name in _SPECS})


def supports(lang: Optional[str]) -> bool:
    return bool(lang) and lang.lower() in _SPECS


def _spec_for(lang: Optional[str]) -> Optional[Sequence[Tuple[str, str]]]:
    if not lang:
        return None
    key = lang.strip().lower()
    key = _ALIASES.get(key, key)
    if not key:
        return None
    return _SPECS.get(key)


def _render_span(token: str, body: str, palette: Dict[str, Tuple[str, str]],
                 noclasses: bool) -> str:
    color, extra = palette.get(token, ("", ""))
    if not color:
        return body
    if noclasses:
        style = "color:%s" % color
        if extra:
            style += ";" + extra
        return '<span style="%s">%s</span>' % (style, body)
    return '<span class="tok-%s">%s</span>' % (token, body)


def style_css(style: str = "friendly", prefix: str = "tok-") -> str:
    """把配色导出成 CSS（``noclasses=False`` 时需要，浏览器页面/预览共用）。

    Args:
        style: ``friendly`` / ``github`` / ``monokai``。
        prefix: class 前缀，与 :func:`highlight_code` 输出的 ``tok-xxx`` 对应。
    """
    palette = STYLES.get(style) or STYLES["friendly"]
    rows: List[str] = []
    for token, (color, extra) in palette.items():
        if not color:
            continue
        decl = "color:%s" % color
        if extra:
            decl += ";" + extra
        rows.append(".%s%s { %s; }" % (prefix, token, decl))
    return "\n".join(rows)


def highlight_code(code: str, lang: Optional[str] = None, style: str = "friendly",
                   noclasses: bool = True) -> str:
    """把源码着色成 HTML 片段（已转义）。

    Args:
        code: 源码。
        lang: 语言名，未知或空则只做转义。
        style: ``friendly`` / ``github`` / ``monokai``。
        noclasses: True 写内联 style，False 写 ``class="tok-xxx"``。
    """
    specs = _spec_for(lang)
    if not specs:
        return escape(code)

    palette = STYLES.get(style) or STYLES["friendly"]
    compiled = [(token, re.compile(pattern, re.MULTILINE)) for token, pattern in specs]

    out: List[str] = []
    plain: List[str] = []

    def flush() -> None:
        if plain:
            out.append(escape("".join(plain)))
            plain.clear()

    i, n = 0, len(code)
    while i < n:
        matched = False
        for token, rx in compiled:
            m = rx.match(code, i)
            if m is not None and m.end() > i:
                flush()
                out.append(_render_span(token, escape(m.group(0)), palette, noclasses))
                i = m.end()
                matched = True
                break
        if not matched:
            plain.append(code[i])
            i += 1
    flush()
    return "".join(out)
