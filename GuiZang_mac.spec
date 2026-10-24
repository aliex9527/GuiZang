# -*- mode: python ; coding: utf-8 -*-
# macOS 打包配置：生成 GuiZang.app（双击运行，无需命令行）
# 用法（在 macOS 上）：pyinstaller GuiZang_mac.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_submodules

# 版本号唯一来源是仓库根的 VERSION（CI 打 tag 时用 GZ_VERSION 覆盖），
# 这样 app 内版本、dmg 文件名、Windows 版三者永远一致。
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
    upx=True,
    console=False,
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
    upx=True,
    upx_exclude=[],
    name='GuiZang',
)

app = BUNDLE(
    coll,
    name='GuiZang.app',
    icon='build/icon.icns',
    bundle_identifier='com.guizang.personal',
    info_plist={
        'CFBundleName': '归藏',
        'CFBundleDisplayName': '归藏',
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleVersion': APP_VERSION,
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.14',
    },
)
