"""Главное окно, системный трей и связывание всех частей.

Окно живёт в трее: закрытие прячет его, а не завершает приложение. Выход — только
через меню трея. Авто-захват (буфер/OCR) открывает диалог с уже заполненными
полями; планировщик шлёт уведомления через всплывающие сообщения трея.
"""
from __future__ import annotations

import base64
import sys
from datetime import datetime

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import autostart, config
from .clipboard_watch import ClipboardWatcher
from .editor import ContestDialog
from .hotkey import HotkeyManager
from .icons import app_icon, asset_icon
from .models import Contest, fmt_countdown, fmt_deadline, fmt_offset
from .parser import parse
from .reminders import ReminderScheduler
from .theme import build_qss


class ContestCard(QFrame):
    def __init__(self, contest: Contest, app: App) -> None:
        super().__init__()
        self.setObjectName("contestCard")
        self._c = contest
        self._app = app
        self.setProperty("expired", contest.is_expired and not contest.done)
        self.setProperty("done", contest.done)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 12, 10)
        outer.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(6)
        outer.addLayout(left, 1)

        title = QLabel(contest.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        if contest.done:
            title.setStyleSheet("text-decoration: line-through; color: #a6adc8;")
        left.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        left.addLayout(meta)

        dt = contest.deadline_dt
        chip = QLabel(fmt_countdown(dt))
        chip.setObjectName(self._chip_style(contest))
        meta.addWidget(chip)

        if dt:
            when = QLabel(fmt_deadline(dt))
            when.setObjectName("muted")
            meta.addWidget(when)

        meta.addStretch(1)

        if contest.reminders:
            rem = QLabel("напоминания: " + ", ".join(
                fmt_offset(m) for m in contest.reminders))
            rem.setObjectName("muted")
            left.addWidget(rem)

        # нижний ряд: ссылка слева, действия справа (одной строкой - карточка ниже)
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        left.addLayout(bottom)
        if contest.url:
            link = QLabel(f'<a style="color:#cba6f7;text-decoration:none" '
                          f'href="{contest.url}">{self._short_url(contest.url)}</a>')
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

        action("Вернуть" if contest.done else "Готово", "done", "ghost",
               lambda: app.toggle_done(contest))
        action("Изменить", "edit", "ghost", lambda: app.edit_contest(contest))
        action("Удалить", "delete", "dangerGhost", lambda: app.delete_contest(contest))

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
        u = url.replace("https://", "").replace("http://", "")
        return u[:48] + ("…" if len(u) > 48 else "")


class App:
    def __init__(self) -> None:
        self.qapp = QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setStyleSheet(build_qss())

        self.settings = config.load_settings()
        self.contests: list[Contest] = config.load_contests()

        self._build_window()
        self._build_tray()

        self.clipboard = ClipboardWatcher()
        self.clipboard.captured.connect(self._on_clipboard)
        self.clipboard.set_enabled(self.settings.get("clipboard_watch", True))

        self.hotkey = HotkeyManager(self.settings.get("hotkey", "ctrl+alt+c"))
        self.hotkey.triggered.connect(self.ocr_capture)
        self.hotkey.start()

        self.scheduler = ReminderScheduler(
            lambda: self.contests, self._notify, self._save)
        self.scheduler.start()

        self._region = None  # держим ссылку на оверлей выбора области
        self.refresh()
        # показываем окно при запуске (потом живёт в трее); автозапуск с
        # Windows передаёт --tray - тогда сразу в фон, без окна
        if autostart.TRAY_FLAG not in sys.argv[1:]:
            self.show_window()

    # --- построение UI --------------------------------------------------
    def _build_window(self) -> None:
        self.win = QWidget()
        self.win.setObjectName("root")
        self.win.setWindowTitle("ContestReminder — напоминалка о конкурсах")
        self.win.setWindowIcon(app_icon())
        self.win.resize(560, 640)
        self.win.closeEvent = self._on_close  # прячем в трей

        root = QVBoxLayout(self.win)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        h = QLabel("Конкурсы")
        h.setObjectName("h1")
        header.addWidget(h)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("muted")
        header.addWidget(self.count_lbl)
        header.addStretch(1)

        cw_btn = QPushButton("Слежение за буфером")
        cw_btn.setCheckable(True)
        cw_btn.setChecked(self.settings.get("clipboard_watch", True))
        cw_btn.setObjectName("ghost")
        cw_btn.setIcon(asset_icon("clipboard"))
        cw_btn.setToolTip("Скопированный пост о конкурсе сразу предлагается сохранить")
        cw_btn.toggled.connect(self._toggle_clipboard)
        self.cw_btn = cw_btn
        header.addWidget(cw_btn)

        ocr_btn = QPushButton("OCR-захват")
        ocr_btn.setObjectName("ghost")
        ocr_btn.setIcon(asset_icon("ocr"))
        ocr_btn.setToolTip("Выделить область экрана с постом и распознать текст")
        ocr_btn.clicked.connect(self.ocr_capture)
        header.addWidget(ocr_btn)

        add_btn = QPushButton("Добавить")
        add_btn.setObjectName("accent")
        add_btn.setIcon(asset_icon("add"))
        add_btn.clicked.connect(self.add_manual)
        header.addWidget(add_btn)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(9)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        hint = QLabel(
            "Скопируй пост/ссылку конкурса — приложение само предложит сохранить. "
            f"Или нажми {self.settings.get('hotkey', 'ctrl+alt+c').upper()} для OCR-захвата области экрана.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        geo = self.settings.get("geometry")
        if geo:
            try:
                self.win.restoreGeometry(QByteArray(base64.b64decode(geo)))
            except (ValueError, TypeError):
                pass

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("ContestReminder")
        menu = QMenu()

        act_open = QAction("Открыть окно", self.qapp)
        act_open.triggered.connect(self.show_window)
        menu.addAction(act_open)

        act_add = QAction("Добавить вручную", self.qapp)
        act_add.triggered.connect(self.add_manual)
        menu.addAction(act_add)

        act_ocr = QAction("OCR-захват области", self.qapp)
        act_ocr.triggered.connect(self.ocr_capture)
        menu.addAction(act_ocr)

        menu.addSeparator()
        self.act_cw = QAction("Слежение за буфером", self.qapp)
        self.act_cw.setCheckable(True)
        self.act_cw.setChecked(self.settings.get("clipboard_watch", True))
        self.act_cw.toggled.connect(self._toggle_clipboard)
        menu.addAction(self.act_cw)

        if autostart.supported():
            self.act_auto = QAction("Запускать вместе с Windows", self.qapp)
            self.act_auto.setCheckable(True)
            self.act_auto.setChecked(autostart.is_enabled())
            self.act_auto.toggled.connect(self._toggle_autostart)
            menu.addAction(self.act_auto)

        menu.addSeparator()
        act_quit = QAction("Выход", self.qapp)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # --- список ---------------------------------------------------------
    def _sort_key(self, c: Contest):
        dt = c.deadline_dt
        # активные раньше выполненных; внутри — по дедлайну (без срока в конец)
        big = 9999999999.0
        ts = dt.timestamp() if dt else big
        return (c.done, ts)

    def refresh(self) -> None:
        # очищаем всё кроме финального stretch
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        ordered = sorted(self.contests, key=self._sort_key)
        active = sum(1 for c in self.contests if not c.done)
        self.count_lbl.setText(f"активных {active} из {len(self.contests)}")

        if not ordered:
            empty = QLabel("Пока пусто. Скопируй пост о конкурсе или добавь вручную.")
            empty.setObjectName("empty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.list_lay.insertWidget(0, empty)
            return

        for c in ordered:
            self.list_lay.insertWidget(self.list_lay.count() - 1, ContestCard(c, self))

    # --- операции с конкурсами -----------------------------------------
    def _save(self) -> None:
        config.save_contests(self.contests)

    def add_manual(self) -> None:
        self.show_window()
        dlg = ContestDialog(self.win,
                            default_reminders=self.settings.get("default_reminders"))
        if dlg.exec() and dlg.contest:
            self.contests.append(dlg.contest)
            self._save()
            self.refresh()

    def edit_contest(self, contest: Contest) -> None:
        dlg = ContestDialog(self.win, contest=contest)
        if dlg.exec():
            self._save()
            self.refresh()

    def delete_contest(self, contest: Contest) -> None:
        box = QMessageBox(self.win)
        box.setWindowTitle("Удаление")
        box.setText(f"Удалить конкурс «{contest.title}»?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.contests = [c for c in self.contests if c.id != contest.id]
            self._save()
            self.refresh()

    def toggle_done(self, contest: Contest) -> None:
        contest.done = not contest.done
        self._save()
        self.refresh()

    # --- авто-захват ----------------------------------------------------
    def _on_clipboard(self, text: str) -> None:
        parsed = parse(text)
        if not parsed.is_contest_like:
            return  # обычная копия — не мешаем
        self._offer(parsed, text,
                    "Похоже на конкурс из буфера обмена — проверь и сохрани")

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
        except Exception as e:  # noqa: BLE001 — OCR-движок/язык может отсутствовать
            QMessageBox.warning(self.win, "OCR", f"Не удалось распознать текст:\n{e}")
            return
        if not text.strip():
            self.tray.showMessage("OCR", "Текст не распознан",
                                  QSystemTrayIcon.MessageIcon.Warning, 3000)
            return
        self._offer(parse(text), text,
                    "Распознан текст с экрана — проверь и сохрани")

    def _offer(self, parsed, raw_text: str, hint: str) -> None:
        self.show_window()
        dlg = ContestDialog(
            self.win, default_reminders=self.settings.get("default_reminders"),
            hint=hint, prefill=parsed)
        dlg.ed_source.setPlainText(raw_text.strip())
        if dlg.exec() and dlg.contest:
            self.contests.append(dlg.contest)
            self._save()
            self.refresh()

    # --- уведомления ----------------------------------------------------
    def _notify(self, contest: Contest, offset: int, expired: bool) -> None:
        if expired:
            head = "Дедлайн прошёл"
        elif offset == 0:
            head = "Дедлайн сейчас!"
        else:
            head = f"Напоминание ({fmt_offset(offset)})"
        body = contest.title
        if contest.deadline_dt:
            body += f"\n{fmt_countdown(contest.deadline_dt)} | {fmt_deadline(contest.deadline_dt)}"
        if contest.url:
            body += f"\n{contest.url}"
        self.tray.showMessage(head, body, app_icon(), 12000)
        self.refresh()

    # --- разное ---------------------------------------------------------
    def _toggle_clipboard(self, on: bool) -> None:
        self.settings["clipboard_watch"] = on
        config.save_settings(self.settings)
        self.clipboard.set_enabled(on)
        # держим обе галки (кнопка в окне и пункт трея) синхронно
        if hasattr(self, "cw_btn") and self.cw_btn.isChecked() != on:
            self.cw_btn.setChecked(on)
        if hasattr(self, "act_cw") and self.act_cw.isChecked() != on:
            self.act_cw.setChecked(on)

    def _toggle_autostart(self, on: bool) -> None:
        try:
            autostart.set_enabled(on)
        except OSError as exc:
            QMessageBox.warning(self.win, "Автозапуск",
                                f"Не удалось изменить автозапуск:\n{exc}")
            self.act_auto.blockSignals(True)
            self.act_auto.setChecked(autostart.is_enabled())
            self.act_auto.blockSignals(False)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def _on_close(self, event) -> None:
        # прячем в трей вместо выхода + сохраняем геометрию
        self.settings["geometry"] = base64.b64encode(
            bytes(self.win.saveGeometry())).decode("ascii")
        config.save_settings(self.settings)
        event.ignore()
        self.win.hide()
        self.tray.showMessage(
            "ContestReminder свернут в трей",
            "Слежу за конкурсами в фоне. Двойной клик по иконке — открыть.",
            app_icon(), 4000)

    def quit(self) -> None:
        self.hotkey.stop()
        self._save()
        config.save_settings(self.settings)
        self.tray.hide()
        self.qapp.quit()

    def run(self) -> int:
        return self.qapp.exec()


def main() -> int:
    app = App()
    return app.run()
