"""本地实时预览服务：``python -m mdengine --serve [文件]``。

只用标准库（``http.server``），把引擎包成一个「左写右看」的编辑器：

* 每次输入把整篇源码 POST 到 ``/render``，服务端用 :class:`LivePreview`
  增量渲染（只重排改动的块），把 HTML 回给页面；
* 页面按块的 ``data-line`` 找到光标所在块，让预览跟着光标滚——这是「实时
  预览」真正要解决的问题，不然每次重排都把阅读位置顶回顶部；
* Ctrl+S 原地写回文件（原子替换），没有指定文件时只预览不落盘。

默认只监听 ``127.0.0.1``：这是给本机写作用的东西，不该暴露到局域网。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import Engine, __version__
from .highlight import style_css
from .live import LivePreview

MAX_BODY = 8 * 1024 * 1024        # 8 MB，超了直接拒掉，别把内存吃光

DEMO = """# mdengine 实时预览

左边随便写，右边立刻变。**不会**每次重排整篇：改动的那一块重排，其余复用上一轮的 HTML。

## 为什么快

| 优化 | 做法 |
| --- | --- |
| 行内解析记忆化 | 没改动的段落直接命中缓存 |
| 块级渲染缓存 | 以块的原文为键，改哪块重排哪块 |
| 增量统计 | 页面右上角显示耗时与复用块数 |

## 语法都在

- 行内：**粗体**、*斜体*、~~删除线~~、==高亮==、`code()`
- 任务：`- [x]` / `- [ ]`
- 表格对齐、代码着色、引用、admonition

```python
def preview(source: str) -> str:
    \"\"\"边写边看。\"\"\"
    return LivePreview(Engine()).update(source)
```

> 提示：Ctrl+S 保存，Tab 缩进四格，Ctrl+B / I 加粗斜体。

!!! note "跟随光标"
    右上角「跟随光标」勾着时，预览会滚到光标所在的块。
