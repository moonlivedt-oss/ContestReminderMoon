"""Карточка конкурса в списке и раскладка списка по группам срока.

Карточка в три строки: название и обратный отсчёт; дата, ссылка и действия;
шкала «сколько времени прошло от записи до дедлайна». Цвет полосы слева, плашки
отсчёта и шкалы - по срочности (`urgency`), сами цвета - в ui/theme.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core.i18n import tr
from ..core.models import Contest, fmt_countdown, fmt_deadline, fmt_offset
from .icons import asset_icon
from .theme import current

if TYPE_CHECKING:
    from ..app import App


def group_of(c: Contest, now: datetime) -> str:
    """Группа в списке: по близости дедлайна."""
    if c.done:
        return tr("Выполненные")
    dt = c.deadline_dt
    if dt is None:
        return tr("Без срока")
    if dt < now:
        return tr("Прошли")
    if dt.date() == now.date():
        return tr("Сегодня")
    if dt.date() == (now + timedelta(days=1)).date():
        return tr("Завтра")
    if dt < now + timedelta(days=7):
        return tr("На этой неделе")
    return tr("Позже")


def urgency_of(c: Contest, now: datetime) -> str:
    """overdue / today / soon / later / none / done - для цвета полосы и шкалы."""
    if c.done:
        return "done"
    dt = c.deadline_dt
    if dt is None:
        return "none"
    left = (dt - now).total_seconds()
    if left < 0:
        return "overdue"
    if left < 86400:
        return "today"
    if left < 3 * 86400:
        return "soon"
    return "later"


def elapsed_share(c: Contest, now: datetime) -> float:
    """Какая часть времени от записи до дедлайна уже прошла (0..1)."""
    dt = c.deadline_dt
    if dt is None:
        return 0.0
    try:
        start = datetime.fromisoformat(c.created)
    except ValueError:
        start = dt - timedelta(days=7)
    total = (dt - start).total_seconds()
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, (now - start).total_seconds() / total))


def matches(c: Contest, query: str) -> bool:
    q = query.strip().lower().replace("ё", "е")
    if not q:
        return True
    hay = " ".join((c.title, c.url, c.source_text)).lower().replace("ё", "е")
    return all(word in hay for word in q.split())


_CHIP = {
    "overdue": "chipErr",
    "today": "chipToday",
    "soon": "chipWarn",
    "later": "chip",
    "none": "chipNone",
    "done": "chipOk",
}


class ContestCard(QFrame):
    def __init__(self, contest: Contest, app: App, now: datetime | None = None) -> None:
        super().__init__()
        now = now or datetime.now()
        self.setObjectName("contestCard")
        urgency = urgency_of(contest, now)
        self.setProperty("urgency", urgency)
        self.setProperty("done", contest.done)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: app.card_menu(contest, self.mapToGlobal(pos))
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 10, 11)
        lay.setSpacing(7)

        # строка 1: название и отсчёт
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(contest.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setProperty("done", contest.done)
        if contest.url:
            title.setProperty("link", True)
            title.setCursor(Qt.CursorShape.PointingHandCursor)
            title.setToolTip(tr("Открыть: {url}", url=contest.url))
            title.mousePressEvent = lambda e: (
                app.open_url(contest) if e.button() == Qt.MouseButton.LeftButton else None
            )
        top.addWidget(title, 1)

        dt = contest.deadline_dt
        if contest.done:
            chip_text = tr("закрыт сам после срока") if contest.auto_closed else tr("готово")
        else:
            chip_text = fmt_countdown(dt, now)
        chip = QLabel(chip_text)
        chip.setObjectName(_CHIP[urgency])
        if contest.reminders and dt and not contest.done:
            chip.setToolTip(
                tr("напоминания: {list}", list=", ".join(fmt_offset(m) for m in contest.reminders))
            )
        top.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        # строка 2: дата, ссылка, отложено - и действия справа
        meta = QHBoxLayout()
        meta.setSpacing(6)
        parts: list[QLabel] = []
        if dt:
            parts.append(self._muted(fmt_deadline(dt)))
        if contest.url:
            accent = current()["accent"]
            link = QLabel(
                f'<a style="color:{accent};text-decoration:none" '
                f'href="{contest.url}">{self._short_url(contest.url)}</a>'
            )
            link.setObjectName("link")
            link.setToolTip(contest.url)
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            parts.append(link)
        if contest.snoozed_dt and not contest.done:
            parts.append(
                self._muted(tr("отложено до {t}", t=contest.snoozed_dt.strftime("%d.%m %H:%M")))
            )
        for i, w in enumerate(parts):
            if i:
                meta.addWidget(self._muted("|", "faint"))
            meta.addWidget(w)
        meta.addStretch(1)

        def icon_btn(icon: str, tip: str, name: str, slot) -> None:
            btn = QPushButton()
            btn.setObjectName(name)
            btn.setIcon(asset_icon(icon))
            btn.setIconSize(QSize(17, 17))
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            meta.addWidget(btn)

        icon_btn(
            "done",
            tr("Вернуть") if contest.done else tr("Готово"),
            "iconBtn",
            lambda: app.toggle_done(contest),
        )
        icon_btn("edit", tr("Изменить"), "iconBtn", lambda: app.edit_contest(contest))
        icon_btn("delete", tr("Удалить"), "iconDanger", lambda: app.delete_contest(contest))
        lay.addLayout(meta)

        # строка 3: шкала времени (только у активных со сроком)
        if dt and not contest.done:
            bar = QProgressBar()
            bar.setObjectName("timeBar")
            bar.setProperty("urgency", urgency)
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(int(elapsed_share(contest, now) * 1000))
            bar.setToolTip(tr("Сколько времени прошло от записи до дедлайна"))
            lay.addWidget(bar)

    @staticmethod
    def _muted(text: str, name: str = "muted") -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(name)
        return lbl

    @staticmethod
    def _short_url(url: str) -> str:
        u = url.replace("https://", "").replace("http://", "").removeprefix("www.")
        return u[:40] + ("…" if len(u) > 40 else "")
