"""Промежуточная проверка парсера Формата 1 на реальных файлах кафедры.

Запуск (из папки backend):
    ../.venv/Scripts/python.exe scripts/inspect_individual.py

Печатает по каждому файлу: кто это (преподаватель/концертмейстер), сколько
занятий на каждом листе, предупреждения, а также сводный отчёт после
сведения дублей по всему пакету файлов (dedup.build_import).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers.individual import parse_individual_workbook
from app.parsers.dedup import build_import

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "samples")
INDIVIDUAL_DIR = os.path.join(BASE_DIR, "individual")
GROUP_DIR = os.path.join(BASE_DIR, "group")

_GROUP_FROM_FILENAME_RE = re.compile(r"^(\d{2})\s*([А-Яа-я]+)")


def known_groups_from_filenames() -> set[str]:
    groups = set()
    for name in os.listdir(GROUP_DIR):
        m = _GROUP_FROM_FILENAME_RE.match(name)
        if m:
            groups.add((m.group(1) + m.group(2)).upper())
    return groups


def main() -> None:
    known_groups = known_groups_from_filenames()
    print("Известные коды групп (из имён файлов Формата 2):", sorted(known_groups))
    print("=" * 100)

    all_sheet_results = []
    files = sorted(os.listdir(INDIVIDUAL_DIR))
    for name in files:
        path = os.path.join(INDIVIDUAL_DIR, name)
        results = parse_individual_workbook(path, known_groups=known_groups)
        all_sheet_results.extend(results)

        print(f"\n### {name}")
        for sr in results:
            if sr.header_text is None and not sr.lessons:
                continue  # полностью пустой служебный лист (0x0) — не интересен
            role_label = sr.role.value if sr.role else "?"
            print(f"  Лист '{sr.sheet_name}': роль={role_label}, ФИО={sr.person_name!r}, занятий={len(sr.lessons)}")
            for w in sr.warnings:
                row_label = w.row_index + 1 if w.row_index is not None else "?"
                print(f"    [предупреждение] {w.message} (строка {row_label})")

    print("\n" + "=" * 100)
    print("СВОДКА ПО ФАЙЛАМ:", len(files))
    total_lessons_raw = sum(len(sr.lessons) for sr in all_sheet_results)
    print("Занятий распознано ДО сведения дублей:", total_lessons_raw)

    report = build_import(all_sheet_results)
    print("Занятий ПОСЛЕ сведения дублей:", len(report.lessons))

    print(f"\n--- Пропущенные пустые/безымянные листы ({len(report.skipped_sheet_notes)}) ---")
    for note in report.skipped_sheet_notes:
        print(" -", note)

    print(f"\n--- Отброшенные листы-дубликаты ({len(report.dropped_sheet_notes)}) ---")
    for note in report.dropped_sheet_notes:
        print(" -", note)

    print(f"\n--- Слияния почти-дублей внутри одного человека ({len(report.merge_notes)}) ---")
    for note in report.merge_notes:
        print(" -", note)

    print(f"\n--- Прочие предупреждения парсинга ({len(report.warnings)}) ---")
    for w in report.warnings:
        print(" -", w.label())

    # Пример вывода нескольких занятий для визуальной проверки формата данных
    print("\n--- Примеры занятий (первые 8) ---")
    for lesson in report.lessons[:8]:
        who = lesson.teacher_name or lesson.accompanist_name
        role = "преп." if lesson.teacher_name else "конц."
        print(
            f"  [{role} {who}] день={lesson.day_of_week} {lesson.start_time} "
            f"({lesson.duration_minutes} мин) студент={lesson.student_name!r} "
            f"группа={lesson.group_normalized} предмет={lesson.subject!r} "
            f"ауд={lesson.room_normalized} источник={lesson.source.label()}"
        )


if __name__ == "__main__":
    main()