"""

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mdengine 实时预览 · __NAME__</title>
<style>
:root {
  --bg: #ffffff; --panel: #fbfbfd; --line: #e6e8ec; --text: #1f2328;
  --muted: #8b939e; --accent: #2f6feb; --code-bg: #f6f8fa; --mark: #fff59d;
  --shadow: 0 1px 2px rgba(16,24,40,.06), 0 4px 12px rgba(16,24,40,.04);
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  display: flex; flex-direction: column; color: var(--text); background: var(--bg);
  font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif;
  font-size: 15px; -webkit-font-smoothing: antialiased;
}
header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  height: 46px; padding: 0 14px; border-bottom: 1px solid var(--line);
  background: var(--panel); flex: 0 0 auto;
}
.brand { display: flex; align-items: center; gap: 9px; min-width: 0; }
.logo {
  width: 22px; height: 22px; border-radius: 6px; background: var(--accent);
  color: #fff; font: 600 12px/22px ui-monospace, monospace; text-align: center;
  flex: 0 0 auto;
}
.name { font-weight: 600; font-size: 13.5px; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis; }
#state { font-size: 12px; color: var(--muted); white-space: nowrap; }
#state.dirty { color: #b26a00; }
.tools { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
#stats { font: 12px ui-monospace, "Cascadia Mono", monospace; color: var(--muted); }
label.chk { display: flex; align-items: center; gap: 5px; font-size: 12.5px;
            color: var(--muted); cursor: pointer; user-select: none; }
button {
  font: inherit; font-size: 12.5px; padding: 5px 11px; border-radius: 7px;
  border: 1px solid var(--line); background: #fff; color: var(--text); cursor: pointer;
}
button:hover { border-color: #c9ced6; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:hover { filter: brightness(1.06); }
main { flex: 1 1 auto; display: flex; min-height: 0; }
.pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
#left { flex: 0 0 50%; border-right: 1px solid var(--line); }
.pane-head {
  display: flex; align-items: center; justify-content: space-between;
  height: 30px; padding: 0 12px; font-size: 11.5px; letter-spacing: .04em;
  color: var(--muted); background: var(--panel); border-bottom: 1px solid var(--line);
  flex: 0 0 auto; text-transform: uppercase;
}
#pos { font: 11.5px ui-monospace, monospace; text-transform: none; letter-spacing: 0; }
#divider { width: 5px; margin: 0 -2px; cursor: col-resize; flex: 0 0 auto;
           position: relative; z-index: 2; }
#divider:hover::after, #divider.active::after {
  content: ""; position: absolute; inset: 0 1px; background: var(--accent); opacity: .35;
  border-radius: 2px;
}
textarea {
  flex: 1 1 auto; width: 100%; min-height: 0; resize: none; border: 0; outline: 0;
  padding: 18px 20px 40vh; background: var(--bg); color: var(--text);
  font: 13.5px/1.75 ui-monospace, "Cascadia Mono", "JetBrains Mono", Consolas, monospace;
  tab-size: 4; white-space: pre-wrap; overflow-wrap: break-word;
}
#preview {
  flex: 1 1 auto; overflow: auto; position: relative; padding: 22px 26px 40vh;
  line-height: 1.72; scroll-behavior: auto;
}
.md-block { border-radius: 4px; transition: background .2s; }
.md-block.flash { background: #eef4ff; }
#preview > :first-child { margin-top: 0; }
#preview h1, #preview h2, #preview h3, #preview h4, #preview h5, #preview h6 {
  line-height: 1.3; margin: 1.5em 0 .6em; font-weight: 650;
}
#preview h1 { font-size: 1.7em; padding-bottom: .3em; border-bottom: 1px solid var(--line); }
#preview h2 { font-size: 1.36em; padding-bottom: .25em; border-bottom: 1px solid var(--line); }
#preview h3 { font-size: 1.16em; }
#preview p { margin: .75em 0; }
#preview a { color: var(--accent); text-decoration: none; }
#preview a:hover { text-decoration: underline; }
#preview blockquote {
  margin: .9em 0; padding: .1em 1em; color: #57606a;
  border-left: .25em solid #d8dee4; background: #fafbfc;
}
#preview ul, #preview ol { padding-left: 1.6em; margin: .7em 0; }
#preview li { margin: .25em 0; }
#preview code {
  font: .9em ui-monospace, "Cascadia Mono", Consolas, monospace;
  background: rgba(27,31,35,.055); padding: .16em .4em; border-radius: 5px;
}
#preview pre {
  margin: .9em 0; padding: 14px 16px; overflow: auto; background: var(--code-bg);
  border: 1px solid var(--line); border-radius: 9px; line-height: 1.6;
}
#preview pre code { background: none; padding: 0; font-size: 12.8px; }
#preview table { border-collapse: collapse; margin: .9em 0; font-size: .95em; }
#preview th, #preview td { border: 1px solid var(--line); padding: 6px 13px; }
#preview th { background: var(--panel); font-weight: 600; }
#preview img { max-width: 100%; border-radius: 8px; }
#preview hr { border: 0; border-top: 1px solid var(--line); margin: 1.6em 0; }
#preview mark { background: var(--mark); }
#preview .admonition {
  margin: .9em 0; padding: 10px 14px; border-left: 3px solid var(--accent);
  background: #f5f8ff; border-radius: 0 8px 8px 0;
}
#preview .admonition-title { margin: 0 0 .35em; font-weight: 600; color: var(--accent); }
#preview input[type=checkbox] { margin-right: .4em; }
.empty { color: var(--muted); }
kbd {
  font: 11px ui-monospace, monospace; border: 1px solid var(--line); border-bottom-width: 2px;
  border-radius: 4px; padding: 1px 5px; background: #fff;
}
__STYLE_CSS__
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="logo">M</div>
    <span class="name">__NAME__</span>
    <span id="state">已保存</span>
  </div>
  <div class="tools">
    <span id="stats">—</span>
    <label class="chk"><input type="checkbox" id="follow" checked> 跟随光标</label>
    <button id="reload">重新载入</button>
    <button id="save" class="primary">保存</button>
  </div>
</header>
<main>
  <section class="pane" id="left">
    <div class="pane-head"><span>Markdown</span><span id="pos">1:1</span></div>
    <textarea id="src" spellcheck="false" autocomplete="off"></textarea>
  </section>
  <div id="divider"></div>
  <section class="pane" id="right">
    <div class="pane-head"><span>预览</span><span>mdengine __VERSION__</span></div>
    <div id="preview"></div>
  </section>
</main>
<script>
const INITIAL = __SOURCE__;
const HAS_FILE = __FILE__;
const ta = document.getElementById('src');
const pv = document.getElementById('preview');
const statsEl = document.getElementById('stats');
const stateEl = document.getElementById('state');
const posEl = document.getElementById('pos');
const followEl = document.getElementById('follow');
let seq = 0, timer = null, dirty = false;

function setState() {
  if (!HAS_FILE) { stateEl.textContent = '仅预览'; stateEl.className = ''; return; }
  stateEl.textContent = dirty ? '未保存' : '已保存';
  stateEl.className = dirty ? 'dirty' : '';
}

function caretLine() {
  const v = ta.value, pos = ta.selectionStart;
  let line = 0, last = -1;
  for (let i = 0; i < pos; i++) if (v.charCodeAt(i) === 10) { line++; last = i; }
  posEl.textContent = (line + 1) + ':' + (pos - last);
  return line;
}

function scrollToCaret() {
  const line = caretLine();
  let target = null;
  for (const el of pv.children) {
    const n = parseInt(el.dataset.line, 10);
    if (!isNaN(n) && n <= line) target = el; else break;
  }
  if (!target) return;
  const top = target.offsetTop, h = pv.clientHeight;
  if (top < pv.scrollTop || top > pv.scrollTop + h - 80) {
    pv.scrollTop = Math.max(0, top - 16);
    target.classList.add('flash');
    setTimeout(() => target.classList.remove('flash'), 450);
  }
}

async function render() {
  const my = ++seq;
  const body = ta.value;
  let data;
  try {
    const res = await fetch('render', {method: 'POST', body: body});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    data = await res.json();
  } catch (err) {
    statsEl.textContent = '渲染失败：' + err.message;
    return;
  }
  if (my !== seq) return;                      // 已有更新的输入，丢弃旧结果
  const oldTop = pv.scrollTop;
  const oldMax = Math.max(1, pv.scrollHeight - pv.clientHeight);
  pv.innerHTML = data.html || '<p class="empty">（空文档）</p>';
  if (followEl.checked) {
    scrollToCaret();
  } else {
    const max = Math.max(1, pv.scrollHeight - pv.clientHeight);
    pv.scrollTop = (oldTop / oldMax) * max;
  }
  statsEl.textContent = data.stats.ms.toFixed(1) + ' ms · 复用 ' +
                        data.stats.reused + '/' + data.stats.blocks;
}

function schedule() {
  dirty = true; setState();
  clearTimeout(timer);
  timer = setTimeout(render, 80);
}

async function save() {
  if (!HAS_FILE) return;
  clearTimeout(timer);
  const res = await fetch('save', {method: 'POST', body: ta.value});
  const data = await res.json();
  if (data.ok) { dirty = false; setState(); }
  else { stateEl.textContent = '保存失败'; stateEl.className = 'dirty'; }
}

async function reload() {
  const res = await fetch('reload');
  const data = await res.json();
  ta.value = data.source;
  dirty = false; setState();
  render();
}

ta.addEventListener('input', schedule);
ta.addEventListener('click', caretLine);
ta.addEventListener('keyup', (e) => { if (e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End') caretLine(); });
ta.addEventListener('keydown', (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
  if (mod && ['b', 'i', 'k', 'e'].includes(e.key.toLowerCase())) {
    e.preventDefault();
    const wraps = {b: '**', i: '*', k: '`', e: '=='};
    const mark = wraps[e.key.toLowerCase()];
    const s = ta.selectionStart, t = ta.selectionEnd;
    const sel = ta.value.slice(s, t);
    ta.setRangeText(mark + sel + mark, s, t, 'select');
    ta.selectionStart = s + mark.length;
    ta.selectionEnd = t + mark.length;
    schedule();
    return;
  }
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = ta.selectionStart;
    if (e.shiftKey) {
      const base = ta.value.lastIndexOf('\\n', s - 1) + 1;
      const cut = ta.value.slice(base, base + 4).match(/^ +/);
      if (cut) ta.setRangeText('', base, base + cut[0].length, 'preserve');
    } else {
      ta.setRangeText('    ', s, ta.selectionEnd, 'end');
    }
    schedule();
  }
});
document.getElementById('save').addEventListener('click', save);
document.getElementById('reload').addEventListener('click', reload);
followEl.addEventListener('change', () => { if (followEl.checked) scrollToCaret(); });

// 左右分栏拖动
const divider = document.getElementById('divider');
const left = document.getElementById('left');
let dragging = false;
divider.addEventListener('mousedown', (e) => {
  dragging = true; divider.classList.add('active');
  document.body.style.cursor = 'col-resize'; e.preventDefault();
});
window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  const pct = Math.min(80, Math.max(20, (e.clientX / window.innerWidth) * 100));
  left.style.flexBasis = pct + '%';
});
window.addEventListener('mouseup', () => {
  dragging = false; divider.classList.remove('active'); document.body.style.cursor = '';
});

ta.value = INITIAL;
setState();
render();
ta.focus();
ta.selectionStart = ta.selectionEnd = 0;
</script>
</body>
</html>
"""


