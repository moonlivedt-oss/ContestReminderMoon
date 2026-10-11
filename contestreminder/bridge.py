"""Локальный мост: браузер (закладка, userscript) и PowerShell присылают текст поста.

HTTP-сервер слушает только 127.0.0.1. Любая страница в браузере может попытаться
обратиться к localhost, поэтому каждое добавление требует секретный ключ
(`bridge_token` в настройках): без него - 403. Заголовок Host проверяется, чтобы
чужой домен, указывающий на 127.0.0.1 (DNS rebinding), не прошёл. Присланное не
сохраняется молча, а идёт тем же путём, что и буфер обмена: карточка
«Сохранить?» (или автосохранение с «Отменить», если так настроено).

  GET  /ping                         -> {"app": "ContestReminder"} (ключ не нужен)
  GET  /add?token=..&text=..&url=..  -> маленькая страница «Отправлено» (закладка)
  POST /add  JSON {token, text, url, title} или заголовок X-Token -> {"ok": true}
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from PyQt6.QtCore import QObject, pyqtSignal

from .i18n import tr

DEFAULT_PORT = 47615
MAX_BODY = 64 * 1024
MAX_TEXT = 8000

_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>ContestReminder</title>
<body style="font:15px Segoe UI,sans-serif;background:#181825;color:#cdd6f4;
display:grid;place-items:center;height:90vh;margin:0">
<div style="text-align:center"><b style="color:#cba6f7">ContestReminder</b><br>{msg}</div>
<script>setTimeout(function(){{window.close()}},900)</script></body>"""


def new_token() -> str:
    return secrets.token_urlsafe(18)


class Bridge(QObject):
    """Сервер в фоновом потоке; присланное приходит сигналом received в главный поток."""

    received = pyqtSignal(str, str, str)  # text, url, title
    action = pyqtSignal(str, str, str)  # done | snooze | open, id конкурса, минуты/"tomorrow"

    def __init__(self, token: str, port: int = DEFAULT_PORT) -> None:
        super().__init__()
        self.token = token
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # без вывода в консоль
                pass

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").split(":")[0].lower()
                return host in ("127.0.0.1", "localhost")

            def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _accept(self, token: str, text: str, url: str, title: str) -> int:
                if not hmac.compare_digest(token or "", bridge.token):
                    return 403
                text = (text or "").strip()[:MAX_TEXT]
                url = (url or "").strip()[:2000]
                if not url.lower().startswith(("http://", "https://")):
                    url = ""
                if not text and not url:
                    return 400
                bridge.received.emit(text, url, (title or "").strip()[:300])
                return 200

            def do_GET(self) -> None:  # noqa: N802 - имя из http.server
                if not self._host_ok():
                    return self._send(403, '{"error": "host"}')
                parts = urlsplit(self.path)
                if parts.path == "/ping":
                    return self._send(200, json.dumps({"app": "ContestReminder"}))
                if parts.path != "/add":
                    return self._send(404, '{"error": "not found"}')
                q = {k: v[0] for k, v in parse_qs(parts.query).items()}
                code = self._accept(
                    q.get("token", ""), q.get("text", ""), q.get("url", ""), q.get("title", "")
                )
                msg = {
                    200: tr("Отправлено, проверьте карточку в углу экрана."),
                    403: tr("Неверный ключ: обновите закладку в настройках программы."),
                    400: tr("Нечего отправлять: выделите текст поста."),
                }[code]
                self._send(code, _DONE_PAGE.format(msg=msg), "text/html")

            def do_POST(self) -> None:  # noqa: N802
                if not self._host_ok():
                    return self._send(403, '{"error": "host"}')
                path = urlsplit(self.path).path
                if path not in ("/add", "/action"):
                    return self._send(404, '{"error": "not found"}')
                size = int(self.headers.get("Content-Length") or 0)
                if size > MAX_BODY:
                    return self._send(413, '{"error": "too large"}')
                raw = self.rfile.read(size).decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw) if raw.strip().startswith("{") else {"text": raw}
                except json.JSONDecodeError:
                    data = {"text": raw}
                token = self.headers.get("X-Token") or str(data.get("token", ""))
                if path == "/action":   # кнопка уведомления Windows (crnative.exe)
                    act = str(data.get("action", ""))
                    if not hmac.compare_digest(token or "", bridge.token):
                        return self._send(403, '{"ok": false}')
                    if act not in ("done", "snooze", "open"):
                        return self._send(400, '{"ok": false}')
                    bridge.action.emit(act, str(data.get("id", ""))[:64], str(data.get("min", ""))[:12])
                    return self._send(200, '{"ok": true}')
                code = self._accept(
                    token,
                    str(data.get("text", "")),
                    str(data.get("url", "")),
                    str(data.get("title", "")),
                )
                self._send(code, json.dumps({"ok": code == 200}))

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as e:  # порт занят - мост выключен, остальное работает
            self.error = str(e)
            self._server = None
            return False
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def bookmarklet(token: str, port: int = DEFAULT_PORT) -> str:
    """Закладка для браузера: выделенный текст (или заголовок страницы) + адрес -> программа.

    Открывает маленькое окно на 127.0.0.1 обычным переходом: так не мешают ни CORS,
    ни смешанное содержимое на https-страницах.
    """
    js = (
        "(function(){var s=String(window.getSelection()||'').trim();"
        "if(!s){var m=document.querySelector('meta[property=\"og:description\"]');"
        "s=(document.title||'')+(m?'\\n'+m.content:'');}"
        f"var u='http://127.0.0.1:{port}/add?token={token}"
        "&text='+encodeURIComponent(s.slice(0,4000))+'&url='+encodeURIComponent(location.href)"
        "+'&title='+encodeURIComponent(document.title);"
        "window.open(u,'cr','width=380,height=160');})();"
    )
    return "javascript:" + js
