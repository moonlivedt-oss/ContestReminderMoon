"""Разбор произвольного текста (из буфера, OCR или страницы) в поля конкурса.

Достаёт:
  * url        - первая http(s)-ссылка или адрес без схемы (vk.com/..., t.me/...);
  * deadline   - дата/время дедлайна (RU и EN формы, абсолютные и относительные);
  * title      - осмысленная строка-заголовок;
  * keyword    - есть ли в тексте маркер конкурса (для авто-срабатывания).

Дат в посте часто несколько («старт 1 октября, приём до 15 октября, итоги 20-го»),
поэтому собираем всех кандидатов и выбираем по словам рядом: «до», «дедлайн»,
«ends» тянут дату вверх, «с», «старт», «итоги» - вниз.

Год у дат без года достраивается: если момент уже прошёл - берём следующий год
(дедлайны всегда в будущем). Время ищем рядом с датой; нет его - ставим 23:59.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# --- словари -------------------------------------------------------------
# Языки постов: русский, английский, украинский, немецкий.
# Список префиксов -> номер месяца. Порядок важен: длинные стемы раньше.
# fmt: off
_MONTHS = [
    (("январ", "янв", "січ", "january", "januar", "jänner", "jan"), 1),
    (("феврал", "фев", "лют", "february", "februar", "feb"), 2),
    (("март", "мар", "берез", "march", "märz", "maerz", "mar"), 3),
    (("апрел", "апр", "квіт", "april", "apr"), 4),
    (("мая", "мае", "май", "трав", "may", "mai"), 5),
    (("июн", "черв", "june", "juni", "jun"), 6),
    (("июл", "лип", "july", "juli", "jul"), 7),
    (("август", "авг", "серп", "august", "aug"), 8),
    (("сентябр", "сент", "сен", "верес", "september", "sept", "sep"), 9),
    (("октябр", "окт", "жовт", "october", "oktober", "oct", "okt"), 10),
    (("ноябр", "ноя", "листопад", "november", "nov"), 11),
    (("декабр", "дек", "груд", "december", "dezember", "dec", "dez"), 12),
]

# день недели -> номер (пн = 0); «до пятницы», «до п'ятниці», «bis Freitag», «until friday»
_WEEKDAYS = [
    (("понедельн", "понеділ", "monday", "montag", "mon"), 0),
    (("вторник", "вівтор", "tuesday", "dienstag", "tue"), 1),
    (("сред", "серед", "wednesday", "mittwoch", "wed"), 2),
    (("четверг", "четвер", "thursday", "donnerstag", "thu"), 3),
    (("пятниц", "friday", "freitag", "fri"), 4),
    (("суббот", "субот", "saturday", "samstag", "sonnabend", "sat"), 5),
    (("воскресен", "неділ", "sunday", "sonntag", "sun"), 6),
]

_KEYWORDS = (
    # ru
    "конкурс", "розыгрыш", "раздач", "дедлайн", "приём работ", "прием работ", "приём заявок",
    "прием заявок", "заявки", "заявку", "подать", "хакатон", "челлендж", "приз", "олимпиад",
    "турнир", "грант", "джем", "регистрац",
    # uk
    "розіграш", "заявк", "реєстрац", "олімпіад",
    # en
    "giveaway", "deadline", "submission", "submit", "hackathon", "challenge", "prize",
    "tournament", "contest", "competition", "jam", "registration",
    # de
    "gewinnspiel", "wettbewerb", "verlosung", "einsendeschluss", "teilnahmeschluss",
    "anmeldeschluss", "bewerbungsschluss", "preisausschreiben", "turnier",
)

# слова перед датой, которые делают её дедлайном (+) или началом/итогами (-)
_LAST_PLUS = ("до", "по", "until", "till", "before", "by", "due", "bis", "zum")
_BEFORE_PLUS = (
    "дедлайн", "deadline", "ends", "closes", "срок", "окончани", "заканчива", "завершит",
    "закончит", "успей", "последний день", "термін", "закінч", "останній день",
    "einsendeschluss", "teilnahmeschluss", "anmeldeschluss", "frist", "endet", "läuft",
)
_LAST_MINUS = ("с", "со", "от", "з", "із", "від", "from", "ab", "von", "seit")
_BEFORE_MINUS = (
    "старт", "start", "начал", "начнётся", "начнется", "открыт", "opens", "итог", "результат",
    "results", "объявим", "объявят", "подвед", "winners", "стрим", "эфир", "вебинар",
    "початок", "почина", "підсум", "оголос", "beginn", "startet", "ergebnis", "gewinner",
    "bekanntgabe", "livestream",
)
# fmt: on

_L = r"[^\W\d_]"  # любая буква (кириллица, латиница, ä/ö/ü/ß, і/ї/є/ґ)

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
# Ссылка без схемы, как её пишут в постах: vk.com/club1, t.me/chan, www.site.ru.
# Нужен путь после домена или www. - иначе «PS5.Конкурс» сошло бы за адрес.
_BARE_URL_RE = re.compile(
    r"(?<![\w@./])(?:www\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-zрф]{2,}(?:/[^\s<>\"')]*)?"
    r"|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ru|me|io|org|net|cc|gg|su|рф|dev|app|art|xyz|ly|tv|by|kz|ua|de|at|ch)"
    r"/[^\s<>\"')]*)",
    re.IGNORECASE,
)
# «18:00»; с точкой («18.00») - только после «в/о/um/at», иначе это дата 18 января
_TIME_RE = re.compile(
    r"(?<![\d.:])(\d{1,2}):(\d{2})(?![\d:])|(?:\bв|\bо|\bum|\bat)\s+(\d{1,2})\.(\d{2})(?![\d.])",
    re.IGNORECASE,
)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?\b")
# dd.mm.yyyy / dd/mm/yy; без года месяц двузначный («05.10»), иначе «3.5 млн» стало бы 3 мая
_NUM_DATE_RE = re.compile(
    r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{2,4})(?![\d.])"
    r"|(?<![\d.])(\d{1,2})[./](\d{2})(?![\d./])"
)
# "15 сентября [2026]" / "20 September" / "15-го октября" / "15. Oktober 2026"
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})(?:-?го|\.)?\s+(" + _L + r"{3,12})\.?(?:\s+(\d{4}))?", re.IGNORECASE
)
# "September 20[, 2026]" - только для латиницы
_MONTH_DAY_RE = re.compile(
    r"\b([A-Za-z]{3,12})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{4}))?", re.IGNORECASE
)
# относительные: "осталось 3 дня", "через 2 недели", "in 5 days", "noch 3 Tage"
_REL_RE = re.compile(
    r"(?:осталось|остал[оa]сь|залишилось|залишилося|через|in|ends?\s+in|within|noch)\s+(\d+)\s+"
    r"(дн|день|дня|дней|днів|дні|час|часа|часов|годин|недел|тижн|минут|хвилин"
    r"|day|days|hour|hours|week|weeks|minute|minutes"
    r"|tag|tage|tagen|stunde|stunden|woche|wochen|minute|minuten)",
    re.IGNORECASE,
)
_WORD_DAY_RE = re.compile(
    r"\b(сегодня|послезавтра|завтра|сьогодні|післязавтра|today|tonight|tomorrow"
    r"|heute|übermorgen|morgen)\b",
    re.IGNORECASE,
)
_WORD_DAY_SHIFT = {
    "сегодня": 0,
    "сьогодні": 0,
    "today": 0,
    "tonight": 0,
    "heute": 0,
    "завтра": 1,
    "tomorrow": 1,
    "morgen": 1,
    "послезавтра": 2,
    "післязавтра": 2,
    "übermorgen": 2,
}
_WEEKDAY_RE = re.compile(
    r"\b(?:до|в|во|к|у|until|till|by|on|this|bis|am|zum)\s+(" + _L + r"{3,12})\b", re.IGNORECASE
)
_END_OF_RE = re.compile(
    r"\b(?:до\s+)?конца\s+(недели|месяца|года)\b"
    r"|\b(?:до\s+)?кінця\s+(тижня|місяця|року)\b"
    r"|\bend\s+of\s+(?:the\s+)?(week|month|year)\b"
    r"|\bende\s+(?:der|des)\s+(woche|monats|jahres)\b",
    re.IGNORECASE,
)
_END_UNIT = {
    "недели": "w",
    "тижня": "w",
    "week": "w",
    "woche": "w",
    "месяца": "m",
    "місяця": "m",
    "month": "m",
    "monats": "m",
    "года": "y",
    "року": "y",
    "year": "y",
    "jahres": "y",
}


@dataclass
class Parsed:
    title: str = ""
    url: str = ""
    deadline: datetime | None = None
    deadline_text: str = ""  # что именно распознали как дату (для подсветки)
    has_keyword: bool = False

    @property
    def is_contest_like(self) -> bool:
        """Достаточно ли похоже на конкурс, чтобы предложить сохранить.

        Одна дата в скопированном тексте - ещё не конкурс (копируют письма,
        расписания, логи). Нужно слово-маркер или пара «дата + ссылка».
        """
        return self.has_keyword or (bool(self.url) and self.deadline is not None)


@dataclass
class _Cand:
    dt: datetime
    start: int
    end: int
    text: str
    has_time: bool = False
    weight: float = 0.0


def _month_from_word(word: str) -> int | None:
    w = word.lower()
    for prefixes, num in _MONTHS:
        if any(w.startswith(p) for p in prefixes):
            # «mar»/«may» и т.п. ловят и обычные слова («market»): короткий
            # префикс принимаем только если слово само короткое
            if (
                w.isascii()
                and len(w) > 4
                and not any(w.startswith(p) for p in prefixes if len(p) >= 4)
            ):
                continue
            return num
    return None


def _weekday_from_word(word: str) -> int | None:
    w = word.lower()
    for prefixes, num in _WEEKDAYS:
        for p in prefixes:
            if w.startswith(p) and (len(p) >= 4 or len(w) <= 4):
                return num
    return None


def _now() -> datetime:
    return datetime.now()


def _fix_year(dt: datetime, now: datetime) -> datetime:
    """Если дата уже заметно в прошлом - переносим на следующий год."""
    if dt < now - timedelta(hours=12):
        try:
            return dt.replace(year=dt.year + 1)
        except ValueError:  # 29 февраля
            return dt.replace(year=dt.year + 1, day=28)
    return dt


def _make(year: int | None, month: int, day: int, now: datetime) -> datetime | None:
    y = year if year else now.year
    if year and year < 100:
        y += 2000
    try:
        dt = datetime(y, month, day, 23, 59)
    except ValueError:
        return None
    return dt if year else _fix_year(dt, now)


def _context_weight(text: str, start: int) -> float:
    """Насколько дата похожа на дедлайн по словам перед ней (в пределах фразы)."""
    before = text[max(0, start - 40) : start].lower()
    # только хвост текущей фразы: «Старт 1 октября. Приём до 15-го» не путаем
    before = re.split(r"[.!?\n;]", before)[-1]
    words = re.findall(r"[^\W\d_]+", before)
    tail = " ".join(words[-4:])
    last = words[-1] if words else ""
    w = 0.0
    if last in _LAST_PLUS:
        w += 3
    elif any(k in tail for k in _BEFORE_PLUS):
        w += 2
    if last in _LAST_MINUS or any(k in tail for k in _BEFORE_MINUS):
        w -= 3
    return w


def _time_near(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Время рядом с датой: «15 сентября в 18:00», «18:00 15.09», «до 23:59 15 мая»."""
    after = text[end : end + 28]
    before = text[max(0, start - 18) : start]
    for chunk in (after, before):
        for tm in _TIME_RE.finditer(chunk):
            h, m = int(tm.group(1) or tm.group(3)), int(tm.group(2) or tm.group(4))
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
    return None


