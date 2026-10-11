"""Оформление: режим (авто / светлая / тёмная / сепия) и палитра.

Палитры те же, что в окне cpp-docs-panel: Catppuccin, Tokyo Night, Dracula, Nord,
Gruvbox, Rosé Pine, One Dark, Лес, Закат. В тёмном режиме палитра задаёт все цвета,
в светлом и в сепии - только акцент (он затемняется, пока не станет читаемым на
светлом фоне). Вся раскраска - в одной таблице стилей; виджеты помечены objectName и
свойствами (у карточки `urgency` - цвет полосы и шкалы). `current()` отдаёт активные
цвета тем, кто рисует сам (ссылки в карточке, выбор темы).
"""

from __future__ import annotations

import colorsys
from pathlib import Path

# ключ: (название, фон, панель, «код»/глубже, текст, вторичный, бледный, акцент,
#        зелёный, красный, оранжевый, жёлтый, голубой)
PALETTES: dict[str, dict[str, str]] = {
    "mocha": {"name": "Catppuccin", "bg": "#181825", "panel": "#1e1e2e", "code": "#11111b", "fg": "#cdd6f4",
              "muted": "#a6adc8", "faint": "#7f849c", "ac": "#cba6f7", "ts": "#a6e3a1", "tp": "#f38ba8",
              "tn": "#fab387", "ty": "#f9e2af", "tf": "#89b4fa"},
    "tokyo": {"name": "Tokyo Night", "bg": "#1a1b26", "panel": "#1f2335", "code": "#16161e", "fg": "#c0caf5",
              "muted": "#a9b1d6", "faint": "#737aa2", "ac": "#7aa2f7", "ts": "#9ece6a", "tp": "#f7768e",
              "tn": "#ff9e64", "ty": "#e0af68", "tf": "#7dcfff"},
    "dracula": {"name": "Dracula", "bg": "#21222c", "panel": "#282a36", "code": "#191a21", "fg": "#f8f8f2",
                "muted": "#bfc3d9", "faint": "#7f87b3", "ac": "#bd93f9", "ts": "#50fa7b", "tp": "#ff5555",
                "tn": "#ffb86c", "ty": "#f1fa8c", "tf": "#8be9fd"},
    "nord": {"name": "Nord", "bg": "#2e3440", "panel": "#353c4a", "code": "#272c36", "fg": "#eceff4",
             "muted": "#d8dee9", "faint": "#8f9ab0", "ac": "#88c0d0", "ts": "#a3be8c", "tp": "#bf616a",
             "tn": "#d08770", "ty": "#ebcb8b", "tf": "#81a1c1"},
    "gruvbox": {"name": "Gruvbox", "bg": "#1d2021", "panel": "#282828", "code": "#171a1b", "fg": "#ebdbb2",
                "muted": "#d5c4a1", "faint": "#a89984", "ac": "#fe8019", "ts": "#b8bb26", "tp": "#fb4934",
                "tn": "#fe8019", "ty": "#fabd2f", "tf": "#83a598"},
    "rosepine": {"name": "Rosé Pine", "bg": "#191724", "panel": "#1f1d2e", "code": "#14121e", "fg": "#e0def4",
                 "muted": "#aaa6c8", "faint": "#817d9e", "ac": "#ebbcba", "ts": "#9ccfd8", "tp": "#eb6f92",
                 "tn": "#f6c177", "ty": "#f6c177", "tf": "#c4a7e7"},
    "onedark": {"name": "One Dark", "bg": "#21252b", "panel": "#282c34", "code": "#1b1f24", "fg": "#d7dae0",
                "muted": "#abb2bf", "faint": "#7f848e", "ac": "#61afef", "ts": "#98c379", "tp": "#e06c75",
                "tn": "#d19a66", "ty": "#e5c07b", "tf": "#c678dd"},
    "forest": {"name": "Лес", "bg": "#141d18", "panel": "#1a2620", "code": "#0f1612", "fg": "#dde9e0",
               "muted": "#a9c2b1", "faint": "#76917f", "ac": "#7fd4a0", "ts": "#9fdc8c", "tp": "#e8828a",
               "tn": "#e3a46f", "ty": "#e6d27f", "tf": "#7cc7d6"},
    "sunset": {"name": "Закат", "bg": "#1f1520", "panel": "#281b29", "code": "#170f18", "fg": "#f3e3e6",
               "muted": "#cfb3bb", "faint": "#96788a", "ac": "#ff9e7a", "ts": "#b5dd8c", "tp": "#ff6f91",
               "tn": "#ffb86b", "ty": "#ffd479", "tf": "#d9a6ff"},
}
MODES = ("auto", "light", "dark", "sepia")

