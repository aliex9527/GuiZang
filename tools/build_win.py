#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 一键打包：每个版本独立目录，历史版本全部保留。

用法（在仓库根目录执行）：
    python tools/build_win.py               按 VERSION 里的版本打包
    python tools/build_win.py --bump        先把补丁号 +1（1.0.4 → 1.0.5）再打包
    python tools/build_win.py --minor       次版本 +1（1.0.4 → 1.1.0）
    python tools/build_win.py --major       主版本 +1（1.0.4 → 2.0.0）
    python tools/build_win.py --set 1.2.0   指定版本打包

产物：
    dist/GuiZang-<版本>-windows-x64/GuiZang-<版本>-windows-x64.exe
    dist/GuiZang-<版本>-windows-x64/版本说明.md      （同时写入 docs/releases/v<版本>.md）

规则：
    - 每个版本的目录都不会被删，想回退直接开旧版本目录里的 exe
    - 新版本目录里还没有 归藏.db 时，从最近一版**复制**一份过来（旧目录不动的），
      这样升级后打开就有原来的笔记；旧目录里的那份是打包时的快照
    - 同版本重复打包默认报错；确需重打加 --force
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_note as rn  # noqa: E402
import win_version as wv  # noqa: E402


def bump(ver: str, part: str) -> str:
    v0, v1, v2, v3 = wv.parse(ver)
    if part == "major":
        return f"{v0 + 1}.0.0"
    if part == "minor":
        return f"{v0}.{v1 + 1}.0"
    return f"{v0}.{v1}.{v2 + 1}"


def inherit_db(dist_root: Path, new_dir: Path) -> list:
    """新版本目录没有资料库时，从最近一版复制一份过来。

    注意是**复制**不是移动：历史版本目录要原样留着，删掉/搬走会让旧版 exe
    打开变空库。这里的 db 只是「打包那一刻的快照」，日常仍以最新版目录为准。
    """
    if list(new_dir.glob("*.db")):
        return []
    if not dist_root.exists():
        return []
    olds = sorted((p for p in dist_root.glob("GuiZang-*-windows-x64") if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in olds:
        if old.resolve() == new_dir.resolve():
            continue
        srcs = sorted(old.glob("*.db"))
        if not srcs:
            continue
        for src in srcs:
            try:
                shutil.copy2(src, new_dir / src.name)
                # 有 -wal 一起带上，避免丢掉最近一次未合并的写入
                wal = src.with_name(src.name + "-wal")
                if wal.exists():
                    shutil.copy2(wal, new_dir / wal.name)
                print(f"  继承资料库：{src.name} ← {old.name}")
                return [src.name]
            except OSError as exc:
                print(f"  ! {src.name} 复制失败，跳过：{exc}")
    return []


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(add_help=True, description="打包 Windows 版归藏")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bump", action="store_true", help="补丁号 +1 后再打包")
    g.add_argument("--minor", action="store_true", help="次版本 +1 后再打包")
    g.add_argument("--major", action="store_true", help="主版本 +1 后再打包")
    g.add_argument("--set", metavar="X.Y.Z", help="指定版本号打包")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的同版本产物")
    args = ap.parse_args(argv[1:])

    current = wv.read_version(ROOT)
    if args.set:
        version = wv.normalize(args.set)
    elif args.bump:
        version = bump(current, "patch")
    elif args.minor:
        version = bump(current, "minor")
    elif args.major:
        version = bump(current, "major")
    else:
        version = current

    out_dir = ROOT / "dist" / f"GuiZang-{version}-windows-x64"
    exe_name = f"GuiZang-{version}-windows-x64.exe"
    target = out_dir / exe_name

    if target.exists() and not args.force:
        print(f"× 已存在同版本产物：{target}")
        print(f"  当前 VERSION = {current}")
        print("  每个版本只产出一次，不覆盖旧文件。请换版本号再打包，例如：")
        print("      python tools/build_win.py --bump")
        return 2

    if version != current:
        print(f"版本：{current} → {version}")
    else:
        print(f"版本：{version}")

    env = dict(os.environ)
    env["GZ_VERSION"] = version

    tmp_dist = ROOT / "build" / "dist_tmp"
    work = ROOT / "build" / "pyi"
    shutil.rmtree(tmp_dist, ignore_errors=True)

    cmd = [sys.executable, "-m", "PyInstaller", "GuiZang.spec",
           "--noconfirm", "--distpath", str(tmp_dist), "--workpath", str(work)]
    print("＋ 开始打包 …")
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if result.returncode != 0:
        print("× 打包失败（见上面的 PyInstaller 输出）")
        return result.returncode

    built = tmp_dist / "GuiZang.exe"
    if not built.exists():
        print(f"× 没找到产物：{built}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(target))
    shutil.rmtree(tmp_dist, ignore_errors=True)

    inherited = inherit_db(ROOT / "dist", out_dir)

    # 打包成功才把版本写回 VERSION，避免构建失败留下一个没用上的版本号
    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")

    size = target.stat().st_size / (1024 * 1024)
    print()
    for name in inherited:
        print(f"＋ 已带上一版资料库：{name}")

    note_path = rn.write_note(version, exe=target)
    print(f"√ 完成：{target}")
    print(f"  大小：{size:.2f} MB")
    print(f"  版本说明：{note_path}")
    print(f"  VERSION 已写为 {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
