"""Точка входа ContestReminder (без консольного окна — .pyw).

Запускать под Python 3.11 (winsdk/mss не имеют колёс для 3.14). См. Запуск.bat.
"""
import sys

from contestreminder.app import main

if __name__ == "__main__":
    sys.exit(main())
