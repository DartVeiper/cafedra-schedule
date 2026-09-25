"""Промежуточная проверка парсера Формата 2 на реальных файлах кафедры.

Запуск (из папки backend):
    ../.venv/Scripts/python.exe scripts/inspect_group.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from app.parsers.doc_convert import convert_doc_to_docx
from app.parsers.group import parse_group_docx

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "samples")
GROUP_DIR = os.path.join(BASE_DIR, "group")
GROUP_DOCX_DIR = os.path.join(BASE_DIR, "group_docx")


def main() -> None:
    os.makedirs(GROUP_DOCX_DIR, exist_ok=True)
    total_lessons = 0
    total_markers = 0
    total_special = 0
    for name in sorted(os.listdir(GROUP_DIR)):
        src = os.path.join(GROUP_DIR, name)
        docx_path = convert_doc_to_docx(src, GROUP_DOCX_DIR)
        result = parse_group_docx(docx_path)
        total_lessons += len(result.lessons)
        total_markers += len(result.individual_marker_slots)
        total_special += len(result.special_event_slots)
        print(f"\n### {name}")
        print(f"  группа: raw={result.group_raw!r} norm={result.group_normalized!r}")
        print(
            f"  занятий: {len(result.lessons)}, слотов 'индивидуальные занятия': "
            f"{len(result.individual_marker_slots)}, служебных событий: {len(result.special_event_slots)}"
        )
        if result.special_event_slots:
            labels = sorted({s[2] for s in result.special_event_slots})
            print(f"    служебные метки: {labels}")
        for w in result.warnings:
            print("  [предупреждение]", w.label())
        for lesson in result.lessons[:4]:
            print(
                f"    день={lesson.day_of_week} {lesson.start_time} ({lesson.duration_minutes} мин) "
                f"предмет={lesson.subject!r} преп={lesson.teacher_name!r} "
                f"ауд={lesson.room_normalized!r} (сырое: {lesson.room_raw!r})"
            )

    print("\n" + "=" * 100)
    print("Всего занятий:", total_lessons, "| слотов индивидуальных занятий:", total_markers)


if __name__ == "__main__":
    main()
