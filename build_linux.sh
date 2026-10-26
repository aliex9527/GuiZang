#!/usr/bin/env bash
# Linux 一键打包脚本：生成 dist/GuiZang/ 和 dist/GuiZang-<版本>-linux-x64.tar.gz
# 用法：./build_linux.sh
#       GZ_VERSION=1.2.3 ./build_linux.sh      （覆盖版本号）

set -e
cd "$(dirname "$0")"

PY=python3
APP_NAME="GuiZang"
VERSION="${GZ_VERSION:-$(cat VERSION 2>/dev/null | tr -d '[:space:]')}"
VERSION="${VERSION:-0.0.0}"
export GZ_VERSION="$VERSION"

echo "==> 检查 Python 版本"
$PY --version

echo "==> 创建虚拟环境（如不存在）"
if [ ! -d ".venv-linux" ]; then
  $PY -m venv .venv-linux
fi
# shellcheck disable=SC1091
source .venv-linux/bin/activate

echo "==> 安装依赖"
pip install --upgrade pip
pip install PySide6-Essentials markdown html2text Pygments pyinstaller

echo "==> 检查 Qt 运行库（缺了会提示，不影响打包但运行会报错）"
missing=""
for lib in libEGL.so.1 libxkbcommon.so.0 libxkbcommon-x11.so.0 libGL.so.1; do
  if ! ldconfig -p 2>/dev/null | grep -q "$lib"; then
    missing="$missing $lib"
  fi
done
if [ -n "$missing" ]; then
  echo "    ! 系统缺少：$missing"
  echo "      Debian/Ubuntu：sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libgl1"
  echo "      Fedora：       sudo dnf install mesa-libEGL libxkbcommon-x11 xcb-util-cursor mesa-libGL"
fi

echo "==> 打包（单目录）"
rm -rf dist/GuiZang
pyinstaller "${APP_NAME}_linux.spec" --noconfirm --distpath dist --workpath build
chmod +x "dist/${APP_NAME}/${APP_NAME}"

echo "==> 打 tar.gz"
TAR="dist/${APP_NAME}-${VERSION}-linux-x64.tar.gz"
rm -f "$TAR"
tar -czf "$TAR" -C dist "$APP_NAME"

echo "==> 完成！产物："
echo "    dist/${APP_NAME}/${APP_NAME}            （可直接运行）"
echo "    ${TAR}   （分发用，解压后 chmod +x 即可）"
echo "    $(du -h "$TAR" | cut -f1) ${TAR}"
