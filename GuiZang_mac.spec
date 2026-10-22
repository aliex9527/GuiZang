# -*- mode: python ; coding: utf-8 -*-
# macOS 打包配置：生成 GuiZang.app（双击运行，无需命令行）
# 用法（在 macOS 上）：pyinstaller GuiZang_mac.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_submodules

# 版本号由构建环境注入（CI 从 tag 派生），这样 app 内的版本和 dmg 文件名不会再对不上
APP_VERSION = os.environ.get('GZ_VERSION', '1.0.3')

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
    datas=[('ui/assets', 'ui/assets')],
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
