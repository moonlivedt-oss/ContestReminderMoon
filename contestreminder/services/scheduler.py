"""Таймер напоминаний: раз в 30 с прогоняет логику из core/reminders.py.

Если приложение было выключено и пропущено несколько порогов - одно уведомление
(самое срочное), а не пачка.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PyQt6.QtCore import QObject, QTimer

from ..core.models import Contest
from ..core.reminders import SNOOZED, digest, digest_due, due_reminders, to_close

NotifyFn = Callable[[Contest, int, bool], None]


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
