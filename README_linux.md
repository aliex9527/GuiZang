# 归藏 · Linux 版

和 Windows / macOS 版是同一套代码，界面、快捷键、数据格式完全一致。
Linux 产物是**单目录 + tar.gz**（不是 AppImage），解压即用。

## 一、下载现成的包

到 [Releases](https://github.com/aliex9527/GuiZang/releases) 找最新版本，
下载 `GuiZang-<版本>-linux-x64.tar.gz`，然后：

```bash
mkdir -p ~/apps && tar -xzf GuiZang-<版本>-linux-x64.tar.gz -C ~/apps
cd ~/apps/GuiZang
./GuiZang
```

想加到应用菜单，可以自己写一个 `~/.local/share/applications/guizang.desktop`：

```ini
[Desktop Entry]
Type=Application
Name=归藏
Comment=个人资料库
Exec=/home/你的用户名/apps/GuiZang/GuiZang
Icon=/home/你的用户名/apps/GuiZang/_internal/ui/assets/btn_favorite.svg
Terminal=false
Categories=Office;Utility;
```

## 二、系统依赖

Qt 运行库已经打包进 `_internal/`，但图形栈用的是系统的：

```bash
# Debian / Ubuntu
sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libgl1 \
                 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libdbus-1-3

# Fedora
sudo dnf install mesa-libEGL libxkbcommon-x11 xcb-util-cursor mesa-libGL \
                 libxcb libdbus
```

跑起来如果报 `Could not load the Qt platform plugin "xcb"`，基本就是缺上面某个库，
用 `QT_DEBUG_PLUGINS=1 ./GuiZang` 能看到具体缺哪个 `.so`。

没有桌面环境（纯 SSH、无 X/Wayland）时是跑不起来的，这是 GUI 程序。

## 三、自己构建

在 Linux 上，仓库根目录执行：

```bash
./build_linux.sh
```

会建 `.venv-linux`、装依赖、打包到 `dist/GuiZang/`，并生成
`dist/GuiZang-<版本>-linux-x64.tar.gz`。要指定版本号：

```bash
GZ_VERSION=1.2.3 ./build_linux.sh
```

## 四、CI

`.github/workflows/build-linux.yml` 在打 `v*` tag 时自动构建，
产物上传到对应版本的 Release；也可以到 Actions 页面手动触发。

## 五、数据

库还是那个单文件 `归藏.db`，正文与附件都在里面（正文压缩存储）。
Linux 与 Windows 版可以互相拷贝同一个 `.db` 继续用，只要版本不低于建库时的版本
（1.1.x 建的库不能被 1.0.x 打开，会显示空正文）。
