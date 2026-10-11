"""Логика напоминаний без Qt: пороги, «Отложить», сводка дня, автозакрытие.

Чистые функции от «сейчас» - их проверяют тесты без таймеров, а C++-сторож
(native/crnative.cpp) повторяет due_reminders один в один. Таймер, который их
вызывает, - services/scheduler.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import Contest

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
