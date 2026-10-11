"""Планировщик напоминаний.

Раз в 30 секунд проверяет конкурсы. Для конкурса берём смещения (reminders) —
минуты до дедлайна. Смещение «наступило», когда now >= deadline - offset. Все
наступившие, но ещё не показанные смещения помечаем как показанные, а тост
выводим только для самого срочного из них — чтобы после простоя приложения не
сыпать пачкой уведомлений.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, QTimer

from .models import Contest

# (contest, offset_minutes, expired) -> показать уведомление
NotifyFn = Callable[[Contest, int, bool], None]


class ReminderScheduler(QObject):
    def __init__(self, get_contests: Callable[[], list[Contest]],
                 notify: NotifyFn, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._get = get_contests
        self._notify = notify
        self._on_changed = on_changed
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.tick)

    def start(self) -> None:
        self._timer.start()
        QTimer.singleShot(1500, self.tick)  # первый прогон вскоре после старта

    def tick(self) -> None:
        now = datetime.now()
        changed = False
        for c in self._get():
            if c.done or not c.deadline_dt:
                continue
            deadline = c.deadline_dt
            due = [off for off in c.reminders
                   if off not in c.notified and now >= deadline - timedelta(minutes=off)]
            if not due:
                continue
            # самый срочный = наименьшее смещение (ближе всего к дедлайну)
            fire = min(due)
            for off in due:
                c.notified.append(off)
            changed = True
            self._notify(c, fire, deadline < now)
        if changed:
            self._on_changed()
