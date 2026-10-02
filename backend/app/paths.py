"""Пути приложения — работает и из исходников (разработка), и как собранный
PyInstaller-exe (для методиста, без Python/git на компьютере).

Шаблоны/статика при сборке PyInstaller распаковываются во временную папку
(sys._MEIPASS), которая создаётся заново при каждом запуске — оттуда их и
читаем. А вот рабочие данные (SQLite, загруженные файлы, реестр кабинетов)
в собранном .exe храним в %LOCALAPPDATA%\\CafedraSchedule — НЕ рядом с самим
файлом .exe: методист может держать .exe хоть на рабочем столе, и уборка
стола (или перенос/переименование ярлыка) не заденет данные. При разработке
из исходников (не frozen) поведение не меняется — данные лежат в data/ и
config/ в корне репозитория, как и раньше.
"""
from __future__ import annotations

import os
import shutil
import sys

APP_NAME = "CafedraSchedule"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_package_dir() -> str:
    """Папка backend/app — шаблоны (templates/) и статика (static/)."""
    if is_frozen():
        return os.path.join(sys._MEIPASS, "app")  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))


def _exe_dir() -> str:
    return os.path.dirname(sys.executable)


def _appdata_base_dir() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, APP_NAME)
    # LOCALAPPDATA не определена (не Windows, урезанное окружение) — запасной
    # вариант: как раньше, рядом с .exe.
    return _exe_dir()


def _base_dir() -> str:
    if is_frozen():
        return _appdata_base_dir()
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def migrate_legacy_storage() -> None:
    """Разовый перенос данных со старого места (рядом с .exe — так хранилось
    до переезда в AppData) на новое, если они там ещё остались. Только для
    frozen .exe; вызывать один раз при старте, до первого обращения к
    runtime_data_dir()/cabinets_config_path()."""
    if not is_frozen():
        return
    legacy_base = _exe_dir()
    new_base = _appdata_base_dir()
    if legacy_base == new_base:
        return  # LOCALAPPDATA недоступна — и так работаем по старой схеме
    for name in ("data", "config"):
        old_path = os.path.join(legacy_base, name)
        new_path = os.path.join(new_base, name)
        if os.path.isdir(old_path) and not os.path.exists(new_path):
            os.makedirs(new_base, exist_ok=True)
            shutil.move(old_path, new_path)


def runtime_data_dir() -> str:
    """Папка для БД и загруженных файлов — переживает перезапуски и обновления."""
    return os.path.join(_base_dir(), "data")


def cabinets_config_path() -> str:
    """Реестр кабинетов кафедры (app/cabinets.py) — НАМЕРЕННО хранится не в
    data/, а в соседней папке config/: список кабинетов не привязан к
    конкретной проверке расписания и должен пережить очистку/удаление data/
    (историю проверок), в отличие от самих проверок."""
    return os.path.join(_base_dir(), "config", "cabinets.json")


def dismissed_conflicts_path() -> str:
    """Накладки, которые методист пометил «это не накладка» (app/dismissed.py).
    Как и реестр кабинетов — в config/, а не в data/: пометки привязаны не к
    одной проверке, а к самим занятиям, и должны пережить удаление проверок."""
    return os.path.join(_base_dir(), "config", "dismissed_conflicts.json")
