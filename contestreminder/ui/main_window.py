"""Главное окно: шапка со сводкой, поиск и фильтры, список по группам, подсказки.

Окно только показывает: все действия (добавить, распознать, отложить...) - методы
App, окно их вызывает. Список перестраивается целиком в `refresh()` - конкурсов
десятки, а не тысячи, так проще и надёжнее, чем точечные правки.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import LANGS, tr
from ..core.models import Contest, fmt_countdown
from .card import ContestCard, group_of, matches
from .icons import app_icon, asset_icon
from .theme import PALETTES

if TYPE_CHECKING:
    from ..app import App

FILTERS = ("active", "done", "all")
_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def sort_key(c: Contest):
    dt = c.deadline_dt
    ts = dt.timestamp() if dt else 9_999_999_999.0
    # выполненные - свежие сверху; активные - ближайший срок сверху
    return (c.done, -ts if c.done else ts)


class MainWindow(QWidget):
    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setObjectName("root")
        self.setWindowTitle(tr("ContestReminder - напоминалка о конкурсах"))
        self.setWindowIcon(app_icon())
        self.resize(620, 720)
        self.setMinimumSize(460, 420)
        geo = app.settings.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(geo)))
            except (ValueError, TypeError):
                pass

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(12)
        root.addLayout(self._header())
        root.addLayout(self._toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("listViewport")
        self.list_host = QWidget()
        self.list_host.setObjectName("listHost")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        self.footer = QHBoxLayout()
        self.footer.setSpacing(6)
        root.addLayout(self.footer)
        self.update_hint()

    # --- построение ---------------------------------------------------------
    def _header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(38, 38)))
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        h = QLabel(tr("Конкурсы"))
        h.setObjectName("h1")
        titles.addWidget(h)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("subtitle")
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)

        ocr_btn = QPushButton(tr("С экрана"))
        ocr_btn.setObjectName("ghost")
        ocr_btn.setIcon(asset_icon("ocr"))
        ocr_btn.setToolTip(
            tr(
                "Выделить область экрана с постом и распознать текст ({key})",
                key=self.app.settings.get("hotkey", "").upper(),
            )
        )
        ocr_btn.clicked.connect(self.app.ocr_capture)
        header.addWidget(ocr_btn)

        add_btn = QPushButton(tr("Добавить"))
        add_btn.setObjectName("accent")
        add_btn.setIcon(asset_icon("add"))
        add_btn.clicked.connect(self.app.add_manual)
        header.addWidget(add_btn)

        more = QPushButton("…")
        more.setObjectName("ghost")
        more.setToolTip(tr("Ещё"))
        more.setMenu(self._more_menu())
        header.addWidget(more)
        return header

    def _toolbar(self) -> QHBoxLayout:
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Поиск по названию, ссылке и тексту"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(asset_icon("ocr"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self.refresh())
        tools.addWidget(self.search, 1)

        self.filter_group = QButtonGroup(self)
        self.filter_btns: dict[str, QPushButton] = {}
        for key, label in zip(FILTERS, (tr("Активные"), tr("Выполненные"), tr("Все")), strict=True):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self.app.set_filter(k))
            self.filter_group.addButton(b)
            self.filter_btns[key] = b
            tools.addWidget(b)
        cur = self.app.settings.get("filter", "active")
        self.filter_btns.get(cur, self.filter_btns["active"]).setChecked(True)
        return tools

    def _more_menu(self) -> QMenu:
        a = self.app
        m = QMenu(self)
        m.addAction(tr("Вставить из буфера"), a.paste_clipboard)
        m.addSeparator()
        m.addAction(tr("Экспорт всех в календарь (.ics)"), a.export_ics_all)
        m.addAction(tr("Сохранить резервную копию…"), a.backup_save)
        m.addAction(tr("Восстановить из копии…"), a.backup_load)
        m.addSeparator()
        m.addAction(tr("Браузер: скопировать закладку"), a.copy_bookmarklet)
        m.addAction(tr("Браузер: сохранить userscript…"), a.save_userscript)
        m.addSeparator()
        lang_menu = m.addMenu(tr("Язык"))
        for code, label in LANGS:
            act = lang_menu.addAction(tr(label) if code == "auto" else label)
            act.setCheckable(True)
            act.setChecked(a.settings.get("lang", "auto") == code)
            act.triggered.connect(lambda _c=False, c=code: a.set_language(c))
        theme_menu = m.addMenu(tr("Тема"))
        for code, label in (("auto", tr("Авто")), ("light", tr("Светлая")), ("dark", tr("Тёмная")),
                            ("sepia", tr("Сепия"))):
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(a.settings.get("theme", "auto") == code)
            act.triggered.connect(lambda _c=False, c=code: a.set_theme(mode=c))
        pal_menu = m.addMenu(tr("Палитра"))
        for key, pal in PALETTES.items():
            act = pal_menu.addAction(tr(pal["name"]))
            act.setCheckable(True)
            act.setChecked(a.settings.get("palette", "mocha") == key)
            act.triggered.connect(lambda _c=False, k=key: a.set_theme(palette=k))
        m.addAction(tr("Настройки…"), a.open_settings)
        m.addAction(tr("О программе"), a.about)
        return m

    def update_hint(self) -> None:
        """Подвал: клавиши и подсказки (то, что включено в настройках)."""
        while self.footer.count():
            item = self.footer.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        s = self.app.settings
        pairs = []
        if s.get("clipboard_watch", True):
            pairs.append((tr("Ctrl+C"), tr("скопировать пост")))
        if s.get("hotkey"):
            pairs.append(("+".join(k.capitalize() for k in s["hotkey"].split("+")), tr("распознать с экрана")))
        pairs.append((tr("Правый клик"), tr("все действия")))
        for i, (key, text) in enumerate(pairs):
            if i:
                self.footer.addSpacing(8)
            k = QLabel(key)
            k.setObjectName("kbd")
            self.footer.addWidget(k)
            t = QLabel(text)
            t.setObjectName("faint")
            self.footer.addWidget(t)
        self.footer.addStretch(1)

    # --- список ---------------------------------------------------------------
    def refresh(self) -> None:
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        contests = self.app.contests
        now = datetime.now()
        flt = self.app.settings.get("filter", "active")
        query = self.search.text()
        shown = [
            c for c in contests if (flt == "all" or (flt == "done") == c.done) and matches(c, query)
        ]
        shown.sort(key=sort_key)

        active = [c for c in contests if not c.done]
        self.filter_btns["active"].setText(tr("Активные") + f"  {len(active)}")
        self.filter_btns["done"].setText(tr("Выполненные") + f"  {len(contests) - len(active)}")
        self.subtitle.setText(self._summary(active, now))

        if not shown:
            self._empty(query, flt)
            return
        groups: dict[str, list[Contest]] = {}
        for c in shown:
            groups.setdefault(group_of(c, now) if flt != "done" else tr("Выполненные"), []).append(
                c
            )
        pos = 0
        for name, items in groups.items():
            self.list_lay.insertWidget(pos, self._group_head(name, len(items)))
            pos += 1
            for c in items:
                self.list_lay.insertWidget(pos, ContestCard(c, self.app, now))
                pos += 1

    @staticmethod
    def _summary(active: list[Contest], now: datetime) -> str:
        if not active:
            return tr("Пока ни одного конкурса")
        soon = [
            c for c in active if c.deadline_dt and now <= c.deadline_dt <= now + timedelta(days=3)
        ]
        upcoming = sorted(
            (c for c in active if c.deadline_dt and c.deadline_dt >= now),
            key=lambda c: c.deadline_dt,
        )
        parts = []
        if soon:
            parts.append(tr("скоро: {n}", n=len(soon)))
        if upcoming:
            parts.append(tr("ближайший {when}", when=fmt_countdown(upcoming[0].deadline_dt, now)))
        return "  |  ".join(parts) if parts else tr("активных: {n}", n=len(active))

    @staticmethod
    def _group_head(name: str, count: int) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        lbl = QLabel(name.upper())
        lbl.setObjectName("groupHead")
        row.addWidget(lbl)
        cnt = QLabel(str(count))
        cnt.setObjectName("groupCount")
        row.addWidget(cnt)
        row.addStretch(1)
        return box

    def _empty(self, query: str, flt: str) -> None:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(20, 40, 20, 20)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        if query:
            mascot, title, text = (
                "mascot-search",
                tr("Ничего не нашлось"),
                tr("Ничего не нашлось по запросу «{q}».", q=query),
            )
        elif flt == "done":
            mascot, title, text = (
                "mascot-waiting",
                tr("Выполненных пока нет"),
                tr("Отмечайте конкурсы кнопкой «Готово» - они соберутся здесь."),
            )
        else:
            mascot, title, text = (
                "mascot-empty",
                tr("Пока пусто"),
                tr(
                    "Скопируйте пост о конкурсе - программа сама найдёт дедлайн "
                    "и предложит сохранить. Или добавьте вручную."
                ),
            )
        pic = QLabel()
        pm = QPixmap(str(_ASSETS / f"{mascot}.png"))
        if not pm.isNull():
            pic.setPixmap(
                pm.scaled(
                    140,
                    140,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        t = QLabel(title)
        t.setObjectName("emptyTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        d = QLabel(text)
        d.setObjectName("empty")
        d.setWordWrap(True)
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setFixedWidth(360)
        lay.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if query:
            b = QPushButton(tr("Сбросить поиск"))
            b.clicked.connect(self.search.clear)
            row.addWidget(b)
        elif flt != "done":
            paste = QPushButton(tr("Вставить из буфера"))
            paste.setIcon(asset_icon("clipboard"))
            paste.clicked.connect(self.app.paste_clipboard)
            row.addWidget(paste)
            add = QPushButton(tr("Добавить вручную"))
            add.setObjectName("accent")
            add.setIcon(asset_icon("add"))
            add.clicked.connect(self.app.add_manual)
            row.addWidget(add)
        lay.addSpacing(6)
        lay.addLayout(row)
        self.list_lay.insertWidget(0, box)

    # --- окно ---------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.app.on_window_close(event)
