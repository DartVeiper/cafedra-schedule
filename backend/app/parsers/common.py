"""Общие утилиты нормализации, используемые всеми парсерами форматов."""
from __future__ import annotations

import re
from datetime import time

# Порядок важен только для документации; сопоставление по подстроке регистронезависимое.
DAY_NAME_TO_INDEX = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
}


def excel_time_fraction_to_time(fraction: float) -> time:
    """xls (xlrd) хранит время как долю суток (float 0..1). Конвертирует в datetime.time."""
    total_minutes = round(fraction * 24 * 60)
    total_minutes %= 24 * 60
    return time(hour=total_minutes // 60, minute=total_minutes % 60)


def normalize_group(raw: str | None) -> str | None:
    """'92ф', '94 Ф', '11-Ф' -> '92Ф', '94Ф', '11Ф'."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"[\s\-]+", "", s)
    return s.upper()


def normalize_room(raw: object, building: str | None = None) -> str | None:
    """Приводит номер аудитории к единому виду; учитывает корпус/здание, если известен.

    Числа вида 418.0 (float из Excel) сводятся к '418'. Текстовые пометки ('м/з')
    сохраняются как есть (в нижнем регистре, без лишних пробелов).
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if raw.is_integer():
            room = str(int(raw))
        else:
            room = str(raw)
    else:
        room = str(raw).strip()
        if not room:
            return None
        # иногда номер аудитории приходит как "418.0" в текстовой ячейке
        if re.fullmatch(r"\d+\.0", room):
            room = room[:-2]
    room = room.strip().lower()
    if not room:
        return None
    if building:
        return f"{building.strip().lower()}:{room}"
    return room


def normalize_person_name(raw: str | None) -> str | None:
    """Чистит ФИО/поле шапки от шаблонных подчёркиваний и пробелов.

    Важно: НЕ обрезает завершающую точку у самого текста — инициалы вида
    'Ананьев А.А.' в расписании кафедры всегда пишутся с точкой на конце,
    и наивный strip(" _.") её съедал бы вместе со шаблонными '____.'.
    """
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    s = s.strip("_").strip()
    if not s or re.fullmatch(r"[_.\s]+", s):
        return None
    return s


def normalize_subject(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip(" .")
    return s or None
