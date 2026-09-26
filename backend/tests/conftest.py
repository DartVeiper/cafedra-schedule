"""Общие фабрики для тестов — конструируют Lesson напрямую, без парсинга файлов."""
from __future__ import annotations

from datetime import time

import pytest

from app.models import Lesson, LessonType, PersonRole, SourceRef
from app.parsers.individual import SheetParseResult


@pytest.fixture
def make_lesson():
    """Фабрика: make_lesson(day=0, start="08:30", ...) -> Lesson с разумными умолчаниями."""

    def _make(
        day: int = 0,
        start: str = "08:30",
        duration: int = 45,
        lesson_type: LessonType = LessonType.INDIVIDUAL,
        teacher: str | None = "Иванов И.И.",
        accompanist: str | None = None,
        student: str | None = "Студент Тестовый",
        group: str = "91Ф",
        subject: str = "специальный инструмент",
        room: str | None = "418",
        source_file: str = "test.xls",
    ) -> Lesson:
        hh, mm = start.split(":")
        return Lesson(
            lesson_type=lesson_type,
            day_of_week=day,
            start_time=time(hour=int(hh), minute=int(mm)),
            duration_minutes=duration,
            teacher_name=teacher,
            accompanist_name=accompanist,
            student_name=student,
            group_raw=group,
            group_normalized=group,
            subject=subject,
            room_raw=room,
            room_normalized=room,
            source=SourceRef(file_name=source_file, sheet_name="Лист3"),
        )

    return _make


@pytest.fixture
def make_sheet_result():
    """Фабрика: make_sheet_result(file_name=..., lessons=[...]) -> SheetParseResult,
    как будто это результат реального парсинга одного листа книги Формата 1."""

    def _make(
        file_name: str,
        lessons: list[Lesson],
        sheet_name: str = "Лист3",
        role: PersonRole = PersonRole.TEACHER,
        person_name: str = "Иванов И.И.",
    ) -> SheetParseResult:
        return SheetParseResult(
            file_name=file_name,
            sheet_name=sheet_name,
            role=role,
            person_name=person_name,
            lessons=lessons,
            warnings=[],
            header_text=f"Преподаватель {person_name}",
        )

    return _make
