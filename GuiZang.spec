# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

# 说明：Windows 单文件 EXE 的版本号由 CI 在打包后改文件名体现
# （如 GuiZang-1.0.3-windows-x64.exe），与 macOS 版共用同一个 tag 派生来源，
# 因此两平台版本天然一致；此处不需要给 EXE 内嵌版本资源。

hiddenimports = ['markdown.extensions.extra', 'markdown.extensions.sane_lists', 'markdown.extensions.nl2br', 'markdown.extensions.admonition', 'markdown.extensions.codehilite']
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
)
