"""Слежение за буфером обмена. При копировании текста эмитит captured(text).

Дедуплицируем повторные события и игнорируем текст, который сами же положили в
буфер (флаг _muted), чтобы не ловить эхо.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


class ClipboardWatcher(QObject):
    captured = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False
        self._last = ""
        self._muted = False
        cb = QApplication.clipboard()
        cb.dataChanged.connect(self._on_change)

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        if on:
            # запоминаем текущее содержимое, чтобы не среагировать на старое
            self._last = QApplication.clipboard().text() or ""

    def mute_next(self) -> None:
        """Пометить, что следующее изменение — наше собственное (не реагировать)."""
        self._muted = True

    def _on_change(self) -> None:
        if not self._enabled:
            return
        if self._muted:
            self._muted = False
            self._last = QApplication.clipboard().text() or ""
            return
        text = (QApplication.clipboard().text() or "").strip()
        if not text or text == self._last:
            return
        self._last = text
        self.captured.emit(text)