def _candidates(text: str, now: datetime) -> list[_Cand]:
    out: list[_Cand] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    def add(dt: datetime | None, m: re.Match, has_time: bool = False) -> None:
        if dt is None or not free(m.start(), m.end()):
            return
        taken.append((m.start(), m.end()))
        out.append(_Cand(dt, m.start(), m.end(), m.group(0).strip(), has_time))

    for m in _ISO_RE.finditer(text):
        dt = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)), now)
        if dt and m.group(4):
            h, mi = int(m.group(4)), int(m.group(5))
            if h <= 23 and mi <= 59:
                dt = dt.replace(hour=h, minute=mi)
        add(dt, m, bool(m.group(4)))
    for m in _DAY_MONTH_RE.finditer(text):
        month = _month_from_word(m.group(2))
        if month:
            add(_make(int(m.group(3)) if m.group(3) else None, month, int(m.group(1)), now), m)
    for m in _MONTH_DAY_RE.finditer(text):
        month = _month_from_word(m.group(1))
        if month and m.group(1).isascii():
            add(_make(int(m.group(3)) if m.group(3) else None, month, int(m.group(2)), now), m)
    for m in _NUM_DATE_RE.finditer(text):
        if m.group(1):
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            day, month, year = int(m.group(4)), int(m.group(5)), None
            # «18.00» после «в» - это время, а не 18 января
            if re.search(r"(?:\bв|\bat)\s*$", text[max(0, m.start() - 4) : m.start()], re.I):
                continue
        if 1 <= day <= 31 and 1 <= month <= 12:
            add(_make(year, month, day, now), m)

    base = now.replace(hour=23, minute=59, second=0, microsecond=0)
    for m in _WORD_DAY_RE.finditer(text):
        add(base + timedelta(days=_WORD_DAY_SHIFT[m.group(1).lower()]), m)
    for m in _WEEKDAY_RE.finditer(text):
        wd = _weekday_from_word(m.group(1))
        if wd is not None:
            days = (wd - now.weekday()) % 7 or 7
            add(base + timedelta(days=days), m)
    for m in _END_OF_RE.finditer(text):
        unit = _END_UNIT[next(g for g in m.groups() if g).lower()]
        if unit == "w":
            dt = base + timedelta(days=6 - now.weekday())
        elif unit == "m":
            dt = base.replace(day=calendar.monthrange(now.year, now.month)[1])
        else:
            dt = base.replace(month=12, day=31)
        add(dt, m)
    for m in _REL_RE.finditer(text):
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith(("недел", "тижн", "week", "woche")):
            delta = timedelta(weeks=n)
        elif unit.startswith(("час", "годин", "hour", "stunde")):
            delta = timedelta(hours=n)
        elif unit.startswith(("минут", "хвилин", "minute")):
            delta = timedelta(minutes=n)
        else:
            delta = timedelta(days=n)
        add(now + delta, m, has_time=True)
    return out


