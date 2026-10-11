"""Выбор темы: плитки режима (Авто / Светлая / Тёмная / Сепия) и карточки палитр.

Как в окне cpp-docs-panel: у режима - нарисованное мини-превью, у палитры - пейзаж
в её цветах и кружки основных цветов. Выбор сразу применяется ко всей программе
(сигнал changed), окно настроек при «Отмене» возвращает прежнюю тему.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QGridLayout, QHBoxLayout, QWidget

from ..core.i18n import tr
from . import theme

_PAL_DIR = Path(__file__).resolve().parents[1] / "assets" / "palettes"
MODE_LABELS = (("auto", "Авто"), ("light", "Светлая"), ("dark", "Тёмная"), ("sepia", "Сепия"))


def _rounded(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path


def _mini_window(p: QPainter, rect: QRectF, bg: str, lines: str, accent: str) -> None:
    """Значок режима: окошко с «текстом» - тремя полосками."""
    p.setPen(QPen(QColor(lines).darker(130), 1))
    p.setBrush(QColor(bg))
    p.drawRoundedRect(rect, 6, 6)
    x, y, w = rect.x() + 8, rect.y() + 9, rect.width() - 16
    for i, k in enumerate((0.55, 0.9, 0.7)):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent if i == 0 else lines))
        p.drawRoundedRect(QRectF(x, y + i * 7, w * k, 3.5), 1.7, 1.7)


class ModeTile(QAbstractButton):
    """Плитка режима: превью и подпись; выбранная - залита акцентом."""

    def __init__(self, mode: str, label: str) -> None:
        super().__init__()
        self.mode = mode
        self.setText(label)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(92, 78))

    def paintEvent(self, _event) -> None:  # noqa: N802 - имя из Qt
        c = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent"]))
        else:
            p.setPen(QPen(QColor(c["accent"] if self.underMouse() else c["border"]), 1))
            p.setBrush(QColor(c["surface"]))
        p.drawRoundedRect(r, 10, 10)

        icon = QRectF(r.center().x() - 26, r.y() + 9, 52, 34)
        light, dark, sepia = (
            ("#f7f7fb", "#9ca0b0", c["accent"]),
            ("#1e1e2e", "#6c7086", c["accent"]),
            ("#f4ecdc", "#b3a483", c["accent"]),
        )
        if self.mode == "auto":  # пополам: светлое и тёмное
            p.save()
            p.setClipPath(_rounded(icon, 6))
            _mini_window(p, icon, *light)
            half = QPainterPath()
            half.moveTo(icon.topRight())
            half.lineTo(icon.bottomRight())
            half.lineTo(icon.bottomLeft())
            half.closeSubpath()
            p.setClipPath(half)
            _mini_window(p, icon, *dark)
            p.restore()
        else:
            _mini_window(p, icon, *{"light": light, "dark": dark, "sepia": sepia}[self.mode])

        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(self.isChecked())
        p.setFont(f)
        p.setPen(QColor(c["accent_text"] if self.isChecked() else c["subtext"]))
        p.drawText(
            QRectF(r.x(), icon.bottom() + 4, r.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )
        p.end()


class PaletteCard(QAbstractButton):
    """Карточка палитры: пейзаж, кружки её цветов, название; выбранная - рамкой и галочкой."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key
        self.pal = theme.PALETTES[key]
        self.setText(tr(self.pal["name"]))
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(158, 118))
        self._pix = QPixmap(str(_PAL_DIR / f"{key}.jpg"))

    def paintEvent(self, _event) -> None:  # noqa: N802
        c = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        clip = _rounded(r, 12)
        p.setClipPath(clip)
        p.fillRect(r, QColor(self.pal["panel"]))
        img = QRectF(r.x(), r.y(), r.width(), 76)
        if not self._pix.isNull():
            pm = self._pix.scaled(
                img.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (pm.width() - img.width()) / 2
            sy = (pm.height() - img.height()) / 2
            p.drawPixmap(img, pm, QRectF(sx, sy, img.width(), img.height()))
        # кружки цветов палитры поверх картинки
        x = img.x() + 9
        for key in ("ac", "tf", "ts", "tn"):
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            p.setBrush(QColor(self.pal[key]))
            p.drawEllipse(QRectF(x, img.bottom() - 21, 14, 14))
            x += 17
        # название на панели палитры (её же цветом текста)
        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(self.pal["fg"]))
        name = self.text() + ("  ✓" if self.isChecked() else "")
        p.drawText(
            QRectF(r.x() + 11, img.bottom(), r.width() - 16, r.bottom() - img.bottom()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name,
        )
        p.setClipping(False)
        if self.isChecked():
            pen = QPen(QColor(c["accent"]), 2.5)
        elif self.underMouse():
            pen = QPen(QColor(c["accent"]), 1.2)
        else:
            pen = QPen(QColor(c["border"]), 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(clip)
        p.end()

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(e)


class ThemePicker(QWidget):
    changed = pyqtSignal(str, str)  # режим, палитра

    def __init__(self, mode: str, palette: str) -> None:
        super().__init__()
        self.mode = mode if mode in theme.MODES else "auto"
        self.palette = palette if palette in theme.PALETTES else "mocha"

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setVerticalSpacing(10)

        modes = QHBoxLayout()
        modes.setSpacing(8)
        self._mode_group = QButtonGroup(self)
        for key, label in MODE_LABELS:
            t = ModeTile(key, tr(label))
            t.setChecked(key == self.mode)
            t.clicked.connect(lambda _c=False, k=key: self._set(mode=k))
            self._mode_group.addButton(t)
            modes.addWidget(t)
        modes.addStretch(1)
        root.addLayout(modes, 0, 0)

        grid = QGridLayout()
        grid.setSpacing(10)
        self._pal_group = QButtonGroup(self)
        for i, key in enumerate(theme.PALETTES):
            card = PaletteCard(key)
            card.setChecked(key == self.palette)
            card.clicked.connect(lambda _c=False, k=key: self._set(palette=k))
            self._pal_group.addButton(card)
            grid.addWidget(card, i // 3, i % 3)
        root.addLayout(grid, 1, 0)

    def _set(self, mode: str | None = None, palette: str | None = None) -> None:
        self.mode = mode or self.mode
        self.palette = palette or self.palette
        self.changed.emit(self.mode, self.palette)
        for w in self.findChildren(QAbstractButton):
            w.update()
