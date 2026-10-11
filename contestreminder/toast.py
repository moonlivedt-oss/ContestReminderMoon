"""Всплывающие карточки в углу экрана: напоминания, предложения сохранить, «Вернуть».

Системное уведомление трея не умеет кнопок, а здесь нужны «Открыть», «Отложить»,
«Сохранить». Карточка не забирает фокус (печатать в другом окне можно дальше),
стопкой растёт вверх от правого нижнего угла, пока мышь над ней - не исчезает.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .icons import asset_icon

_WIDTH = 360
_GAP = 10


@dataclass
class Action:
    label: str
    callback: Callable[[], None] | None = None
    kind: str = "ghost"  # accent | ghost | dangerGhost
    menu: list[tuple[str, Callable[[], None]]] | None = None  # кнопка со списком
    keep_open: bool = False  # не закрывать карточку после нажатия


class Toast(QWidget):
    def __init__(
        self,
        manager: ToastManager,
        title: str,
        body: str,
        actions: list[Action],
        timeout_ms: int,
        icon: str,
        kind: str,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._mgr = manager
        self._timeout = timeout_ms
        self._closing = False
        self.setFixedWidth(_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("toast")
        card.setProperty("kind", kind)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(asset_icon(icon).pixmap(QSize(22, 22)))
        head.addWidget(ico, 0, Qt.AlignmentFlag.AlignTop)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("toastTitle")
        self.lbl_title.setWordWrap(True)
        head.addWidget(self.lbl_title, 1)
        close = QPushButton("×")
        close.setObjectName("toastClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Закрыть")
        close.clicked.connect(self.dismiss)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        self.lbl_body = QLabel(body)
        self.lbl_body.setObjectName("toastBody")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_body.setVisible(bool(body))
        lay.addWidget(self.lbl_body)

        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(6)
        self.btn_row.addStretch(1)
        lay.addLayout(self.btn_row)
        self.set_actions(actions)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    # --- содержимое -------------------------------------------------------
    def set_text(self, title: str | None = None, body: str | None = None) -> None:
        if title is not None:
            self.lbl_title.setText(title)
        if body is not None:
            self.lbl_body.setText(body)
            self.lbl_body.setVisible(bool(body))
        self.adjustSize()
        self._mgr.relayout()

    def set_actions(self, actions: list[Action]) -> None:
        while self.btn_row.count() > 1:
            item = self.btn_row.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        for a in actions:
            btn = QPushButton(a.label)
            btn.setObjectName(a.kind)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if a.menu:
                m = QMenu(btn)
                for label, cb in a.menu:
                    m.addAction(label, self._wrap(cb, a.keep_open))
                btn.setMenu(m)
            else:
                btn.clicked.connect(self._wrap(a.callback, a.keep_open))
            self.btn_row.addWidget(btn)
        self.adjustSize()

    def _wrap(self, cb, keep_open: bool):
        def run() -> None:
            if not keep_open:
                self.dismiss()
            if cb:
                cb()

        return run

    # --- жизнь карточки ---------------------------------------------------
    def start(self) -> None:
        self.adjustSize()
        self.setWindowOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._restart_timer()

    def _restart_timer(self) -> None:
        if self._timeout > 0:
            self._timer.start(self._timeout)

    def enterEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._restart_timer()
        super().leaveEvent(event)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(150)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.finished.connect(self._really_close)
        anim.start()

    def _really_close(self) -> None:
        self._mgr.forget(self)
        self.close()


class ToastManager:
    """Держит открытые карточки и раскладывает их стопкой в правом нижнем углу."""

    MAX = 4

    def __init__(self) -> None:
        self._toasts: list[Toast] = []

    def show(
        self,
        title: str,
        body: str = "",
        actions: list[Action] | None = None,
        timeout_ms: int = 12000,
        icon: str = "bell",
        kind: str = "info",
    ) -> Toast:
        while len(self._toasts) >= self.MAX:
            self._toasts[0].dismiss()
            self.forget(self._toasts[0])
        t = Toast(self, title, body, actions or [], timeout_ms, icon, kind)
        self._toasts.append(t)
        t.start()
        self.relayout()
        return t

    def forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self.relayout()

    def relayout(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        y = area.bottom() - _GAP
        for t in reversed(self._toasts):
            t.adjustSize()
            y -= t.height()
            t.move(area.right() - _WIDTH - _GAP, y)
            y -= _GAP

    def close_all(self) -> None:
        for t in list(self._toasts):
            t.close()
        self._toasts.clear()
