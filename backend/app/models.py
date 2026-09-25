"""Единая модель занятия и вспомогательные типы, общие для всех парсеров."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum


class LessonType(str, Enum):
    INDIVIDUAL = "individual"
    GROUP = "group"


class PersonRole(str, Enum):
    TEACHER = "teacher"  # Преподаватель
    ACCOMPANIST = "accompanist"  # Концертмейстер


# Пн=0 ... Сб=5, как в датском стандарте недели, принятой в расписании кафедры (без воскресенья).
DAY_NAMES_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

INDIVIDUAL_LESSON_MINUTES = 45
GROUP_LESSON_MINUTES = 90  # "пара"


@dataclass
class SourceRef:
    """Откуда взята запись — для отладки и показа пользователю причины конфликта."""

    file_name: str
    sheet_name: str | None = None
    row_index: int | None = None

    def label(self) -> str:
        parts = [self.file_name]
        if self.sheet_name:
            parts.append(self.sheet_name)
        if self.row_index is not None:
            parts.append(f"строка {self.row_index + 1}")
        return " / ".join(parts)


@dataclass
class Lesson:
    """Единая сущность занятия для алгоритма поиска накладок."""

    lesson_type: LessonType
    day_of_week: int  # 0..5
    start_time: time
    duration_minutes: int

    teacher_name: str | None = None
    accompanist_name: str | None = None
    student_name: str | None = None  # только для индивидуальных
    group_raw: str | None = None
    group_normalized: str | None = None
    subject: str | None = None
    room_raw: str | None = None
    room_normalized: str | None = None  # с учётом корпуса

    source: SourceRef = field(default_factory=lambda: SourceRef(file_name="?"))

    @property
    def end_minutes(self) -> int:
        return self.start_minutes + self.duration_minutes

    @property
    def start_minutes(self) -> int:
        return self.start_time.hour * 60 + self.start_time.minute


class ConflictType(str, Enum):
    TEACHER_DOUBLE_BOOKED = "teacher_double_booked"  # преподаватель/концертмейстер в двух местах
    ROOM_DOUBLE_BOOKED = "room_double_booked"  # аудитория занята дважды
    STUDENT_DOUBLE_BOOKED = "student_double_booked"  # студент на двух индивидуальных одновременно
    STUDENT_VS_GROUP = "student_vs_group"  # индивидуальное занятие студента пересекается с его групповым


@dataclass
class Conflict:
    """Две записи, чьи временные интервалы пересекаются и совпадают по ключевому признаку."""

    type: ConflictType
    day_of_week: int
    lesson_a: Lesson
    lesson_b: Lesson
    is_certain: bool = True  # False — конфликт нужно перепроверить вручную (см. note)
    note: str | None = None


@dataclass
class ParseWarning:
    file_name: str
    sheet_name: str | None
    message: str
    row_index: int | None = None

    def label(self) -> str:
        loc = self.file_name
        if self.sheet_name:
            loc += f" / {self.sheet_name}"
        if self.row_index is not None:
            loc += f" / строка {self.row_index + 1}"
        return f"{loc}: {self.message}"
