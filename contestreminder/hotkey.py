"""Глобальная горячая клавиша через Win32 RegisterHotKey (ctypes, без зависимостей).

Отдельный поток крутит цикл сообщений; по срабатыванию эмитит Qt-сигнал triggered
(доставляется в главный поток очередью). Если регистрация не удалась (клавиша занята) —
не падаем, просто hotkey не работает, буфер-режим остаётся.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

_MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
         "shift": 0x0004, "win": 0x0008, "super": 0x0008}
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOTKEY_ID = 1


def parse_spec(spec: str) -> tuple[int, int] | None:
    """'ctrl+alt+c' -> (fsModifiers, vk). None если не разобрали."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    vk = None
    for part in parts:
        if part in _MODS:
            mods |= _MODS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            n = int(part[1:])
            if 1 <= n <= 24:
                vk = 0x70 + (n - 1)
    if vk is None:
        return None
    return mods | _MOD_NOREPEAT, vk


class HotkeyManager(QObject):
    triggered = pyqtSignal()

    def __init__(self, spec: str) -> None:
        super().__init__()
        self._spec = spec
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ok = False

    @property
    def ok(self) -> bool:
        return self._ok

    def start(self) -> None:
        parsed = parse_spec(self._spec)
        if parsed is None:
            return
        mods, vk = parsed
        self._thread = threading.Thread(
            target=self._run, args=(mods, vk), daemon=True)
        self._thread.start()

    def _run(self, mods: int, vk: int) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, _HOTKEY_ID, mods, vk):
            self._ok = False
            return
        self._ok = True
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.triggered.emit()
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, _WM_QUIT, 0, 0)
            self._thread_id = None
