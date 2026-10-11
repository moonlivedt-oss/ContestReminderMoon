"""Пути, настройки и хранилище конкурсов в %APPDATA%\\ContestReminder."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Contest

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ContestReminder"
CONTESTS_FILE = APP_DIR / "contests.json"
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "default_reminders": [1440, 60, 0],   # за день / за час / в момент (в минутах)
    "clipboard_watch": True,               # следить за буфером обмена
    "hotkey": "ctrl+alt+c",                # горячая клавиша OCR-захвата
    "ocr_lang": "ru",                      # язык OCR по умолчанию
    "geometry": None,                       # base64 QByteArray геометрии окна
}


def _ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


# --- настройки ----------------------------------------------------------

def load_settings() -> dict:
    _ensure_dir()
    data = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            data.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_settings(settings: dict) -> None:
    _ensure_dir()
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), "utf-8")
    except OSError:
        pass


# --- конкурсы -----------------------------------------------------------

def load_contests() -> list[Contest]:
    _ensure_dir()
    if not CONTESTS_FILE.exists():
        return []
    try:
        raw = json.loads(CONTESTS_FILE.read_text("utf-8"))
        return [Contest.from_dict(d) for d in raw]
    except (json.JSONDecodeError, OSError):
        return []


def save_contests(contests: list[Contest]) -> None:
    _ensure_dir()
    try:
        CONTESTS_FILE.write_text(
            json.dumps([c.to_dict() for c in contests], ensure_ascii=False, indent=2),
            "utf-8")
    except OSError:
        pass
