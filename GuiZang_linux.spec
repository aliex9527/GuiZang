# -*- mode: python ; coding: utf-8 -*-
# Linux 打包配置：生成单目录 dist/GuiZang（内含可执行文件 GuiZang 与 _internal/）
# 用法（在 Linux 上，仓库根目录）：
#     pyinstaller GuiZang_linux.spec --noconfirm
#     ./dist/GuiZang/GuiZang
#
# 为什么不打单文件：Linux 上 onefile 每次启动都要把 Qt 解压到 /tmp，
# 冷启动要好几秒；单目录 + tar.gz 分发更稳，也不受 /tmp 挂载限制。
import os

from PyInstaller.utils.hooks import collect_submodules


def _repo_version() -> str:
    try:
        base = SPECPATH
    except NameError:
        base = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip() or '0.0.0'
    except OSError:
        return '0.0.0'


APP_VERSION = os.environ.get('GZ_VERSION') or _repo_version()

hiddenimports = ['markdown.extensions.extra', 'markdown.extensions.sane_lists',
                 'markdown.extensions.nl2br', 'markdown.extensions.admonition',
                 'markdown.extensions.codehilite']
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
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GuiZang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # Linux 发行版上的 upx 版本差异大，压了反而容易出问题
    console=False,             # GUI 程序：不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GuiZang',
)
