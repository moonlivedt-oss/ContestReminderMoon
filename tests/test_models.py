"""Модель конкурса, форматтеры и автозапуск."""
from datetime import datetime, timedelta

from contestreminder.core.models import Contest, fmt_countdown, fmt_offset
from contestreminder.services import autostart


def test_roundtrip_dict():
    c = Contest(title="Арт", url="https://x.io", deadline="2030-01-02T03:04:00",
                reminders=[60, 0], notified=[60])
    d = Contest.from_dict(c.to_dict())
    assert d == c


def test_from_dict_defaults_and_bad_deadline():
    c = Contest.from_dict({"deadline": "не дата"})
    assert c.title == "(без названия)"
    assert c.deadline_dt is None
    assert not c.is_expired


def test_fmt_offset():
    assert fmt_offset(0) == "в момент"
    assert fmt_offset(1440) == "за 1 дн"
    assert fmt_offset(60) == "за 1 ч"
    assert fmt_offset(15) == "за 15 мин"


def test_fmt_countdown():
    assert fmt_countdown(None) == "срок не задан"
    assert fmt_countdown(datetime.now() + timedelta(days=2, hours=5)).startswith("через 2 дн")
    assert fmt_countdown(datetime.now() - timedelta(days=3)) == "истёк 3 дн назад"


def test_autostart_command_starts_in_tray():
    cmd = autostart.command()
    assert cmd.endswith(autostart.TRAY_FLAG)
    assert "run.pyw" in cmd
