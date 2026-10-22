#!/usr/bin/env bash
# macOS 一键打包脚本：在 Mac 上运行，生成 dist/GuiZang.app 和 dist/GuiZang.dmg
# 前提：已安装 Homebrew + Python 3.11+ 和依赖（见 README 或本脚本自动安装）

set -e
cd "$(dirname "$0")"

PY=python3
APP_NAME="GuiZang"
# 版本号优先取当前 tag（v1.0.3 → 1.0.3），取不到再用默认值；
# 可以用 GZ_VERSION=1.2.3 ./build_mac.sh 覆盖
VERSION="${GZ_VERSION:-$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//')}"
VERSION="${VERSION:-1.0.3}"
export GZ_VERSION="$VERSION"

echo "==> 检查 Python 版本"
$PY --version

echo "==> 创建虚拟环境（如不存在）"
if [ ! -d ".venv-mac" ]; then
  $PY -m venv .venv-mac
fi
source .venv-mac/bin/activate

echo "==> 安装依赖"
pip install --upgrade pip
pip install PySide6 markdown pygments pyinstaller

echo "==> 生成图标（icon.icns）"
python tools/make_icon.py

echo "==> 打包 .app"
pyinstaller ${APP_NAME}_mac.spec --noconfirm --distpath dist --workpath build

echo "==> 生成 .dmg"
DMG_TMP="dist/dmg_tmp"
DMG_OUT="dist/${APP_NAME}-${VERSION}.dmg"
rm -rf "$DMG_TMP"
mkdir -p "$DMG_TMP"
# 把 .app 拷进临时目录
cp -R "dist/${APP_NAME}.app" "$DMG_TMP/"
# 创建指向 /Applications 的软链，方便拖拽安装
ln -s /Applications "$DMG_TMP/Applications"
# 用 hdiutil 生成 dmg
rm -f "$DMG_OUT"
hdiutil create -volname "${APP_NAME}" \
  -srcfolder "$DMG_TMP" \
  -ov -format UDZO \
  "$DMG_OUT"
rm -rf "$DMG_TMP"

echo "==> 完成！产物："
echo "    dist/${APP_NAME}.app   （应用，可直接双击运行）"
echo "    dist/${APP_NAME}-${VERSION}.dmg  （安装镜像，分发用）"
echo "    首次运行若被拦截，右键 App -> 打开"
