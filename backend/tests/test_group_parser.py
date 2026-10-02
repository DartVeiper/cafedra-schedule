"""Тесты на разбор таблицы группового расписания (Формат 2) — работаем с
rows_to_group_result напрямую, на простых списках строк, без реального .docx.
"""
from __future__ import annotations

from app.models import LessonType
from app.parsers.group import rows_to_group_result

HEADER = ["ДАТА/ВРЕМЯ", "ДАТА/ВРЕМЯ", "Дисциплина", "ФИО преподавателя", "ауд."]


def row(day: str, time: str, subject: str, teacher: str, room: str) -> list[str]:
    return [day, time, subject, teacher, room]


def test_consecutive_identical_rows_merge_into_one_longer_lesson():
    """Реальный кейс кафедры: 'Музыкальная литература' у Иванченко О.М. стоит
    и в 15-10, и в 16-55 подряд — это ОДНО занятие 135 минут (15:10-17:25),
    а не две отдельные пары по 90 минут (что ложно накладывалось на занятие
    в 17:45)."""
    table_rows = [
        HEADER,
        row("Понедельник", "12-00", "История", "Чаплыгин О.В.", "корпус №5 ауд.314"),
        row("Понедельник", "15-10", "Музыкальная литература", "Иванченко О.М.", "корпус №5 ауд.317"),
        row("Понедельник", "16-55", "Музыкальная литература", "Иванченко О.М.", "корпус №5 ауд.317"),
        row("Понедельник", "17-45", "", "", ""),
    ]

    result = rows_to_group_result(table_rows, "91Ф.docx", "91Ф", "91Ф")

    muz_lit = [l for l in result.lessons if l.teacher_name == "Иванченко О.М."]
    assert len(muz_lit) == 1
    lesson = muz_lit[0]
    assert lesson.start_time.strftime("%H:%M") == "15:10"
    assert lesson.duration_minutes == 135  # 90 + 45
    assert lesson.end_minutes == 15 * 60 + 10 + 135  # заканчивается в 17:25, до начала 17:45


def test_three_consecutive_rows_merge_to_double_pair():
    """Обобщение правила на три подряд идущих слота: 90 + 45 + 45 = 180 минут."""
    table_rows = [
        HEADER,
        row("Вторник", "8-30", "Практикум", "Петров П.П.", "215"),
        row("Вторник", "10-15", "Практикум", "Петров П.П.", "215"),
        row("Вторник", "12-00", "Практикум", "Петров П.П.", "215"),
    ]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert len(result.lessons) == 1
    assert result.lessons[0].duration_minutes == 180


def test_single_row_is_a_normal_90_minute_pair():
    table_rows = [HEADER, row("Среда", "12-00", "История", "Иванов И.И.", "314")]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert len(result.lessons) == 1
    assert result.lessons[0].duration_minutes == 90


def test_same_subject_different_room_does_not_merge():
    """Если дисциплина та же, но аудитория другая — это НЕ продолжение той же
    пары (переезд между кабинетами не бывает), должно остаться двумя занятиями."""
    table_rows = [
        HEADER,
        row("Среда", "12-00", "История", "Иванов И.И.", "314"),
        row("Среда", "14-25", "История", "Иванов И.И.", "316"),
    ]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert len(result.lessons) == 2
    assert all(l.duration_minutes == 90 for l in result.lessons)


def test_curator_hour_is_excluded_as_special_event_not_a_lesson():
    """'КУРАТОРСКИЙ ЧАС' записан так, что Дисциплина=Преподаватель=Аудитория —
    без исключения все группы с куратор.часом в одно время дали бы ложную
    накладку по 'преподавателю' и по 'аудитории'."""
    table_rows = [
        HEADER,
        row("Понедельник", "14-25", "КУРАТОРСКИЙ ЧАС", "КУРАТОРСКИЙ ЧАС", "КУРАТОРСКИЙ ЧАС"),
    ]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert result.lessons == []
    assert len(result.special_event_slots) == 1
    assert result.special_event_slots[0][2] == "КУРАТОРСКИЙ ЧАС"


def test_individual_lessons_marker_recorded_separately_not_as_lesson():
    table_rows = [
        HEADER,
        row("Четверг", "8-30", "Индивидуальные занятия", "", ""),
    ]

    result = rows_to_group_result(table_rows, "test.docx", "92Ф", "92Ф")

    assert result.lessons == []
    assert len(result.individual_marker_slots) == 1


def test_blank_slot_produces_nothing():
    table_rows = [HEADER, row("Пятница", "8-30", "", "", "")]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert result.lessons == []
    assert result.special_event_slots == []
    assert result.individual_marker_slots == []


def test_home_building_is_dropped_from_normalized_room():
    """'корпус №5' — здание самой кафедры; в индивидуальных файлах корпус не
    пишется вовсе, поэтому для сравнения кабинетов корпус кафедры опускаем
    (иначе групповое занятие в 421 никогда не пересеклось бы с индивидуальным
    в 421 — реальный пропуск накладки на данных кафедры)."""
    table_rows = [HEADER, row("Среда", "12-00", "История", "Иванов И.И.", "корпус №5 ауд.314")]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    lesson = result.lessons[0]
    assert lesson.room_raw == "корпус №5 ауд.314"
    assert lesson.room_normalized == "314"


def test_other_building_stays_in_normalized_room():
    """Кабинет 405 в корпусе №1 — не кабинет 405 кафедры, корпус сохраняем."""
    table_rows = [HEADER, row("Среда", "12-00", "История", "Иванов И.И.", "корпус №1 ауд.405")]

    result = rows_to_group_result(table_rows, "test.docx", "11Ф", "11Ф")

    assert result.lessons[0].room_normalized == "1:405"


def test_room_spacing_after_aud_prefix_does_not_split_one_room():
    """'ауд.316' и 'ауд. 316' в разных файлах — один и тот же кабинет."""
    a = rows_to_group_result([HEADER, row("Среда", "12-00", "История", "И И.И.", "корпус №5 ауд.316")], "a.docx", "11Ф", "11Ф")
    b = rows_to_group_result([HEADER, row("Среда", "12-00", "Химия", "П П.П.", "корпус №5 ауд. 316")], "b.docx", "12Ф", "12Ф")

    assert a.lessons[0].room_normalized == b.lessons[0].room_normalized == "316"


def test_lesson_type_is_group_and_group_fields_are_passed_through():
    table_rows = [HEADER, row("Среда", "12-00", "История", "Иванов И.И.", "314")]

    result = rows_to_group_result(table_rows, "test.docx", "92 Ф", "92Ф")

    lesson = result.lessons[0]
    assert lesson.lesson_type == LessonType.GROUP
    assert lesson.group_raw == "92 Ф"
    assert lesson.group_normalized == "92Ф"
