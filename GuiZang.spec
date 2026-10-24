# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os

from PyInstaller.utils.hooks import collect_submodules

# ---------------------------------------------------------------- 版本号
# 唯一来源是仓库根的 VERSION 文件；CI 打 tag 时用 GZ_VERSION 覆盖。
# 生成的版本资源会写进 EXE，右键「属性 → 详细信息」能看到
# 「文件版本 / 产品版本」，与安装包文件名一致。
try:
    ROOT = SPECPATH                      # PyInstaller 注入：spec 所在目录
except NameError:                        # 万一分支：直接执行本文件时
    ROOT = os.path.dirname(os.path.abspath(__file__))

_vspec = importlib.util.spec_from_file_location(
    "gz_win_version", os.path.join(ROOT, "tools", "win_version.py"))
_vmod = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)

APP_VERSION = _vmod.read_version(ROOT)
VERSION_FILE = _vmod.write_version_file(
    APP_VERSION, os.path.join(ROOT, "build", "version_info.txt"))
print(f"[归藏] 打包版本 {APP_VERSION}")

hiddenimports = ['markdown.extensions.extra', 'markdown.extensions.sane_lists', 'markdown.extensions.nl2br', 'markdown.extensions.admonition', 'markdown.extensions.codehilite']
hiddenimports += collect_submodules('markdown')
hiddenimports += collect_submodules('pygments.formatters')
hiddenimports += collect_submodules('pygments.lexers')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('ui/assets', 'ui/assets'), ('VERSION', '.')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GuiZang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 声明 PerMonitorV2 DPI 感知，避免 Windows 把窗口位图拉伸导致发虚
    manifest='tools/GuiZang.manifest',
    icon=['build/icon.ico'],
    # 版本资源文件（由 tools/win_version.py 从 VERSION 生成）
    version=VERSION_FILE,
)
