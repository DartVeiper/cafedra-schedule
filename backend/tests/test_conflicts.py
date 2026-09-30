"""Регрессионные тесты на реальные кейсы, найденные при разборе данных кафедры.

Каждый тест назван по конкретной ситуации, а не абстрактно — если он упадёт,
сразу понятно, какой реальный случай снова сломался.
"""
from __future__ import annotations

from app.conflicts import find_conflicts
from app.models import ConflictType, LessonType


def test_teacher_plus_accompanist_same_room_is_not_a_conflict(make_lesson):
    """Ананьев (преп.) + Филатова (конц.) у одной студентки, одна аудитория,
    одно время — обычный совместный урок (аккомпанемент), не накладка."""
    a = make_lesson(teacher="Ананьев А.А.", accompanist=None, student="Попова Мария",
                     room="418", start="08:30", source_file="Ананьев.xls")
    b = make_lesson(teacher=None, accompanist="Филатова С.В.", student="Попова Мария",
                     room="418", start="08:30", source_file="Филатова.xls")

    conflicts = find_conflicts([a, b])

    assert conflicts == []


def test_teacher_plus_accompanist_different_room_flagged_for_review(make_lesson):
    """Тот же студент, тот же час, но преподаватель и концертмейстер в РАЗНЫХ
    аудиториях — может быть опечатка в кабинете у того же совместного занятия,
    а может быть реальная накладка. Не отбрасываем молча, помечаем на проверку."""
    a = make_lesson(teacher="Кривопуск В.А.", accompanist=None, student="Бутырин Илья",
                     room="208", start="16:55", source_file="Кривопуск.xls")
    b = make_lesson(teacher=None, accompanist="Смирнова А.А.", student="Бутырин Илья",
                     room="408", start="16:55", source_file="Смирнова.xls")

    conflicts = find_conflicts([a, b])

    assert len(conflicts) == 1
    assert conflicts[0].type == ConflictType.STUDENT_DOUBLE_BOOKED
    assert conflicts[0].is_certain is False


def test_two_different_accompanists_same_student_same_time_is_a_real_conflict(make_lesson):
    """А вот если студента одновременно должны аккомпанировать ДВА разных
    концертмейстера — это уже реальная накладка, роль-фильтр не должен её съесть.
    Тут же (одна аудитория, одно время) закономерно ловится и накладка по
    аудитории — это два разных, оба верных, основания для проверки."""
    a = make_lesson(teacher=None, accompanist="Меньшикова Е.В.", student="Кузнецова Татьяна",
                     room="211", start="18:15", source_file="Меньшикова.xls")
    b = make_lesson(teacher=None, accompanist="Топорова Е.П.", student="Кузнецова Татьяна",
                     room="211", start="18:15", source_file="Топорова.xls")

    conflicts = find_conflicts([a, b])
    types = {c.type for c in conflicts}

    assert types == {ConflictType.STUDENT_DOUBLE_BOOKED, ConflictType.ROOM_DOUBLE_BOOKED}
    student_conflict = next(c for c in conflicts if c.type == ConflictType.STUDENT_DOUBLE_BOOKED)
    assert student_conflict.is_certain is True


def test_student_name_typo_across_files_still_matches(make_lesson):
    """'Медведева Ананда' в одном файле и 'Медведева Анада' (опечатка) в другом —
    должны опознаться как один и тот же студент, а не как два разных."""
    a = make_lesson(teacher="Ананьев А.А.", student="Медведева Ананда",
                     room="418", start="11:05", source_file="Ананьев.xls")
    b = make_lesson(teacher=None, accompanist="Топорова Е.П.", student="Медведева Анада",
                     room="418", start="11:05", source_file="Топорова.xls")

    conflicts = find_conflicts([a, b])

    # Совместное занятие преп.+конц. у того же (с опечаткой) студента — не накладка.
    assert conflicts == []


def test_different_students_same_surname_are_not_merged(make_lesson):
    """'Попова Мария' и 'Попова Анна' — разные люди с общей фамилией, нечёткое
    сравнение не должно их перепутать, даже если остальные поля совпадают."""
    a = make_lesson(teacher="Ананьев А.А.", student="Попова Мария",
                     room="418", start="08:30", source_file="Ананьев.xls")
    b = make_lesson(teacher=None, accompanist="Филатова С.В.", student="Попова Анна",
                     room="418", start="08:30", source_file="Филатова.xls")

    conflicts = find_conflicts([a, b])

    # Разные студентки в одной аудитории в одно время — это РЕАЛЬНАЯ накладка
    # по аудитории (а не отфильтрованный "совместный урок").
    assert len(conflicts) == 1
    assert conflicts[0].type == ConflictType.ROOM_DOUBLE_BOOKED


def test_room_double_booked_two_unrelated_lessons(make_lesson):
    """Классика: два разных преподавателя, два разных студента, одна аудитория —
    должно ловиться как накладка по аудитории."""
    a = make_lesson(teacher="Байбикова Г.В.", student="Шухуа Ли", room="421", start="14:35")
    b = make_lesson(teacher="Курганская О.А.", student="Бородаенко Олеся", room="421", start="14:35")

    conflicts = find_conflicts([a, b])

    assert len(conflicts) == 1
    assert conflicts[0].type == ConflictType.ROOM_DOUBLE_BOOKED


def test_teacher_double_booked_across_academic_title_variants(make_lesson):
    """Реальная находка на данных кафедры: один и тот же преподаватель в
    индивидуальном файле (Формат 1) указан просто 'Долгачева С.А.', а в
    групповом (Формат 2) — 'доц. Долгачева С.А.' (звание из колонки 'ФИО
    преподавателя'). Без нормализации звания это считались бы два разных
    человека, и реальная накладка (ведёт групповую лекцию и одновременно
    индивидуальное занятие) осталась бы незамеченной."""
    individual_lesson = make_lesson(
        teacher="Долгачева С.А.", room="101", group="91Ф", student="Студент А",
        day=0, start="12:00", duration=45, lesson_type=LessonType.INDIVIDUAL,
    )
    group_lecture = make_lesson(
        teacher="доц. Долгачева С.А.", room="202", group="41Ф", student=None,
        day=0, start="12:00", duration=90, lesson_type=LessonType.GROUP,
    )

    conflicts = find_conflicts([individual_lesson, group_lecture])

    assert len(conflicts) == 1
    assert conflicts[0].type == ConflictType.TEACHER_DOUBLE_BOOKED


def test_no_conflict_when_times_dont_overlap(make_lesson):
    """Базовый случай: если интервалы не пересекаются — накладки нет."""
    a = make_lesson(teacher="Ананьев А.А.", room="418", start="08:30", duration=45)
    b = make_lesson(teacher="Ананьев А.А.", room="418", start="09:20", duration=45)

    assert find_conflicts([a, b]) == []
