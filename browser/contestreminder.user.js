// ==UserScript==
// @name         ContestReminder: отправить конкурс
// @name:en      ContestReminder: send contest
// @namespace    https://github.com/moonlivedt-oss/ContestReminderMoon
// @version      1.2.0
// @description  Выделенный пост о конкурсе (или сама страница) уходит в ContestReminder на этом компьютере
// @description:en Sends the selected contest post (or the page itself) to ContestReminder on this computer
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @grant        GM_notification
// @connect      127.0.0.1
// @noframes
// ==/UserScript==

/*
 * Ключ и порт подставляет программа: меню «…» -> «Браузер: сохранить userscript…».
 * Запрос идёт только на 127.0.0.1, то есть в ContestReminder на этом же компьютере.
 * Без верного ключа программа ничего не примет.
 */
(function () {
  "use strict";

  const TOKEN = "__TOKEN__";
  const PORT = "__PORT__";
  const ENDPOINT = `http://127.0.0.1:${PORT}/add`;
  const MAX_TEXT = 4000;

  const lang = (navigator.language || "ru").slice(0, 2);
  const STRINGS = {
    ru: { menu: "Отправить в ContestReminder", ok: "Отправлено в ContestReminder",
          off: "ContestReminder не запущен", key: "Неверный ключ: сохраните userscript заново" },
    uk: { menu: "Надіслати в ContestReminder", ok: "Надіслано в ContestReminder",
          off: "ContestReminder не запущено", key: "Невірний ключ: збережіть userscript знову" },
    de: { menu: "An ContestReminder senden", ok: "An ContestReminder gesendet",
          off: "ContestReminder läuft nicht", key: "Falscher Schlüssel: Userscript neu speichern" },
    en: { menu: "Send to ContestReminder", ok: "Sent to ContestReminder",
          off: "ContestReminder is not running", key: "Wrong key: save the userscript again" },
  };
  const L = STRINGS[lang] || STRINGS.en;

  /** Текст поста: выделение, иначе заголовок и описание страницы (og:description). */
  function collect() {
    let text = String(window.getSelection() || "").trim();
    if (!text) {
      const meta = document.querySelector('meta[property="og:description"], meta[name="description"]');
      text = [document.title, meta && meta.content].filter(Boolean).join("\n");
    }
    return text.slice(0, MAX_TEXT);
  }

  function say(message) {
    if (typeof GM_notification === "function") {
      GM_notification({ title: "ContestReminder", text: message, timeout: 3500 });
    } else {
      console.info("[ContestReminder]", message);
    }
  }

  function send() {
    const body = JSON.stringify({ token: TOKEN, text: collect(), url: location.href, title: document.title });
    GM_xmlhttpRequest({
      method: "POST",
      url: ENDPOINT,
      headers: { "Content-Type": "application/json" },
      data: body,
      timeout: 4000,
      onload: (r) => say(r.status === 200 ? L.ok : r.status === 403 ? L.key : `HTTP ${r.status}`),
      onerror: () => say(L.off),
      ontimeout: () => say(L.off),
    });
  }

  GM_registerMenuCommand(L.menu, send, "c");
  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.shiftKey && !e.ctrlKey && (e.code === "KeyC")) {
      e.preventDefault();
      send();
    }
  }, true);
})();
