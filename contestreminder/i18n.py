"""Языки интерфейса: русский (исходный), английский, украинский, немецкий.

Ключ перевода - сама русская строка: код читается как есть, а если перевода нет,
показывается русский текст, а не пустое место. Переводы - в `locales.py`.
Подстановки - через str.format: tr("через {n} мин", n=5).
"""

from __future__ import annotations

from .locales import TRANSLATIONS

LANGS = [
    ("auto", "Как в системе"),
    ("ru", "Русский"),
    ("en", "English"),
    ("uk", "Українська"),
    ("de", "Deutsch"),
]

_lang = "ru"


def system_lang() -> str:
    try:
        from PyQt6.QtCore import QLocale

        code = QLocale.system().name().split("_")[0].lower()
    except Exception:  # noqa: BLE001 - без Qt (тесты, CLI) - русский
        return "ru"
    return code if code in TRANSLATIONS or code == "ru" else "en"


def set_lang(code: str) -> str:
    """Включает язык; "auto" - язык Windows. Возвращает итоговый код."""
    global _lang
    if not code or code == "auto":
        code = system_lang()
    _lang = code if code in TRANSLATIONS or code == "ru" else "ru"
    return _lang


def lang() -> str:
    return _lang


def tr(text: str, **kw) -> str:
    s = text if _lang == "ru" else TRANSLATIONS.get(_lang, {}).get(text, text)
    return s.format(**kw) if kw else s
