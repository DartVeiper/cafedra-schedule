"""Нагрузка и «окна» студентов — не накладки, а подсказки методисту.

Накладка — это когда двое мест одновременно. Здесь другое: расписание формально
без конфликтов, но неудобное. Два вида подсказок (пороги можно менять в самой
странице — у каждой кафедры свои привычки):

  * много индивидуальных занятий у одного студента в один день;
  * «окно» — длинная пауза между занятиями студента, у которого рядом есть
    индивидуальное занятие (пары его группы тоже считаются занятиями, иначе
    любое окно, закрытое лекциями, выглядело бы окном).

Для преподавателей таких проверок нет намеренно: у кафедры нормально, когда
преподаватель ведёт по 8 занятий подряд — это не сигнал.

Студенты опознаются по ФИО с допуском на опечатки (как в conflicts.py).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from app import conflicts as C
from app.models import Lesson, LessonType
from app.timegrid import fmt_minutes

MAX_LESSONS_PER_DAY = 6        # от скольких индивидуальных занятий в день предупреждать
BIG_WINDOW_MINUTES = 300       # от какой паузы между занятиями (мин) предупреждать


@dataclass
class LoadItem:
    kind: str            # "many" | "window"
    student: str
    group: str
    day: int
    severity: int        # для сортировки: число занятий или минуты окна
    text: str
    teachers: list[str]


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("ё", "е").replace("Ё", "Е")).strip().casefold()


def _cluster_students(lessons: list[Lesson]) -> dict[int, tuple[str, str]]:
    """{id(занятия): (ключ студента, имя для показа)} — с учётом опечаток в ФИО."""
    reps: list[str] = []                      # ключи-представители кластеров
    display: dict[str, Counter] = defaultdict(Counter)
    out: dict[int, str] = {}
    for l in lessons:
        key = _norm(l.student_name or "")
        if not key:
            continue
        for r in reps:
            if C._names_similar(r, key):
                key = r
                break
        else:
            reps.append(key)
        out[id(l)] = key
        display[key][l.student_name.strip()] += 1
    return {k: (v, display[v].most_common(1)[0][0]) for k, v in out.items()}


def find_load_issues(
    lessons: list[Lesson],
    max_lessons: int = MAX_LESSONS_PER_DAY,
    window_minutes: int = BIG_WINDOW_MINUTES,
) -> list[LoadItem]:
    individual = [l for l in lessons if l.lesson_type == LessonType.INDIVIDUAL and l.student_name]
    who = _cluster_students(individual)

    by_student_day: dict[tuple[str, int], list[Lesson]] = defaultdict(list)
    groups_of: dict[str, Counter] = defaultdict(Counter)
    for l in individual:
        key, _ = who[id(l)]
        by_student_day[(key, l.day_of_week)].append(l)
        if l.group_normalized:
            groups_of[key][l.group_normalized] += 1

    group_lessons: dict[tuple[str, int], list[Lesson]] = defaultdict(list)
    for l in lessons:
        if l.lesson_type == LessonType.GROUP and l.group_normalized:
            group_lessons[(l.group_normalized, l.day_of_week)].append(l)

    items: list[LoadItem] = []
    for (key, day), ls in by_student_day.items():
        name = who[id(ls[0])][1]
        group = groups_of[key].most_common(1)[0][0] if groups_of[key] else ""
        teachers = sorted({(l.teacher_name or l.accompanist_name or "—") for l in ls})
        # одно и то же занятие бывает записано дважды — у преподавателя и у концертмейстера
        # (два файла): считаем по уникальному времени начала, а не по записям
        first_at: dict[int, Lesson] = {}
        for l in sorted(ls, key=lambda l: l.start_minutes):
            first_at.setdefault(l.start_minutes, l)
        ls = list(first_at.values())

        if len(ls) >= max_lessons:
            items.append(LoadItem(
                "many", name, group, day, len(ls),
                f"{len(ls)} индивидуальных занятий в один день — с {fmt_minutes(ls[0].start_minutes)} "
                f"до {fmt_minutes(ls[-1].end_minutes)}", teachers,
            ))

        events = [(l, True) for l in ls] + [(g, False) for g in group_lessons.get((group, day), [])]
        events.sort(key=lambda e: e[0].start_minutes)
        for (a, a_ind), (b, b_ind) in zip(events, events[1:]):
            gap = b.start_minutes - a.end_minutes
            if gap >= window_minutes and (a_ind or b_ind):
                hours, mins = divmod(gap, 60)
                items.append(LoadItem(
                    "window", name, group, day, gap,
                    f"окно {hours} ч {mins:02d} мин — между {fmt_minutes(a.end_minutes)} и {fmt_minutes(b.start_minutes)}",
                    teachers,
                ))

    items.sort(key=lambda i: (i.kind, -i.severity, i.student.casefold(), i.day))
    return items
