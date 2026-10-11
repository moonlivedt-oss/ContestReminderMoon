"""Оформление — палитра Catppuccin Mocha (та же, что в AutoTranslator/VSCodeLauncher).

Окно обычное (в трее), тема применяется на всё приложение. Карточки конкурсов —
QFrame#contestCard, статусные плашки — QLabel с objectName chip*/muted.
"""
from __future__ import annotations

PALETTE = {
    "bg": "#181825", "surface": "#1e1e2e", "surface2": "#11111b",
    "border": "#313244", "text": "#cdd6f4", "subtext": "#a6adc8",
    "accent": "#cba6f7", "accent_text": "#11111b", "accent_hover": "#d9bbff",
    "success": "#a6e3a1", "warn": "#f9e2af", "error": "#f38ba8",
    "track": "#45475a", "input_bg": "#232336", "input_text": "#cdd6f4",
}


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    r, g, bl = (max(0, min(255, round(x + (y - x) * t))) for x, y in zip(a, b, strict=True))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rgba(color: str, a: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


def build_qss(p: dict = PALETTE) -> str:
    hov = _mix(p["surface"], p["text"], 0.06)
    return f"""
* {{
    font-family: 'Segoe UI', 'Segoe UI Variable', sans-serif;
    font-size: 13px; color: {p["text"]};
}}
QWidget#root, QDialog {{ background: {p["bg"]}; }}

QLabel#h1 {{ font-size: 16px; font-weight: 800; letter-spacing: 0.2px; }}
QLabel#muted {{ color: {p["subtext"]}; font-size: 11px; }}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#empty {{ color: {p["subtext"]}; font-size: 13px; }}

QFrame#contestCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_mix(p["surface"], p["text"], 0.02)}, stop:1 {p["surface"]});
    border: 1px solid {p["border"]}; border-radius: 12px;
}}
QFrame#contestCard[expired="true"] {{ border-color: {_rgba(p["error"], 0.5)}; }}
QFrame#contestCard[done="true"] {{ background: {p["surface2"]}; }}

QLabel#chip {{
    color: {p["accent"]}; background: {_rgba(p["accent"], 0.14)};
    border: 1px solid {_rgba(p["accent"], 0.35)};
    border-radius: 9px; padding: 1px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#chipWarn {{
    color: {p["warn"]}; background: {_rgba(p["warn"], 0.14)};
    border: 1px solid {_rgba(p["warn"], 0.35)};
    border-radius: 9px; padding: 1px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#chipErr {{
    color: {p["error"]}; background: {_rgba(p["error"], 0.14)};
    border: 1px solid {_rgba(p["error"], 0.35)};
    border-radius: 9px; padding: 1px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#chipOk {{
    color: {p["success"]}; background: {_rgba(p["success"], 0.14)};
    border: 1px solid {_rgba(p["success"], 0.35)};
    border-radius: 9px; padding: 1px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#link {{ color: {p["accent"]}; font-size: 11px; }}

QLineEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {p["input_bg"]}; border: 1px solid {p["border"]};
    border-radius: 9px; padding: 7px 9px;
    selection-background-color: {p["accent"]}; selection-color: {p["accent_text"]};
}}
QLineEdit:focus, QDateTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p["accent"]};
}}
QDateTimeEdit::drop-down {{ border: none; width: 18px; }}
QDateTimeEdit::down-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {p["subtext"]};
    margin-right: 6px;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

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

QCheckBox {{ spacing: 7px; color: {p["subtext"]}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 6px;
    border: 1px solid {p["border"]}; background: {p["input_bg"]};
}}
QCheckBox::indicator:hover {{ border-color: {p["accent"]}; }}
QCheckBox::indicator:checked {{ background: {p["accent"]}; border-color: {p["accent"]}; }}

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
    background: {p["surface2"]}; color: {p["text"]};
    border: 1px solid {p["accent"]}; border-radius: 6px; padding: 5px 7px;
}}
"""
