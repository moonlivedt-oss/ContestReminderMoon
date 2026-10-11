"""Поиск дублей: тот же конкурс, скопированный второй раз (или репост в другом канале).

Совпадение по нормализованной ссылке (без схемы, www, хвостового слэша и utm-меток)
или по похожему названию. Без Qt - удобно тестировать.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit

from .models import Contest

_TRACKING = ("utm_", "fbclid", "gclid", "yclid", "ref", "from", "si")


def norm_url(url: str) -> str:
    """https://www.Site.ru/a/?utm_source=x -> site.ru/a"""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING)]
    q = ("?" + urlencode(query)) if query else ""
    return f"{host}{parts.path.rstrip('/')}{q}"


def norm_title(title: str) -> str:
    t = re.sub(r"[^\w\s]", " ", (title or "").lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a: str, b: str) -> float:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def find_duplicate(
    contests: list[Contest], title: str, url: str, threshold: float = 0.88
) -> Contest | None:
    """Уже сохранённый конкурс, который совпадает по ссылке или очень похож по названию."""
    nu = norm_url(url)
    if nu:
        for c in contests:
            if c.url and norm_url(c.url) == nu:
                return c
    # короткие названия («Конкурс!») совпадают случайно - сравниваем только длинные
    if len(norm_title(title)) >= 12:
        best, score = None, 0.0
        for c in contests:
            s = title_similarity(title, c.title)
            if s > score:
                best, score = c, s
        if best is not None and score >= threshold:
            return best
    return None
