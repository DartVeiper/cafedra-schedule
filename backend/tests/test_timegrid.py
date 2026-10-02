"""Сетка времени по дням и поиск «кривого» времени начала занятия."""
from __future__ import annotations

from app import cabinets, timegrid

TUE = ["08:30", "09:20", "10:15", "14:25", "15:15"]
SAT = ["08:30", "13:45", "14:35"]


def _filled_week(make_lesson):
    """Достаточно данных, чтобы сетка считалась надёжной: каждый слот встречается
    несколько раз (во вторник — одна сетка, в субботу — другая)."""
    lessons = []
    for day, times in ((1, TUE), (5, SAT)):
        for t in times:
            for k in range(8):
                lessons.append(make_lesson(day=day, start=t, teacher=f"П{k}", student=f"С{day}{t}{k}", room=f"4{k}"))
    return lessons


def test_grid_differs_by_day(make_lesson):
    grids = timegrid.build_day_grids(_filled_week(make_lesson))

    assert [timegrid.fmt_minutes(m) for m in grids[1].slots] == TUE
    assert [timegrid.fmt_minutes(m) for m in grids[5].slots] == SAT
    assert grids[1].reliable and grids[5].reliable


def test_time_from_other_days_grid_is_flagged_with_hint(make_lesson):
    lessons = _filled_week(make_lesson)
    odd = make_lesson(day=1, start="14:35", teacher="Толмачева Э.Г.", student="Габриэлян София", room="417")
    lessons.append(odd)

    found = timegrid.find_irregular_times(lessons)

    assert len(found) == 1 and found[0].lesson is odd
    assert found[0].from_other_days == [5]          # 14:35 есть в субботней сетке
    assert timegrid.fmt_minutes(found[0].nearest) == "14:25"
    text = timegrid.describe(found[0])
    assert "14:35" in text and "суббота" in text and "14:25" in text


def test_regular_week_has_no_irregular_times(make_lesson):
    assert timegrid.find_irregular_times(_filled_week(make_lesson)) == []


def test_small_upload_is_not_judged(make_lesson):
    """Загружен файл одного преподавателя — данных мало, всё «кривым» не объявляем."""
    few = [make_lesson(day=0, start="10:15"), make_lesson(day=0, start="10:22")]

    assert timegrid.find_irregular_times(few) == []


def test_room_schedule_uses_each_days_own_grid_and_puts_odd_time_last(make_lesson):
    lessons = _filled_week(make_lesson)
    odd = make_lesson(day=1, start="14:35", teacher="Толмачева Э.Г.", student="Габриэлян София", room="417")
    lessons.append(odd)

    schedule = cabinets.build_room_schedule(lessons, "417")

    assert [s["start"] for s in schedule[5]] == SAT                  # суббота — своя сетка, без вторничных времён
    assert [s["start"] for s in schedule[1]] == TUE + ["14:35"]      # нестандартное — в конце дня
    assert schedule[1][-1]["irregular"] and schedule[1][-1]["occupied_by"] is odd
    assert not any(s["irregular"] for s in schedule[1][:-1])
    # и не «прячется» внутри соседнего слота 14:25
    assert schedule[1][TUE.index("14:25")]["occupied_by"] is None


def test_irregular_counts_by_room(make_lesson):
    lessons = _filled_week(make_lesson)
    lessons.append(make_lesson(day=1, start="14:35", room="417"))
    lessons.append(make_lesson(day=1, start="16:20", room="417", student="Другой"))

    assert cabinets.irregular_counts_by_room(lessons) == {"417": 2}


def test_break_rows_marks_lunch_gap(make_lesson):
    schedule = cabinets.build_room_schedule(_filled_week(make_lesson), "999")

    # во вторник перерыв 10:15 -> 14:25 перед слотом №4 (индекс 3); суббота: 08:30 -> 13:45 перед №2
    assert cabinets.break_rows(schedule, [1, 5]) == set()  # голоса разошлись — линию не рисуем
    assert cabinets.break_rows({1: schedule[1]}, [1]) == {3}


def _grids_with_monday_shifted(make_lesson):
    """Вт — обычная сетка, Пн — после кураторского часа сетка сдвинута, Сб — своя."""
    lessons = _filled_week(make_lesson)  # вторник TUE, суббота SAT
    for t in ["08:30", "09:20", "10:15", "15:10", "16:00"]:
        for k in range(8):
            lessons.append(make_lesson(day=0, start=t, teacher=f"М{k}", student=f"П{t}{k}", room=f"5{k}"))
    for t in TUE:
        for k in range(8):
            lessons.append(make_lesson(day=3, start=t, teacher=f"Ч{k}", student=f"Ч{t}{k}", room=f"6{k}"))
    return lessons


def test_day_notes_are_derived_from_data_not_hardcoded(make_lesson):
    grids = timegrid.build_day_grids(_grids_with_monday_shifted(make_lesson))
    special = [{"day": 0, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}]

    notes = timegrid.day_notes(grids, special)

    assert notes[0] == "Кураторский час в 14:25 — время после него сдвинуто"
    assert "своя сетка" in notes[5]
    assert 1 not in notes and 3 not in notes  # обычные дни без подписи


def test_curator_hour_moved_to_friday_moves_the_note(make_lesson):
    """Кураторский час «переехал» на пятницу (в следующем полугодии) — подпись едет
    вместе с ним без правок в коде."""
    lessons = _filled_week(make_lesson)
    for t in ["08:30", "09:20", "10:15", "15:10", "16:00"]:
        for k in range(8):
            lessons.append(make_lesson(day=4, start=t, teacher=f"Ф{k}", student=f"Ф{t}{k}", room=f"7{k}"))
    grids = timegrid.build_day_grids(lessons)

    notes = timegrid.day_notes(grids, [{"day": 4, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}])

    assert "Кураторский час" in notes[4] and 0 not in notes


def test_curator_hour_is_a_grey_slot_in_room_schedule(make_lesson):
    lessons = _grids_with_monday_shifted(make_lesson)
    special = [{"day": 0, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}]

    schedule = cabinets.build_room_schedule(lessons, "999", special)

    starts = [s["start"] for s in schedule[0]]
    assert starts == ["08:30", "09:20", "10:15", "14:25", "15:10", "16:00"]
    assert schedule[0][3]["special"] == "Кураторский час"
    assert all(s["special"] is None for i, s in enumerate(schedule[0]) if i != 3)
