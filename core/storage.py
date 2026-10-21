"""附件存储相关工具。

附件内容以 BLOB 形式直接存进 SQLite（`blobs` 表），整个资料库就是**一个 .db 文件**。
外部程序要打开附件时，才把它临时释放到系统缓存目录。
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

# 常见类型补齐（Windows 注册表缺失时 mimetypes 会猜不出）
_EXTRA_MIME = {
    ".md": "text/markdown",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/toml",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".json": "application/json",
    ".csv": "text/csv",
    ".log": "text/plain",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".bat": "text/plain",
    ".ps1": "text/plain",
    ".sh": "text/plain",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".epub": "application/epub+zip",
    ".heic": "image/heic",
    ".webp": "image/webp",
    ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4",
}

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".js", ".ts",
    ".py", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
    ".sql", ".sh", ".bat", ".ps1", ".vue", ".jsx", ".tsx", ".gradle", ".properties",
}

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico", ".tif", ".tiff",
}

ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}

DOC_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".wps", ".et", ".dps",
            ".odt", ".ods", ".odp", ".rtf", ".pages", ".numbers", ".key"}

PDF_EXTS = {".pdf"}

MEDIA_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma",
              ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}

CODE_EXTS = {".py", ".js", ".ts", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go",
             ".rs", ".rb", ".php", ".sql", ".sh", ".bat", ".ps1", ".json", ".yaml",
             ".yml", ".toml", ".html", ".css", ".vue", ".jsx", ".tsx"}


def guess_mime(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def ext_of(name: str) -> str:
    return Path(name).suffix.lower()


def human_size(num: int) -> str:
    if num is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_root() -> Path:
    base = Path(tempfile.gettempdir()) / "GuiZang" / "open"
    base.mkdir(parents=True, exist_ok=True)
    return base


def clear_cache() -> None:
    """启动时清理上次留下的临时文件。"""
    root = Path(tempfile.gettempdir()) / "GuiZang"
    if not root.exists():
        return
    for sub in ("open",):
        target = root / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def materialize(digest: str, name: str, data: bytes) -> Path:
    """把 BLOB 释放成临时文件，供系统默认程序打开。"""
    safe = "".join(c for c in Path(name).name if c not in '\\/:*?"<>|') or "file"
    folder = cache_root() / digest[:16]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / safe
    try:
        if not target.exists() or target.stat().st_size != len(data):
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, target)
    except OSError:
        return target
    return target
