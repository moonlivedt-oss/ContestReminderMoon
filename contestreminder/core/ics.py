"""Экспорт в календарь (.ics, RFC 5545): Google/Outlook/Календарь Windows открывают его сами.

Каждый конкурс со сроком - событие на 30 минут, заканчивающееся в момент дедлайна,
с напоминаниями (VALARM) из настроек конкурса. Время пишем «плавающим» (без зоны):
календарь покажет его в местном времени, как и в программе.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import Contest


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Строки длиннее 75 байт переносятся с пробелом в начале продолжения."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return out


def _dt(d: datetime) -> str:
    return d.strftime("%Y%m%dT%H%M%S")


def build_ics(contests: list[Contest], now: datetime | None = None) -> str:
    now = now or datetime.now()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ContestReminder//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for c in contests:
        end = c.deadline_dt
        if end is None:
            continue
        desc = []
        if c.url:
            desc.append(c.url)
        if c.source_text:
            desc.append(c.source_text[:600])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{c.id}@contestreminder",
            f"DTSTAMP:{_dt(now)}",
            f"DTSTART:{_dt(end - timedelta(minutes=30))}",
            f"DTEND:{_dt(end)}",
            f"SUMMARY:{_esc('Дедлайн: ' + c.title)}",
        ]
        if c.url:
            lines.append(f"URL:{c.url}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
        for minutes in sorted(set(c.reminders), reverse=True):
            # VALARM считается от начала события, а оно за 30 мин до дедлайна
            before = max(0, minutes - 30)
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_esc(c.title)}",
                f"TRIGGER:-PT{before}M",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded = []
    for ln in lines:
        folded += _fold(ln)
    return "\r\n".join(folded) + "\r\n"
