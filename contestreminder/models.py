"""Модель конкурса и вспомогательные форматтеры дат/обратного отсчёта."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .i18n import tr


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Contest:
    title: str
    url: str = ""
    deadline: str | None = None          # ISO-строка момента дедлайна или None
    source_text: str = ""                # исходный текст, из которого распарсили
    reminders: list[int] = field(default_factory=list)  # за сколько минут до дедлайна
    notified: list[int] = field(default_factory=list)    # какие смещения уже сработали
    done: bool = False
    created: str = field(default_factory=_now_iso)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    snoozed_until: str | None = None     # «Отложить»: повторить напоминание в этот момент
    auto_closed: bool = False            # закрыт сам после дедлайна (а не кнопкой «Готово»)

    # --- сериализация ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "deadline": self.deadline, "source_text": self.source_text,
            "reminders": self.reminders, "notified": self.notified,
            "done": self.done, "created": self.created,
            "snoozed_until": self.snoozed_until, "auto_closed": self.auto_closed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Contest:
        return cls(
            id=d.get("id") or uuid.uuid4().hex[:12],
            title=d.get("title") or "(без названия)",
            url=d.get("url", ""),
            deadline=d.get("deadline"),
            source_text=d.get("source_text", ""),
            reminders=list(d.get("reminders", [])),
            notified=list(d.get("notified", [])),
            done=bool(d.get("done", False)),
            created=d.get("created") or _now_iso(),
            snoozed_until=d.get("snoozed_until"),
            auto_closed=bool(d.get("auto_closed", False)),
        )

    # --- удобные свойства ----------------------------------------------
    @property
    def deadline_dt(self) -> datetime | None:
        if not self.deadline:
            return None
        try:
            return datetime.fromisoformat(self.deadline)
        except ValueError:
            return None

    @property
    def snoozed_dt(self) -> datetime | None:
        if not self.snoozed_until:
            return None
        try:
            return datetime.fromisoformat(self.snoozed_until)
        except ValueError:
            return None

    @property
    def is_expired(self) -> bool:
        dt = self.deadline_dt
        return dt is not None and dt < datetime.now()


# --- форматтеры для UI --------------------------------------------------

def fmt_deadline(dt: datetime | None) -> str:
    if dt is None:
        return tr("без срока")
    return dt.strftime("%d.%m.%Y  %H:%M")


def fmt_countdown(dt: datetime | None, now: datetime | None = None) -> str:
    """Человекочитаемый остаток времени: 'через 2 дн 4 ч', 'истёк' и т.п."""
    if dt is None:
        return tr("срок не задан")
    secs = (dt - (now or datetime.now())).total_seconds()
    if secs < 0:
        past = -secs
        if past < 3600:
            return tr("истёк только что")
        if past < 86400:
            return tr("истёк {n} ч назад", n=int(past // 3600))
        return tr("истёк {n} дн назад", n=int(past // 86400))
    days = int(secs // 86400)
    hours = int((secs % 86400) // 3600)
    mins = int((secs % 3600) // 60)
    if days:
        return tr("через {d} дн {h} ч", d=days, h=hours)
    if hours:
        return tr("через {h} ч {m} мин", h=hours, m=mins)
    return tr("через {m} мин", m=mins)


def fmt_offset(minutes: int) -> str:
    """Подпись смещения напоминания: 0 -> 'в момент', 60 -> 'за 1 ч'."""
    if minutes <= 0:
        return tr("в момент")
    if minutes % 1440 == 0:
        return tr("за {n} дн", n=minutes // 1440)
    if minutes % 60 == 0:
        return tr("за {n} ч", n=minutes // 60)
    return tr("за {n} мин", n=minutes)
