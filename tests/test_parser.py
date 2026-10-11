"""Разбор текста поста в заголовок, ссылку и дедлайн."""
from datetime import datetime, timedelta

import pytest

from contestreminder.core.parser import parse


def test_ru_date_with_time_and_url():
    p = parse("Конкурс арта! Приём работ до 15 сентября в 23:59. https://example.com/art")
    assert p.url == "https://example.com/art"
    assert (p.deadline.month, p.deadline.day) == (9, 15)
    assert (p.deadline.hour, p.deadline.minute) == (23, 59)
    assert p.deadline > datetime.now()  # год без указания - ближайший будущий
    assert p.has_keyword and p.is_contest_like
    assert "https://" not in p.title


def test_numeric_date_with_year_kept_as_is():
    p = parse("Розыгрыш PS5, дедлайн 20.09.2030")
    assert p.deadline == datetime(2030, 9, 20, 23, 59)


def test_en_month_name():
    p = parse("Giveaway ends September 30! https://site.io/win")
    assert (p.deadline.month, p.deadline.day) == (9, 30)
    assert p.url == "https://site.io/win"
    assert p.title == "Giveaway ends September 30!"


def test_iso_date_with_time():
    p = parse("Submit your entry before 2030-12-01 18:00")
    assert p.deadline == datetime(2030, 12, 1, 18, 0)


@pytest.mark.parametrize(("text", "days"), [
    ("Хакатон, осталось 3 дня до конца регистрации", 3),
    ("Челлендж недели: через 2 недели подведём итоги", 14),
    ("Contest ends in 5 days", 5),
])
def test_relative_deadline(text, days):
    p = parse(text)
    assert p.deadline is not None
    expected = datetime.now() + timedelta(days=days)
    assert abs((p.deadline - expected).total_seconds()) < 86400


def test_no_date_no_keyword():
    p = parse("Обычный текст про погоду на выходных")
    assert p.deadline is None
    assert not p.has_keyword
    assert not p.is_contest_like


@pytest.mark.parametrize(("text", "url"), [
    ("Розыгрыш, участвуй тут vk.com/club1", "https://vk.com/club1"),
    ("Заявки до 05.10 t.me/chan.", "https://t.me/chan"),
    ("Подробности: www.site.ru", "https://www.site.ru"),
])
def test_bare_links_get_scheme(text, url):
    assert parse(text).url == url


@pytest.mark.parametrize("text", [
    "PS5.Конкурс до 5 мая",       # точка без пробела - не адрес
    "пишите на a@mail.ru/x",      # почта - не ссылка
])
def test_not_a_link(text):
    assert parse(text).url == ""


def test_title_without_links_and_extra_spaces():
    assert parse("Конкурс www.site.ru итоги").title == "Конкурс итоги"