def _js_json(text: str) -> str:
    """把文本安全地嵌进 ``<script>`` 里的 JSON 字面量。

    中文不转义（页面是 UTF-8，转成 ``\\uXXXX`` 只是让人读不了）；``</`` 要拆开，
    否则文件里出现 ``</script>`` 会把脚本标签提前关掉。
    """
    return json.dumps(text, ensure_ascii=False).replace("</", "<\\/")


def _page(name: str, source: str, has_file: bool, style: str) -> str:
    return (_PAGE
            .replace("__STYLE_CSS__", style_css(style))
            .replace("__VERSION__", __version__)
            .replace("__NAME__", name)
            .replace("__SOURCE__", _js_json(source))
            .replace("__FILE__", "true" if has_file else "false"))


def _handler_factory(live: LivePreview, lock: threading.Lock,
                     path: Optional[Path], name: str, style: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mdengine-live/" + __version__

        # -------------------------------------------------- 工具
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError):
                pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")

        def _body(self) -> str:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                return ""
            return self.rfile.read(max(0, length)).decode("utf-8", "replace")

        def log_message(self, fmt, *args):   # 别把每条请求都刷到终端
            pass

        # -------------------------------------------------- 路由
        def do_GET(self):                     # noqa: N802 - BaseHTTPRequestHandler
            if self.path in ("/", "/index.html"):
                source = ""
                if path is not None and path.exists():
                    source = path.read_text(encoding="utf-8", errors="replace")
                html = _page(name, source, path is not None, style)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/reload":
                source = ""
                if path is not None and path.exists():
                    source = path.read_text(encoding="utf-8", errors="replace")
                self._json({"source": source})
                return
            if self.path == "/health":
                self._json({"ok": True, "version": __version__})
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):                    # noqa: N802
            text = self._body()
            if self.path == "/render":
                with lock:
                    html = live.update(text)
                    stats = live.stats.as_dict()
                self._json({"html": html, "stats": stats})
                return
            if self.path == "/save":
                if path is None:
                    self._json({"ok": False, "reason": "未指定文件"}, 409)
                    return
                try:
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text(text, encoding="utf-8")
                    os.replace(tmp, path)      # 原子替换：中途崩了也不会留半截文件
                except OSError as exc:
                    self._json({"ok": False, "reason": str(exc)}, 500)
                    return
                self._json({"ok": True, "bytes": len(text.encode("utf-8"))})
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def make_server(target: Optional[str] = None, port: int = 0,
                host: str = "127.0.0.1", style: str = "friendly",
                highlight: bool = True):
    """建好服务但不启动（测试与嵌入用）。

    Returns:
        ``(httpd, url)``；调用方负责 ``serve_forever`` / ``shutdown`` / ``close``。
    """
    path = Path(target).expanduser().resolve() if target else None
    if path is not None and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    engine = Engine(highlight=highlight, noclasses=False, hl_style=style)
    live = LivePreview(engine, anchor=True)
    lock = threading.Lock()
    name = path.name if path is not None else "示例文档"

    handler = _handler_factory(live, lock, path, name, style)
    httpd = None
    last_error: Optional[OSError] = None
    for candidate in [port] + ([port + i for i in range(1, 10)] if port else []):
        try:
            httpd = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError as exc:            # 端口被占，往后挪
            last_error = exc
    if httpd is None:
        raise last_error if last_error else OSError("无法绑定端口")
    httpd.daemon_threads = True
    return httpd, "http://%s:%d/" % (host, httpd.server_address[1])


