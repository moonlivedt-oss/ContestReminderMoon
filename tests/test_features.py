"""Новое в 1.2: многоязычный парсер, дубли, календарь, страница по ссылке, планировщик, мост."""

import ast
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication

from contestreminder import config, i18n, ics
from contestreminder.bridge import Bridge, bookmarklet
from contestreminder.dedupe import find_duplicate, norm_url
from contestreminder.enrich import PageInfo, merge, page_info
from contestreminder.locales import TRANSLATIONS
from contestreminder.models import Contest
from contestreminder.parser import parse
from contestreminder.reminders import SNOOZED, digest, digest_due, due_reminders, to_close

app = QCoreApplication.instance() or QCoreApplication([])
NOW = datetime(2026, 10, 11, 12, 0)  # воскресенье


# --- парсер ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Старт 1 октября, приём работ до 15 октября, итоги 20 октября",
            datetime(2026, 10, 15, 23, 59),
        ),
        ("Конкурс: с 1 по 15 ноября", datetime(2026, 11, 15, 23, 59)),
        ("Розыгрыш завтра в 19:00", datetime(2026, 10, 12, 19, 0)),
        ("Конкурс до пятницы 18:00", datetime(2026, 10, 16, 18, 0)),
        ("Конкурс до конца месяца", datetime(2026, 10, 31, 23, 59)),
        ("Стрим в 18.00, конкурс до 20.10", datetime(2026, 10, 20, 23, 59)),
        # украинский
        ("Розіграш! Прийом робіт до 25 листопада о 18:00", datetime(2026, 11, 25, 18, 0)),
        ("Конкурс триває до п’ятниці", datetime(2026, 10, 16, 23, 59)),
        ("конкурс 15 січня", datetime(2027, 1, 15, 23, 59)),
        # немецкий
        (
            "Gewinnspiel: Teilnahmeschluss ist der 15. November 2026 um 18:30 Uhr",
            datetime(2026, 11, 15, 18, 30),
        ),
        ("Wettbewerb läuft bis Freitag", datetime(2026, 10, 16, 23, 59)),
        ("Verlosung endet übermorgen", datetime(2026, 10, 13, 23, 59)),
        ("Start am 1. November, Einsendeschluss 30. November", datetime(2026, 11, 30, 23, 59)),
    ],
)
def test_deadline_choice(text, expected):
    assert parse(text, NOW).deadline == expected


@pytest.mark.parametrize(
    "text",
    [
        "3.5 млн призовых, конкурс",
        "Market research конкурс",
    ],
)
def test_no_false_dates(text):
    assert parse(text, NOW).deadline is None


def test_plain_date_is_not_a_contest():
    p = parse("Встреча 12.10 в 15:00", NOW)
    assert p.deadline is not None and not p.is_contest_like


def test_title_is_first_sentence_without_emoji_and_hashtags():
    p = parse("🔥🎉 #конкурс #арт\nБольшой арт-конкурс «Осень»! Призы и подарки. До 30 ноября", NOW)
    assert p.title == "Большой арт-конкурс «Осень»!"


# --- дубли ----------------------------------------------------------------
def test_norm_url_strips_noise():
    assert norm_url("https://www.Site.ru/a/?utm_source=tg&id=5") == "site.ru/a?id=5"
    assert norm_url("site.ru/a") == "site.ru/a"


def test_find_duplicate_by_url_and_title():
    a = Contest(title="Большой арт-конкурс «Осень»", url="https://site.ru/art")
    b = Contest(title="Хакатон по геймдеву", url="")
    assert find_duplicate([a, b], "что угодно", "http://www.site.ru/art/?utm_medium=x") is a
    assert find_duplicate([a, b], "Хакатон по геймдеву!", "") is b
    assert find_duplicate([a, b], "Конкурс", "") is None  # слишком коротко для сравнения


# --- календарь -------------------------------------------------------------
def test_ics_event_and_alarms():
    c = Contest(
        title="Арт, конкурс; осень",
        url="https://x.io",
        deadline="2026-11-30T18:00:00",
        reminders=[1440, 0],
    )
    text = ics.build_ics([c, Contest(title="без срока")], now=NOW)
    assert text.count("BEGIN:VEVENT") == 1
    assert "DTEND:20261130T180000" in text
    assert "SUMMARY:Дедлайн: Арт\\, конкурс\\; осень" in text
    assert "TRIGGER:-PT1410M" in text and "TRIGGER:-PT0M" in text
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))


# --- страница по ссылке ----------------------------------------------------
HTML = """<html><head><title>Ignored</title>
<meta property="og:title" content="Конкурс иллюстраций &laquo;Зима&raquo;">
<meta property="og:description" content="Принимаем работы до 20 декабря в 21:00. Призы!">
<script>var x = "до 1 января";</script></head>
<body><p>Меню</p><div>Итоги 25 декабря</div></body></html>"""


