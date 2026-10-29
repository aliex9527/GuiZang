# mdengine

零依赖的 Markdown 引擎。纯标准库实现，同时提供三个方向：

- **Markdown → HTML**：块级 + 行内完整解析，代码块自带语法着色
- **HTML → Markdown**：把富文本还原成 Markdown 源码
- **代码着色**：内置词法规则与三套配色，不依赖 Pygments

替代 `markdown` + `html2text` + `Pygments` 这一套三件套，装进任何 Python 3.8+ 项目都能直接跑。

```
mdengine/
├── __init__.py      Engine 门面 + 模块级快捷函数
├── options.py       扩展开关（Options）
├── nodes.py         AST 节点（dataclass，可直接 == 比较两棵树）
├── block.py         块级解析：行 → 块级 AST
├── inline.py        行内解析：强调/代码/链接/图片（CommonMark 分隔符栈算法）
├── render.py        AST → HTML
├── html_to_md.py    HTML → Markdown（先建极简 DOM，再递归下降）
├── highlight.py     轻量语法着色 + 配色表
├── live.py          实时预览：按块增量渲染（LivePreview）
├── server.py        本地实时预览服务（左写右看，标准库实现）
└── cli.py, __main__.py   命令行
```

## 快速开始

```python
from mdengine import to_html, to_markdown

to_html("# 标题\n\n**粗** 与 `code`")
# '<h1>标题</h1>\n\n<p><strong>粗</strong> 与 <code>code</code></p>\n'

to_markdown("<h1>标题</h1>")
# '# 标题\n'
```

需要复用配置时用 `Engine`（可跨线程复用，每次调用互不共享状态）：

```python
from mdengine import Engine

engine = Engine(nl2br=True, highlight=True, noclasses=True, hl_style="github")
html = engine.to_html(source)
doc = engine.parse(source)        # 需要 AST 时
```

命令行：

```bash
python -m mdengine README.md                       # 输出 HTML 片段
python -m mdengine README.md --standalone -o a.html # 完整页面
python -m mdengine page.html --reverse              # HTML → Markdown
python -m mdengine in.md --style monokai --drop codehilite
python -m mdengine README.md --serve --open       # 实时预览编辑器
```

## 实时预览

编辑器边打字边看效果，难点不在"渲染得快"，而在**别每次重排整篇**。

```python
from mdengine import Engine

live = Engine().live()          # 等价于 LivePreview(Engine())
html = live.update(source)      # 只重排改动过的块
print(live.stats)               # RenderStats(ms=0.4, blocks=8, rendered=1, reused=7)
```

做法是两层缓存：

1. **行内解析记忆化**：没改动的段落文字一个字都没变，直接命中（行内解析原本占了整篇解析六成时间）；
2. **块级渲染缓存**：以「顶层块的原文」为键缓存 HTML，改哪块重排哪块。

块的行范围由**解析器自己报告**（`BlockParser.parse_spans`），不是另写一套正则去猜——早期
版本就是这么错的：```` ``` ```` 被 HTML 块吞掉、围栏在列表项里被重新缩进时，扫描器与解析器
判断不一致，增量结果和全量渲染对不上。现在拼接结果与 `Engine.to_html` **逐字节相等**，
`tests/test_live.py` 用真实语料 + 随机编辑（8 000+ 次）做差分测试盯着这一点。

缓存键里还带了「块之后的那一行」：列表的紧凑/松散会看块外第一行，只拿块原文做键，
同一段文字会命中上一轮的紧密版本。

| 场景 | 全量 | 增量 | 复用 |
| --- | ---: | ---: | ---: |
| 44 KB 语料，随机插一个字符 | 37 ms | 12 ms | 356/357 块 |
| 2 KB 笔记，末尾连打 | 1.3 ms | 0.4 ms | 7/8 块 |

### 本地实时预览服务

```bash
python -m mdengine 笔记.md --serve --open
```

左写右看：每次输入把源码 POST 到本地服务，增量渲染后回填；页面按块的
`data-line` 找光标所在的块，让预览跟着滚（长文档里这一条比速度更重要）。
`Ctrl+S` 原地写回文件（临时文件 + `os.replace` 原子替换），`Tab` 缩进四格，
`Ctrl+B/I/K/E` 套标记。只监听 `127.0.0.1`。

## 在归藏里启用

引擎是**默认引擎**；两条老链路（`markdown` / `html2text`）保留为兜底。想退回：

```bash
# Windows
set GUICANG_MD_ENGINE=0 && python main.py
# macOS / Linux
GUICANG_MD_ENGINE=0 python main.py
```

引擎负责的是"把 Markdown 变成 HTML"这条链路（导出、卡片摘要、历史富文本迁移）。
编辑区本身**不走 HTML**——它在原地排版，见下一节。

另外两个文件里的第三方库已改成**可选导入**：把 `requirements.txt` 里的
`markdown` / `html2text` / `Pygments` 删掉，应用照样能跑（自动落到自研引擎）。

## 归藏编辑区：就地渲染

`ui/live_render.py` 让编辑区长得像 Typora：单栏，边写边排版，没有右侧预览。

关键是**不改文档内容**——不重建 `QTextDocument`、不替换字符，只给字符打格式：

| 目标 | 做法 |
| --- | --- |
| 隐藏标记 | `setFontPointSize(0.1)` + 前景 `alpha=0`（用背景色会在图片上露馅） |
| 标题层次 | 按 `HEAD_SCALE` 放大字号，行高自然变高 |
| 代码块/引用/表头底色、引用竖线、分隔横线 | 在 `paintEvent` 里、父类之前画（`palette().Base` 设透明，父类的填充才不会盖掉） |
| 内嵌图片 | 整行字符抹成透明，用第一个字符的字号把行高撑到图片大小 |
| 光标块显示源码 | 只对该块把标记换回强调色小字，排版保持不变（标题不会突然缩回去） |

因为文本一个字没动，`toPlainText()` 始终是用户写下的原文：存盘、搜索、撤销栈、
输入法全部照旧，也不需要"富文本 → Markdown"的反向转换。

进图片行、代码围栏行时行高会变化，所以光标所在块收起图片、露出围栏——
这正是 Typora 的行为，也顺带避开了"撑高的行把光标拉成一根竖条"。

没有预览面板之后，`md_to_html` 仍被列表卡片的摘要用到；`ui/markdown_render.py`
里的分屏预览控件保留但默认隐藏。

打包配置（`GuiZang*.spec`）已加入 `collect_submodules('mdengine')`——引擎是懒加载的，
不显式声明的话 PyInstaller 静态分析看不到它。

## 语法支持

| 语法 | 支持 | 说明 |
| --- | :---: | --- |
| ATX / Setext 标题 | ✅ | `# H`、`H\n===`，支持 `{#id}` |
| 段落、硬换行 | ✅ | 行尾两空格或反斜杠；`nl2br` 可让单换行生效 |
| 强调 | ✅ | `*斜*` / `**粗**` / `***both***`，`_` 遵循词内不强调 |
| 删除线 / 高亮 | ✅ | `~~删~~` / `==亮==` |
| 行内代码、围栏代码 | ✅ | 反引号串可嵌套；``` 与 ~~~ 均可，info string 取语言名 |
| 链接 / 图片 | ✅ | 行内、引用式、快捷式，`<https://…>` 自动链接 |
| 图片宽度 | ✅ | `![a](b.png){width=300}` |
| 列表 | ✅ | 有序/无序、嵌套、紧凑与松散、`start` 属性 |
| 任务列表 | ✅ | `- [ ]` / `- [x]`，可渲染成 `<input>` 或 ☐/☑ 字形 |
| 表格 | ✅ | 管道表格 + 左/中/右对齐，单元格内 `\|` 转义 |
| 引用 | ✅ | 可嵌套，支持懒续行 |
| 分隔线 | ✅ | `---` / `***` / `___` |
| 原样 HTML | ✅ | 块级标签白名单 + 行内标签直通 |
| Admonition | ✅ | `!!! note "标题"` + 4 空格缩进正文 |
| 链接引用定义 | ✅ | `[id]: url "title"` |

