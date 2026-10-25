#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 一键打包：文件名带版本号，磁盘上只保留最新一版。

用法（在仓库根目录执行）：
    python tools/build_win.py               按 VERSION 里的版本打包
    python tools/build_win.py --bump        先把补丁号 +1（1.0.4 → 1.0.5）再打包
    python tools/build_win.py --minor       次版本 +1（1.0.4 → 1.1.0）
    python tools/build_win.py --major       主版本 +1（1.0.4 → 2.0.0）
    python tools/build_win.py --set 1.2.0   指定版本打包

产物：
    dist/GuiZang-<版本>-windows-x64/GuiZang-<版本>-windows-x64.exe

打包成功后会删掉 dist 下更早版本的目录，只留这一版。
旧目录里如果躺着便携资料库（第一次运行 exe 时生成的 归藏.db），
会先搬到新目录再删，不会连数据一起删掉。
同版本重复打包默认报错；确需重打加 --force。
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

import win_version as wv  # noqa: E402


def bump(ver: str, part: str) -> str:
    v0, v1, v2, v3 = wv.parse(ver)
    if part == "major":
        return f"{v0 + 1}.0.0"
    if part == "minor":
        return f"{v0}.{v1 + 1}.0"
    return f"{v0}.{v1}.{v2 + 1}"


def prune_old(dist_root: Path, keep: Path) -> list:
    """删掉 dist 下更早版本的产物目录，只留下 keep 这一版。

    旧目录里可能已经有便携资料库（`归藏.db` 及其 -wal/-shm），
    先把它们搬到新目录再删，避免把用户的笔记一起删掉。
    """
    removed = []
    if not dist_root.exists():
        return removed
    # 从新到旧地处理：旧目录里的资料库如果新目录还没有，优先搬最新的那个
    olds = sorted((p for p in dist_root.glob("GuiZang-*-windows-x64") if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in olds:
        if old.resolve() == keep.resolve():
            continue
        for pattern in ("*.db", "*.db-wal", "*.db-shm"):
            for src in sorted(old.glob(pattern)):
                dst = keep / src.name
                if dst.exists():
                    continue
                try:
                    shutil.move(str(src), str(dst))
                    print(f"  搬移资料库：{src.name} ← {old.name}")
                except OSError as exc:
                    print(f"  ! {src.name} 搬不动，跳过：{exc}")
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    # dist 根下遗留的散落 exe 一并清掉
    for stray in list(dist_root.glob("GuiZang*.exe")):
        try:
            stray.unlink()
            removed.append(stray.name)
        except OSError:
            pass
    return removed


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

    # 打包成功才把版本写回 VERSION，避免构建失败留下一个没用上的版本号
    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")

    removed = prune_old(ROOT / "dist", out_dir)

    size = target.stat().st_size / (1024 * 1024)
    print()
    for name in removed:
        print(f"− 已清理旧版本：{name}")
    print(f"√ 完成：{target}")
    print(f"  大小：{size:.2f} MB")
    print(f"  VERSION 已写为 {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
