归藏 @VERSION@ · Linux x64
==============================

运行
  cd 到本目录后执行：  ./GuiZang
  或在文件管理器里双击 GuiZang（需勾选「允许作为程序执行」）。

首次启动
  程序目录可写时，资料库建在同目录下的「归藏.db」；
  不可写时放到 ~/.local/share/GuiZang/归藏.db。
  第一次打开会问你要「创建资料库」还是「打开已有资料库」。

依赖
  Qt 运行库已经打包进 _internal/，系统还需要常见的图形库：
    Debian/Ubuntu: sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libgl1
    Fedora:        sudo dnf install mesa-libEGL libxkbcommon-x11 xcb-util-cursor mesa-libGL
  纯 SSH / 无桌面环境跑不起来，这是 GUI 程序。

数据
  整个资料库就是一个 .db 文件（正文和附件都在里面，正文压缩存储），
  拷走它就是完整备份。
  注意：新版本创建的库是 schema 5，不要用 1.0.x 的旧版打开，否则正文显示为空。
