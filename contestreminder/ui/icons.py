"""Иконки: векторный колокольчик (QPainter) и значки из assets/."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import PALETTE


def bell_icon(size: int = 64, color: str = PALETTE["accent"],
              bg: str | None = None) -> QIcon:
    """Колокольчик-напоминание. Если bg задан — рисуем на скруглённой подложке."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    if bg:
        p.setBrush(QBrush(QColor(bg)))
        p.setPen(Qt.PenStyle.NoPen)
        r = size * 0.16
        p.drawRoundedRect(QRectF(0, 0, size, size), r, r)

    s = size
    col = QColor(color)
    p.setPen(QPen(col, s * 0.06, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(col))

    # тело колокола
    path = QPainterPath()
    path.moveTo(s * 0.5, s * 0.18)
    path.cubicTo(s * 0.78, s * 0.2, s * 0.72, s * 0.5, s * 0.78, s * 0.66)
    path.lineTo(s * 0.22, s * 0.66)
    path.cubicTo(s * 0.28, s * 0.5, s * 0.22, s * 0.2, s * 0.5, s * 0.18)
    path.closeSubpath()
    p.drawPath(path)
    # язычок
    p.drawEllipse(QPointF(s * 0.5, s * 0.75), s * 0.06, s * 0.06)
    # ножка сверху
    p.drawEllipse(QPointF(s * 0.5, s * 0.16), s * 0.035, s * 0.035)

    p.end()
    return QIcon(pm)


_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def asset_icon(name: str) -> QIcon:
    """Значок из assets/ (картинки из библиотеки автора, набор «Фиолетовая ночь»).

    Нет файла - пустая иконка: кнопка просто останется с подписью.
    """
    path = _ASSETS / f"{name}.png"
    return QIcon(str(path)) if path.exists() else QIcon()


def app_icon() -> QIcon:
    """Иконка окна и трея: колокольчик из библиотеки, запасной - векторный."""
    icon = asset_icon("bell")
    return icon if not icon.isNull() else bell_icon(64)
