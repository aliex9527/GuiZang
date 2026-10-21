"""SQLite 数据层：节点树 / 富文本笔记 / 附件（BLOB 内嵌）/ 检索。

设计要点：**一个资料库 = 一个 .db 文件**。附件内容不进文件系统，
而是以内容寻址（sha256）的方式存在 `blobs` 表里，天然去重，拷走单个
文件即可完成备份与迁移。
"""

from __future__ import annotations

import html as html_lib
import re
import zlib
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .storage import guess_mime, materialize, sha256_bytes

SCHEMA_VERSION = 4

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HEAD_RE = re.compile(r"<(head|style|script)\b[^>]*>.*?</\1>", re.I | re.S)

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS nodes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id   INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
        title       TEXT    NOT NULL DEFAULT '',
        note_text   TEXT    NOT NULL DEFAULT '',
        note_format TEXT    NOT NULL DEFAULT 'html',
        note_plain  TEXT    NOT NULL DEFAULT '',
        tags        TEXT    NOT NULL DEFAULT '',
        starred     INTEGER NOT NULL DEFAULT 0,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        expanded    INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT    NOT NULL DEFAULT '',
        updated_at  TEXT    NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id, sort_order)",
    """
    CREATE TABLE IF NOT EXISTS blobs (
        hash TEXT PRIMARY KEY,
        size INTEGER NOT NULL,
        data BLOB NOT NULL,
        compressed INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id     INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
        name        TEXT    NOT NULL,
        hash        TEXT    NOT NULL DEFAULT '',
        stored_name TEXT    NOT NULL DEFAULT '',
        size        INTEGER NOT NULL DEFAULT 0,
        mime        TEXT    NOT NULL DEFAULT '',
        note        TEXT    NOT NULL DEFAULT '',
        sort_order  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT ''
    )
    """,
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_files_node ON files(node_id, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash)",
]


_MIN_SAVING = 40          # 至少省下这么多字节才值得压缩
_ZLEVEL = 6


def _pack(data: bytes) -> tuple[bytes, int]:
    """返回 (要入库的字节, 是否已压缩)。"""
    if len(data) < 256:
        return data, 0
    try:
        comp = zlib.compress(data, _ZLEVEL)
    except zlib.error:
        return data, 0
    if len(comp) < len(data) - _MIN_SAVING:
        return comp, 1
    return data, 0


def _unpack(data: bytes, compressed: int) -> bytes:
    if not compressed:
        return data
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    html = _HEAD_RE.sub(" ", html)
    txt = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", html, flags=re.I)
    txt = _TAG_RE.sub(" ", txt)
    txt = html_lib.unescape(txt)
    return _WS_RE.sub(" ", txt).strip()


