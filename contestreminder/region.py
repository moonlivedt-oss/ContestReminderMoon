"""Оверлей на весь виртуальный рабочий стол для выбора прямоугольника под OCR.

ЛКМ + тянуть — рамка; отпустил — selected(left, top, w, h) в экранных координатах.
Esc / ПКМ — cancelled.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class RegionSelector(QWidget):
    selected = pyqtSignal(int, int, int, int)
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        virt = QRect()
        for scr in QGuiApplication.screens():
            virt = virt.united(scr.geometry())
        self._origin_offset = virt.topLeft()
        self.setGeometry(virt)

        self._start: QPoint | None = None
        self._end: QPoint | None = None

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._start and self._end:
            sel = QRect(self._start, self._end).normalized()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(0xcb, 0xa6, 0xf7), 2))
            p.drawRect(sel)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()
            return
        self._start = event.pos()
        self._end = event.pos()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start:
            self._end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._start:
            return
        sel = QRect(self._start, self._end).normalized()
        self.close()
        if sel.width() < 5 or sel.height() < 5:
            self.cancelled.emit()
            return
        off = self._origin_offset
        self.selected.emit(
            sel.left() + off.x(), sel.top() + off.y(), sel.width(), sel.height())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
