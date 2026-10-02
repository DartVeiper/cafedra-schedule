"""Сетка времени начала индивидуальных занятий и поиск «кривого» времени.

Единой сетки "звонков" в исходных файлах нет, а на практике она РАЗНАЯ по дням:
например, вторник–пятница после обеда начинаются в 14:25, 15:15, 16:10, ...,
в понедельник — в 15:10, 16:00, 16:55, ..., в субботу — в 13:45, 14:35, 15:30, ...
Поэтому сетка восстанавливается из данных ОТДЕЛЬНО для каждого дня: время —
слот дня, если оно встречается у кафедры в этот день достаточно часто. Всё
остальное — нестандартное время (скорее всего, опечатка преподавателя в файле).

Если данных за день мало (например, загружен файл одного преподавателя), судить
о сетке рано — тогда слотами считаются все встретившиеся времена и ничего не
помечается «кривым».
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.models import DAY_NAMES_RU, Lesson, LessonType

MIN_SLOT_SUPPORT = 3   # время — слот дня, если встречается в этот день не реже
MIN_DAY_LESSONS = 20   # меньше индивидуальных занятий за день — сетку не определяем
NEAR_MINUTES = 30      # дальше этого "ближайший слот" уже не подсказываем


@dataclass
class DayGrid:
    slots: list[int]      # минуты от полуночи, по возрастанию
    reliable: bool        # хватило данных, чтобы считать остальные времена нестандартными


@dataclass
class IrregularTime:
    lesson: Lesson
    nearest: int | None           # ближайший слот этого дня (минуты) или None, если далеко
    from_other_days: list[int]    # дни, в чьей сетке это время есть


def fmt_minutes(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def build_day_grids(lessons: list[Lesson]) -> dict[int, DayGrid]:
    by_day: dict[int, Counter] = {}
    for l in lessons:
        if l.lesson_type == LessonType.INDIVIDUAL:
            by_day.setdefault(l.day_of_week, Counter())[l.start_minutes] += 1
    grids: dict[int, DayGrid] = {}
    for day, counts in by_day.items():
        if sum(counts.values()) >= MIN_DAY_LESSONS:
            slots = sorted(t for t, n in counts.items() if n >= MIN_SLOT_SUPPORT)
            grids[day] = DayGrid(slots, reliable=True)
        else:
            grids[day] = DayGrid(sorted(counts), reliable=False)
    return grids


def is_irregular(lesson: Lesson, grids: dict[int, DayGrid]) -> bool:
    grid = grids.get(lesson.day_of_week)
    return bool(
        lesson.lesson_type == LessonType.INDIVIDUAL
        and grid is not None and grid.reliable and lesson.start_minutes not in grid.slots
    )


def find_irregular_times(lessons: list[Lesson]) -> list[IrregularTime]:
    grids = build_day_grids(lessons)
    out: list[IrregularTime] = []
    for l in lessons:
        if not is_irregular(l, grids):
            continue
        slots = grids[l.day_of_week].slots
        nearest = min(slots, key=lambda s: abs(s - l.start_minutes), default=None)
        if nearest is not None and abs(nearest - l.start_minutes) > NEAR_MINUTES:
            nearest = None
        others = sorted(
            d for d, g in grids.items()
            if d != l.day_of_week and g.reliable and l.start_minutes in g.slots
        )
        out.append(IrregularTime(l, nearest, others))
    out.sort(key=lambda i: (i.lesson.day_of_week, i.lesson.start_minutes))
    return out


def describe(item: IrregularTime) -> str:
    """Подсказка методисту: что не так со временем и на что оно похоже."""
    day = DAY_NAMES_RU[item.lesson.day_of_week].lower()
    parts = [f"{fmt_minutes(item.lesson.start_minutes)} — нет в сетке занятий ({day})"]
    if item.nearest is not None:
        parts.append(f"ближайшее по сетке — {fmt_minutes(item.nearest)}")
    if item.from_other_days:
        days = ", ".join(DAY_NAMES_RU[d].lower() for d in item.from_other_days)
        parts.append(f"такое время есть в сетке: {days}")
    return "; ".join(parts)


def day_notes(grids: dict[int, DayGrid], special_slots: list[dict]) -> dict[int, str]:
    """Подписи под названиями дней на странице кабинета — чтобы своя сетка дня
    не выглядела ошибкой. Всё определяется по данным, а не вписано вручную:
    кураторский час (и другие служебные слоты групповых файлов) может менять
    день каждое полугодие, и подпись сама переедет вместе с ним.

    «Обычная» сетка — та, что встречается у большинства дней; день с другой
    сеткой помечается как отличающийся."""
    reliable = {d: tuple(g.slots) for d, g in grids.items() if g.reliable}
    typical = Counter(reliable.values()).most_common(1)[0][0] if reliable else None

    notes: dict[int, str] = {}
    for day in grids:
        differs = typical is not None and day in reliable and reliable[day] != typical
        specials = [s for s in special_slots if s["day"] == day]
        if specials:
            parts = [f"{s['subject'].capitalize()} в {s['start']}" for s in specials]
            text = ", ".join(parts)
            if differs:
                text += " — время после него сдвинуто"
            notes[day] = text
        elif differs:
            notes[day] = "своя сетка времени (отличается от других дней)"
    return notes
