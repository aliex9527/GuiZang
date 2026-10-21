# 归藏 · macOS 版本打包说明

「归藏」代码本身已做跨平台适配（路径、字体、文件管理器调用、配置目录均按平台分支处理），
因此**同一份源码**即可在 Windows 和 macOS 上运行。唯一不同的是打包：PyInstaller 不能跨平台交叉编译，
所以 macOS 版必须在**一台 Mac 上**执行打包，才能得到可双击运行的 `.app`。

## 一、准备环境（只需一次）

1. 安装 Homebrew（如已装跳过）：
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. 安装 Python 3（≥3.10）：
   ```bash
   brew install python@3.13
   ```

## 二、把项目拷到 Mac 上

把整个 `GuiZang/` 目录（含 `main.py`、`ui/`、`core/`、`tools/`、`build/icon.ico`、
`GuiZang_mac.spec`、`build_mac.sh`）拷贝到 Mac 任意目录，例如 `~/GuiZang`。

## 三、一键打包

```bash
cd ~/GuiZang
chmod +x build_mac.sh
./build_mac.sh
```

脚本会自动：建虚拟环境 → 装依赖（PySide6 / markdown / pygments / pyinstaller）→
生成图标 → 打包成 `dist/GuiZang.app` → 再封装成 `dist/GuiZang-1.0.0.dmg`。

## 四、运行与安装

- **直接运行**：双击 `dist/GuiZang.app` 即可。
- **用 dmg 安装**：双击 `dist/GuiZang-1.0.0.dmg`，在弹出的窗口里把「GuiZang」图标拖到「Applications」即可安装到系统。
- 首次运行若被系统拦截（未签名应用），在 Finder 里右键 App →「打开」，再点「打开」即可。

## 五、手动打包（不想用脚本时）

```bash
cd ~/GuiZang
python3 -m venv .venv-mac && source .venv-mac/bin/activate
pip install PySide6 markdown pygments pyinstaller
python tools/make_icon.py            # 生成 build/icon.icns
pyinstaller GuiZang_mac.spec --noconfirm   # 得到 dist/GuiZang.app

# 封装成 dmg
mkdir -p dist/dmg && cp -R dist/GuiZang.app dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "GuiZang" -srcfolder dist/dmg \
  -ov -format UDZO dist/GuiZang-1.0.0.dmg
```

## 六、注意事项

- **数据文件**：资料库 `.db` 文件与平台无关，Windows 上生成的库文件可直接拷到 Mac 打开。
- **配置目录**：Mac 上配置存在 `~/Library/Application Support/GuiZang/config.json`。
- **签名/公证**：当前产物未签名，仅适合个人使用。要分发给他人或上架，需 Apple 开发者账号
  做代码签名（`codesign`）与公证（`notarytool`），这里不展开。
- **代码跨平台点**（已处理）：
  - 字体：`ui/fonts.py` 按平台返回 `Microsoft YaHei UI` / `PingFang SC` / `Noto Sans CJK SC`
  - 文件管理器：`reveal_db` 用 `explorer /select`（Win）或 `open -R`（Mac）
  - 配置/缓存目录：`core/config.py`、`core/storage.py` 按平台分支
