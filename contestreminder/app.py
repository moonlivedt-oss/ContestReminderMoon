"""Главное окно, системный трей и связывание всех частей.

Окно живёт в трее: закрытие прячет его, а не завершает приложение. Найденный
конкурс (буфер, OCR, браузер, PowerShell) идёт одним путём `capture`: дубли
отсеиваются, страница по ссылке дочитывается в фоне, а дальше - карточка
«Сохранить?» в углу, автосохранение с «Отменить» или окно правки (настройка).
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __version__, autostart, config, enrich
from .bridge import DEFAULT_PORT, Bridge, bookmarklet, new_token
from .clipboard_watch import ClipboardWatcher
from .dedupe import find_duplicate
from .editor import ContestDialog
from .hotkey import HotkeyManager
from .i18n import LANGS, set_lang, tr
from .icons import app_icon, asset_icon
from .ics import build_ics
from .models import Contest, fmt_countdown, fmt_deadline, fmt_offset
from .parser import Parsed, parse
from .reminders import SNOOZED, ReminderScheduler
from .settings_dialog import SettingsDialog
from .theme import build_qss
from .toast import Action, ToastManager

FILTERS = ("active", "done", "all")


def _beep() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001 - не Windows или звук выключен в системе
        pass


def group_of(c: Contest, now: datetime) -> str:
    """Группа в списке: по близости дедлайна."""
    if c.done:
        return tr("Выполненные")
    dt = c.deadline_dt
    if dt is None:
        return tr("Без срока")
    if dt < now:
        return tr("Прошли")
    if dt.date() == now.date():
        return tr("Сегодня")
    if dt.date() == (now + timedelta(days=1)).date():
        return tr("Завтра")
    if dt < now + timedelta(days=7):
        return tr("На этой неделе")
    return tr("Позже")


def matches(c: Contest, query: str) -> bool:
    q = query.strip().lower().replace("ё", "е")
    if not q:
        return True
    hay = " ".join((c.title, c.url, c.source_text)).lower().replace("ё", "е")
    return all(word in hay for word in q.split())


class ContestCard(QFrame):
    def __init__(self, contest: Contest, app: App) -> None:
        super().__init__()
        self.setObjectName("contestCard")
        self._c = contest
        self._app = app
        self.setProperty("expired", contest.is_expired and not contest.done)
        self.setProperty("done", contest.done)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: app.card_menu(contest, self.mapToGlobal(pos))
        )

        left = QVBoxLayout(self)
        left.setContentsMargins(14, 12, 12, 10)
        left.setSpacing(6)

        title = QLabel()
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setText(contest.title)
        if contest.done:
            title.setProperty("done", True)
        if contest.url:
            title.setCursor(Qt.CursorShape.PointingHandCursor)
            title.setToolTip(tr("Открыть: {url}", url=contest.url))
            title.mousePressEvent = lambda e: (
                app.open_url(contest) if e.button() == Qt.MouseButton.LeftButton else None
            )
        left.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        left.addLayout(meta)
        dt = contest.deadline_dt
        chip_text = tr("готово") if contest.done else fmt_countdown(dt)
        if contest.done and contest.auto_closed:
            chip_text = tr("закрыт сам после срока")
        chip = QLabel(chip_text)
        chip.setObjectName(self._chip_style(contest))
        meta.addWidget(chip)
        if dt:
            when = QLabel(fmt_deadline(dt))
            when.setObjectName("muted")
            meta.addWidget(when)
        if contest.snoozed_dt and not contest.done:
            snz = QLabel(tr("отложено до {t}", t=contest.snoozed_dt.strftime("%d.%m %H:%M")))
            snz.setObjectName("muted")
            meta.addWidget(snz)
        meta.addStretch(1)

        if contest.reminders and not contest.done and dt:
            rem = QLabel(
                tr("напоминания: {list}", list=", ".join(fmt_offset(m) for m in contest.reminders))
            )
            rem.setObjectName("muted")
            left.addWidget(rem)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        left.addLayout(bottom)
        if contest.url:
            link = QLabel(
                f'<a style="color:#cba6f7;text-decoration:none" '
                f'href="{contest.url}">{self._short_url(contest.url)}</a>'
            )
            link.setObjectName("link")
            link.setToolTip(contest.url)
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            bottom.addWidget(link)
        bottom.addStretch(1)

        def action(text: str, icon: str, name: str, slot) -> None:
            btn = QPushButton(text)
            btn.setObjectName(name)
            btn.setIcon(asset_icon(icon))
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            bottom.addWidget(btn)

        action(
            tr("Вернуть") if contest.done else tr("Готово"),
            "done",
            "ghost",
            lambda: app.toggle_done(contest),
        )
        action(tr("Изменить"), "edit", "ghost", lambda: app.edit_contest(contest))
        action(tr("Удалить"), "delete", "dangerGhost", lambda: app.delete_contest(contest))

    @staticmethod
    def _chip_style(c: Contest) -> str:
        if c.done:
            return "chipOk"
        dt = c.deadline_dt
        if dt is None:
            return "chip"
        secs = (dt - datetime.now()).total_seconds()
        if secs < 0:
            return "chipErr"
        if secs < 86400:
            return "chipWarn"
        return "chip"

    @staticmethod
    def _short_url(url: str) -> str:
        u = url.replace("https://", "").replace("http://", "").removeprefix("www.")
        return u[:48] + ("…" if len(u) > 48 else "")


class App:
    def __init__(self) -> None:
        self.qapp = QApplication.instance() or QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setStyleSheet(build_qss())

        self.settings = config.load_settings()
        set_lang(self.settings.get("lang", "auto"))
        if not self.settings.get("bridge_token"):
            self.settings["bridge_token"] = new_token()
            config.save_settings(self.settings)
        self.contests: list[Contest] = config.load_contests()
        self.toasts = ToastManager()
        self._jobs: list = []  # держим ссылки на фоновые загрузки страниц
        self._recent: dict[str, datetime] = {}  # недавно предложенные тексты

        self._build_window()
        self._build_tray()

        self.clipboard = ClipboardWatcher()
        self.clipboard.captured.connect(lambda text: self.capture(text, "clipboard"))
        self.clipboard.set_enabled(self.settings.get("clipboard_watch", True))

        self.hotkey: HotkeyManager | None = None
        self._start_hotkey()

        self.bridge = Bridge(
            self.settings["bridge_token"], int(self.settings.get("bridge_port", DEFAULT_PORT))
        )
        self.bridge.received.connect(self._on_bridge)
        self.bridge.start()

        self.scheduler = ReminderScheduler(
            lambda: self.contests,
            self._notify,
            self._changed,
            get_settings=lambda: self.settings,
            on_digest=self._digest,
            on_closed=lambda closed: None,
        )
        self.scheduler.start()

        # раз в минуту обновляем отсчёт «через N мин» в открытом окне
        self._ticker = QTimer()
        self._ticker.setInterval(60_000)
        self._ticker.timeout.connect(lambda: self.win.isVisible() and self.refresh())
        self._ticker.start()

        self._region = None  # держим ссылку на оверлей выбора области
        self.refresh()
        if autostart.TRAY_FLAG not in sys.argv[1:]:
            self.show_window()

    # --- построение UI --------------------------------------------------
    def _build_window(self) -> None:
        self.win = QWidget()
        self.win.setObjectName("root")
        self.win.setWindowTitle(tr("ContestReminder - напоминалка о конкурсах"))
        self.win.setWindowIcon(app_icon())
        self.win.resize(600, 680)
        geo = self.settings.get("geometry")
        if geo:
            try:
                self.win.restoreGeometry(QByteArray(base64.b64decode(geo)))
            except (ValueError, TypeError):
                pass
        self.win.closeEvent = self._on_close

        root = QVBoxLayout(self.win)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        h = QLabel(tr("Конкурсы"))
        h.setObjectName("h1")
        header.addWidget(h)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("muted")
        header.addWidget(self.count_lbl)
        header.addStretch(1)

        ocr_btn = QPushButton(tr("С экрана"))
        ocr_btn.setObjectName("ghost")
        ocr_btn.setIcon(asset_icon("ocr"))
        ocr_btn.setToolTip(
            tr(
                "Выделить область экрана с постом и распознать текст ({key})",
                key=self.settings.get("hotkey", "").upper(),
            )
        )
        ocr_btn.clicked.connect(self.ocr_capture)
        header.addWidget(ocr_btn)

        add_btn = QPushButton(tr("Добавить"))
        add_btn.setObjectName("accent")
        add_btn.setIcon(asset_icon("add"))
        add_btn.clicked.connect(self.add_manual)
        header.addWidget(add_btn)

        more = QPushButton("…")
        more.setObjectName("ghost")
        more.setToolTip(tr("Ещё"))
        more.setMenu(self._more_menu())
        header.addWidget(more)
        root.addLayout(header)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Поиск по названию, ссылке и тексту"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        tools.addWidget(self.search, 1)
        self.filter_group = QButtonGroup(self.win)
        self.filter_btns: dict[str, QPushButton] = {}
        for key, label in zip(FILTERS, (tr("Активные"), tr("Выполненные"), tr("Все")), strict=True):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            self.filter_group.addButton(b)
            self.filter_btns[key] = b
            tools.addWidget(b)
        cur = self.settings.get("filter", "active")
        self.filter_btns.get(cur, self.filter_btns["active"]).setChecked(True)
        root.addLayout(tools)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self._update_hint()

    def _update_hint(self) -> None:
        parts = []
        if self.settings.get("clipboard_watch", True):
            parts.append(tr("Скопируйте пост о конкурсе - программа сама предложит сохранить."))
        key = self.settings.get("hotkey", "")
        if key:
            parts.append(tr("{key} - распознать пост с экрана.", key=key.upper()))
        parts.append(tr("Правый клик по карточке - все действия."))
        self.hint.setText(" ".join(parts))

    def _more_menu(self) -> QMenu:
        m = QMenu(self.win)
        m.addAction(tr("Вставить из буфера"), self.paste_clipboard)
        m.addSeparator()
        m.addAction(tr("Экспорт всех в календарь (.ics)"), self.export_ics_all)
        m.addAction(tr("Сохранить резервную копию…"), self.backup_save)
        m.addAction(tr("Восстановить из копии…"), self.backup_load)
        m.addSeparator()
        m.addAction(tr("Браузер: скопировать закладку"), self.copy_bookmarklet)
        m.addAction(tr("Браузер: сохранить userscript…"), self.save_userscript)
        m.addSeparator()
        lang_menu = m.addMenu(tr("Язык"))
        for code, label in LANGS:
            act = lang_menu.addAction(tr(label) if code == "auto" else label)
            act.setCheckable(True)
            act.setChecked(self.settings.get("lang", "auto") == code)
            act.triggered.connect(lambda _c=False, c=code: self.set_language(c))
        m.addAction(tr("Настройки…"), self.open_settings)
        m.addAction(tr("О программе"), self.about)
        return m

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("ContestReminder")
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _fill_tray_menu(self) -> None:
        menu = self.tray_menu
        menu.clear()
        menu.addAction(tr("Открыть окно"), self.show_window)
        menu.addAction(tr("Добавить вручную"), self.add_manual)
        menu.addAction(tr("Вставить из буфера"), self.paste_clipboard)
        menu.addAction(tr("Распознать с экрана"), self.ocr_capture)

        soon = sorted(
            (
                c
                for c in self.contests
                if not c.done and c.deadline_dt and c.deadline_dt >= datetime.now()
            ),
            key=lambda c: c.deadline_dt,
        )[:6]
        sub = menu.addMenu(tr("Ближайшие"))
        if not soon:
            sub.addAction(tr("нет активных со сроком")).setEnabled(False)
        for c in soon:
            label = f"{c.title[:40]}  |  {fmt_countdown(c.deadline_dt)}"
            sub.addAction(label, lambda c=c: self.open_url(c) if c.url else self.edit_contest(c))

        menu.addSeparator()
        act_cw = menu.addAction(tr("Следить за буфером"))
        act_cw.setCheckable(True)
        act_cw.setChecked(self.settings.get("clipboard_watch", True))
        act_cw.toggled.connect(self._toggle_clipboard)
        menu.addAction(tr("Настройки…"), self.open_settings)
        menu.addSeparator()
        menu.addAction(tr("Выход"), self.quit)

        nxt = soon[0] if soon else None
        tip = "ContestReminder"
        if nxt:
            tip += "\n" + tr(
                "Ближайший: {t}, {when}", t=nxt.title[:50], when=fmt_countdown(nxt.deadline_dt)
            )
        self.tray.setToolTip(tip)

    # --- список ---------------------------------------------------------
    def _set_filter(self, key: str) -> None:
        self.settings["filter"] = key
        config.save_settings(self.settings)
        self.refresh()

    @staticmethod
    def _sort_key(c: Contest):
        dt = c.deadline_dt
        ts = dt.timestamp() if dt else 9_999_999_999.0
        # выполненные - свежие сверху; активные - ближайший срок сверху
        return (c.done, -ts if c.done else ts)

    def refresh(self) -> None:
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        now = datetime.now()
        flt = self.settings.get("filter", "active")
        query = self.search.text()
        shown = [
            c
            for c in self.contests
            if (flt == "all" or (flt == "done") == c.done) and matches(c, query)
        ]
        shown.sort(key=self._sort_key)

        active = sum(1 for c in self.contests if not c.done)
        done = len(self.contests) - active
        self.filter_btns["active"].setText(tr("Активные") + f" {active}")
        self.filter_btns["done"].setText(tr("Выполненные") + f" {done}")
        soon = sum(
            1
            for c in self.contests
            if not c.done and c.deadline_dt and now <= c.deadline_dt <= now + timedelta(days=3)
        )
        self.count_lbl.setText(tr("{n} скоро", n=soon) if soon else "")

        if not shown:
            if query:
                text = tr("Ничего не нашлось по запросу «{q}».", q=query)
            elif flt == "done":
                text = tr("Выполненных пока нет.")
            else:
                text = tr("Пока пусто. Скопируйте пост о конкурсе или добавьте вручную.")
            empty = QLabel(text)
            empty.setObjectName("empty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.list_lay.insertWidget(0, empty)
        else:
            last_group = None
            for c in shown:
                g = group_of(c, now)
                if g != last_group and flt != "done":
                    lbl = QLabel(g)
                    lbl.setObjectName("groupHead")
                    self.list_lay.insertWidget(self.list_lay.count() - 1, lbl)
                    last_group = g
                self.list_lay.insertWidget(self.list_lay.count() - 1, ContestCard(c, self))
        self._fill_tray_menu()

    def card_menu(self, c: Contest, pos) -> None:
        m = QMenu(self.win)
        if c.url:
            m.addAction(tr("Открыть ссылку"), lambda: self.open_url(c))
            m.addAction(tr("Копировать ссылку"), lambda: self._copy(c.url))
            m.addAction(tr("Уточнить по ссылке"), lambda: self.refine(c))
        if not c.done and c.deadline_dt:
            snz = m.addMenu(tr("Отложить напоминание"))
            for label, minutes in self._snooze_choices():
                snz.addAction(label, lambda mm=minutes: self.snooze(c, mm))
        m.addAction(tr("Добавить в календарь (.ics)"), lambda: self.export_ics([c]))
        m.addSeparator()
        m.addAction(tr("Вернуть") if c.done else tr("Готово"), lambda: self.toggle_done(c))
        m.addAction(tr("Изменить"), lambda: self.edit_contest(c))
        m.addAction(tr("Удалить"), lambda: self.delete_contest(c))
        m.exec(pos)

    # --- операции с конкурсами -----------------------------------------
    def _changed(self) -> None:
        config.save_contests(self.contests)
        self.refresh()

    def _save(self) -> None:
        config.save_contests(self.contests)

    def add_manual(self) -> None:
        self.show_window()
        dlg = ContestDialog(self.win, default_reminders=self.settings.get("default_reminders"))
        if dlg.exec() and dlg.contest:
            self.contests.append(dlg.contest)
            self._changed()

    def edit_contest(self, contest: Contest) -> None:
        self.show_window()
        dlg = ContestDialog(self.win, contest=contest)
        if dlg.exec():
            self._changed()

    def delete_contest(self, contest: Contest) -> None:
        idx = next((i for i, c in enumerate(self.contests) if c.id == contest.id), None)
        if idx is None:
            return
        removed = self.contests.pop(idx)
        self._changed()

        def undo() -> None:
            if all(c.id != removed.id for c in self.contests):
                self.contests.insert(min(idx, len(self.contests)), removed)
                self._changed()

        self.toasts.show(
            tr("Удалено"), removed.title, [Action(tr("Вернуть"), undo, "accent")], 8000, "delete"
        )

    def toggle_done(self, contest: Contest) -> None:
        contest.done = not contest.done
        contest.auto_closed = False
        if contest.done:
            contest.snoozed_until = None
        self._changed()

    def snooze(self, c: Contest, minutes: int) -> None:
        c.snoozed_until = (
            (datetime.now() + timedelta(minutes=minutes))
            .replace(second=0, microsecond=0)
            .isoformat(timespec="seconds")
        )
        self._changed()

    @staticmethod
    def _snooze_choices() -> list[tuple[str, int]]:
        now = datetime.now()
        morning = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return [
            (tr("на 15 минут"), 15),
            (tr("на 1 час"), 60),
            (tr("на 3 часа"), 180),
            (tr("до завтра 9:00"), int((morning - now).total_seconds() // 60)),
        ]

    def open_url(self, c: Contest) -> None:
        if c.url:
            QDesktopServices.openUrl(QUrl(c.url))

    def _copy(self, text: str) -> None:
        self.clipboard.mute_next()
        QApplication.clipboard().setText(text)

    # --- автозапись -----------------------------------------------------
    def paste_clipboard(self) -> None:
        text = QApplication.clipboard().text() or ""
        if not text.strip():
            self.toasts.show(
                tr("Буфер пуст"), tr("Скопируйте текст поста о конкурсе."), timeout_ms=4000
            )
            return
        self.capture(text, "manual")

    def _on_bridge(self, text: str, url: str, title: str) -> None:
        body = text
        if url and url not in body:
            body = (body + "\n" + url).strip()
        self.capture(body, "browser", page_title=title)

    def capture(self, text: str, source: str, page_title: str = "") -> None:
        """Единый путь для всего найденного: буфер, OCR, браузер, вставка вручную."""
        parsed = parse(text)
        explicit = source != "clipboard"  # пользователь сам попросил - предлагаем всегда
        if not explicit and not parsed.is_contest_like:
            return
        key = text.strip()[:500]
        now = datetime.now()
        if not explicit and key in self._recent and now - self._recent[key] < timedelta(minutes=30):
            return
        self._recent[key] = now
        if page_title and (len(parsed.title) < 12 or parsed.title == text.strip()[:90]):
            parsed.title = page_title[:90]

        dup = find_duplicate(self.contests, parsed.title, parsed.url)
        if dup is not None:
            self._offer_duplicate(dup, parsed, explicit)
            return

        mode = self.settings.get("capture_mode", "ask")
        pending = {"parsed": parsed, "raw": text, "toast": None, "contest": None}
        if mode == "dialog":
            self._open_dialog(pending, tr("Похоже на конкурс - проверьте и сохраните"))
        elif mode == "auto":
            self._save_pending(pending)
        else:
            pending["toast"] = self.toasts.show(
                self._offer_title(parsed),
                self._offer_body(parsed),
                [
                    Action(tr("Сохранить"), lambda: self._save_pending(pending), "accent"),
                    Action(tr("Изменить…"), lambda: self._open_dialog(pending)),
                    Action(tr("Не надо")),
                ],
                timeout_ms=25000,
                icon="clipboard",
                kind="offer",
            )
        if self.settings.get("enrich", True) and parsed.url:
            self._enrich(pending)

    @staticmethod
    def _offer_title(p: Parsed) -> str:
        return tr("Сохранить конкурс?") + "\n" + p.title

    @staticmethod
    def _offer_body(p: Parsed, note: str = "") -> str:
        lines = []
        if p.deadline:
            lines.append(
                tr("Срок: {d} ({c})", d=fmt_deadline(p.deadline), c=fmt_countdown(p.deadline))
            )
        else:
            lines.append(tr("Срок не найден - можно указать в «Изменить…»"))
        if p.url:
            lines.append(p.url)
        if note:
            lines.append(note)
        return "\n".join(lines)

    def _contest_from(self, p: Parsed, raw: str) -> Contest:
        return Contest(
            title=p.title or tr("(без названия)"),
            url=p.url,
            deadline=p.deadline.isoformat(timespec="seconds") if p.deadline else None,
            source_text=raw.strip()[:4000],
            reminders=list(self.settings.get("default_reminders", [1440, 60, 0])),
        )

    def _save_pending(self, pending: dict) -> None:
        if pending.get("contest") is not None:
            return
        c = self._contest_from(pending["parsed"], pending["raw"])
        pending["contest"] = c
        self.contests.append(c)
        self._changed()
        if self.settings.get("capture_mode") == "auto":

            def undo() -> None:
                self.contests = [x for x in self.contests if x.id != c.id]
                self._changed()

            pending["toast"] = self.toasts.show(
                tr("Сохранено"),
                c.title
                + "\n"
                + (fmt_deadline(c.deadline_dt) if c.deadline_dt else tr("без срока")),
                [
                    Action(tr("Отменить"), undo, "dangerGhost"),
                    Action(tr("Изменить…"), lambda: self.edit_contest(c)),
                ],
                timeout_ms=10000,
                icon="done",
                kind="ok",
            )

    def _open_dialog(self, pending: dict, hint: str = "") -> None:
        self.show_window()
        dlg = ContestDialog(
            self.win,
            default_reminders=self.settings.get("default_reminders"),
            hint=hint,
            prefill=pending["parsed"],
        )
        dlg.ed_source.setPlainText(pending["raw"].strip())
        if dlg.exec() and dlg.contest:
            pending["contest"] = dlg.contest
            self.contests.append(dlg.contest)
            self._changed()

    def _offer_duplicate(self, dup: Contest, p: Parsed, explicit: bool) -> None:
        new_dl = p.deadline
        old_dl = dup.deadline_dt
        if new_dl and (old_dl is None or abs((new_dl - old_dl).total_seconds()) > 60):

            def update() -> None:
                dup.deadline = new_dl.isoformat(timespec="seconds")
                dup.notified = []
                dup.done = False
                self._changed()

            self.toasts.show(
                tr("Этот конкурс уже есть"),
                tr(
                    "«{t}»\nСейчас: {old}\nВ тексте: {new}",
                    t=dup.title,
                    old=fmt_deadline(old_dl),
                    new=fmt_deadline(new_dl),
                ),
                [Action(tr("Обновить срок"), update, "accent"), Action(tr("Не надо"))],
                timeout_ms=20000,
                icon="edit",
                kind="offer",
            )
        elif explicit:
            self.toasts.show(tr("Уже сохранён"), dup.title, timeout_ms=5000, icon="done")

    def _enrich(self, pending: dict) -> None:
        p: Parsed = pending["parsed"]
        toast = pending.get("toast")
        if toast is not None:
            toast.set_text(body=self._offer_body(p, tr("Читаю страницу по ссылке…")))

        def done(info, error) -> None:
            self._jobs = [j for j in self._jobs if j is not job]
            if info is None:
                if toast is not None and pending.get("contest") is None:
                    toast.set_text(body=self._offer_body(p))
                return
            merged = enrich.merge(p, info)
            changed = (merged.deadline != p.deadline) or (merged.title != p.title)
            pending["parsed"] = merged
            c = pending.get("contest")
            if c is not None and changed:  # уже сохранили - дополняем сохранённое
                if c.deadline is None and merged.deadline:
                    c.deadline = merged.deadline.isoformat(timespec="seconds")
                if c.title == p.title:
                    c.title = merged.title
                self._changed()
            if toast is not None and c is None:
                note = tr("Дополнено со страницы") if changed else ""
                toast.set_text(self._offer_title(merged), self._offer_body(merged, note))

        job = enrich.start(p.url, done)
        self._jobs.append(job)

    def refine(self, c: Contest) -> None:
        """«Уточнить по ссылке» для уже сохранённого конкурса."""

        def done(info, error) -> None:
            if info is None:
                self.toasts.show(
                    tr("Не удалось открыть страницу"), error or "", timeout_ms=6000, icon="ocr"
                )
                return
            base = Parsed(title=c.title, url=c.url, deadline=c.deadline_dt)
            merged = enrich.merge(base, info)
            if merged.deadline and c.deadline_dt is None:
                c.deadline = merged.deadline.isoformat(timespec="seconds")
            if merged.title != c.title:
                c.title = merged.title
            self._changed()
            self.toasts.show(
                tr("Уточнено по ссылке"),
                c.title + "\n" + fmt_deadline(c.deadline_dt),
                timeout_ms=6000,
                icon="done",
            )

        self._jobs.append(enrich.start(c.url, done))

    def ocr_capture(self) -> None:
        from .region import RegionSelector

        self._region = RegionSelector()
        self._region.selected.connect(self._on_region)
        self._region.cancelled.connect(lambda: setattr(self, "_region", None))
        self._region.show()

    def _on_region(self, left: int, top: int, w: int, h: int) -> None:
        self._region = None
        try:
            from .ocr import ocr_region

            text = ocr_region(left, top, w, h, self.settings.get("ocr_lang", "ru"))
        except Exception as e:  # noqa: BLE001 - OCR-движок/язык может отсутствовать
            QMessageBox.warning(self.win, "OCR", tr("Не удалось распознать текст:\n{e}", e=e))
            return
        if not text.strip():
            self.toasts.show("OCR", tr("Текст не распознан"), timeout_ms=4000, icon="ocr")
            return
        self.capture(text, "ocr")

    # --- уведомления ----------------------------------------------------
    def _notify(self, contest: Contest, offset: int, expired: bool) -> None:
        if offset == SNOOZED:
            head = tr("Отложенное напоминание")
        elif expired:
            head = tr("Дедлайн прошёл")
        elif offset == 0:
            head = tr("Дедлайн сейчас!")
        else:
            head = tr("Напоминание ({when})", when=fmt_offset(offset))
        body = contest.title
        if contest.deadline_dt:
            body += (
                "\n"
                + fmt_countdown(contest.deadline_dt)
                + " | "
                + fmt_deadline(contest.deadline_dt)
            )
        if self.settings.get("sound", True):
            _beep()
        if self.settings.get("notify_style", "toast") == "tray":
            self.tray.showMessage(
                head, body + (f"\n{contest.url}" if contest.url else ""), app_icon(), 12000
            )
            return
        actions = []
        if contest.url:
            actions.append(Action(tr("Открыть"), lambda: self.open_url(contest), "accent"))
        if not expired:
            actions.append(
                Action(
                    tr("Отложить"),
                    menu=[
                        (label, lambda m=m: self.snooze(contest, m))
                        for label, m in self._snooze_choices()
                    ],
                )
            )
        actions.append(
            Action(tr("Готово"), lambda: (setattr(contest, "done", True), self._changed()))
        )
        self.toasts.show(
            head,
            body,
            actions,
            timeout_ms=0 if offset in (0, SNOOZED) else 30000,
            icon="bell",
            kind="warn" if expired or offset == 0 else "info",
        )

    def _digest(self, soon: list[Contest]) -> None:
        config.save_settings(self.settings)  # digest_last
        if not soon:
            return
        lines = [f"{c.title[:48]}: {fmt_countdown(c.deadline_dt)}" for c in soon[:6]]
        if len(soon) > 6:
            lines.append(tr("и ещё {n}", n=len(soon) - 6))
        self.toasts.show(
            tr("Сводка: {n} скоро", n=len(soon)),
            "\n".join(lines),
            [Action(tr("Открыть список"), self.show_window, "accent")],
            timeout_ms=0,
            icon="bell",
        )

    # --- экспорт и копии ------------------------------------------------
    def export_ics(self, contests: list[Contest]) -> None:
        with_dl = [c for c in contests if c.deadline_dt]
        if not with_dl:
            self.toasts.show(
                tr("Нечего экспортировать"), tr("У конкурса нет срока."), timeout_ms=4000
            )
            return
        path = (
            Path(tempfile.gettempdir())
            / f"contestreminder-{with_dl[0].id if len(with_dl) == 1 else 'all'}.ics"
        )
        path.write_text(build_ics(with_dl), "utf-8")
        os.startfile(path)  # noqa: S606 - открыть календарём по умолчанию

    def export_ics_all(self) -> None:
        self.export_ics([c for c in self.contests if not c.done])

    def backup_save(self) -> None:
        name = f"contestreminder-{datetime.now():%Y-%m-%d}.json"
        path, _ = QFileDialog.getSaveFileName(
            self.win, tr("Резервная копия"), str(Path.home() / name), "JSON (*.json)"
        )
        if path:
            config.export_backup(Path(path), self.contests, self.settings)
            self.toasts.show(tr("Копия сохранена"), path, timeout_ms=5000, icon="done")

    def backup_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.win, tr("Восстановить из копии"), str(Path.home()), "JSON (*.json)"
        )
        if not path:
            return
        try:
            incoming = config.import_backup(Path(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(
                self.win, tr("Восстановление"), tr("Не удалось прочитать файл:\n{e}", e=e)
            )
            return
        added = config.merge_contests(self.contests, incoming)
        self._changed()
        self.toasts.show(
            tr("Восстановлено"),
            tr("Добавлено конкурсов: {n}", n=added),
            timeout_ms=5000,
            icon="done",
        )

    # --- браузер --------------------------------------------------------
    def copy_bookmarklet(self) -> None:
        if not self.bridge.running:
            QMessageBox.warning(
                self.win,
                tr("Браузер"),
                tr("Мост для браузера не запустился: {e}", e=self.bridge.error),
            )
            return
        self._copy(bookmarklet(self.bridge.token, self.bridge.port))
        QMessageBox.information(
            self.win,
            tr("Закладка скопирована"),
            tr(
                "Создайте в браузере новую закладку и вставьте скопированное в поле «Адрес» (URL).\n\n"
                "Дальше на любой странице: выделите текст поста и нажмите закладку - "
                "конкурс придёт сюда карточкой «Сохранить?»."
            ),
        )

    def save_userscript(self) -> None:
        src = userscript_template()
        try:
            text = src.read_text("utf-8")
        except OSError as e:
            QMessageBox.warning(self.win, "userscript", str(e))
            return
        text = text.replace("__TOKEN__", self.bridge.token).replace(
            "__PORT__", str(self.bridge.port)
        )
        path, _ = QFileDialog.getSaveFileName(
            self.win,
            "userscript",
            str(Path.home() / "contestreminder.user.js"),
            "JavaScript (*.user.js)",
        )
        if path:
            Path(path).write_text(text, "utf-8")
            QMessageBox.information(
                self.win,
                "userscript",
                tr(
                    "Файл сохранён. Откройте его в браузере с Tampermonkey или Violentmonkey "
                    "(перетащите в окно) и установите.\n\nНа странице: выделите текст и нажмите "
                    "Alt+Shift+C или пункт меню расширения «Отправить в ContestReminder»."
                ),
            )

    # --- настройки и язык ----------------------------------------------
    def open_settings(self) -> None:
        self.show_window()
        old_hotkey = self.settings.get("hotkey")
        dlg = SettingsDialog(self.win, self.settings)
        if not dlg.exec():
            return
        config.save_settings(self.settings)
        self.clipboard.set_enabled(self.settings.get("clipboard_watch", True))
        if self.settings.get("hotkey") != old_hotkey:
            self._start_hotkey()
        if autostart.supported() and dlg.autostart != autostart.is_enabled():
            try:
                autostart.set_enabled(dlg.autostart)
            except OSError as e:
                QMessageBox.warning(
                    self.win, tr("Автозапуск"), tr("Не удалось изменить автозапуск:\n{e}", e=e)
                )
        if dlg.lang != self.settings.get("lang", "auto"):
            self.set_language(dlg.lang)
        else:
            self._update_hint()
            self.refresh()

    def set_language(self, code: str) -> None:
        """Язык меняется сразу: окно и меню пересобираются."""
        self.settings["lang"] = code
        config.save_settings(self.settings)
        set_lang(code)
        geo = self.win.saveGeometry()
        visible = self.win.isVisible()
        self.win.hide()
        self.win.deleteLater()
        self._build_window()
        self.win.restoreGeometry(geo)
        self.refresh()
        if visible:
            self.show_window()

    def about(self) -> None:
        QMessageBox.about(
            self.win,
            "ContestReminder",
            tr(
                "ContestReminder {v}\nНапоминалка о конкурсах: ловит посты из буфера, с экрана и из "
                "браузера, сама находит дедлайн и напоминает.\n\nДанные: {path}",
                v=__version__,
                path=config.APP_DIR,
            ),
        )

    def _start_hotkey(self) -> None:
        if self.hotkey is not None:
            self.hotkey.stop()
        self.hotkey = None
        spec = self.settings.get("hotkey", "")
        if spec:
            self.hotkey = HotkeyManager(spec)
            self.hotkey.triggered.connect(self.ocr_capture)
            self.hotkey.start()

    def _toggle_clipboard(self, on: bool) -> None:
        self.settings["clipboard_watch"] = on
        config.save_settings(self.settings)
        self.clipboard.set_enabled(on)
        self._update_hint()

    # --- окно и выход ---------------------------------------------------
    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        self.refresh()
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def _on_close(self, event) -> None:
        self.settings["geometry"] = base64.b64encode(bytes(self.win.saveGeometry())).decode("ascii")
        config.save_settings(self.settings)
        event.ignore()
        self.win.hide()
        if not self.settings.get("tray_hint_shown"):
            self.settings["tray_hint_shown"] = True
            config.save_settings(self.settings)
            self.toasts.show(
                tr("Программа работает в трее"),
                tr("Слежу за конкурсами в фоне. Значок в трее - открыть окно, правый клик - меню."),
                timeout_ms=7000,
            )

    def quit(self) -> None:
        if self.hotkey is not None:
            self.hotkey.stop()
        self.bridge.stop()
        self.toasts.close_all()
        self._save()
        config.save_settings(self.settings)
        self.tray.hide()
        self.qapp.quit()

    def run(self) -> int:
        return self.qapp.exec()


def userscript_template() -> Path:
    """Шаблон userscript: в исходниках - browser/, в exe - та же папка внутри сборки."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "browser" / "contestreminder.user.js"


def main() -> int:
    from .selftest import FLAG
    from .selftest import run as selftest
    if FLAG in sys.argv:
        return selftest(sys.argv)
    _qapp = QApplication.instance() or QApplication(sys.argv)  # нужен до сокета одной копии
    from .single_instance import InstanceServer, notify_running

    if notify_running():
        return 0
    server = InstanceServer()
    app = App()
    server.show_requested.connect(app.show_window)
    app._instance_server = server
    return app.run()
