"""Полный прогон: Формат 1 + Формат 2 -> единый список занятий -> поиск накладок.

Запуск (из папки backend):
    ../.venv/Scripts/python.exe scripts/run_conflicts.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from app.conflicts import find_conflicts
from app.models import DAY_NAMES_RU, ConflictType
from app.pipeline import load_all_lessons

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "samples")
INDIVIDUAL_DIR = os.path.join(BASE_DIR, "individual")
GROUP_DIR = os.path.join(BASE_DIR, "group")
GROUP_DOCX_DIR = os.path.join(BASE_DIR, "group_docx")

CONFLICT_LABELS = {
    ConflictType.TEACHER_DOUBLE_BOOKED: "Преподаватель/концертмейстер в двух местах",
    ConflictType.ROOM_DOUBLE_BOOKED: "Аудитория занята дважды",
    ConflictType.STUDENT_DOUBLE_BOOKED: "Студент на двух индивидуальных одновременно",
    ConflictType.STUDENT_VS_GROUP: "Студент: индивидуальное пересекается с групповым",
}


def describe_lesson(lesson) -> str:
    who = lesson.teacher_name or lesson.accompanist_name or "-"
    student = f", студент {lesson.student_name}" if lesson.student_name else ""
    return (
        f"{lesson.start_time.strftime('%H:%M')}-"
        f"{(lesson.start_minutes + lesson.duration_minutes) // 60:02d}:"
        f"{(lesson.start_minutes + lesson.duration_minutes) % 60:02d} "
        f"[{who}{student}, гр.{lesson.group_raw}, '{lesson.subject}', ауд.{lesson.room_raw}] "
        f"источник: {lesson.source.label()}"
    )


def main() -> None:
    all_lessons, individual_report, group_warnings, failed_files = load_all_lessons(
        INDIVIDUAL_DIR, GROUP_DIR, GROUP_DOCX_DIR
    )

    print(f"Индивидуальных+концертмейстерских занятий: {len(individual_report.lessons)}")
    group_count = len(all_lessons) - len(individual_report.lessons)
    print(f"Групповых занятий: {group_count}")
    print(f"ВСЕГО занятий в базе: {len(all_lessons)}")
    if failed_files:
        print(f"\nНе удалось прочитать файлы ({len(failed_files)}):")
        for f in failed_files:
            print(" -", f)

    conflicts = find_conflicts(all_lessons)
    certain = [c for c in conflicts if c.is_certain]
    review = [c for c in conflicts if not c.is_certain]
    print(f"\nНайдено накладок: {len(certain)} явных + {len(review)} требующих ручной проверки")

    for ctype in ConflictType:
        group = [c for c in conflicts if c.type == ctype]
        if not group:
            continue
        print(f"\n{'=' * 100}\n{CONFLICT_LABELS[ctype]} ({len(group)})\n{'=' * 100}")
        for c in group:
            marker = "" if c.is_certain else " [ТРЕБУЕТ ПРОВЕРКИ]"
            print(f"\n  {DAY_NAMES_RU[c.day_of_week]}{marker}")
            if c.note:
                print(f"    примечание: {c.note}")
            print("    A:", describe_lesson(c.lesson_a))
            print("    B:", describe_lesson(c.lesson_b))


if __name__ == "__main__":
    main()
