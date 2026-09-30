"""Фильтр отчёта по ФИО — выпадающий список "Показать только по ФИО" на
странице отчёта (см. report.html): выбор одного человека сужает список
накладок до тех, что его касаются, либо показывает "всё в порядке"."""
from __future__ import annotations

from app.conflicts import find_conflicts
from app.main import _collect_all_names, _filter_conflicts_by_person


def test_collect_all_names_includes_teacher_accompanist_and_student(make_lesson):
    lessons = [
        make_lesson(teacher="Иванов И.И.", accompanist=None, student="Петров П.П."),
        make_lesson(teacher=None, accompanist="Сидорова С.С.", student="Петров П.П."),
    ]

    names = _collect_all_names(lessons)

    assert names == sorted(["Иванов И.И.", "Петров П.П.", "Сидорова С.С."], key=str.casefold)


def test_filter_by_person_keeps_only_their_conflicts(make_lesson):
    a = make_lesson(day=0, start="10:00", teacher="Иванов И.И.", room="101")
    b = make_lesson(day=0, start="10:15", teacher="Иванов И.И.", room="101")
    c = make_lesson(day=0, start="11:00", teacher="Петров П.П.", room="202")
    d = make_lesson(day=0, start="11:15", teacher="Петров П.П.", room="202")
    conflicts = find_conflicts([a, b, c, d])

    filtered = _filter_conflicts_by_person(conflicts, "Иванов И.И.")

    assert filtered
    assert len(filtered) < len(conflicts)
    assert all("Иванов И.И." in (c.lesson_a.teacher_name, c.lesson_b.teacher_name) for c in filtered)


def test_filter_by_person_is_case_insensitive_but_exact(make_lesson):
    a = make_lesson(day=0, start="10:00", teacher="Иванов И.И.", room="101")
    b = make_lesson(day=0, start="10:15", teacher="Иванов И.И.", room="101")
    conflicts = find_conflicts([a, b])

    assert _filter_conflicts_by_person(conflicts, "иванов и.и.") == conflicts
    # Выбор идёт из готового списка ФИО (выпадающий список), а не свободный
    # текстовый поиск — частичное совпадение (одна фамилия) не должно находить.
    assert _filter_conflicts_by_person(conflicts, "Иванов") == []


def test_empty_person_returns_all_conflicts_unfiltered(make_lesson):
    a = make_lesson(day=0, start="10:00", teacher="Иванов И.И.", room="101")
    b = make_lesson(day=0, start="10:15", teacher="Иванов И.И.", room="101")
    conflicts = find_conflicts([a, b])

    assert _filter_conflicts_by_person(conflicts, "") == conflicts
