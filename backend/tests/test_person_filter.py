"""Фильтр отчёта по ФИО — выпадающий список "Показать только по ФИО" на
странице отчёта (см. report.html): выбор одного человека сужает список
накладок до тех, что его касаются, либо показывает "всё в порядке"."""
from __future__ import annotations

from app.conflicts import find_conflicts
from app.main import _collect_all_names, _filter_conflicts_by_person
from app.models import ConflictType


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


def test_collect_all_names_collapses_academic_title_variants(make_lesson):
    """Реальный случай с данными кафедры: 'Долгачева С.А.' (Формат 1, без
    звания) и 'доц. Долгачева С.А.' (Формат 2, с званием) — один и тот же
    человек, не должны попадать в список ФИО как два разных пункта."""
    lessons = [
        make_lesson(teacher="Долгачева С.А.", student="Иванов И.И."),
        make_lesson(teacher="доц. Долгачева С.А.", student="Петров П.П."),
    ]

    names = _collect_all_names(lessons)

    matches = [n for n in names if "долгачева" in n.casefold()]
    assert len(matches) == 1
    assert matches[0] == "Долгачева С.А."  # без звания — короче и узнаваемее


def test_filter_by_person_matches_across_academic_title_variants(make_lesson):
    """Выбрав из списка 'Долгачева С.А.', методист должен увидеть и накладки,
    записанные под 'доц. Долгачева С.А.' в групповом файле — иначе фильтр
    будет молчать о реальных накладках только из-за разного написания."""
    a = make_lesson(day=0, start="10:00", teacher="Долгачева С.А.", room="101", group="91Ф", student="Иванова Анна")
    b = make_lesson(day=0, start="10:15", teacher="доц. Долгачева С.А.", room="202", group="41Ф", student="Петров Пётр")
    conflicts = find_conflicts([a, b])

    teacher_conflicts = [c for c in conflicts if c.type == ConflictType.TEACHER_DOUBLE_BOOKED]
    assert len(teacher_conflicts) == 1  # без нормализации звания её вообще не нашли бы
    assert _filter_conflicts_by_person(teacher_conflicts, "Долгачева С.А.") == teacher_conflicts
    assert _filter_conflicts_by_person(teacher_conflicts, "доц. Долгачева С.А.") == teacher_conflicts
