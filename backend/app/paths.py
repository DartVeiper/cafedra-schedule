"""Пути приложения — работает и из исходников (разработка), и как собранный
PyInstaller-exe (для методиста, без Python/git на компьютере).

Шаблоны/статика при сборке PyInstaller распаковываются во временную папку
(sys._MEIPASS), которая создаётся заново при каждом запуске — оттуда их и
читаем. А вот рабочие данные (SQLite, загруженные файлы) храним РЯДОМ С
ФАЙЛОМ EXE, а не во временной папке — иначе база обнулялась бы при каждом
перезапуске программы.
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_package_dir() -> str:
    """Папка backend/app — шаблоны (templates/) и статика (static/)."""
    if is_frozen():
        return os.path.join(sys._MEIPASS, "app")  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))


def runtime_data_dir() -> str:
    """Папка для БД и загруженных файлов — переживает перезапуски и обновления."""
    if is_frozen():
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "data")
