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

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import __version__
from .core import config
from .core.dedupe import find_duplicate
from .core.i18n import lang, set_lang, tr
from .core.ics import build_ics
from .core.models import Contest, fmt_countdown, fmt_deadline, fmt_offset
from .core.parser import Parsed, parse
from .core.reminders import SNOOZED
from .services import autostart, enrich, native
from .services.bridge import DEFAULT_PORT, Bridge, bookmarklet, new_token
from .services.clipboard_watch import ClipboardWatcher
from .services.hotkey import HotkeyManager
from .services.scheduler import ReminderScheduler
from .ui import theme
from .ui.editor import ContestDialog
from .ui.icons import app_icon
from .ui.main_window import MainWindow
from .ui.settings_dialog import SettingsDialog
from .ui.toast import Action, ToastManager


def _beep() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001 - не Windows или звук выключен в системе
        pass


class App:
    def __init__(self) -> None:
        self.qapp = QApplication.instance() or QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)

        self.settings = config.load_settings()
        set_lang(self.settings.get("lang", "auto"))
        theme.apply(self.qapp, self.settings.get("theme", "auto"), self.settings.get("palette", "mocha"))
        if not self.settings.get("bridge_token"):
            self.settings["bridge_token"] = new_token()
            config.save_settings(self.settings)
        self.contests: list[Contest] = config.load_contests()
        self.toasts = ToastManager()
        self._jobs: list = []  # держим ссылки на фоновые загрузки страниц
        self._recent: dict[str, datetime] = {}  # недавно предложенные тексты

        self.win = MainWindow(self)
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
        self.bridge.action.connect(self._on_toast_action)
        self.bridge.start()

        # нативная часть (C++): уведомления Windows и лёгкий сторож; нет её - без них
        self.app_mutex = native.AppMutex()
        self.native = None
        try:
            self.native = native.install()
            if self.native is not None:
                native.register(self.native)
        except Exception:  # noqa: BLE001 - нативная часть необязательна
            self.native = None
        self._sync_autostart()

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
    def refresh(self) -> None:
        self.win.refresh()
        self._fill_tray_menu()

    def set_filter(self, key: str) -> None:
        self.settings["filter"] = key
        config.save_settings(self.settings)
        self.refresh()

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
        self._remove_native(contest)
        contest.done = not contest.done
        contest.auto_closed = False
        if contest.done:
            contest.snoozed_until = None
        self._changed()

    def snooze(self, c: Contest, minutes: int) -> None:
        self._remove_native(c)
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
        from .ui.region import RegionSelector

        self._region = RegionSelector()
        self._region.selected.connect(self._on_region)
        self._region.cancelled.connect(lambda: setattr(self, "_region", None))
        self._region.show()

    def _on_region(self, left: int, top: int, w: int, h: int) -> None:
        self._region = None
        try:
            from .services.ocr import ocr_region

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
        if self.settings.get("sound", True) and self._notify_style() != "windows":
            _beep()  # у уведомления Windows свой звук
        style = self._notify_style()
        if style == "windows" and native.toast(
            self.native,
            contest.id,
            head,
            body,
            contest.url,
            lang(),
            urgent=offset in (0, SNOOZED) or expired,
        ):
            return
        if style == "tray":
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
        dlg = SettingsDialog(self.win, self.settings, native_ok=bool(self.native))
        if not dlg.exec():
            return
        config.save_settings(self.settings)
        self.clipboard.set_enabled(self.settings.get("clipboard_watch", True))
        if self.settings.get("hotkey") != old_hotkey:
            self._start_hotkey()
        if autostart.supported():
            try:
                self._sync_autostart(dlg.autostart)
            except OSError as e:
                QMessageBox.warning(
                    self.win, tr("Автозапуск"), tr("Не удалось изменить автозапуск:\n{e}", e=e)
                )
        theme_changed = (dlg.theme, dlg.palette) != (
            self.settings.get("theme", "auto"), self.settings.get("palette", "mocha"))
        if theme_changed:
            self.settings["theme"], self.settings["palette"] = dlg.theme, dlg.palette
            config.save_settings(self.settings)
            theme.apply(self.qapp, dlg.theme, dlg.palette)
        if dlg.lang != self.settings.get("lang", "auto"):
            self.set_language(dlg.lang)          # пересоберёт окно и с новой темой
        elif theme_changed:
            self._rebuild_window()
        else:
            self.win.update_hint()
            self.refresh()

    def set_language(self, code: str) -> None:
        """Язык меняется сразу: окно и меню пересобираются."""
        self.settings["lang"] = code
        config.save_settings(self.settings)
        set_lang(code)
        self._rebuild_window()

    def set_theme(self, mode: str | None = None, palette: str | None = None) -> None:
        """Режим (авто/светлая/тёмная/сепия) и палитра - сразу, без перезапуска."""
        if mode:
            self.settings["theme"] = mode
        if palette:
            self.settings["palette"] = palette
        config.save_settings(self.settings)
        theme.apply(self.qapp, self.settings.get("theme", "auto"), self.settings.get("palette", "mocha"))
        self._rebuild_window()

    def _rebuild_window(self) -> None:
        geo = self.win.saveGeometry()
        visible = self.win.isVisible()
        query = self.win.search.text()
        old = self.win
        self.win = MainWindow(self)
        self.win.restoreGeometry(geo)
        self.win.search.setText(query)
        old.hide()
        old.deleteLater()
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
        self.win.update_hint()

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

    def on_window_close(self, event) -> None:
        if getattr(self, "_quitting", False):
            event.accept()
            return
        self.settings["geometry"] = base64.b64encode(bytes(self.win.saveGeometry())).decode("ascii")
        config.save_settings(self.settings)
        event.ignore()
        if self._lite():
            # лёгкий режим: программа выходит целиком, напоминает сторож (~2 МБ)
            self.win.hide()
            self.quit()
            return
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
        # Qt 6 перед выходом просит закрыться все окна, а наше на закрытие прячется в
        # трей - флаг говорит ему «на этот раз выходим», иначе выход отменится
        self._quitting = True
        if self.hotkey is not None:
            self.hotkey.stop()
        self.bridge.stop()
        self.toasts.close_all()
        self._save()
        config.save_settings(self.settings)
        self.tray.hide()
        if self._lite():
            self.app_mutex.release()  # сторож видит, что программа закрылась
            native.start_watcher(self.native)
        self.win.hide()
        self.qapp.exit(0)

    # --- нативная часть -------------------------------------------------
    def _lite(self) -> bool:
        """Лёгкий фоновый режим: вместо программы в трее работает сторож на C++."""
        return bool(self.native) and bool(self.settings.get("watcher_mode", False))

    def _notify_style(self) -> str:
        style = self.settings.get("notify_style", "auto")
        if style == "auto":
            style = "windows" if self.native else "toast"
        if style == "windows" and not self.native:
            style = "toast"
        return style

    def _remove_native(self, c: Contest) -> None:
        if self.native:
            native.remove(self.native, c.id)

    def _sync_autostart(self, on: bool | None = None) -> None:
        """Автозапуск указывает на сторож в лёгком режиме и на программу - в обычном."""
        if not autostart.supported():
            return
        if on is None:
            on = autostart.is_enabled()
        cmd = native.watcher_command(self.native) if self._lite() else autostart.command()
        if not on:
            if autostart.is_enabled():
                autostart.set_enabled(False)
        elif autostart.current() != cmd:
            autostart.set_enabled(True, cmd)

    def _on_toast_action(self, action: str, cid: str, minutes: str) -> None:
        """Кнопка уведомления Windows, нажатая, пока программа запущена."""
        if action == "open" or not cid:
            self.show_window()
            return
        c = next((x for x in self.contests if x.id == cid), None)
        if c is None:
            return
        if action == "done":
            if not c.done:
                self.toggle_done(c)
        elif action == "snooze":
            if minutes == "tomorrow":
                mins = self._snooze_choices()[-1][1]
            else:
                try:
                    mins = max(1, int(minutes))
                except ValueError:
                    mins = 60
            self.snooze(c, mins)

    def run(self) -> int:
        return self.qapp.exec()


def userscript_template() -> Path:
    """Шаблон userscript: в исходниках - browser/, в exe - та же папка внутри сборки."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "browser" / "contestreminder.user.js"


def _install_excepthook() -> None:
    """Ошибка в обработчике Qt не должна закрывать программу (PyQt6 по умолчанию её
    роняет). Пишем в %APPDATA%\\ContestReminder\\errors.log и работаем дальше."""
    import traceback

    def hook(exc_type, exc, tb) -> None:
        try:
            config.APP_DIR.mkdir(parents=True, exist_ok=True)
            log = config.APP_DIR / "errors.log"
            if log.exists() and log.stat().st_size > 512_000:
                log.unlink()
            with log.open("a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} ContestReminder {__version__}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    from .selftest import FLAG
    from .selftest import run as selftest

    if FLAG in sys.argv:
        return selftest(sys.argv)
    _install_excepthook()
    _qapp = QApplication.instance() or QApplication(sys.argv)  # нужен до сокета одной копии
    from .services.single_instance import InstanceServer, notify_running

    if notify_running():
        return 0
    server = InstanceServer()
    app = App()
    server.show_requested.connect(app.show_window)
    app._instance_server = server
    return app.run()