def test_page_info():
    info = page_info(HTML)
    assert info.title == "Конкурс иллюстраций «Зима»"
    assert "20 декабря" in info.description
    assert "1 января" not in info.text  # скрипты выброшены


def test_merge_fills_missing_deadline_and_weak_title():
    base = parse("Конкурс! https://t.me/chan/5", NOW)
    merged = merge(base, page_info(HTML), NOW)
    assert merged.deadline == datetime(2026, 12, 20, 21, 0)
    assert merged.title == "Конкурс иллюстраций «Зима»"


def test_merge_keeps_own_deadline():
    base = parse("Конкурс иллюстраций до 5 декабря https://x.io", NOW)
    merged = merge(base, PageInfo(title="T", description="до 20 декабря"), NOW)
    assert merged.deadline == datetime(2026, 12, 5, 23, 59)


# --- планировщик ------------------------------------------------------------
def test_snooze_fires_once_and_wins_over_thresholds():
    c = Contest(
        title="t",
        deadline=(NOW + timedelta(days=5)).isoformat(),
        reminders=[1440],
        snoozed_until=(NOW - timedelta(minutes=1)).isoformat(),
    )
    assert due_reminders(c, NOW) == (SNOOZED, [])


def test_to_close_and_digest():
    old = Contest(title="old", deadline=(NOW - timedelta(days=5)).isoformat())
    fresh = Contest(title="fresh", deadline=(NOW - timedelta(days=1)).isoformat())
    soon = Contest(title="soon", deadline=(NOW + timedelta(days=2)).isoformat())
    later = Contest(title="later", deadline=(NOW + timedelta(days=9)).isoformat())
    assert to_close([old, fresh, soon], NOW, 3) == [old]
    assert to_close([old], NOW, 0) == []
    assert digest([later, soon, old], NOW, 3) == [soon]


def test_digest_due():
    assert digest_due(NOW, "10:00", "")
    assert not digest_due(NOW, "10:00", "2026-10-11")
    assert not digest_due(NOW, "13:00", "")
    assert not digest_due(NOW, "", "")


# --- резервная копия --------------------------------------------------------
def test_backup_roundtrip(tmp_path: Path):
    a, b = Contest(title="A"), Contest(title="B")
    path = tmp_path / "backup.json"
    config.export_backup(path, [a, b], {"lang": "en", "geometry": "x"})
    data = json.loads(path.read_text("utf-8"))
    assert "geometry" not in data["settings"]
    current = [a]
    assert config.merge_contests(current, config.import_backup(path)) == 1
    assert [c.title for c in current] == ["A", "B"]


# --- мост --------------------------------------------------------------------
def test_bridge_token_and_host(port=47699):
    got = []
    br = Bridge("secret", port)
    br.received.connect(lambda *a: got.append(a))
    assert br.start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert json.load(urllib.request.urlopen(base + "/ping")) == {"app": "ContestReminder"}
        req = urllib.request.Request(
            base + "/add",
            method="POST",
            data=json.dumps(
                {"token": "secret", "text": "Конкурс до 5 мая", "url": "javascript:alert(1)"}
            ).encode(),
        )
        assert json.load(urllib.request.urlopen(req)) == {"ok": True}
        bad = urllib.request.Request(
            base + "/add", method="POST", data=b'{"token":"no","text":"x"}'
        )
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 403
        for _ in range(20):
            app.processEvents()
        assert got == [("Конкурс до 5 мая", "", "")]  # не-http ссылка отброшена
    finally:
        br.stop()


def test_bookmarklet_contains_token():
    js = bookmarklet("tok123", 47615)
    assert js.startswith("javascript:") and "token=tok123" in js and "127.0.0.1:47615" in js


# --- переводы ---------------------------------------------------------------
def _tr_keys() -> set[str]:
    keys = set()
    for f in Path(__file__).resolve().parents[1].joinpath("contestreminder").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                keys.add(node.args[0].value)
    return keys


@pytest.mark.parametrize("code", ["en", "uk", "de"])
def test_every_string_translated(code):
    missing = sorted(_tr_keys() - set(TRANSLATIONS[code]))
    assert not missing, missing


@pytest.mark.parametrize("code", ["en", "uk", "de"])
def test_placeholders_match(code):
    import string

    fmt = string.Formatter()
    for ru, tr_text in TRANSLATIONS[code].items():
        a = {f for _, f, _, _ in fmt.parse(ru) if f}
        b = {f for _, f, _, _ in fmt.parse(tr_text) if f}
        assert a == b, (code, ru)


def test_switch_language():
    try:
        assert i18n.set_lang("de") == "de"
        assert i18n.tr("за {n} ч", n=2) == "2 Std. vorher"
        assert i18n.set_lang("xx") == "ru"
    finally:
        i18n.set_lang("ru")
