"""Связь с нативной частью crnative.exe (C++/WinRT): уведомления Windows и сторож.

crnative.exe ставится в %LOCALAPPDATA%\\ContestReminder\\bin: реестр (протокол
contestreminder://, AUMID уведомлений, автозапуск сторожа) должен указывать на
постоянный файл, а у собранного ContestReminder.exe распакованное живёт во
временной папке только пока он запущен. Нет crnative.exe (запуск из исходников без
MSVC) - всё работает как раньше: карточки программы вместо уведомлений Windows,
без сторожа.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_MUTEX = "Local\\ContestReminder-App"
WATCH_MUTEX = "Local\\ContestReminder-Watcher"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
_SYNCHRONIZE = 0x00100000

BIN_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ContestReminder" / "bin"


def bundled_dir() -> Path:
    """Где лежит собранный crnative.exe: внутри exe или native/bin в исходниках."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "native"
    return Path(__file__).resolve().parents[2] / "native" / "bin"


def app_command() -> str:
    """Команда запуска программы - для кнопок уведомлений, когда она закрыта."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowed = exe.with_name("pythonw.exe")
    run = Path(__file__).resolve().parents[2] / "run.pyw"
    return f'"{windowed if windowed.exists() else exe}" "{run}"'


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def install() -> Path | None:
    """Кладёт crnative.exe и значок в постоянную папку; возвращает путь или None."""
    src = bundled_dir() / "crnative.exe"
    dst = BIN_DIR / "crnative.exe"
    if not src.exists():
        return dst if dst.exists() else None
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        icon = bundled_dir() / "icon.png"
        if icon.exists() and not _same(icon, BIN_DIR / "icon.png"):
            shutil.copyfile(icon, BIN_DIR / "icon.png")
        if not _same(src, dst):
            was_running = watcher_running()
            if was_running and dst.exists():
                _run([str(dst), "stop"])  # занятый файл не заменить
            shutil.copyfile(src, dst)
            if was_running:
                start_watcher(dst)
    except OSError:
        return dst if dst.exists() else None
    return dst


def _run(args: list[str], timeout: float = 8) -> int:
    try:
        return subprocess.run(
            args,
            timeout=timeout,
            creationflags=_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


def register(exe: Path) -> bool:
    return _run([str(exe), "register", "--app", app_command()]) == 0


def unregister(exe: Path) -> bool:
    return _run([str(exe), "unregister"]) == 0


def toast(
    exe: Path, cid: str, head: str, body: str, url: str = "", lang: str = "ru", urgent: bool = False
) -> bool:
    args = [str(exe), "toast", "--id", cid, "--head", head, "--body", body, "--lang", lang]
    if url:
        args += ["--url", url]
    if urgent:
        args.append("--urgent")
    return _run(args) == 0


def remove(exe: Path, cid: str) -> None:
    _run([str(exe), "remove", "--id", cid], timeout=4)


def _mutex_exists(name: str) -> bool:
    if sys.platform != "win32":
        return False
    h = ctypes.windll.kernel32.OpenMutexW(_SYNCHRONIZE, False, name)
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def watcher_running() -> bool:
    return _mutex_exists(WATCH_MUTEX)


def start_watcher(exe: Path) -> bool:
    if watcher_running():
        return True
    try:
        subprocess.Popen(
            [str(exe), "watch"],
            creationflags=_DETACHED | _NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def stop_watcher(exe: Path) -> None:
    _run([str(exe), "stop"])


def watcher_command(exe: Path) -> str:
    return f'"{exe}" watch'


class AppMutex:
    """Пока программа работает, сторож молчит: он видит этот мьютекс."""

    def __init__(self) -> None:
        self.handle = None
        if sys.platform == "win32":
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)

    def release(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
