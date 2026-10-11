"""Автозапуск вместе с Windows: строка в ``HKCU\\...\\Run`` (без прав администратора).

Включается только явно, в настройках. Из исходников запуск идёт через ``pythonw
run.pyw``, из собранного ``ContestReminder.exe`` - самим exe; в обоих случаях с
ключом ``--tray``: при входе в систему окно не всплывает, приложение сразу в трее.
"""
from __future__ import annotations

import sys
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE = "ContestReminder"
_ENTRY = Path(__file__).resolve().parents[1] / "run.pyw"
TRAY_FLAG = "--tray"


def frozen() -> bool:
    """Запущены из exe (PyInstaller), а не из исходников."""
    return bool(getattr(sys, "frozen", False))


def supported() -> bool:
    return sys.platform == "win32" and (frozen() or _ENTRY.exists())


def command() -> str:
    if frozen():
        return f'"{Path(sys.executable)}" {TRAY_FLAG}'
    exe = Path(sys.executable)
    windowed = exe.with_name("pythonw.exe")
    if windowed.exists():
        exe = windowed
    return f'"{exe}" "{_ENTRY}" {TRAY_FLAG}'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            val, _ = winreg.QueryValueEx(key, _VALUE)
            return bool(val)
    except OSError:
        return False


def current() -> str:
    """Что сейчас записано в автозапуск ("" - ничего)."""
    if sys.platform != "win32":
        return ""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, _VALUE)[0])
    except OSError:
        return ""


def set_enabled(on: bool, cmd: str | None = None) -> None:
    """Включает/выключает автозапуск. cmd - своя команда (сторож crnative.exe watch).

    OSError - пусть покажет вызывающий.
    """
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if on:
            winreg.SetValueEx(key, _VALUE, 0, winreg.REG_SZ, cmd or command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE)
            except FileNotFoundError:
                pass
