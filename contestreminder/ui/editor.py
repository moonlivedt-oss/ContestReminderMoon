"""Диалог добавления/редактирования конкурса.

Тот же диалог служит карточкой подтверждения для авто-захвата (буфер/OCR):
поля уже заполнены разобранными данными, пользователю остаётся проверить и нажать
Сохранить. hint выводит поясняющую плашку сверху.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import tr
from ..core.models import Contest
from ..core.parser import Parsed
from ..services import enrich

# Наборы напоминаний, доступные галочками (минуты до дедлайна).
REMINDER_CHOICES = [
    (4320, "за 3 дня"), (1440, "за 1 день"), (360, "за 6 ч"),
    (60, "за 1 час"), (15, "за 15 мин"), (0, "в момент"),
]


class ContestDialog(QDialog):
    def __init__(self, parent=None, contest: Contest | None = None,
                 default_reminders: list[int] | None = None,
                 hint: str = "", prefill=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Конкурс"))
        self.setMinimumWidth(440)
        self._result: Contest | None = None
        editing = contest is not None
        self._base = contest

        # начальные значения: из редактируемого конкурса, иначе из prefill (Parsed)
        init_title = contest.title if editing else (prefill.title if prefill else "")
        init_url = contest.url if editing else (prefill.url if prefill else "")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        if hint:
            banner = QLabel(hint)
            banner.setObjectName("chip")
            banner.setWordWrap(True)
            root.addWidget(banner)

        title = QLabel(tr("Редактировать конкурс") if editing else tr("Новый конкурс"))
        title.setObjectName("h1")
        root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        root.addLayout(grid)

        grid.addWidget(QLabel(tr("Название")), 0, 0)
        self.ed_title = QLineEdit(init_title)
        self.ed_title.setPlaceholderText(tr("Название конкурса"))
        grid.addWidget(self.ed_title, 0, 1)

        grid.addWidget(QLabel(tr("Ссылка")), 1, 0)
        self.ed_url = QLineEdit(init_url)
        self.ed_url.setPlaceholderText("https://...")
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        url_row.addWidget(self.ed_url, 1)
        self.btn_fetch = QPushButton(tr("По ссылке"))
        self.btn_fetch.setObjectName("ghost")
        self.btn_fetch.setToolTip(tr("Открыть страницу и взять оттуда название и срок"))
        self.btn_fetch.clicked.connect(self._fetch)
        url_row.addWidget(self.btn_fetch)
        grid.addLayout(url_row, 1, 1)
        self.fetch_status = QLabel("")
        self.fetch_status.setObjectName("muted")
        self.fetch_status.setVisible(False)
        grid.addWidget(self.fetch_status, 2, 1)
        self._job = None

        grid.addWidget(QLabel(tr("Дедлайн")), 3, 0, Qt.AlignmentFlag.AlignTop)
        dl_box = QVBoxLayout()
        dl_box.setSpacing(6)
        self.chk_has_deadline = QCheckBox(tr("Есть срок окончания"))
        dl_box.addWidget(self.chk_has_deadline)
        self.ed_deadline = QDateTimeEdit()
        self.ed_deadline.setCalendarPopup(True)
        self.ed_deadline.setDisplayFormat("dd.MM.yyyy  HH:mm")
        dl_box.addWidget(self.ed_deadline)
        grid.addLayout(dl_box, 3, 1)

        dt = contest.deadline_dt if editing else (prefill.deadline if prefill else None)
        has_deadline = dt is not None
        if dt is None:
            dt = (datetime.now() + timedelta(days=1)).replace(
                hour=23, minute=59, second=0, microsecond=0)
        self.chk_has_deadline.setChecked(has_deadline)
        self.ed_deadline.setDateTime(QDateTime(dt))
        self.chk_has_deadline.toggled.connect(self.ed_deadline.setEnabled)
        self.ed_deadline.setEnabled(self.chk_has_deadline.isChecked())

        # напоминания
        grid.addWidget(QLabel(tr("Напоминать")), 4, 0, Qt.AlignmentFlag.AlignTop)
        rem_wrap = QWidget()
        rem_grid = QGridLayout(rem_wrap)
        rem_grid.setContentsMargins(0, 0, 0, 0)
        rem_grid.setHorizontalSpacing(14)
        rem_grid.setVerticalSpacing(4)
        preset = set(contest.reminders if editing else (default_reminders or [1440, 60, 0]))
        self.rem_checks: list[tuple[int, QCheckBox]] = []
        for i, (minutes, label) in enumerate(REMINDER_CHOICES):
            cb = QCheckBox(tr(label))
            cb.setChecked(minutes in preset)
            rem_grid.addWidget(cb, i // 2, i % 2)
            self.rem_checks.append((minutes, cb))
        grid.addWidget(rem_wrap, 4, 1)

        grid.addWidget(QLabel(tr("Исходник")), 5, 0, Qt.AlignmentFlag.AlignTop)
        self.ed_source = QPlainTextEdit(contest.source_text if editing else "")
        self.ed_source.setPlaceholderText(tr("Текст, из которого взята информация (необязательно)"))
        self.ed_source.setFixedHeight(70)
        grid.addWidget(self.ed_source, 5, 1)

        grid.setColumnStretch(1, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr("Отмена"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton(tr("Сохранить"))
        save.setObjectName("accent")
        save.clicked.connect(self._save)
        save.setDefault(True)
        btns.addWidget(save)
        root.addLayout(btns)

    def _save(self) -> None:
        title = self.ed_title.text().strip() or tr("(без названия)")
        deadline = None
        if self.chk_has_deadline.isChecked():
            deadline = self.ed_deadline.dateTime().toPyDateTime().replace(
                second=0, microsecond=0).isoformat(timespec="seconds")
        reminders = sorted((m for m, cb in self.rem_checks if cb.isChecked()),
                           reverse=True)
        if self._base is not None:
            c = self._base
            c.title = title
            c.url = self.ed_url.text().strip()
            new_deadline = deadline
            if new_deadline != c.deadline:
                c.notified = []  # дедлайн изменился — напоминания заново
            c.deadline = new_deadline
            c.reminders = reminders
            c.source_text = self.ed_source.toPlainText().strip()
        else:
            c = Contest(
                title=title, url=self.ed_url.text().strip(), deadline=deadline,
                source_text=self.ed_source.toPlainText().strip(),
                reminders=reminders)
        self._result = c
        self.accept()

    def _fetch(self) -> None:
        url = self.ed_url.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.fetch_status.setText(tr("Нужна ссылка, начинающаяся с http:// или https://"))
            self.fetch_status.setVisible(True)
            return
        self.btn_fetch.setEnabled(False)
        self.fetch_status.setText(tr("Читаю страницу…"))
        self.fetch_status.setVisible(True)
        self._job = enrich.start(url, self._fetched)

    def _fetched(self, info, error) -> None:
        self._job = None
        try:
            self.btn_fetch.setEnabled(True)
        except RuntimeError:          # окно уже закрыли
            return
        if info is None:
            self.fetch_status.setText(tr("Не удалось открыть страницу: {e}", e=error))
            return
        dl = (self.ed_deadline.dateTime().toPyDateTime()
              if self.chk_has_deadline.isChecked() else None)
        base = Parsed(title=self.ed_title.text().strip(), url=self.ed_url.text().strip(), deadline=dl)
        merged = enrich.merge(base, info)
        got = []
        if merged.title and merged.title != base.title:
            self.ed_title.setText(merged.title)
            got.append(tr("название"))
        if merged.deadline and dl is None:
            self.chk_has_deadline.setChecked(True)
            self.ed_deadline.setDateTime(QDateTime(merged.deadline))
            got.append(tr("срок"))
        self.fetch_status.setText(tr("Со страницы: {what}", what=", ".join(got)) if got
                                  else tr("На странице нового не нашлось"))

    @property
    def contest(self) -> Contest | None:
        return self._result
