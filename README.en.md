# ContestReminder

[Русский](README.md) | **English**

[![tests](https://github.com/moonlivedt-oss/ContestReminderMoon/actions/workflows/tests.yml/badge.svg)](https://github.com/moonlivedt-oss/ContestReminderMoon/actions/workflows/tests.yml)
![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6)
![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-cba6f7)](LICENSE)

![ContestReminder window](docs/screenshot-en.png)

A tray app that remembers contest deadlines for you. Copy a contest post and it finds the
deadline, offers to save it and reminds you in time.

## Features

- **Capture from anywhere:** clipboard, screen OCR (`Ctrl+Alt+C`), browser (bookmarklet or
  userscript, `Alt+Shift+C`), PowerShell (`tools/cr.ps1`), or manually.
- **Smart parsing in 4 languages** (Russian, Ukrainian, English, German): picks the real
  deadline among several dates ("starts Oct 1, submissions until Oct 15, results Oct 20"),
  understands `tomorrow`, `until Friday`, `end of the month`, `in 5 days`,
  `Einsendeschluss 15. November`, `до п'ятниці`.
- **No duplicates:** the same link or a near-identical title is not offered twice; a new
  deadline for a saved contest is offered as an update.
- **Reads the linked page** in the background when the post has no deadline or a vague title
  (Telegram posts work without login).
- **Windows notifications** with Open, In 1 h, Tomorrow and Done buttons, made by a small C++/WinRT
  helper (`native/crnative.cpp`); the buttons work even when the app is closed. Without the
  C++ part - in-app cards with Snooze. Daily summary; past contests are closed automatically.
- **Lightweight background mode:** closing the window quits the app and a C++ watcher
  (~3 MB of memory) keeps reminding.
- **Window:** groups by deadline, search, filters, right-click menu, undo for delete,
  calendar export (`.ics`), backup and restore, upcoming deadlines in the tray.
- **Themes:** Auto / Light / Dark / Sepia and nine palettes (Catppuccin, Tokyo Night,
  Dracula, Nord, Gruvbox, Rosé Pine, One Dark, Forest, Sunset) picked from landscape cards;
  urgency stripes and a time bar on every contest card.
- **Interface languages:** English, Russian, Ukrainian, German (follows Windows by default,
  switches instantly).

## Install and run

Easiest: download `ContestReminder.exe` from
[Releases](https://github.com/moonlivedt-oss/ContestReminderMoon/releases/latest) - no Python
needed. From source (Windows 10/11): download the repository and double-click **`Запуск.bat`** ("Run"): it finds
Python 3.11 or 3.12 (offers to install it via `winget`), installs the packages from
`requirements.txt` on first start and launches the app without a console window.

Data lives in `%APPDATA%\ContestReminder\`. Development: `py -3.11 -m pytest`,
`py -3.11 -m ruff check .`.

## Browser and PowerShell

The app listens on `127.0.0.1:47615` (this computer only). Every request must carry the
secret key from the settings; whatever arrives shows up as the same "Save?" card.

- Bookmarklet: menu "…" -> "Browser: copy bookmarklet".
- Userscript (`browser/contestreminder.user.js`): menu "…" -> "Browser: save userscript…",
  install it in Tampermonkey or Violentmonkey.
- PowerShell: `.\tools\cr.ps1 "post text"` or `Get-Clipboard | .\tools\cr.ps1`.

## License

Code - [MIT](LICENSE). Icons in `contestreminder/assets/` come from the author's
[photosMOONprojects](https://github.com/moonlivedt-oss/photosMOONprojects) library and are
not covered by MIT.
