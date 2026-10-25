#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为每个版本生成一份说明文件（Markdown）。

产物：
    docs/releases/v<版本>.md          仓库内永久保存，进 git
    dist/GuiZang-<版本>-windows-x64/版本说明.md   随包分发

内容来自两处：
    1. 打包产物本身（文件名、大小、SHA256、打包日期）
    2. git 提交记录（上一个版本的说明文件里记了当时的提交号，从它往后取）

用法：
    python tools/release_note.py --version 1.0.7
        按现有产物 + git 记录生成 1.0.7 的说明
    python tools/release_note.py --version 1.0.7 --since <sha> --until <sha>
        指定提交区间（补写历史版本时用）
    python tools/release_note.py --backfill
        为 docs/releases 里缺的历史版本批量补写
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / "docs" / "releases"
DIST = ROOT / "dist"

_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# 说明文件里记录的「对应提交」，用来给下一版划区间
_SHA_LINE_RE = re.compile(r"^\| 代码提交 \| `([0-9a-f]{7,40})` \|$", re.MULTILINE)


# ---------------------------------------------------------------- git 小工具

def git(*args: str) -> str:
    """跑一条 git 命令，返回 stdout（失败返回空串）。"""
    try:
        out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True)
    except OSError:
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.decode("utf-8", "replace").strip()


def head_sha(short: bool = True) -> str:
    sha = git("rev-parse", "--short=10", "HEAD") if short else git("rev-parse", "HEAD")
    return sha


def parse_ver(text: str) -> Optional[Tuple[int, int, int]]:
    m = _VER_RE.match(text.strip().lstrip("v"))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------- 版本说明

def note_path(version: str) -> Path:
    return RELEASES / f"v{version}.md"


def known_versions() -> List[Tuple[Tuple[int, int, int], Path]]:
    """docs/releases 下已有的版本说明，按版本号升序。"""
    found = []
    if RELEASES.exists():
        for p in RELEASES.glob("v*.md"):
            ver = parse_ver(p.stem)
            if ver:
                found.append((ver, p))
    return sorted(found)


def prev_version(version: str) -> Optional[Tuple[str, Optional[str]]]:
    """比 version 小的最近一个版本 → (版本号, 它记录的提交号)。"""
    cur = parse_ver(version)
    if not cur:
        return None
    cands = [(v, p) for v, p in known_versions() if v < cur]
    if not cands:
        return None
    _, path = cands[-1]
    text = path.read_text(encoding="utf-8")
    m = _SHA_LINE_RE.search(text)
    return path.stem.lstrip("v"), (m.group(1) if m else None)


def commits_between(since: Optional[str], until: str = "HEAD",
                    limit: int = 40) -> List[Tuple[str, str, str]]:
    """取 (短 sha, 标题, 正文) 列表；since 为空时表示「一直到 until 为止的历史」。"""
    if since:
        rng = [f"{since}..{until}"]
    else:
        # 没有起点（第一个版本）：以 until 为终点往回取
        rng = ([until] if until and until != "HEAD" else []) + [f"-{limit}"]
    raw = git("log", "--no-merges", "--pretty=format:%h%x1f%s%x1f%b%x1e", *rng)
    out = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        if len(parts) < 2:
            continue
        sha, subject = parts[0].strip(), parts[1].strip()
        body = parts[2] if len(parts) > 2 else ""
        out.append((sha, subject, body))
    return out


def _bullets(body: str, limit: int = 6, width: int = 120) -> List[str]:
    """把提交正文里的列表项抽出来，折行的续行拼回去，太长就截断。

    只认「列表项 + 紧邻的折行」；空行之后的段落是另一段话，不算条目。
    """
    items: List[str] = []
    fresh_para = True          # 上一个非空行之后是否隔了空行
    for line in body.splitlines():
        s = line.strip()
        if not s:
            fresh_para = True
            continue
        if s.startswith(("- ", "* ")):
            items.append(s[2:].strip())
            fresh_para = False
        elif items and not fresh_para and not s.startswith(("#", "|", ">", "```")):
            items[-1] = (items[-1] + s).strip()
        else:
            fresh_para = True
    out = []
    for s in items[:limit]:
        out.append(s if len(s) <= width else s[:width - 1] + "…")
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render(version: str,
           exe: Optional[Path],
           changes: List[Tuple[str, str, str]],
           sha: str,
           prev: Optional[str],
           note: str = "",
           rel_date: str = "") -> str:
    lines = [f"# 归藏 v{version}", ""]
    if note:
        lines += [f"> {note}", ""]

    size = f"{exe.stat().st_size / (1024 * 1024):.2f} MB" if exe and exe.exists() else "—"
    digest = sha256_of(exe) if exe and exe.exists() else "—"
    lines += [
        "## 版本信息",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
        f"| 版本号 | `{version}` |",
        f"| 发布日期 | {rel_date or date.today().isoformat()} |",
        f"| 安装包 | `{exe.name}` |" if exe else "| 安装包 | — |",
        f"| 大小 | {size} |",
        f"| SHA256 | `{digest}` |",
        "| 平台 | Windows 10 / 11 · 64 位 |",
        f"| 代码提交 | `{sha}` |",
        f"| 上一版 | v{prev} |" if prev else "| 上一版 | — |",
        "",
    ]

    lines += ["## 本版改动", ""]
    if changes:
        for csha, subject, body in changes:
            lines.append(f"- `{csha}` {subject}")
            for bullet in _bullets(body):
                lines.append(f"  - {bullet}")
    else:
        lines.append("- 本次打包未发现新的代码提交（重建或仅改打包参数）。")
    lines.append("")

    lines += [
        "## 使用说明",
        "",
        f"- 便携版：双击 `{exe.name if exe else 'GuiZang-<版本>-windows-x64.exe'}` 即用，"
        "资料库 `归藏.db` 就在 exe 同目录。",
        "- 本目录是**该版本的归档**，里面的 `归藏.db` 是打包时的数据快照；"
        "日常使用请以最新版本目录为准。",
        "- 覆盖升级：把旧目录里的 `归藏.db` 复制到新目录即可（或在软件里用"
        "「备份 / 恢复」搬运）。",
        "",
    ]
    return "\n".join(lines)