def _pick(text: str, cands: list[_Cand], now: datetime) -> _Cand | None:
    """Самая вероятная дата-дедлайн среди кандидатов."""
    if not cands:
        return None
    for c in cands:
        c.weight = _context_weight(text, c.start)
        if c.dt < now - timedelta(hours=12):
            c.weight -= 4  # прошедшая дата с указанным годом - вряд ли дедлайн
    # при равенстве весов берём более позднюю дату: в анонсе обычно
    # «начало ... окончание», а напоминать нужно об окончании
    return max(cands, key=lambda c: (c.weight, c.dt))


_APOSTROPHE = re.compile(r"(?<=\w)['ʼ’](?=\w)")


def _find_date(text: str, now: datetime | None = None) -> tuple[datetime | None, str]:
    now = now or _now()
    text = _APOSTROPHE.sub("", text)
    best = _pick(text, _candidates(text, now), now)
    if best is None:
        return None, ""
    dt = best.dt
    if not best.has_time:
        tm = _time_near(text, best.start, best.end)
        if tm:
            dt = dt.replace(hour=tm[0], minute=tm[1])
    return dt.replace(second=0, microsecond=0), best.text


_JUNK_LINE = re.compile(r"^[\W_\d]*$")
_HASHTAGS = re.compile(r"(?:^|\s)#\w+")


