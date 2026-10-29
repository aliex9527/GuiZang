# 归藏 · 个人资料库

> 一个本地优先、单文件存储的个人知识库桌面应用。整个资料库就是**一个 `.db` 文件**，
> 支持树状分类、Markdown 笔记、附件管理、全文搜索、可定制快捷键与浅/深色主题。
> 同一份源码可运行于 **Windows / macOS / Linux**。

---

## 一、主要功能

- **单文件资料库**：所有笔记、分类、附件都存在一个 `归藏.db`（SQLite）里，复制这个文件就完成了备份/迁移。
- **树状分类**：支持无限层级的目录树，自由增删改节点，拖拽整理结构。
- **所见即所得的 Markdown**：单栏即时渲染，标记符号随手写、立刻变成排版（标题、列表、引用、代码块、表格、图片）；光标停在段落里也不回退成源码，想看原文就切「源码模式」。引擎为自研，零第三方依赖，库里只存 Markdown 原文，保存不改写你的格式；历史 HTML 笔记会自动迁移。
- **附件管理**：图片、文档等附件随库保存，临时解包查看后不留痕。
- **全文搜索**：跨节点快速检索，定位内容。
- **可定制快捷键**：支持查看与自定义快捷键（`keymap`），把操作改成顺手的键位。
- **浅色 / 深色主题**：主题跟随资料库存放，多端一致。
- **首次启动引导**：第一次打开时引导你「创建数据库」或「打开已有数据库」。
- **数据库压缩**：正文以 zlib 压缩存储，并支持 `VACUUM` 精简，减小体积。
- **便携运行**：Windows 便携版把 `归藏.db` 放在 exe 同目录，直接拷到 U 盘即可换机使用。
- **跨平台**：Windows / macOS / Linux 同一份源码，界面、数据格式、快捷键完全一致。

---

## 二、下载与安装

