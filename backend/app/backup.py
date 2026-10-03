"""Резервная копия настроек программы: список кабинетов кафедры и пометки
«это не накладка». Это то, что методист накапливает вручную и что не восстановить
повторной загрузкой файлов (сами проверки — другое дело: их можно получить снова из
файлов расписания, поэтому в копию они не входят — там реальные ФИО студентов).

Копия — один небольшой JSON-файл, который можно положить на флешку или в облако.
Восстановление ОБЪЕДИНЯЕТ копию с текущими данными (ничего не стирает), а любые
некорректные записи в файле молча пропускает — чужой или повреждённый файл не
может сломать программу.
"""
from __future__ import annotations

import re
from datetime import datetime

from app import cabinets as cabinets_module
from app import dismissed as dismissed_module

BACKUP_APP = "CafedraSchedule"
BACKUP_FORMAT = 1
MAX_BACKUP_BYTES = 2_000_000
_KEY_RE = re.compile(r"^[0-9a-f]{16}$")


class BackupError(ValueError):
    """Файл не похож на копию настроек этой программы — текст ошибки показываем человеку."""


def build_backup(cabinets_path: str, dismissed_path: str, app_version: str) -> dict:
    return {
        "app": BACKUP_APP,
        "format": BACKUP_FORMAT,
        "version": app_version,
        "created": datetime.now().isoformat(timespec="seconds"),
        "cabinets": cabinets_module.load_config(cabinets_path),
        "dismissed": dismissed_module.load_dismissed(dismissed_path),
    }


def restore_backup(data: object, cabinets_path: str, dismissed_path: str) -> dict:
    """Объединяет копию с текущими настройками. Возвращает {"rooms": сколько кабинетов
    добавлено, "marks": сколько пометок добавлено}."""
    if not isinstance(data, dict) or data.get("app") != BACKUP_APP:
        raise BackupError("Это не копия настроек программы «Проверка расписания».")
    if data.get("format") != BACKUP_FORMAT:
        raise BackupError("Копия сделана другой версией программы и не читается.")

    # --- кабинеты
    config = cabinets_module.load_config(cabinets_path)
    rooms_added = 0
    departments = (data.get("cabinets") or {}).get("departments")
    if isinstance(departments, dict):
        for dept_id, dept in list(departments.items())[:50]:
            rooms = dept.get("rooms") if isinstance(dept, dict) else None
            if not isinstance(rooms, list):
                continue
            existing = set(config["departments"].get(dept_id, {}).get("rooms", []))
            for room in rooms[:500]:
                if isinstance(room, str) and 0 < len(room.strip()) <= 40 and room.strip() not in existing:
                    cabinets_module.add_room(config, room, dept_id)
                    existing.add(room.strip())
                    rooms_added += 1
    cabinets_module.save_config(cabinets_path, config)

    # --- пометки «это не накладка»
    current = dismissed_module.load_dismissed(dismissed_path)
    marks_added = 0
    incoming = data.get("dismissed")
    if isinstance(incoming, dict):
        for key, meta in list(incoming.items())[:20000]:
            if not isinstance(key, str) or not _KEY_RE.match(key) or key in current:
                continue
            meta = meta if isinstance(meta, dict) else {}
            label, at = meta.get("label", ""), meta.get("at", "")
            current[key] = {
                "label": label[:300] if isinstance(label, str) else "",
                "at": at[:40] if isinstance(at, str) else "",
            }
            marks_added += 1
    if marks_added:
        dismissed_module._save(dismissed_path, current)
    return {"rooms": rooms_added, "marks": marks_added}
