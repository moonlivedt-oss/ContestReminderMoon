"""Снимки окон для README: py -3.11 tools/screenshots.py

Берёт демо-конкурсы во временной папке (настоящие данные не трогает), снимает
главное окно в тёмной и светлой теме, пустой список, окно правки, настройки,
всплывающие карточки и английский интерфейс - в docs/.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TMP = Path(tempfile.mkdtemp(prefix="cr-shots-"))
os.environ["APPDATA"] = str(TMP / "roaming")
os.environ["LOCALAPPDATA"] = str(TMP / "local")
sys.path.insert(0, str(ROOT))
sys.argv = [sys.argv[0], "--tray"]

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QTabWidget  # noqa: E402

from contestreminder.core import config  # noqa: E402
from contestreminder.core.models import Contest  # noqa: E402


def demo() -> list[Contest]:
    n = datetime.now().replace(second=0, microsecond=0)

    def iso(d: timedelta) -> str:
        return (n + d).isoformat()

    return [
        Contest(
            title="Литературный конкурс рассказов",
            deadline=iso(timedelta(days=-1)),
            reminders=[0],
            notified=[0],
            created=iso(timedelta(days=-10)),
        ),
        Contest(
            title="Хакатон «Код за выходные»",
            url="https://t.me/hack/42",
            deadline=iso(timedelta(hours=5)),
            reminders=[1440, 60, 0],
            created=iso(timedelta(days=-6)),
        ),
        Contest(
            title="Олимпиада по программированию",
            deadline=iso(timedelta(days=1, hours=8)),
            reminders=[1440],
            snoozed_until=iso(timedelta(hours=3)),
            created=iso(timedelta(days=-3)),
        ),
        Contest(
            title="Конкурс арта: осенний пейзаж",
            url="https://example.com/art",
            deadline=iso(timedelta(days=4, hours=3)),
            reminders=[1440, 60, 0],
            created=iso(timedelta(days=-4)),
        ),
        Contest(
            title="Giveaway: графический планшет",
            url="https://site.io/win",
            deadline=iso(timedelta(days=12)),
            reminders=[1440, 0],
            created=iso(timedelta(days=-2)),
        ),
        Contest(title="Грант на инди-игру", url="https://grants.example.org/indie", reminders=[]),
    ]


def main() -> None:
    (TMP / "roaming" / "ContestReminder").mkdir(parents=True)
    config.save_settings(
        {
            **config.DEFAULT_SETTINGS,
            "digest_time": "",
            "bridge_port": 47693,
            "notify_style": "toast",
            "lang": "ru",
            "theme": "dark",
        }
    )
    config.save_contests(demo())

    from contestreminder.app import App
    from contestreminder.ui.editor import ContestDialog
    from contestreminder.ui.settings_dialog import SettingsDialog

    a = App()
    steps = []

    def window(name: str, w: int = 640, h: int = 760) -> None:
        a.win.resize(w, h)
        a.win.move(-4000, 40)
        a.win.show()
        steps.append(lambda: a.win.grab().save(str(DOCS / name)))

    def dialog(dlg, name: str) -> None:
        dlg.move(-4000, 40)
        dlg.show()
        dlg.adjustSize()
        steps.append(lambda: (dlg.grab().save(str(DOCS / name)), dlg.close()))

    def themes_tab() -> None:
        dlg = SettingsDialog(a.win, dict(a.settings), native_ok=True)
        dlg.findChild(QTabWidget).setCurrentIndex(1)
        dialog(dlg, "themes.png")

    def toasts() -> None:
        a.capture(
            "Розыгрыш наушников! Принимаем заявки до 25 ноября в 18:00 https://vk.com/wall-1_2",
            "manual",
        )
        a._notify(a.contests[1], 60, False)

        def save() -> None:
            ts = a.toasts._toasts
            h = sum(t.height() for t in ts) + 12 * (len(ts) + 1)
            pm = QPixmap(384, h)
            pm.fill(QColor("#11111b"))
            p = QPainter(pm)
            y = 12
            for t in ts:
                p.drawPixmap(12, y, t.grab())
                y += t.height() + 12
            p.end()
            pm.save(str(DOCS / "toasts.png"))
            a.toasts.close_all()

        steps.append(save)

    plan = [
        lambda: window("screenshot.png"),
        lambda: dialog(ContestDialog(a.win, contest=a.contests[3]), "editor.png"),
        lambda: dialog(SettingsDialog(a.win, dict(a.settings), native_ok=True), "settings.png"),
        lambda: themes_tab(),
        toasts,
        lambda: (a.set_theme("light"), window("screenshot-light.png")),
        lambda: (setattr(a, "contests", []), a.refresh(), window("empty.png", 640, 620)),
        lambda: (setattr(a, "contests", demo()), a.set_theme("sepia", "forest"), window("screenshot-sepia.png")),
        lambda: (a.set_theme("dark", "sunset"), window("screenshot-sunset.png")),
        lambda: (
            setattr(a, "contests", demo()),
            a.set_theme("dark"),
            a.set_language("en"),
            window("screenshot-en.png"),
        ),
    ]

    def run(i: int = 0) -> None:
        for step in steps:
            step()
        steps.clear()
        if i < len(plan):
            plan[i]()
            QTimer.singleShot(600, lambda: run(i + 1))
        else:
            a.quit()

    QTimer.singleShot(800, run)
    a.run()
    print("docs:", ", ".join(sorted(p.name for p in DOCS.glob("*.png"))))


if __name__ == "__main__":
    main()
