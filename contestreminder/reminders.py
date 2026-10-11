"""Планировщик: напоминания по порогам, отложенные напоминания, сводка дня, автоархив.

Раз в 30 с (и вскоре после старта) смотрим все конкурсы. Если приложение было
выключено и пропущено несколько порогов - шлём одно уведомление (самое срочное),
а не пачку. Логика времени - в чистых функциях (`due_reminders`, `digest`,
`to_close`), их проверяют тесты без таймеров.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, QTimer

from .models import Contest

NotifyFn = Callable[[Contest, int, bool], None]
SNOOZED = -1  # смещение «отложенного» напоминания


def due_reminders(c: Contest, now: datetime) -> tuple[int | None, list[int]]:
    """(что показать, какие пороги отметить). Отложенное важнее порогов."""
    if c.done:
        return None, []
    snooze = c.snoozed_dt
    if snooze is not None and now >= snooze:
        return SNOOZED, []
    deadline = c.deadline_dt
    if deadline is None:
        return None, []
    due = [
        off
        for off in c.reminders
        if off not in c.notified and now >= deadline - timedelta(minutes=off)
    ]
    if not due:
        return None, []
    return min(due), due  # самый срочный = ближе всего к дедлайну


def to_close(contests: list[Contest], now: datetime, after_days: int) -> list[Contest]:
    """Незакрытые конкурсы, дедлайн которых прошёл больше after_days дней назад."""
    if after_days <= 0:
        return []
    edge = now - timedelta(days=after_days)
    return [
        c for c in contests if not c.done and c.deadline_dt is not None and c.deadline_dt < edge
    ]


def digest(contests: list[Contest], now: datetime, days: int = 3) -> list[Contest]:
    """Активные конкурсы с дедлайном в ближайшие `days` дней, по возрастанию срока."""
    edge = now + timedelta(days=days)
    soon = [
        c
        for c in contests
        if not c.done and c.deadline_dt is not None and now <= c.deadline_dt <= edge
    ]
    return sorted(soon, key=lambda c: c.deadline_dt)


def digest_due(now: datetime, at: str, last: str) -> bool:
    """Пора ли показать сводку: время «ЧЧ:ММ» сегодня наступило, а сегодня её ещё не было."""
    if not at:
        return False
    try:
        h, m = (int(x) for x in at.split(":"))
    except ValueError:
        return False
    today = now.date().isoformat()
    return last != today and now >= now.replace(hour=h, minute=m, second=0, microsecond=0)


class ReminderScheduler(QObject):
    def __init__(
        self,
        get_contests: Callable[[], list[Contest]],
        notify: NotifyFn,
        on_changed: Callable[[], None],
        get_settings: Callable[[], dict] | None = None,
        on_digest: Callable[[list[Contest]], None] | None = None,
        on_closed: Callable[[list[Contest]], None] | None = None,
    ) -> None:
        super().__init__()
        self._get = get_contests
        self._notify = notify
        self._on_changed = on_changed
        self._settings = get_settings or (lambda: {})
        self._on_digest = on_digest
        self._on_closed = on_closed
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.tick)

    def start(self) -> None:
        self._timer.start()
        QTimer.singleShot(1500, self.tick)  # первый прогон вскоре после старта

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        changed = False
        contests = self._get()
        for c in contests:
            fire, mark = due_reminders(c, now)
            if fire is None:
                continue
            if fire == SNOOZED:
                c.snoozed_until = None
            for off in mark:
                c.notified.append(off)
            changed = True
            deadline = c.deadline_dt
            self._notify(c, fire, deadline is not None and deadline < now)

        st = self._settings()
        closed = to_close(contests, now, int(st.get("auto_close_days", 3)))
        for c in closed:
            c.done = True
            c.auto_closed = True
        if closed:
            changed = True
            if self._on_closed:
                self._on_closed(closed)

        if self._on_digest and digest_due(
            now, st.get("digest_time", ""), st.get("digest_last", "")
        ):
            st["digest_last"] = now.date().isoformat()   # сохраняет вызывающий в on_digest
            self._on_digest(digest(contests, now, int(st.get("digest_days", 3))))
            changed = True
        if changed:
            self._on_changed()