# светлые основы: от палитры берут только акцент
_LIGHT_BASE = {
    "bg": "#eff1f5", "surface": "#ffffff", "surface2": "#e6e9ef", "raised": "#f7f7fb",
    "border": "#dce0e8", "text": "#4c4f69", "subtext": "#6c6f85", "faint": "#8c8fa1",
    "success": "#40a02b", "warn": "#df8e1d", "orange": "#fe640b", "error": "#d20f39",
    "blue": "#1e66f5", "track": "#ccd0da", "input_bg": "#ffffff",
}
_SEPIA_BASE = {
    "bg": "#f4ecdc", "surface": "#fbf6ea", "surface2": "#ece2cd", "raised": "#fffaf0",
    "border": "#ddd0b6", "text": "#453a2a", "subtext": "#7a6a52", "faint": "#a4977c",
    "success": "#5c8a3a", "warn": "#b0742f", "orange": "#c0602a", "error": "#b04a2f",
    "blue": "#3a6a9a", "track": "#d8ccb2", "input_bg": "#fffaf0",
}


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    r, g, bl = (max(0, min(255, round(x + (y - x) * t))) for x, y in zip(a, b, strict=True))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rgba(color: str, a: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


def _lum(c: str) -> float:
    def ch(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def darken_for(color: str, bg: str, ratio: float = 4.5) -> str:
    """Темнее, пока цвет не станет читаемым на светлом фоне (тон сохраняется)."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, lig, sat = colorsys.rgb_to_hls(r, g, b)
    out = color
    while contrast(out, bg) < ratio and lig > 0.05:
        lig -= 0.03
        rr, gg, bb = colorsys.hls_to_rgb(h, lig, min(1.0, sat * 1.02))
        out = f"#{round(rr * 255):02x}{round(gg * 255):02x}{round(bb * 255):02x}"
    return out


def make(mode: str, palette: str) -> dict:
    """Цвета для режима (light/dark/sepia, без auto) и палитры."""
    pal = PALETTES.get(palette, PALETTES["mocha"])
    if mode == "dark":
        return {
            "name": "dark", "bg": pal["bg"], "surface": pal["panel"], "surface2": pal["code"],
            "raised": _mix(pal["panel"], pal["fg"], 0.04), "border": _mix(pal["panel"], pal["fg"], 0.13),
            "text": pal["fg"], "subtext": pal["muted"], "faint": pal["faint"], "accent": pal["ac"],
            "accent_text": pal["code"], "accent_hover": _mix(pal["ac"], "#ffffff", 0.18),
            "success": pal["ts"], "warn": pal["ty"], "orange": pal["tn"], "error": pal["tp"],
            "blue": pal["tf"], "track": _mix(pal["panel"], pal["fg"], 0.22),
            "input_bg": _mix(pal["panel"], pal["fg"], 0.03),
        }
    base = dict(_SEPIA_BASE if mode == "sepia" else _LIGHT_BASE)
    accent = darken_for(pal["ac"], base["surface"])
    base.update({"name": "light", "accent": accent, "accent_text": "#ffffff",
                 "accent_hover": _mix(accent, "#ffffff", 0.15)})
    return base


DARK = make("dark", "mocha")
LIGHT = make("light", "mocha")
PALETTE = DARK          # совместимость: векторный колокольчик берёт отсюда акцент
_current = DARK


def system_is_dark() -> bool:
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication
        hints = QGuiApplication.styleHints()
        return hints is None or hints.colorScheme() != Qt.ColorScheme.Light
    except Exception:  # noqa: BLE001 - старый Qt или нет приложения: тёмная
        return True


def resolve(mode: str, palette: str = "mocha") -> dict:
    if mode not in ("light", "dark", "sepia"):
        mode = "dark" if system_is_dark() else "light"
    return make(mode, palette)


def current() -> dict:
    return _current


def apply(qapp, mode: str = "auto", palette: str = "mocha") -> dict:
    """Ставит тему на всё приложение; возвращает выбранные цвета."""
    global _current
    _current = resolve(mode, palette)
    qapp.setStyleSheet(build_qss(_current))
    return _current


def urgency_color(urgency: str, p: dict | None = None) -> str:
    p = p or _current
    return {"overdue": p["error"], "today": p["orange"], "soon": p["warn"],
            "later": p["accent"], "none": p["faint"], "done": p["success"]}.get(urgency, p["accent"])


def _chip(name: str, color: str) -> str:
    return f"""QLabel#{name} {{
    color: {color}; background: {_rgba(color, 0.13)};
    border: 1px solid {_rgba(color, 0.32)};
    border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 700;
}}
"""


def build_qss(p: dict | None = None) -> str:
    p = p or DARK
    asset = (Path(__file__).resolve().parents[1] / "assets").as_posix()
    tone = p["name"]
    hov = _mix(p["surface"], p["text"], 0.06)
    stripes = "".join(
        f'QFrame#contestCard[urgency="{u}"] {{ border-left: 4px solid {urgency_color(u, p)}; }}\n'
        f'QProgressBar#timeBar[urgency="{u}"]::chunk {{ background: {urgency_color(u, p)}; border-radius: 2px; }}\n'
        for u in ("overdue", "today", "soon", "later", "none", "done")
    )
    return f"""