def serve(target: Optional[str] = None, port: int = 8137, host: str = "127.0.0.1",
          open_browser: bool = False, style: str = "friendly",
          highlight: bool = True) -> int:
    """启动实时预览服务，阻塞到 Ctrl+C。

    Args:
        target: 要编辑的文件；``None`` 表示只用内存里的示例文档（不能保存）。
        port: 端口，0 表示让系统分配。端口被占用时自动往后试。
        host: 监听地址，默认只监听本机。
        open_browser: 启动后自动打开浏览器。
        style: 代码配色。
        highlight: 是否着色。
    """
    httpd, url = make_server(target, port=port, host=host, style=style,
                             highlight=highlight)
    _say("mdengine 实时预览 %s" % __version__)
    _say("  文件：%s" % (Path(target).expanduser().resolve() if target
                          else "（未指定，仅预览，不落盘）"))
    _say("  地址：%s" % url)
    _say("  停止：Ctrl+C")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        _say("\n已停止。")
    finally:
        httpd.server_close()
    return 0


def _say(text: str) -> None:
    """Windows 控制台默认 GBK，中文可能编码失败——别让它把服务带崩。"""
    try:
        print(text)
    except UnicodeEncodeError:            # pragma: no cover - 老控制台
        print(text.encode("ascii", "replace").decode("ascii"))
    try:
        sys.stdout.flush()
    except Exception:                     # noqa: BLE001
        pass