def write_note(version: str,
               exe: Optional[Path] = None,
               since: Optional[str] = None,
               until: str = "HEAD",
               note: str = "",
               also_dist: bool = True) -> Path:
    """生成一份版本说明，返回仓库内那份的路径。"""
    prev = prev_version(version)
    prev_ver, prev_sha = prev if prev else (None, None)
    if since is None and prev_sha:
        since = prev_sha
    changes = commits_between(since, until)

    if exe is None:
        cand = DIST / f"GuiZang-{version}-windows-x64" / f"GuiZang-{version}-windows-x64.exe"
        flat = DIST / f"GuiZang-{version}-windows-x64.exe"
        exe = cand if cand.exists() else (flat if flat.exists() else None)
    elif not exe.is_absolute():
        exe = ROOT / exe

    # 日期取「这一版对应提交」的日期，补写历史版本才不会被写成今天
    rel_date = git("log", "-1", "--pretty=%ad", "--date=short", until) or date.today().isoformat()

    text = render(version, exe, changes,
                  head_sha() if until == "HEAD" else (git("rev-parse", "--short=10", until) or until),
                  prev_ver, note, rel_date)

    RELEASES.mkdir(parents=True, exist_ok=True)
    path = note_path(version)
    path.write_text(text, encoding="utf-8", newline="\n")

    if also_dist and exe is not None:
        (exe.parent / "版本说明.md").write_text(text, encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------- 历史补写

# 有些版本当时没打 tag（或 tag 落在 CI 提交上、和实际打包提交错开），
# 用提交号钉住「这一版真正对应哪次提交」，补写历史说明时才不会串味。
_PINNED = {
    "1.0.4": "dbd3404",
    "1.0.5": "8728c79",
    "1.0.6": "c02132e",
}


def backfill() -> int:
    """给缺说明的版本补写：终点优先用钉住的提交，其次用 tag。"""
    tags = {}
    for line in git("tag", "--list", "v*").splitlines():
        ver = parse_ver(line)
        if ver:
            tags["%d.%d.%d" % ver] = line

    made = 0
    plan = sorted(set(tags) | set(_PINNED), key=lambda v: parse_ver(v) or (0, 0, 0))
    for version in plan:
        if note_path(version).exists():
            continue
        until = _PINNED.get(version) or tags.get(version)
        if not until:
            continue
        # 起点不给：自动取上一版说明里记录的提交号
        write_note(version, until=until,
                   note="历史版本补写（按 git 提交区间整理）。")
        made += 1
        print(f"  ＋ v{version}  ..{until}")
    return made


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="生成归藏版本说明")
    ap.add_argument("--version", help="要写说明的版本号，如 1.0.7")
    ap.add_argument("--since", help="起始提交（不含），默认取上一版说明里记录的提交")
    ap.add_argument("--until", default="HEAD", help="结束提交，默认 HEAD")
    ap.add_argument("--note", default="", help="一句话摘要，写在标题下面")
    ap.add_argument("--exe", help="安装包路径，默认在 dist 下按版本号找")
    ap.add_argument("--backfill", action="store_true", help="批量补写历史版本说明")
    args = ap.parse_args(argv[1:])

    if args.backfill:
        n = backfill()
        print(f"√ 补写完成，共 {n} 份" if n else "√ 无需补写，历史说明已齐全")
        return 0

    if not args.version:
        ap.error("需要 --version 或 --backfill")

    exe = Path(args.exe) if args.exe else None
    path = write_note(args.version, exe=exe, since=args.since,
                      until=args.until, note=args.note)
    print(f"√ 版本说明：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
