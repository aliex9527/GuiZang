# 归藏 · 个人资料库

> 一个本地优先、单文件存储的个人知识库桌面应用。整个资料库就是**一个 `.db` 文件**，
> 支持树状分类、所见即所得的 Markdown 笔记、附件管理、全文搜索、可定制快捷键与浅/深色主题。
> Markdown 引擎为自研（零第三方依赖），同一份源码可运行于 **Windows / macOS / Linux**。

---

## 一、主要功能

- **单文件资料库**：所有笔记、分类、附件都存在一个 `归藏.db`（SQLite）里，复制这个文件就完成了备份/迁移。
- **树状分类**：支持无限层级的目录树，自由增删改节点，拖拽整理结构。
- **所见即所得的 Markdown**：单栏即时渲染，标记符号随手写、立刻变成排版（标题、列表、引用、代码块、表格、图片）；光标停在段落里也不回退成源码，想看原文按 `Ctrl+/` 切「源码模式」。库里只存 Markdown 原文，保存不改写你的格式；历史 HTML 笔记会自动迁移。
- **自研渲染引擎**：`mdengine` 纯标准库实现，同时提供 Markdown→HTML、HTML→Markdown 与代码着色（内置多语言规则，不依赖 Pygments）。
- **右侧标题导航**：编辑区右边缘的刻度条跟随正文滚动，悬停可展开当前文档的标题列表，点击跳转。
- **附件管理**：图片、文档等附件随库保存，临时解包查看后不留痕；图片可直接拖进正文。
- **全文搜索**：跨节点快速检索，定位内容。
- **可定制快捷键**：默认键位对齐 Typora 习惯，全部可在「快捷键」设置里改（存进库的 `keymap`）。
- **浅色 / 深色主题**：主题跟着资料库走，多端一致；深色下系统标题栏、资料库标签栏、对话框按钮区一并变暗。
- **首次启动引导**：第一次打开时引导你「创建数据库」或「打开已有数据库」。
- **数据库压缩**：正文以 zlib 压缩存储，菜单里的「精简数据库」会重建并 `VACUUM`。
- **便携运行**：Windows 便携版把 `归藏.db` 放在 exe 同目录，直接拷到 U 盘即可换机使用。
- **跨平台**：Windows / macOS / Linux 同一份源码，界面、数据格式、快捷键完全一致。

---

## 二、下载与安装

