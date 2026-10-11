# -*- mode: python ; coding: utf-8 -*-
# Сборка одного ContestReminder.exe (без консоли): pyinstaller ContestReminder.spec
# Внутрь кладутся значки и шаблон userscript - код ищет их рядом с модулями.
# Python 3.11/3.12: под них есть winsdk (Windows OCR).

block_cipher = None

# winsdk грузит модули WinRT лениво (import внутри функции) - PyInstaller их не видит
hidden = [
    "winsdk.windows.globalization",
    "winsdk.windows.graphics.imaging",
    "winsdk.windows.media.ocr",
    "winsdk.windows.storage.streams",
    "winsdk.windows.foundation",
    "winsdk.windows.foundation.collections",
    "PyQt6.QtNetwork",
    "PyQt6.sip",
]

a = Analysis(
    ["run.pyw"],
    pathex=[],
    binaries=[],
    datas=[
        ("contestreminder/assets", "contestreminder/assets"),
        ("browser/contestreminder.user.js", "browser"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # лишнее из PyQt6 и stdlib - exe меньше
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia", "PyQt6.Qt3DCore",
              "PyQt6.QtBluetooth", "PyQt6.QtPdf", "PyQt6.QtSql", "PyQt6.QtTest",
              "numpy", "pytest"],
    noarchive=False,
)
# программный OpenGL (~20 МБ), PDF, QML и переводы Qt окну не нужны
_DROP = ("opengl32sw", "qt6pdf", "qt6qml", "qt6quick", "qt6virtualkeyboard", "d3dcompiler",
         "qt6openglwidgets")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower() for d in _DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/").lower()]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ContestReminder",
    icon="contestreminder/assets/app.ico",
    console=False,
    upx=False,
    strip=False,
    debug=False,
)
