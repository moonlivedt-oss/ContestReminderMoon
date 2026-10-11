"""Самопроверка сборки: `ContestReminder.exe --selftest` (или `py run.pyw --selftest`).

Ничего не показывает и не трогает данные пользователя. Проверяет то, что ломается
именно в exe: модули Windows OCR (winsdk грузит их лениво), значки и шаблон
userscript внутри сборки, Qt-плагины, парсер. Итог - код выхода (0 - всё в порядке)
и отчёт в файле, путь к которому передан после ключа (у exe без консоли нет stdout).
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

FLAG = "--selftest"


def _checks() -> list[tuple[str, object]]:
    def ocr_modules() -> None:
        for name in (
            "winsdk.windows.globalization",
            "winsdk.windows.graphics.imaging",
            "winsdk.windows.media.ocr",
            "winsdk.windows.storage.streams",
        ):
            importlib.import_module(name)

    def ocr_engine() -> None:
        from winsdk.windows.media.ocr import OcrEngine

        # языковых пакетов на машине может не быть - важно, что WinRT отвечает
        OcrEngine.available_recognizer_languages  # noqa: B018

    def screen_capture() -> None:
        import mss

        with mss.mss() as sct:
            assert sct.monitors

    def assets() -> None:
        from .icons import _ASSETS

        for name in ("bell", "add", "check", "arrow-down"):
            assert (_ASSETS / f"{name}.png").exists(), name
        assert (_ASSETS / "app.ico").exists()

    def userscript() -> None:
        from .app import userscript_template

        assert "__TOKEN__" in userscript_template().read_text("utf-8")

    def qt() -> None:
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QApplication

        from .icons import app_icon
        from .theme import build_qss

        qapp = QApplication.instance() or QApplication(["selftest"])
        qapp.setStyleSheet(build_qss())
        assert not app_icon().isNull()
        assert isinstance(QIcon(), QIcon)

    def parser() -> None:
        from .parser import parse

        p = parse("Конкурс до 15 ноября 2030 в 18:00 https://example.com")
        assert p.deadline and p.deadline.hour == 18 and p.url

    def translations() -> None:
        from .i18n import set_lang, tr

        assert set_lang("de") == "de" and tr("Сохранить") == "Speichern"
        set_lang("ru")

    return [
        ("OCR: модули winsdk", ocr_modules),
        ("OCR: WinRT", ocr_engine),
        ("захват экрана (mss)", screen_capture),
        ("значки", assets),
        ("шаблон userscript", userscript),
        ("Qt и оформление", qt),
        ("парсер", parser),
        ("переводы", translations),
    ]


def run(argv: list[str]) -> int:
    out = []
    failed = 0
    for name, fn in _checks():
        try:
            fn()
            out.append(f"ok    {name}")
        except Exception:  # noqa: BLE001 - отчёт о любой поломке сборки
            failed += 1
            out.append(f"FAIL  {name}\n{traceback.format_exc()}")
    out.append(
        f"\n{'OK' if not failed else f'{failed} FAIL'} ({'exe' if getattr(sys, 'frozen', False) else 'py'})"
    )
    report = "\n".join(out)
    idx = argv.index(FLAG)
    if idx + 1 < len(argv):
        Path(argv[idx + 1]).write_text(report, "utf-8")
    elif sys.stdout is not None:
        print(report)
    return 1 if failed else 0
