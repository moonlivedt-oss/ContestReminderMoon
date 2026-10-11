"""Тесты без экрана: Qt работает в offscreen-режиме, данные пишутся во временную папку."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
