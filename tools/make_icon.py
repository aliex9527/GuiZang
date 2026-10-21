"""生成 Windows 图标文件（build/icon.ico），打包前运行一次即可。"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.icons import app_icon  # noqa: E402


def _png_bytes(size: int) -> bytes:
    pix = app_icon(size).pixmap(size, size)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """写出多尺寸 ICO（每个尺寸内嵌 PNG，Vista 以后通用）。"""
    images = [(s, _png_bytes(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, payload = b"", b""
    for size, data in images:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + payload)


def write_icns(path: Path, sizes=(16, 32, 64, 128, 256, 512, 1024)) -> None:
    """写出 macOS 的 ICNS（每个尺寸一个 PNG chunk，类型码按像素命名）。"""
    type_map = {16: "icp4", 32: "icp5", 64: "icp6", 128: "ic07",
                256: "ic08", 512: "ic09", 1024: "ic10"}
    chunks = b""
    for size in sizes:
        data = _png_bytes(size)
        code = type_map.get(size)
        if code is None:
            continue
        # chunk: 4字节类型 + 4字节长度(含8字节头) + PNG数据
        chunks += code.encode("ascii") + struct.pack(">I", len(data) + 8) + data
    total = 8 + len(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", total) + chunks)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    base = Path(__file__).resolve().parent.parent / "build"
    write_ico(base / "icon.ico")
    print(f"已生成 {base / 'icon.ico'}")
    write_icns(base / "icon.icns")
    print(f"已生成 {base / 'icon.icns'}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