到 [Releases](https://github.com/aliex9527/GuiZang/releases) 下载对应平台的最新版本：

| 平台 | 安装包 | 说明 |
| --- | --- | --- |
| Windows 10 / 11 · 64 位 | `GuiZang-<版本>-windows-x64.exe` | 一键式 exe，双击即用 |
| macOS · Intel / Apple 芯片 | `GuiZang-<版本>-x64.dmg` / `-arm64.dmg` | 拖入「应用程序」即可 |
| Linux · x64 | `GuiZang-<版本>-linux-x64.tar.gz` | 解压即用 |

各平台的系统依赖、菜单集成、手动打包步骤见对应文档：

- Windows：见仓库根目录说明（exe 直接运行）
- macOS：[`README_mac.md`](README_mac.md)
- Linux：[`README_linux.md`](README_linux.md)
- CI 自动构建：[`README_github_actions.md`](README_github_actions.md)

> 当前最新版本：**v1.1.4**（Windows 便携版约 44 MB）。
> 版本改动写在对应 Release 的说明正文里，仓库内同时留档于 [`docs/releases/`](docs/releases/)。

---

## 三、快速上手

1. **首次启动**：会弹出引导框，选择「创建数据库」（选个目录，生成 `归藏.db`）或「打开已有数据库」。
2. **新建分类 / 笔记**：在左侧分类树右键或用工具栏新增节点，右侧直接开始写。
3. **写作**：写 `# ` 就是标题，`- ` 就是列表，写 `**粗**` 立刻变粗；符号本身在排版里不显示。
4. **看原文**：按 `Ctrl+/` 切到源码模式，看到的就是存进库里的原始 Markdown，再按一次切回。
5. **附件**：把图片拖进正文即可插入；普通文件拖到附件栏随库保存。
6. **搜索**：`Ctrl+P` 快速打开，或用搜索面板在全部节点中检索内容。
7. **备份 / 迁移**：直接复制 `归藏.db` 文件即可；也可用软件内的「备份 / 恢复」搬运。

### 关于 `Delete` 键（重要）

为避免误操作，删除条目的 `Delete` 键**只在「分类树」聚焦时生效**：

- 焦点在**分类树**且选中某节点 → 按 `Delete` 会先弹确认框，确认后删除该节点（含其全部子节点）。
- 焦点在**正文 / 搜索框 / 标题**等文本控件 → `Delete` 正常删字，不会删除条目。
- 焦点在**附件栏** → 按 `Delete` 删除选中的附件。

也就是说，在编辑文字时按 `Delete` 只删字符，不会动到你的资料结构。

---

## 四、编辑器与自研引擎

编辑区是单栏的「就地渲染」：文档始终是一份纯文本，渲染层只给字符打格式，不重建文档，所以光标位置、输入法、撤销栈都不受影响。

- **标记不显示**：`#`、`**`、反引号、`~~`、`==`、`[](地址)`、`>`、`---`、代码围栏、表格分隔行在编辑区都不可见；无序列表的 `-` 由装饰层画成圆点，代码块只留语言名标签。
- **光标进入不露符号**：以前 Typora 式地「光标所在段显示标记」的行为已取消，段内编辑也不会看到源码跳动。需要原文时按 `Ctrl+/` 切源码模式。
- **渲染即排版**：标题字号、表格对齐、引用底色、图片尺寸（`{width=}`）都按最终样式呈现。

引擎 `mdengine/` 是纯标准库实现，可以单独使用：

```bash
python -m mdengine README.md -o out.html          # Markdown → HTML
python -m mdengine page.html --reverse             # HTML → Markdown
python -m mdengine --serve --open README.md        # 本地实时预览（只监听 127.0.0.1）
```

能力覆盖：ATX / Setext 标题（支持 `{#id}`）、粗体 / 斜体 / 删除线 / `==高亮==`、嵌套引用、有序 / 无序 / 任务列表、表格（含对齐）、围栏 / 缩进代码块（内置多语言着色）、链接 / 图片 / 引用式链接 / 自动链接 / `gzs://` 内嵌图、Admonition、原生 HTML 透传，以及反向的 HTML→Markdown。

> 旧的第三方链路（`markdown` + `html2text` + `Pygments`）仍保留作回退：设置环境变量 `GUICANG_MD_ENGINE=0` 即可切回。

---

## 五、数据文件说明

- 资料库是一个单文件 `归藏.db`（SQLite），正文以 zlib 压缩存放在 `note_gz` 列，搜索仍走明文索引列。
- **跨平台互通**：Windows 上生成的库文件可直接拷到 macOS / Linux 打开，反之亦然。
- **版本兼容**：用较新版本（如 1.1.x）建立的库，**不能用旧版本（如 1.0.x）打开**，否则正文显示为空白。请保持打开库的版本 ≥ 建库时的版本。
- 删除内容后文件大小不会立即变小（SQLite 只标记空闲页），需要时用菜单里的「精简数据库」回收。
- 旧的 `GuiZangData/` 目录式存储会在首次启动时自动迁移为单文件库。

---

## 六、目录结构

```
归藏-工作区/
├── main.py              # 程序入口：解析库文件、首启动引导、主题应用
├── GuiZang.spec         # Windows PyInstaller 打包配置
├── GuiZang_mac.spec / GuiZang_linux.spec   # macOS / Linux 打包配置
├── build_mac.sh / build_linux.sh           # 一键打包脚本
├── core/
│   ├── database.py      # SQLite 封装：节点增删改、压缩存储、迁移、精简
│   ├── storage.py       # 附件缓存与清理
│   ├── ui_state.py      # 最近库、首启动判断
│   └── version.py       # 版本号
├── mdengine/            # 自研 Markdown 引擎（零依赖）
│   ├── block.py / inline.py   # 块级 / 行内解析
│   ├── render.py / nodes.py   # AST → HTML
│   ├── html_to_md.py          # HTML → Markdown
│   ├── highlight.py           # 代码着色与配色
│   ├── live.py / server.py    # 增量渲染与本地预览服务
│   └── cli.py                 # 命令行
├── ui/
│   ├── database_view.py # 主视图：分类树 + 编辑器 + 附件
│   ├── note_editor.py   # 编辑器外壳：源码模式切换、工具栏动作
│   ├── source_edit.py   # 源码编辑器：语法着色、列表续行、图片拖放
│   ├── live_render.py   # 就地渲染层：标记隐藏、标题/引用/代码块装饰
│   ├── md_engine_bridge.py / md_source.py  # 引擎桥接与历史 HTML 迁移
│   ├── doc_nav.py       # 右侧标题导航条
│   ├── attachments.py   # 附件面板
│   ├── search_panel.py / find_dialog.py    # 搜索与查找替换
│   ├── keymap.py / keymap_dialog.py / shortcuts_dialog.py  # 快捷键
│   ├── theme.py / style.py / fonts.py / win_dark.py        # 主题、样式、系统标题栏
│   ├── welcome.py       # 首启动引导框
│   ├── msgbox.py        # 中文按钮对话框
│   └── ...
├── tests/               # 单元测试（引擎、桥接、渲染层）
├── tools/               # 图标生成、版本读取、发布说明等工具脚本
├── docs/releases/       # 各版本说明存档
├── requirements.txt     # Python 依赖
└── VERSION              # 当前版本号
```

---

## 七、从源码运行

需要 Python ≥ 3.10。

```bash
# 1. 克隆仓库
git clone git@github.com:aliex9527/GuiZang.git
cd GuiZang

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 运行
python main.py

# 指定资料库启动
python main.py --db /path/to/归藏.db
# 或通过环境变量
GUIZANG_DB=/path/to/归藏.db python main.py
```

### 依赖

- `PySide6-Essentials>=6.6` —— 唯一的必需依赖（Qt 绑定）。
- `markdown` / `html2text` / `Pygments` —— 仅在 `GUICANG_MD_ENGINE=0` 走回退链路时需要，可删。

### 测试

```bash
python -m unittest discover -s tests -q
```

---

## 八、各平台打包

| 平台 | 命令 / 脚本 | 产物 |
| --- | --- | --- |
| Windows | `python tools/build_win.py` | `dist/GuiZang-<版本>-windows-x64/GuiZang-<版本>-windows-x64.exe` |
| macOS | `./build_mac.sh` | `dist/GuiZang-<版本>-<架构>.dmg` |
| Linux | `./build_linux.sh` | `dist/GuiZang-<版本>-linux-x64.tar.gz` |

> PyInstaller 不能跨平台交叉编译，macOS / Linux 包需在对应系统上执行打包脚本。
> 推 `v*` tag 会触发 CI 三平台自动构建，并把包发布到对应 Release；版本说明只作为 Release 正文，不再作为附件上传。
> 详情见各平台 README 与 `README_github_actions.md`。

---

## 九、快捷键

默认键位对齐 Typora 习惯，全部可在「快捷键」设置里改（`F1` 随时查看一览）。常用：

| 操作 | 键 |
| --- | --- |
| 保存 | `Ctrl+S` |
| 新建子条目 / 同级条目 | `Ctrl+Alt+N` / `Ctrl+N` |
| 快速打开（聚焦搜索） | `Ctrl+P` |
| 源码 / 即时渲染切换 | `Ctrl+/` |
| 一~六级标题 / 正文段落 | `Ctrl+1` ~ `Ctrl+6` / `Ctrl+0` |
| 加粗 / 斜体 / 删除线 / 高亮 | `Ctrl+B` / `Ctrl+I` / `Alt+Shift+5` / `Ctrl+Shift+H` |
| 行内代码 / 链接 / 图片 | `Ctrl+Shift+反引号键` / `Ctrl+K` / `Ctrl+Shift+I` |
| 代码块 / 引用 / 表格 | `Ctrl+Shift+K` / `Ctrl+Shift+Q` / `Ctrl+T` |
| 查找 / 替换 | `Ctrl+F` / `Ctrl+H` |
| 删除条目 | `Delete`（**仅在分类树聚焦时**生效，且会先弹确认） |

---

## 十、常见问题

- **正文里看不到 `#`、`**` 这些符号？** 这是默认行为——编辑区显示的是排版结果，不是源码。按 `Ctrl+/` 切源码模式看原文。
- **打开旧版本建的库显示空白？** 用旧版本（1.0.x）打开了新版本（1.1.x）建的库。请用 ≥ 建库版本的软件打开，或把库升级到当前版本。
- **删除内容后 `归藏.db` 还是那么大？** SQLite 删除只标记空闲页，不自动缩文件。用菜单「精简数据库（压缩并整理）」回收。
- **Windows 深色模式下标题栏仍是黑的/白的？** Win10 只提供纯黑标题栏，Win11 会跟随主题面板色；切主题后无需重启即可生效。
- **Linux 报 `Could not load the Qt platform plugin "xcb"`？** 缺图形栈依赖，按 [`README_linux.md`](README_linux.md) 安装 `libegl1 libxkbcommon-x11-0 libxcb-cursor0 libgl1` 等，并用 `QT_DEBUG_PLUGINS=1 ./GuiZang` 排查。
- **资料库在哪？** 便携版在 exe 同目录的 `归藏.db`；非便携版默认在系统用户数据目录（如 Windows `LOCALAPPDATA` 或程序目录下）。
- **如何备份？** 直接复制 `归藏.db` 即可。

---

## 十一、许可证

本项目当前未附带明确开源许可证，仅供个人使用。如需分发或二次开发，请先联系作者确认授权。