def like_escape(kw: str) -> str:
    return kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    def __init__(self, db_file: Path):
        self.db_path = Path(db_file)
        if self.db_path.suffix.lower() != ".db":
            self.db_path = self.db_path / "guizang.db"
        self.root = self.db_path.parent
        self.root.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        for stmt in SCHEMA:
            self.conn.execute(stmt)
        self.conn.commit()
        self._migrate()
        for stmt in INDEXES:
            self.conn.execute(stmt)
        self.conn.commit()
        self._set_meta("schema_version", str(SCHEMA_VERSION))
        if self.count_nodes() == 0:
            self._seed()

    @property
    def file_name(self) -> str:
        return self.db_path.name

    # ---------------------------------------------------------------- meta

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def _migrate(self) -> None:
        """把旧版「附件放在 files/ 目录」的数据搬进库里。"""
        ncols = {r["name"] for r in self.conn.execute("PRAGMA table_info(nodes)")}
        if ncols and "starred" not in ncols:
            self.conn.execute(
                "ALTER TABLE nodes ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

        bcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(blobs)")}
        if bcols and "compressed" not in bcols:
            self.conn.execute(
                "ALTER TABLE blobs ADD COLUMN compressed INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "hash" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

        legacy_dir = self.root / "files"
        rows = list(self.conn.execute(
            "SELECT id, stored_name FROM files WHERE hash = '' AND stored_name <> ''"))
        migrated = 0
        for row in rows:
            name = row["stored_name"]
            src = legacy_dir / name[:2] / name
            if not src.exists():
                continue
            data = src.read_bytes()
            digest = sha256_bytes(data)
            self._put_blob(digest, data)
            self.conn.execute("UPDATE files SET hash = ? WHERE id = ?", (digest, row["id"]))
            migrated += 1
        self.conn.commit()
        if rows and migrated == len(rows) and legacy_dir.exists():
            shutil.rmtree(legacy_dir, ignore_errors=True)

    def close(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.Error:
            pass
        self.conn.close()

    # --------------------------------------------------------------- nodes

    def count_nodes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]

    def count_files(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]

    def _next_order(self, parent_id: Optional[int]) -> int:
        sql = ("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM nodes "
               "WHERE parent_id IS NULL" if parent_id is None else
               "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM nodes WHERE parent_id = ?")
        args = () if parent_id is None else (parent_id,)
        return int(self.conn.execute(sql, args).fetchone()["n"])

    def create_node(
        self,
        title: str = "未命名",
        parent_id: Optional[int] = None,
        note_text: str = "",
        tags: str = "",
        note_format: str = "html",
    ) -> int:
        ts = now_str()
        plain = self._plain_of(note_text, note_format)
        cur = self.conn.execute(
            "INSERT INTO nodes(parent_id, title, note_text, note_format, note_plain, tags, "
            "sort_order, expanded, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (parent_id, title, note_text, note_format, plain, tags,
             self._next_order(parent_id), ts, ts),
        )
        self.conn.commit()
        if parent_id is not None:
            self.conn.execute("UPDATE nodes SET expanded = 1 WHERE id = ?", (parent_id,))
            self.conn.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _plain_of(text: str, fmt: str) -> str:
        if fmt == "md":
            stripped = re.sub(r"[#>*`_~]", " ", text or "")
            return _WS_RE.sub(" ", stripped).strip()
        return html_to_text(text)

    def get_node(self, node_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()

    def all_nodes(self) -> List[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT id, parent_id, title, tags, sort_order, expanded, starred "
            "FROM nodes ORDER BY COALESCE(parent_id, 0), sort_order, id"
        ))

    def set_starred(self, node_id: int, on: bool) -> None:
        self.conn.execute("UPDATE nodes SET starred = ? WHERE id = ?",
                          (1 if on else 0, node_id))
        self.conn.commit()

    def is_starred(self, node_id: int) -> bool:
        row = self.conn.execute("SELECT starred FROM nodes WHERE id = ?",
                                (node_id,)).fetchone()
        return bool(row and row["starred"])

    def starred_nodes(self) -> List[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT id, title FROM nodes WHERE starred = 1 ORDER BY updated_at DESC"))

    def auto_number(self, parent_id) -> int:
        """给子条目自动编号：1. 2. 3. …（已有编号先剥掉）"""
        rows = self.children(parent_id)
        for i, r in enumerate(rows, 1):
            title = re.sub(r"^\s*\d+\s*[.、)．]\s*", "", r["title"] or "").strip()
            self.conn.execute("UPDATE nodes SET title = ? WHERE id = ?",
                              (f"{i}. {title}", r["id"]))
        self.conn.commit()
        return len(rows)

    def duplicate_branch(self, node_id: int) -> int:
        """复制条目（含子分枝与附件），插在原条目后面。"""
        row = self.get_node(node_id)
        if row is None:
            return 0
        new_id = self._copy_node(row, row["parent_id"])
        self.place_sibling(new_id, self.sibling_index(node_id) + 1)
        return new_id

    def _copy_node(self, row, parent_id) -> int:
        new_id = self.create_node(row["title"], parent_id,
                                  note_text=row["note_text"] or "",
                                  tags=row["tags"] or "")
        for f in self.files_of(row["id"]):
            data = self.blob_bytes(f["id"])
            if data is not None:
                self.add_bytes(new_id, f["name"], data)
        for ch in self.children(row["id"]):
            self._copy_node(ch, new_id)
        return new_id

    def node_stats(self, node_id: int) -> Dict[str, Any]:
        row = self.get_node(node_id)
        if row is None:
            return {}
        ids = [node_id] + self.descendant_ids(node_id)
        qmarks = ",".join("?" * len(ids))
        files = self.conn.execute(
            f"SELECT COUNT(*) AS c, COALESCE(SUM(size),0) AS s FROM files "
            f"WHERE node_id IN ({qmarks})", ids).fetchone()
        return {
            "title": row["title"],
            "path": self.path_of(node_id),
            "children": len(ids) - 1,
            "files": files["c"],
            "bytes": files["s"],
            "chars": len(row["note_plain"] or ""),
            "created": row["created_at"],
            "updated": row["updated_at"],
            "starred": bool(row["starred"]),
        }

    def promote_to_top(self, node_id: int) -> None:
        """把条目提升为顶层条目。"""
        self.conn.execute("UPDATE nodes SET parent_id = NULL, sort_order = ? WHERE id = ?",
                          (self._next_order(None), node_id))
        self.conn.commit()

    def place_sibling(self, node_id: int, index: int) -> None:
        """把节点放到同级指定位置。"""
        row = self.get_node(node_id)
        if row is None:
            return
        sibs = [r for r in self.children(row["parent_id"]) if r["id"] != node_id]
        index = max(0, min(index, len(sibs)))
        sibs.insert(index, row)
        self.conn.executemany(
            "UPDATE nodes SET sort_order = ? WHERE id = ?",
            [(i, r["id"]) for i, r in enumerate(sibs)],
        )
        self.conn.commit()

    def sibling_index(self, node_id: int) -> int:
        row = self.get_node(node_id)
        if row is None:
            return 0
        sibs = self.children(row["parent_id"])
        for i, r in enumerate(sibs):
            if r["id"] == node_id:
                return i
        return 0

    def move_sibling(self, node_id: int, delta: int) -> bool:
        """在同一层级里上移/下移。"""
        row = self.get_node(node_id)
        if row is None:
            return False
        sibs = self.children(row["parent_id"])
        idx = next((i for i, r in enumerate(sibs) if r["id"] == node_id), None)
        if idx is None:
            return False
        tgt = idx + delta
        if not (0 <= tgt < len(sibs)):
            return False
        sibs[idx], sibs[tgt] = sibs[tgt], sibs[idx]
        self.conn.executemany(
            "UPDATE nodes SET sort_order = ? WHERE id = ?",
            [(i, r["id"]) for i, r in enumerate(sibs)],
        )
        self.conn.commit()
        return True

    def reorder_siblings(self, parent_id, key: str, reverse: bool = False) -> None:
        """按标题/时间重排同一层级的顺序。"""
        rows = self.children(parent_id)
        if key == "title":
            rows.sort(key=lambda r: (r["title"] or "").lower(), reverse=reverse)
        elif key == "created":
            rows.sort(key=lambda r: r["created_at"] or "", reverse=not reverse)
        elif key == "updated":
            rows.sort(key=lambda r: r["updated_at"] or "", reverse=not reverse)
        self.conn.executemany(
            "UPDATE nodes SET sort_order = ? WHERE id = ?",
            [(i, r["id"]) for i, r in enumerate(rows)],
        )
        self.conn.commit()

    def children(self, node_id: Optional[int]) -> List[sqlite3.Row]:
        if node_id is None:
            return list(self.conn.execute(
                "SELECT * FROM nodes WHERE parent_id IS NULL ORDER BY sort_order, id"))
        return list(self.conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY sort_order, id", (node_id,)))

    def update_node(self, node_id: int, plain: Optional[str] = None, **fields: Any) -> None:
        allowed = {"title", "note_text", "note_format", "tags", "expanded",
                   "parent_id", "sort_order"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"不允许更新的字段: {k}")
            sets.append(f"{k} = ?")
            vals.append(v)
        if "note_text" in fields:
            if plain is not None:
                text = plain
            else:
                fmt = fields.get("note_format")
                if fmt is None:
                    row = self.get_node(node_id)
                    fmt = row["note_format"] if row else "html"
                text = self._plain_of(fields["note_text"], fmt)
            sets.append("note_plain = ?")
            vals.append(text)
        sets.append("updated_at = ?")
        vals.append(now_str())
        vals.append(node_id)
        self.conn.execute(f"UPDATE nodes SET {', '.join(sets)} WHERE id = ?", vals)
        self.conn.commit()

    def title_of(self, node_id: int) -> str:
        row = self.get_node(node_id)
        return row["title"] if row else ""

    def path_of(self, node_id: int) -> str:
        parts: List[str] = []
        cur = node_id
        guard = 0
        while cur is not None and guard < 200:
            row = self.get_node(cur)
            if row is None:
                break
            parts.append(row["title"] or "未命名")
            cur = row["parent_id"]
            guard += 1
        return " / ".join(reversed(parts))

    def descendant_ids(self, node_id: int) -> List[int]:
        out: List[int] = []
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for row in self.conn.execute(
                    "SELECT id FROM nodes WHERE parent_id = ?", (cur,)):
                out.append(int(row["id"]))
                stack.append(int(row["id"]))
        return out

    def apply_tree(self, structure: Sequence[Tuple[int, Optional[int], int]]) -> None:
        self.conn.executemany(
            "UPDATE nodes SET parent_id = ?, sort_order = ? WHERE id = ?",
            [(pid, order, nid) for nid, pid, order in structure],
        )
        self.conn.commit()

    def delete_node(self, node_id: int) -> int:
        ids = [node_id] + self.descendant_ids(node_id)
        qmarks = ",".join("?" * len(ids))
        hashes = [r["hash"] for r in self.conn.execute(
            f"SELECT DISTINCT hash FROM files WHERE node_id IN ({qmarks})", ids)]
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self.conn.commit()
        for digest in hashes:
            self._gc_blob(digest)
        return len(ids)

    # --------------------------------------------------------------- blobs

    def _put_blob(self, digest: str, data: bytes) -> None:
        """附件内容压缩后入库；压不动（已压缩格式）就原样存。"""
        payload, flag = _pack(data)
        self.conn.execute(
            "INSERT OR IGNORE INTO blobs(hash, size, data, compressed) VALUES(?, ?, ?, ?)",
            (digest, len(data), sqlite3.Binary(payload), flag),
        )

    def _gc_blob(self, digest: str) -> None:
        if not digest:
            return
        left = self.conn.execute(
            "SELECT COUNT(*) AS c FROM files WHERE hash = ?", (digest,)).fetchone()["c"]
        if left == 0:
            self.conn.execute("DELETE FROM blobs WHERE hash = ?", (digest,))
            self.conn.commit()

    def blob_bytes(self, file_id: int) -> Optional[bytes]:
        row = self.conn.execute(
            "SELECT b.data, b.compressed FROM files f JOIN blobs b ON b.hash = f.hash "
            "WHERE f.id = ?", (file_id,)).fetchone()
        if row is None:
            return None
        return _unpack(bytes(row["data"]), row["compressed"])

    # --------------------------------------------------------------- files

    def files_of(self, node_id: int) -> List[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM files WHERE node_id = ? ORDER BY sort_order, id", (node_id,)))

    def get_file(self, file_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()

    def path_of_file(self, file_id: int) -> Optional[Path]:
        """把附件释放到临时目录后返回路径（用于交给系统程序打开）。"""
        row = self.get_file(file_id)
        if row is None or not row["hash"]:
            return None
        data = self.blob_bytes(file_id)
        if data is None:
            return None
        return materialize(row["hash"], row["name"], data)

    def _insert_file_row(self, node_id: int, name: str, digest: str, size: int) -> int:
        order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM files WHERE node_id = ?",
            (node_id,),
        ).fetchone()["n"]
        cur = self.conn.execute(
            "INSERT INTO files(node_id, name, hash, size, mime, sort_order, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (node_id, name, digest, size, guess_mime(name), int(order), now_str()),
        )
        self.conn.execute("UPDATE nodes SET updated_at = ? WHERE id = ?",
                          (now_str(), node_id))
        self.conn.commit()
        return int(cur.lastrowid)

    def add_file(self, node_id: int, src: Path, display_name: str = "") -> int:
        src = Path(src)
        return self.add_bytes(node_id, display_name or src.name, src.read_bytes())

    def add_bytes(self, node_id: int, name: str, data: bytes) -> int:
        digest = sha256_bytes(data)
        self._put_blob(digest, data)
        return self._insert_file_row(node_id, name, digest, len(data))

    def rename_file(self, file_id: int, new_name: str) -> None:
        self.conn.execute("UPDATE files SET name = ?, mime = ? WHERE id = ?",
                          (new_name, guess_mime(new_name), file_id))
        self.conn.commit()

    def delete_file(self, file_id: int) -> None:
        row = self.get_file(file_id)
        if row is None:
            return
        self.conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self.conn.commit()
        self._gc_blob(row["hash"])

    def unique_attachment_name(self, node_id: int, name: str) -> str:
        existing = {r["name"] for r in self.files_of(node_id)}
        if name not in existing:
            return name
        p = Path(name)
        stem, suffix = p.stem, p.suffix
        i = 2
        while f"{stem} ({i}){suffix}" in existing:
            i += 1
        return f"{stem} ({i}){suffix}"

    # -------------------------------------------------------------- search

    def search(self, keyword: str, limit: int = 400) -> List[Dict[str, Any]]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        pat = f"%{like_escape(kw)}%"
        rows = self.conn.execute(
            """
            SELECT n.id, n.title, n.tags, n.updated_at, n.parent_id,
                   (SELECT COUNT(*) FROM files f WHERE f.node_id = n.id) AS file_count,
                   CASE
                     WHEN n.title LIKE ? ESCAPE '\\' THEN '标题'
                     WHEN n.tags  LIKE ? ESCAPE '\\' THEN '标签'
                     WHEN n.note_plain LIKE ? ESCAPE '\\' THEN '正文'
                     ELSE '附件'
                   END AS hit
            FROM nodes n
            WHERE n.title      LIKE ? ESCAPE '\\'
               OR n.tags       LIKE ? ESCAPE '\\'
               OR n.note_plain LIKE ? ESCAPE '\\'
               OR EXISTS (SELECT 1 FROM files f
                          WHERE f.node_id = n.id
                            AND (f.name LIKE ? ESCAPE '\\' OR f.note LIKE ? ESCAPE '\\'))
            ORDER BY n.updated_at DESC
            LIMIT ?
            """,
            (pat, pat, pat, pat, pat, pat, pat, pat, limit),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["path"] = self.path_of(d["id"])
            if d["hit"] == "正文":
                d["snippet"] = self._snippet(d["id"], kw)
            elif d["hit"] == "附件":
                d["snippet"] = self._file_hit(d["id"], kw)
            else:
                d["snippet"] = ""
            out.append(d)
        return out

    def _snippet(self, node_id: int, kw: str, span: int = 90) -> str:
        row = self.get_node(node_id)
        if row is None:
            return ""
        text = row["note_plain"] or ""
        idx = text.lower().find(kw.lower())
        if idx < 0:
            return text[:span]
        start = max(0, idx - span // 2)
        return (("…" if start > 0 else "") + text[start:start + span]
                + ("…" if start + span < len(text) else ""))

    def _file_hit(self, node_id: int, kw: str) -> str:
        names = [r["name"] for r in self.files_of(node_id)
                 if kw.lower() in r["name"].lower()]
        return "、".join(names[:3])

    def all_tags(self) -> List[str]:
        tags: Dict[str, int] = {}
        for row in self.conn.execute("SELECT tags FROM nodes WHERE tags <> ''"):
            for t in re.split(r"[,，;；\s]+", row["tags"]):
                t = t.strip()
                if t:
                    tags[t] = tags.get(t, 0) + 1
        return [t for t, _ in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))]

    # --------------------------------------------------------------- stats

    def disk_size(self) -> int:
        """库在磁盘上的实际占用（含运行期的 WAL）。"""
        total = 0
        for suffix in ("", "-wal"):
            p = Path(str(self.db_path) + suffix)
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def stats(self) -> Dict[str, Any]:
        db_bytes = self.disk_size()
        return {
            "nodes": self.count_nodes(),
            "files": self.count_files(),
            "bytes": self.conn.execute(
                "SELECT COALESCE(SUM(size), 0) AS s FROM files").fetchone()["s"],
            "db_bytes": db_bytes,
            "updated": self.conn.execute(
                "SELECT COALESCE(MAX(updated_at), '') AS u FROM nodes").fetchone()["u"],
        }

    def compact(self) -> Dict[str, int]:
        """压缩已有附件并整理数据库文件，返回前后体积。"""
        before = self.disk_size()
        rows = list(self.conn.execute(
            "SELECT hash, data FROM blobs WHERE compressed = 0"))
        packed = 0
        for r in rows:
            raw = bytes(r["data"])
            payload, flag = _pack(raw)
            if flag:
                self.conn.execute(
                    "UPDATE blobs SET data = ?, compressed = 1 WHERE hash = ?",
                    (sqlite3.Binary(payload), r["hash"]))
                packed += 1
        self.conn.commit()
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("VACUUM")
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        return {"packed": packed, "before": before, "after": self.disk_size()}

    # -------------------------------------------------------------- backup

    def save_copy_to(self, target: Path) -> Path:
        """用 SQLite 备份接口导出一份完整的单文件副本。"""
        target = Path(target)
        if target.suffix.lower() != ".db":
            target = target.with_suffix(".db")
        target.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(target))
        try:
            with dest:
                self.conn.backup(dest)
        finally:
            dest.close()
        return target

    # ---------------------------------------------------------------- seed

    def _seed(self) -> None:
        md = """# 欢迎使用 归藏

这是一个把**任意格式资料**按树形分类收起来的本地小库。整个资料库就是**一个 .db 文件**，
拷走它就是完整备份。

## 三个区块

| 位置 | 作用 |
|---|---|
| 左侧 | 分类树，右键新建 / F2 重命名 / 直接拖动改变层级 |
| 中间 | 当前条目的笔记，边写边自动存，也可以按 Ctrl+S |
| 附件 | 把文件直接拖进笔记正文，就存成这个条目的附件（内容进数据库） |

## 记笔记就一种写法：Markdown

像 Typora 一样直接打语法，标记打完就地渲染：

    # 井号加空格   → 一级标题
    - 减号加空格  → 无序列表
    > 大于号加空格 → 引用
    ~~~ 加空格    → 代码块

行内写法：`**加粗**`、`*斜体*`、`` `代码` ``、`[文字](链接)`、`~~删除线~~`。
停手 0.2 秒就生效，不用管输入法是不是全角空格。

- ☑ 试试把这个条目拖到别的分类下
- ☐ 把一份 PDF 直接拖进正文，它会变成这个条目的附件
- ☐ 按 F1 看全部快捷键

> 笔记与附件都装在库里，不依赖任何外部文件。

---

*本说明可以直接删除。*
"""
        try:
            import markdown as _md
            html = _md.markdown(md, extensions=["extra", "sane_lists"])
        except Exception:  # noqa: BLE001
            from html import escape
            html = "<pre>" + escape(md) + "</pre>"
        guide_id = self.create_node("使用说明", None, note_text=html, tags="帮助")
        self.update_node(guide_id, expanded=1)
