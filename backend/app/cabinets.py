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

from app import timegrid
from app.conflicts import find_conflicts
from app.models import INDIVIDUAL_LESSON_MINUTES, ConflictType, Lesson, LessonType

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


def build_room_schedule(
    lessons: list[Lesson], room: str, special_slots: list[dict] | None = None
) -> dict[int, list[dict]]:
    """{день_недели: [{"start": "10:15", "occupied_by": Lesson|None,
    "conflict_with": Lesson|None, "irregular": bool}, ...]}, только для дней,
    где вообще есть индивидуальные занятия у кафедры.

    Слоты дня — сетка времени ЭТОГО дня (timegrid.py: она разная по дням).
    Занятия этого кабинета в нестандартное время (не из сетки дня) вынесены в
    конец дня отдельными слотами с "irregular": True — так видно, что время
    «кривое», и оно не прячется внутри чужого слота. "conflict_with" заполнен,
    если в этом слоте кабинет реально занят дважды (переиспользуем
    find_conflicts — ту же логику, что и в основном отчёте).

    special_slots — служебные слоты групповых файлов (кураторский час): они
    встают в сетку дня на своё время отдельной серой ячейкой, поэтому после
    них время «сдвинуто» не выглядит ошибкой, а строки дней остаются
    сопоставимыми по номеру занятия."""
    grids = timegrid.build_day_grids(lessons)
    room_lessons = [l for l in lessons if l.room_normalized == room]
    irregular_lessons = [l for l in room_lessons if timegrid.is_irregular(l, grids)]
    regular_room_lessons = [l for l in room_lessons if not any(l is i for i in irregular_lessons)]

    # ROOM_DOUBLE_BOOKED группируется в conflicts.py по room_normalized, так что
    # если lesson_a в этом кабинете — lesson_b тоже в нём же.
    room_conflicts = [
        c for c in find_conflicts(lessons)
        if c.type == ConflictType.ROOM_DOUBLE_BOOKED and c.lesson_a.room_normalized == room
    ]

    def slot_for(day: int, start: int, pool: list[Lesson], irregular: bool) -> dict:
        end = start + INDIVIDUAL_LESSON_MINUTES
        occupant = None
        conflict_with = None
        for c in room_conflicts:
            if c.day_of_week != day:
                continue
            overlap_start = max(c.lesson_a.start_minutes, c.lesson_b.start_minutes)
            overlap_end = min(c.lesson_a.end_minutes, c.lesson_b.end_minutes)
            if _overlaps(start, end, overlap_start, overlap_end):
                occupant, conflict_with = c.lesson_a, c.lesson_b
                break
        if occupant is None:
            occupant = next(
                (l for l in pool if l.day_of_week == day and _overlaps(start, end, l.start_minutes, l.end_minutes)),
                None,
            )
        return {
            "start": timegrid.fmt_minutes(start),
            "occupied_by": occupant,
            "conflict_with": conflict_with,
            "irregular": irregular,
            "special": None,
        }

    schedule: dict[int, list[dict]] = {}
    for day, grid in grids.items():
        starts = list(grid.slots)
        specials = {}
        for sp in special_slots or []:
            m = _to_minutes(sp["start"])
            if sp["day"] == day and m not in starts:
                specials[m] = sp["subject"].capitalize()
        starts = sorted(starts + list(specials))
        day_slots = []
        for start in starts:
            if start in specials:
                slot = slot_for(day, start, [], False)
                slot["special"] = specials[start]
                day_slots.append(slot)
            else:
                day_slots.append(slot_for(day, start, regular_room_lessons, False))
        extra_starts = sorted({l.start_minutes for l in irregular_lessons if l.day_of_week == day})
        day_slots += [
            slot_for(day, start, [l for l in irregular_lessons if l.start_minutes == start], True)
            for start in extra_starts
        ]
        schedule[day] = day_slots
    return schedule


def grid_rows(schedule: dict[int, list[dict]], days: list[int]) -> list[list[dict | None]]:
    """Строки таблицы «n-е занятие дня»: у каждого дня своя сетка времени, поэтому
    сопоставляем дни не по часам, а по порядковому номеру слота (в каждом дне
    слот №1 — первое занятие, и т.д.; послеобеденные слоты тоже совпадают по
    номеру). Время слота подписано в самой ячейке. Если у дня слотов меньше —
    в ячейке None."""
    height = max((len(schedule.get(d, [])) for d in days), default=0)
    return [
        [schedule[d][i] if i < len(schedule.get(d, [])) else None for d in days]
        for i in range(height)
    ]


def irregular_counts_by_room(lessons: list[Lesson]) -> dict[str, int]:
    """{кабинет: сколько занятий в нестандартное время} — для списка кабинетов."""
    counts: dict[str, int] = {}
    for item in timegrid.find_irregular_times(lessons):
        room = item.lesson.room_normalized
        if room:
            counts[room] = counts.get(room, 0) + 1
    return counts


LUNCH_GAP_MINUTES = 60  # обычный шаг сетки 50–55 мин; пауза длиннее — «большой перерыв» (обед)


def break_rows(schedule: dict[int, list[dict]], days: list[int]) -> set[int]:
    """Номера строк grid_rows, перед которыми у большинства дней большой
    перерыв (обед) — таблица рисует над ними жирную линию, чтобы сетка не
    выглядела «съехавшей»: до обеда и после него времена идут своими рядами."""
    votes: dict[int, int] = {}
    for d in days:
        slots = [s for s in schedule.get(d, []) if not s["irregular"]]
        for i in range(1, len(slots)):
            gap = _to_minutes(slots[i]["start"]) - _to_minutes(slots[i - 1]["start"])
            if gap > LUNCH_GAP_MINUTES:
                votes[i] = votes.get(i, 0) + 1
    return {i for i, n in votes.items() if n * 2 > len(days)}


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)
