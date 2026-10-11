"""Запуск как модуля: py -3.11 -m contestreminder [--tray | --selftest отчёт.txt]."""
import sys

from .app import main

sys.exit(main())