到 [Releases](https://github.com/aliex9527/GuiZang/releases) 下载对应平台的最新版本：

| 平台 | 安装包 | 说明 |
| --- | --- | --- |
| Windows 10 / 11 · 64 位 | `GuiZang-<版本>-windows-x64.exe` | 一键式 exe，双击即用 |
| macOS · Intel / Apple 芯片 | `GuiZang-<版本>-mac-*.dmg` | 拖入「应用程序」即可 |
| Linux · x64 | `GuiZang-<版本>-linux-x64.tar.gz` | 解压即用 |

各平台的系统依赖、菜单集成、手动打包步骤见对应文档：

- Windows：见仓库根目录说明（exe 直接运行）
- macOS：[`README_mac.md`](README_mac.md)
- Linux：[`README_linux.md`](README_linux.md)
- CI 自动构建：[`README_github_actions.md`](README_github_actions.md)

> 当前最新版本：**v1.1.4**（Windows 便携版约 40 MB）。

---

## 三、快速上手

1. **首次启动**：会弹出引导框，选择「创建数据库」（选个目录，生成 `归藏.db`）或「打开已有数据库」。
2. **新建分类 / 笔记**：在左侧分类树右键或用工具栏新增节点，右侧编辑正文。
3. **附件**：在笔记里添加图片或文件，附件随资料库一起保存。
4. **搜索**：使用搜索面板在全部节点中检索内容。
5. **备份 / 迁移**：直接复制 `归藏.db` 文件即可；也可用软件内的「备份 / 恢复」搬运。

### 关于 `Delete` 键（重要）

为避免误操作，删除条目的 `Delete` 键**只在「分类树」聚焦时生效**：

- 焦点在**分类树**且选中某节点 → 按 `Delete` 会先弹确认框，确认后删除该节点（含其全部子节点）。
- 焦点在**正文 / 搜索框 / 标题**等文本控件 → `Delete` 正常删字，不会删除条目。
- 焦点在**附件栏** → 按 `Delete` 删除选中的附件。

也就是说，在编辑文字时按 `Delete` 只删字符，不会动到你的资料结构。

---

## 四、数据文件说明

- 资料库是一个单文件 `归藏.db`（SQLite），正文以 zlib 压缩存放在 `note_gz` 列，搜索仍走明文索引列。
- **跨平台互通**：Windows 上生成的库文件可直接拷到 macOS / Linux 打开，反之亦然。
- **版本兼容**：用较新版本（如 1.1.x）建立的库，**不能用旧版本（如 1.0.x）打开**，否则正文显示为空白。请保持打开库的版本 ≥ 建库时的版本。
- 旧的 `GuiZangData/` 目录式存储会在首次启动时自动迁移为单文件库。

---

## 五、目录结构

```
归藏-工作区/
├── main.py              # 程序入口：解析库文件、首启动引导、主题应用
├── GuiZang.spec         # Windows PyInstaller 打包配置
├── GuiZang_mac.spec     # macOS 打包配置
├── GuiZang_linux.spec   # Linux 打包配置
├── build_mac.sh / build_linux.sh   # 一键打包脚本
├── core/
│   ├── database.py      # SQLite 封装：节点增删改、压缩存储、迁移、VACUUM
│   ├── storage.py       # 附件缓存与清理
│   ├── ui_state.py      # 最近库、首启动判断
│   └── version.py       # 版本号
├── ui/
│   ├── database_view.py # 主视图：分类树 + 笔记编辑/预览 + 附件
│   ├── note_editor.py   # Markdown 编辑器
│   ├── markdown_render.py  # Markdown 渲染
│   ├── attachments.py   # 附件面板
│   ├── search_panel.py / find_dialog.py  # 搜索
│   ├── keymap.py / keymap_dialog.py / shortcuts_dialog.py  # 快捷键
│   ├── theme.py / style.py / fonts.py     # 主题、样式、字体
│   ├── welcome.py       # 首启动引导框
│   ├── msgbox.py        # 中文按钮对话框
│   └── ...
├── tools/               # 图标生成、版本读取、发布说明等工具脚本
├── requirements.txt     # Python 依赖
└── VERSION              # 当前版本号
```

---

## 六、从源码运行

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

- `PySide6-Essentials>=6.6`（Qt 绑定）
- `markdown>=3.5`
- `html2text>=2020.1.16`（HTML→Markdown 迁移）
- `Pygments>=2.17`（代码高亮）

---

## 七、各平台打包

| 平台 | 命令 / 脚本 | 产物 |
| --- | --- | --- |
| Windows | `python tools/build_win.py` | `dist/GuiZang-<版本>-windows-x64/GuiZang-<版本>-windows-x64.exe` |
| macOS | `./build_mac.sh` | `dist/GuiZang-<版本>-mac-*.dmg` |
| Linux | `./build_linux.sh` | `dist/GuiZang-<版本>-linux-x64.tar.gz` |

> PyInstaller 不能跨平台交叉编译，macOS / Linux 包需在对应系统上执行打包脚本。
> 详情见各平台 README 与 `README_github_actions.md`（CI 在打 `v*` tag 时自动构建三平台并发布）。

---

## 八、快捷键

默认快捷键可在软件内的「快捷键」设置中查看与自定义。常用：

- 删除节点：`Delete`（**仅在分类树聚焦时**生效，且会先弹确认）
- 更多键位：菜单 → 快捷键 / 设置 中查看。

---

## 九、常见问题

- **打开旧版本建的库显示空白？** 用旧版本（1.0.x）打开了新版本（1.1.x）建的库。请用 ≥ 建库版本的软件打开，或把库升级到当前版本。
- **Linux 报 `Could not load the Qt platform plugin "xcb"`？** 缺图形栈依赖，按 [`README_linux.md`](README_linux.md) 安装 `libegl1 libxkbcommon-x11-0 libxcb-cursor0 libgl1` 等，并用 `QT_DEBUG_PLUGINS=1 ./GuiZang` 排查。
- **资料库在哪？** 便携版在 exe 同目录的 `归藏.db`；非便携版默认在系统用户数据目录（如 Windows `LOCALAPPDATA` 或程序目录下）。
- **如何备份？** 直接复制 `归藏.db` 即可。

---

## 十、许可证

本项目当前未附带明确开源许可证，仅供个人使用。如需分发或二次开发，请先联系作者确认授权。
