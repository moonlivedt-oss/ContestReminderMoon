"""Разбор произвольного текста (из буфера или OCR) в поля конкурса.

Достаёт:
  * url        — первая http(s)-ссылка;
  * deadline   — дата/время дедлайна (RU и EN формы, абсолютные и относительные);
  * title      — осмысленная первая строка;
  * keyword    — есть ли в тексте маркер конкурса (для авто-срабатывания).

Год у дат без года достраивается: если получившийся момент уже прошёл — берём
следующий год (дедлайны всегда в будущем). Если времени нет — ставим 23:59.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# --- словари месяцев ----------------------------------------------------
# Список префиксов -> номер месяца. Порядок важен: длинные стемы раньше.
_MONTHS = [
    (("январ", "янв", "january", "jan"), 1),
    (("феврал", "фев", "february", "feb"), 2),
    (("март", "мар", "march", "mar"), 3),
    (("апрел", "апр", "april", "apr"), 4),
    (("мая", "мае", "май", "may"), 5),
    (("июн", "june", "jun"), 6),
    (("июл", "july", "jul"), 7),
    (("август", "авг", "august", "aug"), 8),
    (("сентябр", "сент", "сен", "september", "sept", "sep"), 9),
    (("октябр", "окт", "october", "oct"), 10),
    (("ноябр", "ноя", "november", "nov"), 11),
    (("декабр", "дек", "december", "dec"), 12),
]

_KEYWORDS = (
    "конкурс", "розыгрыш", "giveaway", "раздач", "дедлайн", "deadline",
    "приём работ", "прием работ", "заявки", "заявку", "подать", "submission",
    "submit", "хакатон", "hackathon", "челлендж", "challenge", "приз", "prize",
)

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
# Ссылка без схемы, как её пишут в постах: vk.com/club1, t.me/chan, www.site.ru.
# Нужен путь после домена или www. - иначе «PS5.Конкурс» сошло бы за адрес.
_BARE_URL_RE = re.compile(
    r"(?<![\w@./])(?:www\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-zрф]{2,}(?:/[^\s<>\"')]*)?"
    r"|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ru|me|io|org|net|cc|gg|su|рф|dev|app|art|xyz|ly|tv|by|kz|ua)"
    r"/[^\s<>\"')]*)",
    re.IGNORECASE)
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_NUM_DATE_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
# "15 сентября [2026]" / "20 September [2026]"
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+([А-Яа-яЁёA-Za-z]{3,12})\.?(?:\s+(\d{4}))?", re.IGNORECASE)
# "September 20[, 2026]" — только для латиницы
_MONTH_DAY_RE = re.compile(
    r"\b([A-Za-z]{3,12})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?", re.IGNORECASE)
# относительные: "осталось 3 дня", "через 2 недели", "in 5 days", "ends in 2 hours"
_REL_RE = re.compile(
    r"(?:осталось|остал[оa]сь|через|in|ends?\s+in|within)\s+(\d+)\s+"
    r"(дн|день|дня|дней|час|часа|часов|недел|минут|day|days|hour|hours|week|weeks|minute|minutes)",
    re.IGNORECASE)


@dataclass
class Parsed:
    title: str = ""
    url: str = ""
    deadline: datetime | None = None
    deadline_text: str = ""       # что именно распознали как дату (для подсветки)
    has_keyword: bool = False

    @property
    def is_contest_like(self) -> bool:
        """Похоже ли на конкурс достаточно, чтобы предложить сохранить."""
        return self.has_keyword or (bool(self.url) and self.deadline is not None) \
            or self.deadline is not None


def _month_from_word(word: str) -> int | None:
    w = word.lower()
    for prefixes, num in _MONTHS:
        if any(w.startswith(p) for p in prefixes):
            return num
    return None


def _fix_year(dt: datetime) -> datetime:
    """Если дата уже заметно в прошлом — переносим на следующий год."""
    if dt < datetime.now() - timedelta(hours=12):
        try:
            return dt.replace(year=dt.year + 1)
        except ValueError:  # 29 февраля
            return dt.replace(year=dt.year + 1, day=28)
    return dt


def _make(year: int | None, month: int, day: int) -> datetime | None:
    now = datetime.now()
    y = year if year else now.year
    if year and year < 100:
        y += 2000
    try:
        dt = datetime(y, month, day, 23, 59)
    except ValueError:
        return None
    return dt if year else _fix_year(dt)


def _find_date(text: str) -> tuple[datetime | None, str]:
    """Ищем первую правдоподобную дату. Возвращаем (datetime|None, matched_text)."""
    # 1) ISO yyyy-mm-dd
    m = _ISO_RE.search(text)
    if m:
        dt = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return dt, m.group(0)
    # 2) "15 сентября [год]" / "20 September [год]"
    for m in _DAY_MONTH_RE.finditer(text):
        month = _month_from_word(m.group(2))
        if month:
            dt = _make(int(m.group(3)) if m.group(3) else None, month, int(m.group(1)))
            if dt:
                return dt, m.group(0)
    # 3) "September 20[, год]"
    for m in _MONTH_DAY_RE.finditer(text):
        month = _month_from_word(m.group(1))
        if month:
            dt = _make(int(m.group(3)) if m.group(3) else None, month, int(m.group(2)))
            if dt:
                return dt, m.group(0)
    # 4) числовая dd.mm[.yyyy] (день.месяц — рус. порядок)
    for m in _NUM_DATE_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            dt = _make(int(m.group(3)) if m.group(3) else None, month, day)
            if dt:
                return dt, m.group(0)
    # 5) относительные
    m = _REL_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith(("недел", "week")):
            delta = timedelta(weeks=n)
        elif unit.startswith(("час", "hour")):
            delta = timedelta(hours=n)
        elif unit.startswith(("минут", "minute")):
            delta = timedelta(minutes=n)
        else:
            delta = timedelta(days=n)
        return datetime.now() + delta, m.group(0)
    return None, ""


def _attach_time(dt: datetime, text: str, date_span: str) -> datetime:
    """Если рядом с датой есть 'в HH:MM' — уточняем время (иначе остаётся 23:59)."""
    # ищем время во всём тексте; берём первое валидное
    for tm in _TIME_RE.finditer(text):
        h, mnt = int(tm.group(1)), int(tm.group(2))
        if 0 <= h <= 23 and 0 <= mnt <= 59:
            return dt.replace(hour=h, minute=mnt)
    return dt


def _extract_title(text: str, url: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        stripped = re.sub(r"\s{2,}", " ", _BARE_URL_RE.sub("", _URL_RE.sub("", ln))).strip(" -–—:·|,")
        if len(stripped) >= 3:
            return stripped[:90]
    if lines:
        return lines[0][:90]
    return "(без названия)"


def parse(text: str) -> Parsed:
    text = (text or "").strip()
    if not text:
        return Parsed()
    low = text.lower()

    url_match = _URL_RE.search(text)
    url = url_match.group(0).rstrip(".,)!") if url_match else ""
    if not url:
        bare = _BARE_URL_RE.search(text)
        if bare:
            url = "https://" + bare.group(0).rstrip(".,)!")

    dt, span = _find_date(text)
    if dt is not None:
        dt = _attach_time(dt, text, span).replace(second=0, microsecond=0)

    return Parsed(
        title=_extract_title(text, url),
        url=url,
        deadline=dt,
        deadline_text=span,
        has_keyword=any(k in low for k in _KEYWORDS),
    )


if __name__ == "__main__":  # быстрый ручной прогон парсера
    samples = [
        "Конкурс арта! Приём работ до 15 сентября в 23:59. https://example.com/art",
        "Розыгрыш PS5, дедлайн 20.09.2026, участвуй тут vk.com/xxx",
        "Giveaway ends September 30! https://site.io/win",
        "Хакатон, осталось 3 дня до конца регистрации",
        "Просто скопированный текст без конкурса",
        "Заявки до 05.10 https://t.me/chan",
        "Submit your entry before 2026-12-01 18:00",
        "Челлендж недели: через 2 недели подведём итоги",
    ]
    for s in samples:
        p = parse(s)
        print(f"\n> {s}")
        print(f"  title={p.title!r}")
        print(f"  url={p.url!r}")
        print(f"  deadline={p.deadline}  (matched {p.deadline_text!r})")
        print(f"  keyword={p.has_keyword}  contest_like={p.is_contest_like}")
