"""Окно настроек: всё, что раньше правилось только в settings.json."""

from __future__ import annotations

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from . import autostart
from .editor import REMINDER_CHOICES
from .hotkey import parse_spec
from .i18n import LANGS, tr

CAPTURE_MODES = [
    ("ask", "Спрашивать карточкой в углу"),
    ("auto", "Сохранять сразу (с кнопкой «Отменить»)"),
    ("dialog", "Открывать окно редактирования"),
]
NOTIFY_STYLES = [
    ("toast", "Карточка с кнопками"),
    ("tray", "Уведомление Windows"),
]
OCR_LANGS = [("ru", "Русский"), ("en-US", "Английский"), ("", "Как в системе")]


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def _combo(items: list[tuple[str, str]], value: str) -> QComboBox:
    cb = QComboBox()
    for key, label in items:
        cb.addItem(tr(label), key)
    idx = cb.findData(value)
    cb.setCurrentIndex(max(0, idx))
    return cb


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Настройки"))
        self.setMinimumWidth(500)
        self._s = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        h = QLabel(tr("Настройки"))
        h.setObjectName("h1")
        root.addWidget(h)

        # --- захват ---
        form = QFormLayout()
        form.addRow(_section(tr("Автозапись")))
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.chk_clip = QCheckBox(tr("Следить за буфером обмена"))
        self.chk_clip.setChecked(settings.get("clipboard_watch", True))
        form.addRow(self.chk_clip)
        self.cb_mode = _combo(CAPTURE_MODES, settings.get("capture_mode", "ask"))
        form.addRow(tr("Нашёл конкурс"), self.cb_mode)
        self.chk_enrich = QCheckBox(tr("Уточнять название и срок по ссылке (загружает страницу)"))
        self.chk_enrich.setChecked(settings.get("enrich", True))
        form.addRow(self.chk_enrich)
        self.ed_hotkey = QLineEdit(settings.get("hotkey", "ctrl+alt+c"))
        self.ed_hotkey.setPlaceholderText(tr("например ctrl+alt+c или ctrl+shift+f9"))
        form.addRow(tr("Клавиша OCR"), self.ed_hotkey)
        self.cb_ocr = _combo(OCR_LANGS, settings.get("ocr_lang", "ru"))
        form.addRow(tr("Язык OCR"), self.cb_ocr)

        # --- напоминания ---
        form.addRow(_section(tr("Напоминания")))
        rem = QWidget()
        grid = QGridLayout(rem)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        preset = set(settings.get("default_reminders", [1440, 60, 0]))
        self.rem_checks: list[tuple[int, QCheckBox]] = []
        for i, (minutes, label) in enumerate(REMINDER_CHOICES):
            cb = QCheckBox(tr(label))
            cb.setChecked(minutes in preset)
            grid.addWidget(cb, 0 if i < 3 else 1, i % 3)
            self.rem_checks.append((minutes, cb))
        form2 = form
        form2.addRow(tr("Для новых конкурсов"), rem)
        self.cb_style = _combo(NOTIFY_STYLES, settings.get("notify_style", "toast"))
        form2.addRow(tr("Как показывать"), self.cb_style)
        self.chk_sound = QCheckBox(tr("Звук"))
        self.chk_sound.setChecked(settings.get("sound", True))
        form2.addRow(self.chk_sound)

        digest_row = QHBoxLayout()
        digest_row.setSpacing(8)
        self.chk_digest = QCheckBox(tr("Сводка дня в"))
        at = settings.get("digest_time", "10:00")
        self.chk_digest.setChecked(bool(at))
        self.ed_digest = QTimeEdit(QTime.fromString(at or "10:00", "HH:mm"))
        self.ed_digest.setDisplayFormat("HH:mm")
        self.sp_days = QSpinBox()
        self.sp_days.setRange(1, 14)
        self.sp_days.setValue(int(settings.get("digest_days", 3)))
        self.sp_days.setSuffix(tr(" дн. вперёд"))
        digest_row.addWidget(self.ed_digest)
        digest_row.addWidget(self.sp_days)
        digest_row.addStretch(1)
        self.chk_digest.toggled.connect(self.ed_digest.setEnabled)
        self.chk_digest.toggled.connect(self.sp_days.setEnabled)
        self.ed_digest.setEnabled(bool(at))
        self.sp_days.setEnabled(bool(at))
        form2.addRow(self.chk_digest, digest_row)

        self.sp_close = QSpinBox()
        self.sp_close.setRange(0, 60)
        self.sp_close.setValue(int(settings.get("auto_close_days", 3)))
        self.sp_close.setSpecialValueText(tr("никогда"))
        self.sp_close.setSuffix(tr(" дн. после дедлайна"))
        form2.addRow(tr("Убирать прошедшие"), self.sp_close)

        # --- система ---
        form.addRow(_section(tr("Система")))
        self.cb_lang = _combo([(c, tr(lbl) if c == "auto" else lbl) for c, lbl in LANGS],
                              settings.get("lang", "auto"))
        form.addRow("Язык / Language", self.cb_lang)
        self.chk_auto = QCheckBox(tr("Запускать вместе с Windows (сразу в трей)"))
        self.chk_auto.setEnabled(autostart.supported())
        self.chk_auto.setChecked(autostart.is_enabled())
        form.addRow(self.chk_auto)
        root.addLayout(form)

        self.err = QLabel("")
        self.err.setObjectName("error")
        self.err.setVisible(False)
        root.addWidget(self.err)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("sep")
        root.addWidget(line)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr("Отмена"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("Сохранить"))
        ok.setObjectName("accent")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _save(self) -> None:
        hotkey = self.ed_hotkey.text().strip().lower().replace(" ", "")
        if hotkey and parse_spec(hotkey) is None:
            self.err.setText(tr("Клавишу не понял. Формат: ctrl+alt+c, ctrl+shift+f9."))
            self.err.setVisible(True)
            return
        s = self._s
        s["clipboard_watch"] = self.chk_clip.isChecked()
        s["capture_mode"] = self.cb_mode.currentData()
        s["enrich"] = self.chk_enrich.isChecked()
        s["hotkey"] = hotkey
        s["ocr_lang"] = self.cb_ocr.currentData()
        s["default_reminders"] = sorted(
            (m for m, cb in self.rem_checks if cb.isChecked()), reverse=True
        )
        s["notify_style"] = self.cb_style.currentData()
        s["sound"] = self.chk_sound.isChecked()
        s["digest_time"] = (
            self.ed_digest.time().toString("HH:mm") if self.chk_digest.isChecked() else ""
        )
        s["digest_days"] = self.sp_days.value()
        s["auto_close_days"] = self.sp_close.value()
        self.autostart = self.chk_auto.isChecked()
        self.lang = self.cb_lang.currentData()
        self.accept()
