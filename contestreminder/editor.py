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

from .models import Contest

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
        self.setWindowTitle("Конкурс")
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

        title = QLabel("Редактировать конкурс" if editing else "Новый конкурс")
        title.setObjectName("h1")
        root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        root.addLayout(grid)

        grid.addWidget(QLabel("Название"), 0, 0)
        self.ed_title = QLineEdit(init_title)
        self.ed_title.setPlaceholderText("Название конкурса")
        grid.addWidget(self.ed_title, 0, 1)

        grid.addWidget(QLabel("Ссылка"), 1, 0)
        self.ed_url = QLineEdit(init_url)
        self.ed_url.setPlaceholderText("https://...")
        grid.addWidget(self.ed_url, 1, 1)

        grid.addWidget(QLabel("Дедлайн"), 2, 0, Qt.AlignmentFlag.AlignTop)
        dl_box = QVBoxLayout()
        dl_box.setSpacing(6)
        self.chk_has_deadline = QCheckBox("Есть срок окончания")
        dl_box.addWidget(self.chk_has_deadline)
        self.ed_deadline = QDateTimeEdit()
        self.ed_deadline.setCalendarPopup(True)
        self.ed_deadline.setDisplayFormat("dd.MM.yyyy  HH:mm")
        dl_box.addWidget(self.ed_deadline)
        grid.addLayout(dl_box, 2, 1)

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
        grid.addWidget(QLabel("Напоминать"), 3, 0, Qt.AlignmentFlag.AlignTop)
        rem_wrap = QWidget()
        rem_grid = QGridLayout(rem_wrap)
        rem_grid.setContentsMargins(0, 0, 0, 0)
        rem_grid.setHorizontalSpacing(14)
        rem_grid.setVerticalSpacing(4)
        preset = set(contest.reminders if editing else (default_reminders or [1440, 60, 0]))
        self.rem_checks: list[tuple[int, QCheckBox]] = []
        for i, (minutes, label) in enumerate(REMINDER_CHOICES):
            cb = QCheckBox(label)
            cb.setChecked(minutes in preset)
            rem_grid.addWidget(cb, i // 2, i % 2)
            self.rem_checks.append((minutes, cb))
        grid.addWidget(rem_wrap, 3, 1)

        grid.addWidget(QLabel("Исходник"), 4, 0, Qt.AlignmentFlag.AlignTop)
        self.ed_source = QPlainTextEdit(contest.source_text if editing else "")
        self.ed_source.setPlaceholderText("Текст, из которого взята информация (необязательно)")
        self.ed_source.setFixedHeight(70)
        grid.addWidget(self.ed_source, 4, 1)

        grid.setColumnStretch(1, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("Сохранить")
        save.setObjectName("accent")
        save.clicked.connect(self._save)
        save.setDefault(True)
        btns.addWidget(save)
        root.addLayout(btns)

    def _save(self) -> None:
        title = self.ed_title.text().strip() or "(без названия)"
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

    @property
    def contest(self) -> Contest | None:
        return self._result
