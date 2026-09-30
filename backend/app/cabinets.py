"""Реестр кабинетов кафедры и построение сетки их занятости.

Список кабинетов хранится ОТДЕЛЬНО от data/ (см. app/paths.py:cabinets_config_path)
— он не привязан к конкретной проверке расписания и меняется гораздо реже, чем
сами проверки, поэтому должен пережить удаление/очистку data/.

Задел на будущее: несколько кафедр в одном файле (`departments`) — сейчас
используется только один департамент ("default"), но при появлении второй
кафедры не придётся менять схему хранения, только добавить интерфейс выбора.

Единой сетки "звонков" ни в одном формате исходных файлов нет — она
восстанавливается из данных: слоты дня = времена начала всех ИНДИВИДУАЛЬНЫХ
занятий кафедры в этот день недели (across всех преподавателей), а "занято
ли" конкретный кабинет в слоте проверяется по ЛЮБЫМ занятиям (и
индивидуальным, и групповым) — пара иногда идёт в кабинете, обычно
предназначенном под индивидуальные занятия.
"""
from __future__ import annotations

import json
import os

from app.models import INDIVIDUAL_LESSON_MINUTES, Lesson, LessonType

DEFAULT_DEPARTMENT_ID = "default"


def _empty_config() -> dict:
    return {
        "active_department": DEFAULT_DEPARTMENT_ID,
        "departments": {
            DEFAULT_DEPARTMENT_ID: {"name": "Кафедра", "rooms": []},
        },
    }


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        return _empty_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        return _empty_config()
    if not isinstance(config, dict) or not config.get("departments"):
        return _empty_config()
    return config


def save_config(path: str, config: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_rooms(config: dict, department_id: str = DEFAULT_DEPARTMENT_ID) -> list[str]:
    dept = config["departments"].get(department_id)
    if not dept:
        return []
    return sorted(dept["rooms"], key=str.casefold)


def add_room(config: dict, room: str, department_id: str = DEFAULT_DEPARTMENT_ID) -> dict:
    room = room.strip()
    dept = config["departments"].setdefault(department_id, {"name": "Кафедра", "rooms": []})
    if room and room not in dept["rooms"]:
        dept["rooms"].append(room)
    return config


def remove_room(config: dict, room: str, department_id: str = DEFAULT_DEPARTMENT_ID) -> dict:
    dept = config["departments"].get(department_id)
    if dept and room in dept["rooms"]:
        dept["rooms"].remove(room)
    return config


def suggest_rooms(lessons: list[Lesson]) -> set[str]:
    """Кабинеты, встретившиеся в ИНДИВИДУАЛЬНЫХ занятиях текущей проверки, но
    ещё не добавленные в реестр — подсказка методисту, без принудительного
    автодобавления (иначе в реестр натащило бы случайные разовые кабинеты)."""
    return {
        l.room_normalized
        for l in lessons
        if l.lesson_type == LessonType.INDIVIDUAL and l.room_normalized
    }


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def build_room_schedule(lessons: list[Lesson], room: str) -> dict[int, list[dict]]:
    """{день_недели: [{"start": "10:15", "occupied_by": Lesson|None}, ...]},
    только для дней, где вообще есть индивидуальные занятия у кафедры."""
    room_lessons = [l for l in lessons if l.room_normalized == room]

    slot_starts_by_day: dict[int, set[int]] = {}
    for l in lessons:
        if l.lesson_type == LessonType.INDIVIDUAL:
            slot_starts_by_day.setdefault(l.day_of_week, set()).add(l.start_minutes)

    schedule: dict[int, list[dict]] = {}
    for day, starts in slot_starts_by_day.items():
        day_slots = []
        for start in sorted(starts):
            end = start + INDIVIDUAL_LESSON_MINUTES
            occupant = next(
                (
                    l for l in room_lessons
                    if l.day_of_week == day and _overlaps(start, end, l.start_minutes, l.end_minutes)
                ),
                None,
            )
            day_slots.append({"start": f"{start // 60:02d}:{start % 60:02d}", "occupied_by": occupant})
        schedule[day] = day_slots
    return schedule
