"""命令行：``python -m mdengine``。

    python -m mdengine README.md                 # 输出 HTML 片段
    python -m mdengine README.md --standalone -o out.html
    python -m mdengine page.html --reverse       # HTML → Markdown
    python -m mdengine README.md --serve         # 实时预览编辑器（左写右看）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import Engine, __version__
from .options import DEFAULT_EXTENSIONS

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ max-width: 860px; margin: 40px auto; padding: 0 20px;
       font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
       font-size: 16px; line-height: 1.7; color: #24292f; }}
h1, h2 {{ border-bottom: 1px solid #eaecef; padding-bottom: .3em; }}
pre {{ background: #f6f8fa; padding: 14px; overflow-x: auto; border-radius: 6px; }}
code {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 90%; }}
:not(pre) > code {{ background: rgba(27,31,35,.06); padding: .2em .4em; border-radius: 4px; }}
blockquote {{ margin: 0; padding: 0 1em; color: #6a737d; border-left: .25em solid #dfe2e5; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #dfe2e5; padding: 6px 12px; }}
th {{ background: #f6f8fa; }}
img {{ max-width: 100%; }}
mark {{ background: #fff59d; }}
.tok-kw {{ color: #007020; font-weight: 600; }}
.tok-str {{ color: #4070a0; }}
.tok-com {{ color: #60a0b0; font-style: italic; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _read(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    data = sys.stdin.buffer.read()
    return data.decode("utf-8", "replace")


def _write(text: str, path: Optional[str]) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")
        return
    stream = sys.stdout
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    stream.write(text)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mdengine", description="自研 Markdown 引擎（双向 + 代码高亮）")
    ap.add_argument("input", nargs="?", help="输入文件；省略则从 stdin 读")
    ap.add_argument("-o", "--output", help="输出文件；省略则打印到 stdout")
    ap.add_argument("--reverse", action="store_true", help="反向：HTML → Markdown")
    ap.add_argument("--standalone", action="store_true", help="包成完整 HTML 页面")
    ap.add_argument("--title", default="mdengine", help="--standalone 的页面标题")
    ap.add_argument("--no-highlight", action="store_true", help="关闭代码着色")
    ap.add_argument("--style", default="friendly", help="着色主题：friendly/github/monokai")
    ap.add_argument("--classes", action="store_true", help="着色用 class 而不是内联 style")
    ap.add_argument("--nl2br", action="store_true", help="单个换行转为 <br>")
    ap.add_argument("--keep", action="append", default=[], metavar="EXT",
                    help="只保留指定扩展（可重复）")
    ap.add_argument("--drop", action="append", default=[], metavar="EXT",
                    help="关闭指定扩展（可重复）")
    ap.add_argument("--serve", action="store_true",
                    help="启动实时预览编辑器（本地网页，边写边看）")
    ap.add_argument("--port", type=int, default=8137,
                    help="--serve 的端口（默认 8137，0 表示自动分配）")
    ap.add_argument("--open", action="store_true", help="--serve 启动后打开浏览器")
    ap.add_argument("--version", action="version", version="mdengine " + __version__)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.serve:
        if args.output:
            build_parser().error("--serve 与 -o 不能同时用")
        from .server import serve
        try:
            return serve(args.input, port=args.port, open_browser=args.open,
                         style=args.style, highlight=not args.no_highlight)
        except OSError as exc:
            print("无法启动服务：%s" % exc, file=sys.stderr)
            return 1

    source = _read(args.input)

    if args.reverse:
        engine = Engine()
        _write(engine.to_markdown(source), args.output)
        return 0

    extensions = set(DEFAULT_EXTENSIONS)
    if args.keep:
        extensions = set(args.keep)
    for name in args.drop:
        extensions.discard(name)

    engine = Engine(extensions=extensions,
                    nl2br=args.nl2br,
                    highlight=not args.no_highlight,
                    noclasses=not args.classes,
                    hl_style=args.style)
    html = engine.to_html(source)

    if args.standalone:
        html = PAGE.format(title=args.title, body=html.rstrip("\n"))
    _write(html, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
