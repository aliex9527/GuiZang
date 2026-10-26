#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""读取仓库根的 VERSION，并生成 PyInstaller 需要的 Windows 版本资源文件。

PyInstaller 的 EXE(version=...) 参数要的是一个**版本资源文件路径**，
不是版本号字符串。这个模块负责把 "1.0.4" 变成那份文件。

单独运行也可以：
    python tools/win_version.py            # 打印当前版本
    python tools/win_version.py 1.0.5      # 生成 build/version_info.txt（版本 1.0.5）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

VERSION_TEMPLATE = """\
# UTF-8
# 由 tools/win_version.py 自动生成，请勿手改
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, {v3}),
    prodvers=({v0}, {v1}, {v2}, {v3}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', '归藏'),
         StringStruct('FileDescription', '归藏 · 个人资料库'),
         StringStruct('FileVersion', '{ver}'),
         StringStruct('InternalName', 'GuiZang'),
         StringStruct('LegalCopyright', ''),
         StringStruct('OriginalFilename', 'GuiZang-{ver}-windows-x64.exe'),
         StringStruct('ProductName', '归藏'),
         StringStruct('ProductVersion', '{ver}'),
         StringStruct('Comments', '单文件个人知识库：所有资料收在一个 .db 里')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def root_dir() -> Path:
    """仓库根目录（tools/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def parse(ver: str) -> tuple:
    """'1.0.4' → (1, 0, 4, 0)；允许 1~4 段。"""
    parts = [p for p in str(ver).strip().lstrip("vV").split(".") if p != ""]
    nums = []
    for p in parts[:4]:
        try:
            nums.append(int(p))
        except ValueError:
            raise ValueError(f"版本号不合法：{ver!r}（应形如 1.0.4）") from None
    if not nums:
        raise ValueError(f"版本号不合法：{ver!r}")
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


def normalize(ver: str) -> str:
    """统一成三段式字符串，去掉多余的前导 v 和空段。"""
    nums = parse(ver)
    return ".".join(str(n) for n in nums[:3])


def read_version(root: Path | str | None = None) -> str:
    """读 VERSION 文件；环境变量 GZ_VERSION 优先（CI 用 tag 注入）。

    注意 root 可能是 str：PyInstaller 注入的 SPECPATH 就是字符串，
    所以这里必须自己转 Path，否则 `str / "VERSION"` 会直接抛 TypeError。
    """
    env = os.environ.get("GZ_VERSION", "").strip()
    if env:
        return normalize(env)
    path = Path(root or root_dir()) / "VERSION"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return normalize(text) if text else "0.0.0"


def write_version_file(ver: str, out_path: str | os.PathLike) -> str:
    """生成版本资源文件，返回其绝对路径。"""
    v0, v1, v2, v3 = parse(ver)
    text = VERSION_TEMPLATE.format(v0=v0, v1=v1, v2=v2, v3=v3,
                                   ver=normalize(ver))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # PyInstaller 用 utf-8 读取这份文件，中文不会乱码
    out.write_text(text, encoding="utf-8", newline="\n")
    return str(out.resolve())


def main(argv: list) -> int:
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    ver = normalize(argv[1]) if len(argv) > 1 else read_version()
    target = root_dir() / "build" / "version_info.txt"
    path = write_version_file(ver, target)
    print(f"版本号：{ver}")
    print(f"版本资源：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