* {{
    font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
    font-size: 13px; color: {p["text"]};
}}
QWidget#root, QDialog {{ background: {p["bg"]}; }}

/* --- шапка --- */
QLabel#h1 {{ font-size: 19px; font-weight: 800; letter-spacing: 0.2px; }}
QLabel#subtitle {{ color: {p["subtext"]}; font-size: 12px; }}
QLabel#muted {{ color: {p["subtext"]}; font-size: 11px; }}
QLabel#faint {{ color: {p["faint"]}; font-size: 11px; }}
QLabel#kbd {{
    color: {p["subtext"]}; background: {p["surface"]}; border: 1px solid {p["border"]};
    border-bottom-width: 2px; border-radius: 5px; padding: 0 5px; font-size: 11px; font-weight: 600;
}}

/* --- список --- */
QLabel#groupHead {{
    color: {p["subtext"]}; font-size: 11px; font-weight: 800;
    letter-spacing: 0.8px; padding: 8px 2px 0 4px;
}}
QLabel#groupCount {{
    color: {p["faint"]}; background: {p["surface2"]}; border-radius: 8px;
    padding: 0 7px; font-size: 11px; font-weight: 700; margin-top: 8px;
}}
QFrame#contestCard {{
    background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: 12px;
}}
QFrame#contestCard:hover {{ border-color: {_rgba(p["accent"], 0.45)}; background: {p["raised"]}; }}
QFrame#contestCard[done="true"] {{ background: {p["surface2"]}; }}
{stripes}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#cardTitle[link="true"]:hover {{ color: {p["accent"]}; }}
QLabel#cardTitle[done="true"] {{ color: {p["faint"]}; text-decoration: line-through; }}
QProgressBar#timeBar {{
    background: {p["surface2"]}; border: none; border-radius: 2px;
    max-height: 4px; min-height: 4px;
}}
{_chip("chip", p["accent"])}{_chip("chipWarn", p["warn"])}{_chip("chipToday", p["orange"])}{_chip("chipErr", p["error"])}{_chip("chipOk", p["success"])}{_chip("chipNone", p["faint"])}
QLabel#link {{ color: {p["accent"]}; font-size: 11px; }}
QPushButton#iconBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 5px; min-width: 18px;
}}
QPushButton#iconBtn:hover {{ background: {_rgba(p["accent"], 0.14)}; border-color: {_rgba(p["accent"], 0.35)}; }}
QPushButton#iconDanger {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 5px; min-width: 18px;
}}
QPushButton#iconDanger:hover {{ background: {_rgba(p["error"], 0.14)}; border-color: {_rgba(p["error"], 0.45)}; }}

/* --- пустой список --- */
QLabel#emptyTitle {{ font-size: 16px; font-weight: 800; }}
QLabel#empty {{ color: {p["subtext"]}; font-size: 13px; }}

/* --- поля --- */
QLineEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background: {p["input_bg"]}; border: 1px solid {p["border"]};
    border-radius: 9px; padding: 7px 9px;
    selection-background-color: {p["accent"]}; selection-color: {p["accent_text"]};
}}
QLineEdit#search {{ padding-left: 6px; border-radius: 10px; }}
QLineEdit:focus, QDateTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus {{
    border-color: {p["accent"]};
}}
QDateTimeEdit::drop-down, QComboBox::drop-down {{ border: none; width: 18px; }}
QDateTimeEdit::down-arrow, QComboBox::down-arrow {{
    image: url({asset}/arrow-{tone}.png); width: 12px; height: 12px; margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {p["surface"]}; border: 1px solid {p["border"]};
    selection-background-color: {_rgba(p["accent"], 0.25)}; outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: none; }}
QTimeEdit::up-arrow, QTimeEdit::down-arrow {{ image: none; width: 0; height: 0; }}
QTimeEdit {{
    background: {p["input_bg"]}; border: 1px solid {p["border"]};
    border-radius: 9px; padding: 7px 9px;
}}
QDateTimeEdit:disabled, QSpinBox:disabled {{ color: {p["track"]}; }}