**未实现**（Python-Markdown 的 `extra` 里有、这里没做）：脚注 footnote、缩写 abbr、
定义列表 def_list、`md_in_html`。归藏的笔记语料里没出现这四种；需要时可作为扩展加进来。

## 性能

项目自身 27 个 Markdown 文件、36 900 字符，预热后单次渲染（含代码着色）：

| 指标 | 数值 |
| --- | --- |
| 中位耗时 | 38 ms |
| 吞吐 | ≈ 940 k 字符/秒 |
| 渲染 + 回译一整轮 | 69 ms |

畸形输入不会把界面拖死（这些都有回归用例兜着）：

| 输入 | 耗时 |
| --- | --- |
| 一万个未闭合 `[` | 9.6 ms |
| `*a**b***c*` 重复 2000 次（20 000 字符） | 57 ms |
| 未闭合图片 `![a](gzs:///1` ×500 | 93 ms |
| 500 层嵌套引用 | 0.9 ms（超 64 层降级为纯文本，不爆栈） |

这三条护栏值得单独说：链接标签扫描封顶 `MAX_LABEL=2000`、URL 扫描封顶
`MAX_DEST=512`、强调配对用 CommonMark 的 `openers_bottom` 剪枝。去掉任何一条，
上表第一行和第三行就会退化到秒级（O(n²)）。

## 加一门语言

`highlight.py` 里加一张 `(token, 正则)` 表即可，匹配顺序就是优先级，
注释和字符串放最前面：

```python
_LUA = [
    ("com", r"--[^\n]*"),
    ("str", r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""),
    ("kw", r"\b(?:local|function|end|if|then|else|for|while|return)\b"),
    ("num", r"\b\d+(?:\.\d+)?\b"),
]
_SPECS["lua"] = _LUA
```

已有的语言：python、javascript/typescript、json、yaml、toml/ini、html/xml、css、
bash/sh、sql、c/cpp/java/cs/go/rust/kotlin/swift/php、diff/patch。

## 与 Python-Markdown 的行为差异

1. **代码高亮输出**：`<pre class="highlight"><code class="language-x">…</code></pre>`，
   默认写内联 `style`（`noclasses=False` 可切换成 `class="tok-kw"`）。
2. **`==高亮==`** 输出 `<mark>`，不是带背景色的 `<span>`。
3. **软换行**默认保留 `\n`；`nl2br=True` 时才变 `<br>`。
4. **HTML 块**按标签白名单识别，`<https://x>` 不会被当成 HTML 块吞掉。
5. 表格、列表等容错更宽松（缩进 2 或 4 空格都能吃），代价是极少数边界写法与
   CommonMark 参考实现不同。

## 测试

```bash
# 引擎本体（纯标准库，任意 Python 3.8+ 都能跑）
python -m unittest discover -s tests -v

# 接入层用例需要 PySide6，用项目自带的 .venv
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

129 项用例，覆盖六大类：块级/行内语法、反向转换往返、畸形输入（耗时上界与不崩）、
实时预览（增量与全量渲染的**逐字节差分**，含 8 000+ 次随机编辑）、编辑区就地渲染
（字号层次、标记隐藏、光标块展开、图片撑高与收起）、以及归藏接入层
（开关生效、Qt 能解析、**载入再保存不丢任务/表格/代码块**）。
