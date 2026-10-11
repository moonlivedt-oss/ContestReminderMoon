"""Пути, настройки и хранилище конкурсов в %APPDATA%\\ContestReminder.

Запись атомарная (временный файл + замена): выключение компьютера посреди
записи не оставит пустой contests.json. Битый файл не затирается молча, а
откладывается рядом как *.broken.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Contest

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ContestReminder"
CONTESTS_FILE = APP_DIR / "contests.json"
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "default_reminders": [1440, 60, 0],  # за день / за час / в момент (в минутах)
    "clipboard_watch": True,  # следить за буфером обмена
    "capture_mode": "ask",  # ask - карточка в углу, auto - сохранять сразу, dialog - окно
    "enrich": True,  # уточнять название и срок по ссылке
    "hotkey": "ctrl+alt+c",  # горячая клавиша OCR-захвата
    "ocr_lang": "ru",  # язык OCR (ru, en-US или "" - как в системе)
    "notify_style": "toast",  # toast - карточка с кнопками, tray - уведомление Windows
    "sound": True,  # звук при напоминании
    "digest_time": "10:00",  # сводка дня; "" - выключена
    "digest_days": 3,  # сводка: дедлайны на сколько дней вперёд
    "digest_last": "",  # дата последней сводки (служебное)
    "auto_close_days": 3,  # прошедшие закрывать сами через N дней; 0 - никогда
    "filter": "active",  # что показано в списке
    "geometry": None,  # base64 QByteArray геометрии окна
}


def _ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def _write_atomic(path: Path, data) -> None:
    _ensure_dir()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def _read(path: Path):
    """Содержимое JSON или None. Битый файл переименовываем, чтобы не потерять."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            os.replace(path, path.with_suffix(".broken.json"))
        except OSError:
            pass
        return None
    except OSError:
        return None


# --- настройки ----------------------------------------------------------


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    raw = _read(SETTINGS_FILE)
    if isinstance(raw, dict):
        data.update(raw)
    return data


def save_settings(settings: dict) -> None:
    try:
        _write_atomic(SETTINGS_FILE, settings)
    except OSError:
        pass


# --- конкурсы -----------------------------------------------------------


def contests_from_json(raw) -> list[Contest]:
    if isinstance(raw, dict):  # резервная копия: {"contests": [...], ...}
        raw = raw.get("contests", [])
    if not isinstance(raw, list):
        raise ValueError("в файле нет списка конкурсов")
    return [Contest.from_dict(d) for d in raw if isinstance(d, dict)]


def load_contests() -> list[Contest]:
    raw = _read(CONTESTS_FILE)
    if raw is None:
        return []
    try:
        return contests_from_json(raw)
    except ValueError:
        return []


def save_contests(contests: list[Contest]) -> None:
    try:
        _write_atomic(CONTESTS_FILE, [c.to_dict() for c in contests])
    except OSError:
        pass


def export_backup(path: Path, contests: list[Contest], settings: dict) -> None:
    data = {
        "app": "ContestReminder",
        "version": 1,
        "contests": [c.to_dict() for c in contests],
        "settings": {k: v for k, v in settings.items() if k != "geometry"},
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def import_backup(path: Path) -> list[Contest]:
    return contests_from_json(json.loads(Path(path).read_text("utf-8")))


def merge_contests(current: list[Contest], incoming: list[Contest]) -> int:
    """Добавляет новые по id (существующие не трогает). Возвращает, сколько добавлено."""
    known = {c.id for c in current}
    added = [c for c in incoming if c.id not in known]
    current.extend(added)
    return len(added)
