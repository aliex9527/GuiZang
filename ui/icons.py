"""运行时绘制的图标，避免依赖外部图片资源。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtSvg import QSvgRenderer

_ASSET_DIR = Path(__file__).resolve().parent / "assets"

from core.storage import (ARCHIVE_EXTS, CODE_EXTS, DOC_EXTS, IMAGE_EXTS, MEDIA_EXTS,
                          PDF_EXTS, ext_of)

_CATEGORY = [
    ("image", IMAGE_EXTS, "#10b981"),
    ("pdf", PDF_EXTS, "#ef4444"),
    ("doc", DOC_EXTS, "#2563eb"),
    ("archive", ARCHIVE_EXTS, "#f59e0b"),
    ("media", MEDIA_EXTS, "#8b5cf6"),
    ("code", CODE_EXTS, "#0ea5e9"),
]


def category_of(name: str) -> str:
    ext = ext_of(name)
    for cat, exts, _ in _CATEGORY:
        if ext in exts:
            return cat
    return "other"


def category_color(name: str) -> str:
    ext = ext_of(name)
    for cat, exts, color in _CATEGORY:
        if ext in exts:
            return color
    return "#94a3b8"


def _base_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def _star_badge(p: QPainter, size: float, s: float) -> None:
    """右下角小金星。"""
    star = QPainterPath()
    cx, cy, r = size * 0.78, size * 0.80, size * 0.22
    import math
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.44
        pt = QPointF(cx + math.cos(ang) * rad, cy + math.sin(ang) * rad)
        if i == 0:
            star.moveTo(pt)
        else:
            star.lineTo(pt)
    star.closeSubpath()
    p.setPen(QPen(QColor("#ffffff"), 1.6 * s))
    p.setBrush(QColor("#f5b301"))
    p.drawPath(star)


def folder_icon(size: int = 48, color: str = "#f0b429", starred: bool = False) -> QIcon:
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 48.0
    body = QRectF(6 * s, 16 * s, 36 * s, 26 * s)
    tab = QRectF(6 * s, 10 * s, 16 * s, 10 * s)

    grad = QLinearGradient(body.topLeft(), body.bottomLeft())
    base = QColor(color)
    grad.setColorAt(0.0, base.lighter(112))
    grad.setColorAt(1.0, base.darker(108))

    path = QPainterPath()
    path.addRoundedRect(tab, 3 * s, 3 * s)
    path.addRoundedRect(body, 4 * s, 4 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawPath(path.simplified())
    p.setBrush(QColor(255, 255, 255, 40))
    p.drawRoundedRect(body.adjusted(0, 0, 0, -body.height() * 0.55), 4 * s, 4 * s)
    if starred:
        _star_badge(p, size, s)
    p.end()
    return QIcon(pm)


def file_icon(name: str, size: int = 48) -> QIcon:
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 48.0
    color = QColor(category_color(name))
    ext = ext_of(name).lstrip(".").upper()
    label = ext[:4] if ext else "?"

    # 纸张
    page = QPainterPath()
    x, y, w, h = 8 * s, 5 * s, 32 * s, 38 * s
    fold = 10 * s
    page.moveTo(x, y + 4 * s)
    page.quadTo(x, y, x + 4 * s, y)
    page.lineTo(x + w - fold, y)
    page.lineTo(x + w, y + fold)
    page.lineTo(x + w, y + h - 4 * s)
    page.quadTo(x + w, y + h, x + w - 4 * s, y + h)
    page.lineTo(x + 4 * s, y + h)
    page.quadTo(x, y + h, x, y + h - 4 * s)
    page.closeSubpath()

    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(page)
    p.setBrush(color.lighter(160))
    p.setPen(QPen(color.lighter(135), 1.1 * s))
    p.drawPath(page)

    # 折角
    corner = QPainterPath()
    corner.moveTo(x + w - fold, y)
    corner.lineTo(x + w - fold, y + fold - 2 * s)
    corner.quadTo(x + w - fold, y + fold, x + w - fold + 2 * s, y + fold)
    corner.lineTo(x + w, y + fold)
    corner.lineTo(x + w - fold, y)
    p.setBrush(QColor(255, 255, 255, 200))
    p.setPen(Qt.NoPen)
    p.drawPath(corner)

    # 类型条
    bar = QRectF(x + 3 * s, y + h - 15 * s, w - 6 * s, 12 * s)
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(bar, 2.5 * s, 2.5 * s)

    f = QFont("Segoe UI", int(6.6 * s), QFont.Bold)
    f.setLetterSpacing(QFont.PercentageSpacing, 96)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(bar, Qt.AlignCenter, label)
    p.end()
    return QIcon(pm)


def leaf_icon(size: int = 48, color: str = "#9aa4b8", starred: bool = False) -> QIcon:
    """没有子节点的条目：一页纸的抽象。"""
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 48.0
    base = QColor(color)
    path = QPainterPath()
    x, y, w, h = 11 * s, 7 * s, 26 * s, 34 * s
    fold = 8 * s
    path.moveTo(x, y + 3 * s)
    path.quadTo(x, y, x + 3 * s, y)
    path.lineTo(x + w - fold, y)
    path.lineTo(x + w, y + fold)
    path.lineTo(x + w, y + h - 3 * s)
    path.quadTo(x + w, y + h, x + w - 3 * s, y + h)
    path.lineTo(x + 3 * s, y + h)
    path.quadTo(x, y + h, x, y + h - 3 * s)
    path.closeSubpath()
    p.setBrush(QColor(base.red(), base.green(), base.blue(), 28))
    p.setPen(QPen(base, 2.0 * s))
    p.drawPath(path)
    p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 150), 1.8 * s))
    for i, frac in enumerate((0.42, 0.56, 0.70)):
        p.drawLine(QPointF(x + 5 * s, (y + h * frac)),
                   QPointF(x + w - (5 * s if i < 2 else 9 * s), (y + h * frac)))
    if starred:
        _star_badge(p, size, s)
    p.end()
    return QIcon(pm)


def chip_icon(name: str, size: int = 52) -> QIcon:
    """小尺寸用的类型色块，靠颜色区分大类、靠文字标后缀。"""
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    color = QColor(category_color(name))
    ext = ext_of(name).lstrip(".").upper()[:3] or "?"
    rect = QRectF(2, 2, size - 4, size - 4)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(rect, size * 0.26, size * 0.26)
    f = QFont("Segoe UI", int(size * 0.34), QFont.Bold)
    f.setLetterSpacing(QFont.PercentageSpacing, 94)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pm.rect(), Qt.AlignCenter, ext)
    p.end()
    return QIcon(pm)


def dot_icon(color: str, size: int = 24) -> QIcon:
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(size * 0.28, size * 0.28, size * 0.44, size * 0.44))
    p.end()
    return QIcon(pm)


def line_icon(name: str, size: int = 44, color: str = "#5b6478") -> QIcon:
    """工具栏用的细线图标。"""
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 44.0
    pen = QPen(QColor(color), 2.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def poly(points):
        path = QPainterPath()
        path.moveTo(QPointF(*points[0]))
        for pt in points[1:]:
            path.lineTo(QPointF(*pt))
        p.drawPath(path)

    if name == "back":
        poly([(26 * s, 12 * s), (14 * s, 22 * s), (26 * s, 32 * s)])
    elif name == "forward":
        poly([(18 * s, 12 * s), (30 * s, 22 * s), (18 * s, 32 * s)])
    elif name == "plus":
        poly([(22 * s, 11 * s), (22 * s, 33 * s)])
        poly([(11 * s, 22 * s), (33 * s, 22 * s)])
    elif name == "trash":
        poly([(12 * s, 15 * s), (32 * s, 15 * s)])
        poly([(18 * s, 15 * s), (18 * s, 10 * s), (26 * s, 10 * s), (26 * s, 15 * s)])
        poly([(15 * s, 15 * s), (16.5 * s, 34 * s), (27.5 * s, 34 * s), (29 * s, 15 * s)])
    elif name == "undo":
        path = QPainterPath()
        path.moveTo(QPointF(15 * s, 26 * s))
        path.cubicTo(QPointF(20 * s, 12 * s), QPointF(34 * s, 14 * s), QPointF(33 * s, 26 * s))
        p.drawPath(path)
        poly([(15 * s, 26 * s), (15 * s, 16 * s)])
        poly([(15 * s, 26 * s), (25 * s, 26 * s)])
    elif name == "redo":
        path = QPainterPath()
        path.moveTo(QPointF(29 * s, 26 * s))
        path.cubicTo(QPointF(24 * s, 12 * s), QPointF(10 * s, 14 * s), QPointF(11 * s, 26 * s))
        p.drawPath(path)
        poly([(29 * s, 26 * s), (29 * s, 16 * s)])
        poly([(29 * s, 26 * s), (19 * s, 26 * s)])
    elif name == "expand":
        poly([(12 * s, 18 * s), (22 * s, 28 * s), (32 * s, 18 * s)])
        poly([(12 * s, 36 * s), (22 * s, 36 * s)])
    elif name == "collapse":
        poly([(12 * s, 28 * s), (22 * s, 18 * s), (32 * s, 28 * s)])
        poly([(12 * s, 38 * s), (32 * s, 38 * s)])
    elif name == "search":
        p.drawEllipse(QRectF(11 * s, 11 * s, 17 * s, 17 * s))
        poly([(26 * s, 26 * s), (34 * s, 34 * s)])
    elif name == "save":
        p.drawRoundedRect(QRectF(10 * s, 10 * s, 24 * s, 24 * s), 3 * s, 3 * s)
        poly([(16 * s, 10 * s), (16 * s, 19 * s), (28 * s, 19 * s), (28 * s, 10 * s)])
        p.drawRect(QRectF(16 * s, 25 * s, 12 * s, 9 * s))
    elif name == "new_child":
        p.drawRoundedRect(QRectF(10 * s, 8 * s, 18 * s, 22 * s), 2.5 * s, 2.5 * s)
        poly([(13 * s, 14 * s), (25 * s, 14 * s)])
        poly([(13 * s, 19 * s), (22 * s, 19 * s)])
        poly([(31 * s, 27 * s), (31 * s, 38 * s)])
        poly([(25.5 * s, 32.5 * s), (36.5 * s, 32.5 * s)])
    elif name == "sort":
        for yy in (13, 22, 31):
            poly([(10 * s, yy * s), ((30 if yy == 13 else 24) * s, yy * s)])
        poly([(34 * s, 12 * s), (34 * s, 32 * s)])
        poly([(29 * s, 27 * s), (34 * s, 33 * s), (39 * s, 27 * s)])
    elif name in ("star", "star_on"):
        import math
        path = QPainterPath()
        cx, cy, r = 22 * s, 22 * s, 15 * s
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.44
            pt = QPointF(cx + math.cos(ang) * rad, cy + math.sin(ang) * rad)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        if name == "star_on":
            p.setBrush(QColor("#f5b301"))
            p.setPen(QPen(QColor("#e0a000"), 1.6 * s))
        p.drawPath(path)
    elif name == "settings":
        p.drawEllipse(QRectF(18 * s, 18 * s, 8 * s, 8 * s))
        p.drawEllipse(QRectF(10 * s, 10 * s, 24 * s, 24 * s))
    p.end()
    return QIcon(pm)


def app_icon(size: int = 256) -> QIcon:
    """应用主图标：一叠卡片 + 书脊，抽象表达『收纳』。"""
    pm = _base_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 256.0

    bg = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    bg.setColorAt(0.0, QColor("#4f7cff"))
    bg.setColorAt(1.0, QColor("#2b4fd6"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(QRectF(0, 0, size, size), 56 * s, 56 * s)

    p.setBrush(QColor(255, 255, 255, 46))
    p.drawRoundedRect(QRectF(48 * s, 66 * s, 160 * s, 34 * s), 16 * s, 16 * s)
    p.setBrush(QColor(255, 255, 255, 82))
    p.drawRoundedRect(QRectF(56 * s, 112 * s, 144 * s, 34 * s), 16 * s, 16 * s)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(64 * s, 158 * s, 128 * s, 58 * s), 18 * s, 18 * s)

    p.setBrush(QColor("#2b4fd6"))
    for i in range(3):
        p.drawRoundedRect(QRectF((84 + i * 26) * s, 176 * s, 16 * s, 22 * s), 4 * s, 4 * s)
    p.end()
    return QIcon(pm)


# myBase 原版图标文件名 -> 内部图标名 映射
MYBASE_MAP = {
    "back": "btn_go_back.svg",
    "forward": "btn_go_forward.svg",
    "plus": "btn_new.svg",
    "new_child": "btn_new_child.svg",
    "new_before": "btn_new_before.svg",
    "new_after": "btn_new_after.svg",
    "move_up": "btn_move_up.svg",
    "move_down": "btn_move_down.svg",
    "relation": "btn_relation.svg",
    "save": "btn_save.svg",
    "undo": "btn_undo.svg",
    "redo": "btn_redo.svg",
    "star": "btn_favorite.svg",
    "star_on": "btn_favorite.svg",
    "sort": "btn_sort.svg",
    "trash": "btn_delete.svg",
}


def svg_icon(name: str, size: int = 44, color: str = "#5b6478") -> QIcon:
    """加载 myBase 原版 SVG 图标，并把 currentColor 染成主题色。"""
    fname = MYBASE_MAP.get(name)
    if fname is None:
        return line_icon(name, size=size, color=color)

    path = _ASSET_DIR / fname
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return line_icon(name, size=size, color=color)

    # QSvgRenderer 不解析 CSS 的 currentColor，这里替换为具体颜色
    tint = QColor(color).name(QColor.HexRgb)
    svg = raw.replace("currentColor", tint)

    renderer = QSvgRenderer(svg.encode("utf-8"))
    if not renderer.isValid():
        return line_icon(name, size=size, color=color)

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.end()
    return QIcon(pm)