QLabel#section {{
    color: {p["accent"]}; font-size: 12px; font-weight: 700; padding-top: 6px;
}}
QLabel#error {{ color: {p["error"]}; }}
QFrame#sep {{ color: {p["border"]}; }}

/* --- кнопки --- */
QPushButton {{
    background: {p["input_bg"]}; border: 1px solid {p["border"]};
    border-radius: 9px; padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {hov}; border-color: {p["accent"]}; }}
QPushButton:pressed {{ background: {_mix(p["surface"], p["surface2"], 0.5)}; }}
QPushButton#accent {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["accent_hover"]}, stop:1 {p["accent"]});
    color: {p["accent_text"]}; border: 1px solid {p["accent"]};
}}
QPushButton#accent:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_mix(p["accent_hover"], "#ffffff", 0.18)}, stop:1 {p["accent_hover"]});
}}
QPushButton#danger:hover {{ background: {_rgba(p["error"], 0.85)}; border-color: {p["error"]}; color: {p["accent_text"]}; }}
QPushButton#ghost {{ background: transparent; border-color: transparent; padding: 6px 10px; }}
QPushButton#ghost:hover {{ background: {_rgba(p["accent"], 0.14)}; border-color: {_rgba(p["accent"], 0.35)}; }}
QPushButton#ghost:checked {{ background: {_rgba(p["accent"], 0.18)}; border-color: {_rgba(p["accent"], 0.45)}; color: {p["accent"]}; }}
QPushButton#dangerGhost {{ background: transparent; border-color: transparent; padding: 6px 10px; color: {p["subtext"]}; }}
QPushButton#dangerGhost:hover {{ background: {_rgba(p["error"], 0.16)}; border-color: {_rgba(p["error"], 0.5)}; color: {p["error"]}; }}
QPushButton#seg {{
    background: transparent; border: 1px solid {p["border"]}; border-radius: 10px;
    padding: 6px 12px; color: {p["subtext"]}; font-weight: 600;
}}
QPushButton#seg:hover {{ border-color: {_rgba(p["accent"], 0.6)}; color: {p["text"]}; }}
QPushButton#seg:checked {{
    background: {_rgba(p["accent"], 0.16)}; border-color: {_rgba(p["accent"], 0.6)};
    color: {p["accent"]};
}}
QPushButton::menu-indicator {{ width: 0; image: none; }}

QCheckBox {{ spacing: 7px; color: {p["subtext"]}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 6px;
    border: 1px solid {p["border"]}; background: {p["input_bg"]};
}}
QCheckBox::indicator:hover {{ border-color: {p["accent"]}; }}
QCheckBox::indicator:checked {{
    background: {p["accent"]}; border-color: {p["accent"]}; image: url({asset}/check-{tone}.png);
}}

/* --- всплывающие карточки --- */
QFrame#toast {{
    background: {p["surface"]}; border: 1px solid {p["border"]};
    border-left: 4px solid {p["accent"]}; border-radius: 12px;
}}
QFrame#toast[kind="warn"] {{ border-left-color: {p["warn"]}; }}
QFrame#toast[kind="ok"] {{ border-left-color: {p["success"]}; }}
QFrame#toast[kind="offer"] {{ border-left-color: {p["accent"]}; }}
QLabel#toastTitle {{ font-size: 13px; font-weight: 700; }}
QLabel#toastBody {{ color: {p["subtext"]}; font-size: 12px; }}
QPushButton#toastClose {{
    background: transparent; border: none; padding: 0 4px; color: {p["subtext"]};
    font-size: 15px; font-weight: 400;
}}
QPushButton#toastClose:hover {{ color: {p["error"]}; }}

/* --- вкладки настроек --- */
QTabWidget::pane {{ border: none; border-top: 1px solid {p["border"]}; }}
QTabBar::tab {{
    background: transparent; color: {p["subtext"]}; padding: 8px 14px; margin-right: 4px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {p["text"]}; }}
QTabBar::tab:selected {{ color: {p["accent"]}; border-bottom-color: {p["accent"]}; }}

/* --- прочее --- */
QScrollArea {{ border: none; background: transparent; }}
QWidget#listViewport, QWidget#listHost {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p["track"]}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p["accent"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {_rgba(p["accent"], 0.22)}; }}
QMenu::separator {{ height: 1px; background: {p["border"]}; margin: 4px 8px; }}

QToolTip {{
    background: {p["surface"]}; color: {p["text"]};
    border: 1px solid {p["accent"]}; border-radius: 6px; padding: 5px 7px;
}}
"""