def _extract_title(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:8]:
        s = _BARE_URL_RE.sub("", _URL_RE.sub("", ln))
        s = _HASHTAGS.sub(" ", s)
        s = re.sub(r"\s{2,}", " ", s).strip(" -–—:·|,*_")
        # эмодзи и значки в начале строки («🔥🎉 Конкурс!») заголовку не нужны
        s = re.sub(r"^[^\w«\"(]+", "", s)
        if len(s) >= 3 and not _JUNK_LINE.match(s):
            # длинная строка-пост: заголовок - первая фраза («Конкурс арта «Осень»!»)
            if len(s) > 40:
                m = re.match(r"(.{10,70}?[!?.…])(?:\s|$)", s)
                if m and not re.search(r"\d[.]$", m.group(1)):
                    s = m.group(1).rstrip(".")
            if len(s) > 90:
                cut = s[:90].rsplit(" ", 1)[0]
                s = (cut if len(cut) > 40 else s[:90]).rstrip(" ,.;:") + "…"
            return s
    if lines:
        return lines[0][:90]
    return "(без названия)"


def find_url(text: str) -> str:
    m = _URL_RE.search(text)
    if m:
        return m.group(0).rstrip(".,)!»")
    bare = _BARE_URL_RE.search(text)
    if bare:
        return "https://" + bare.group(0).rstrip(".,)!»")
    return ""


def has_keyword(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _KEYWORDS)


def parse(text: str, now: datetime | None = None) -> Parsed:
    text = (text or "").strip()
    if not text:
        return Parsed()
    dt, span = _find_date(text, now)
    return Parsed(
        title=_extract_title(text),
        url=find_url(text),
        deadline=dt,
        deadline_text=span,
        has_keyword=has_keyword(text),
    )


if __name__ == "__main__":  # быстрый ручной прогон парсера
    samples = [
        "Конкурс арта! Приём работ до 15 сентября в 23:59. https://example.com/art",
        "Розыгрыш PS5, дедлайн 20.09.2026, участвуй тут vk.com/xxx",
        "Giveaway ends September 30! https://site.io/win",
        "Хакатон, осталось 3 дня до конца регистрации",
        "Старт 1 октября, приём работ до 15 октября, итоги 20 октября",
        "Конкурс до пятницы 18:00",
        "Submit your entry before 2026-12-01 18:00",
    ]
    for s in samples:
        p = parse(s)
        print(
            f"\n> {s}\n  title={p.title!r} url={p.url!r}\n  deadline={p.deadline} ({p.deadline_text!r})"
        )
