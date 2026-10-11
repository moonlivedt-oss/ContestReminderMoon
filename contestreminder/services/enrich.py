"""Уточнение по ссылке: берём страницу конкурса и достаём название и дедлайн.

Пост из буфера часто обрезан («подробности по ссылке»), а на странице есть и
нормальное название, и срок. Читаем только http(s), с таймаутом и пределом
размера; Telegram-посты (t.me/канал/123) отдают текст в og:description без входа.

Разбор HTML (`page_info`) без сети и без Qt - его и тестируем. Загрузка (`fetch`)
идёт в фоновом потоке (`EnrichJob`), окно не замирает.
"""

from __future__ import annotations

import html
import re
import threading
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.parser import Parsed, has_keyword, parse

_MAX_BYTES = 1_500_000
_TIMEOUT = 8
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 ContestReminder"
)


@dataclass
class PageInfo:
    title: str = ""
    description: str = ""
    text: str = ""


def _meta(doc: str, *names: str) -> str:
    for name in names:
        for pat in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']',
        ):
            m = re.search(pat, doc, re.IGNORECASE)
            if m and m.group(1).strip():
                return html.unescape(m.group(1)).strip()
    return ""


def page_info(doc: str) -> PageInfo:
    """Название, описание и видимый текст страницы (грубо, без DOM)."""
    title = _meta(doc, "og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.IGNORECASE | re.DOTALL)
        title = html.unescape(m.group(1)).strip() if m else ""
    title = re.sub(r"\s+", " ", title)
    desc = _meta(doc, "og:description", "twitter:description", "description")
    body = re.sub(
        r"<(script|style|noscript|svg|head)\b.*?</\1>", " ", doc, flags=re.IGNORECASE | re.DOTALL
    )
    body = re.sub(r"<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", body, flags=re.IGNORECASE)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    body = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in body.splitlines())
    body = re.sub(r"\n{2,}", "\n", body).strip()
    return PageInfo(title=title, description=desc, text=body[:20000])


def merge(base: Parsed, info: PageInfo, now: datetime | None = None) -> Parsed:
    """Дополняет разобранное из буфера тем, что нашлось на странице.

    Своё не перетираем: дедлайн и заголовок со страницы берём, только если в
    тексте поста их не было или заголовок слишком общий.
    """
    out = Parsed(
        title=base.title,
        url=base.url,
        deadline=base.deadline,
        deadline_text=base.deadline_text,
        has_keyword=base.has_keyword,
    )
    page_text = "\n".join(x for x in (info.description, info.text) if x)
    if out.deadline is None and page_text:
        # описание (пост целиком) надёжнее, чем весь текст страницы с меню и подвалом
        for chunk in (info.description, info.text[:6000]):
            p = parse(chunk, now) if chunk else None
            if p and p.deadline is not None:
                out.deadline, out.deadline_text = p.deadline, p.deadline_text
                break
    weak = len(out.title) < 12 or out.title.startswith(("http", "(без"))
    if info.title and weak:
        out.title = info.title[:90]
    out.has_keyword = out.has_keyword or has_keyword(info.title + " " + info.description)
    return out


def fetch(url: str) -> PageInfo:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("нужна ссылка http(s)")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError("по ссылке не страница")
        raw = resp.read(_MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        doc = raw.decode(charset, errors="replace")
    except LookupError:
        doc = raw.decode("utf-8", errors="replace")
    return page_info(doc)


class EnrichJob(QObject):
    """Загрузка страницы в фоновом потоке; результат - сигналом done в главный поток.

    Поток обычный (daemon), а не из пула Qt: на выходе из программы недокачанная
    страница не держит процесс и не стреляет сигналом в уже разрушенный Qt.
    Ссылку на задачу держит вызывающий, пока не придёт ответ.
    """

    done = pyqtSignal(object, object)  # (PageInfo | None, ошибка str | None)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            info, error = fetch(self.url), None
        except Exception as e:  # noqa: BLE001 - сеть, кодировка, 403: не роняем окно
            info, error = None, str(e)
        try:
            self.done.emit(info, error)
        except RuntimeError:  # окно/программа уже закрыты
            pass


def start(url: str, callback) -> EnrichJob:
    """Запускает загрузку; callback(info | None, error | None) - в главном потоке."""
    job = EnrichJob(url)
    job.done.connect(callback)
    job.start()
    return job
