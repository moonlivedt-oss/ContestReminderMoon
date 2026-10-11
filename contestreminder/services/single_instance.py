"""Одна копия программы: второй запуск не плодит второй трей, а показывает окно первой.

Локальный сокет QLocalServer с именем по пользователю Windows. Первая копия
слушает; вторая подключается, шлёт «show» и выходит.
"""

from __future__ import annotations

import getpass

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


def _name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - нет переменных окружения пользователя
        user = "user"
    return f"ContestReminder-{user}"


def notify_running() -> bool:
    """True, если копия уже запущена (ей отправлена просьба показать окно)."""
    sock = QLocalSocket()
    sock.connectToServer(_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    show_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        QLocalServer.removeServer(_name())  # хвост от упавшей копии
        self._server.listen(_name())
        self._server.newConnection.connect(self._on_conn)

    def _on_conn(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda: self._read(sock))

    def _read(self, sock: QLocalSocket) -> None:
        if bytes(sock.readAll()).startswith(b"show"):
            self.show_requested.emit()
        sock.disconnectFromServer()
