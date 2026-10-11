"""Планировщик: после простоя шлёт одно самое срочное напоминание, а не пачку."""
from datetime import datetime, timedelta

from PyQt6.QtCore import QCoreApplication

from contestreminder.models import Contest
from contestreminder.reminders import ReminderScheduler

app = QCoreApplication.instance() or QCoreApplication([])


def _run(contests):
    sent, changed = [], []
    s = ReminderScheduler(lambda: contests, lambda c, off, exp: sent.append((c.id, off, exp)),
                          lambda: changed.append(1))
    s.tick()
    return sent, changed


def test_missed_thresholds_fire_once():
    dl = (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds")
    c = Contest(title="t", deadline=dl, reminders=[1440, 60, 0])
    sent, changed = _run([c])
    assert sent == [(c.id, 60, False)]
    assert sorted(c.notified) == [60, 1440]
    assert changed
    sent, _ = _run([c])  # повторный тик ничего не шлёт
    assert sent == []


def test_done_and_undated_skipped():
    dl = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    sent, changed = _run([Contest(title="a", deadline=dl, reminders=[0], done=True),
                          Contest(title="b", reminders=[0])])
    assert sent == [] and changed == []


def test_expired_flag():
    dl = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    c = Contest(title="t", deadline=dl, reminders=[0])
    sent, _ = _run([c])
    assert sent == [(c.id, 0, True)]
