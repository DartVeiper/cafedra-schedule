"""Реестр кабинетов (хранится отдельно от data/, см. app/paths.py) и сетка
занятости кабинета, восстановленная из данных проверки — единой сетки
"звонков" ни в одном исходном формате нет (см. app/cabinets.py)."""
from __future__ import annotations

from app import cabinets
from app.models import LessonType


def test_load_config_missing_file_returns_default_skeleton(tmp_path):
    config = cabinets.load_config(str(tmp_path / "does_not_exist.json"))

    assert config["departments"][cabinets.DEFAULT_DEPARTMENT_ID]["rooms"] == []


def test_load_config_corrupt_file_falls_back_to_default(tmp_path):
    path = tmp_path / "cabinets.json"
    path.write_text("not valid json {{{", encoding="utf-8")

    config = cabinets.load_config(str(path))

    assert config["departments"][cabinets.DEFAULT_DEPARTMENT_ID]["rooms"] == []


def test_add_and_remove_room_roundtrip_via_file(tmp_path):
    path = str(tmp_path / "config" / "cabinets.json")

    config = cabinets.load_config(path)
    cabinets.add_room(config, "418")
    cabinets.add_room(config, "418")  # не должно задублироваться
    cabinets.save_config(path, config)

    reloaded = cabinets.load_config(path)
    assert cabinets.get_rooms(reloaded) == ["418"]

    cabinets.remove_room(reloaded, "418")
    cabinets.save_config(path, reloaded)

    assert cabinets.get_rooms(cabinets.load_config(path)) == []


def test_suggest_rooms_only_from_individual_lessons(make_lesson):
    individual = make_lesson(lesson_type=LessonType.INDIVIDUAL, room="101")
    group = make_lesson(lesson_type=LessonType.GROUP, room="202", duration=90)

    assert cabinets.suggest_rooms([individual, group]) == {"101"}


def test_build_room_schedule_marks_group_lesson_spanning_two_slots(make_lesson):
    seed_a = make_lesson(day=0, start="10:15", room="101")  # задаёт слот 10:15
    seed_b = make_lesson(day=0, start="11:00", room="101")  # задаёт слот 11:00
    group = make_lesson(day=0, start="10:15", duration=90, room="418", lesson_type=LessonType.GROUP)

    schedule = cabinets.build_room_schedule([seed_a, seed_b, group], "418")

    assert [s["start"] for s in schedule[0]] == ["10:15", "11:00"]
    assert schedule[0][0]["occupied_by"] is group
    assert schedule[0][1]["occupied_by"] is group


def test_build_room_schedule_only_includes_days_with_individual_lessons(make_lesson):
    monday_only = make_lesson(day=0, start="10:15", room="101")

    schedule = cabinets.build_room_schedule([monday_only], "101")

    assert set(schedule.keys()) == {0}


def test_build_room_schedule_room_with_no_occupants_is_all_free(make_lesson):
    seed = make_lesson(day=0, start="10:15", room="101")

    schedule = cabinets.build_room_schedule([seed], "999")

    assert all(slot["occupied_by"] is None for slot in schedule[0])


def test_build_room_schedule_marks_real_room_double_booking_as_conflict(make_lesson):
    a = make_lesson(day=0, start="10:15", room="418", teacher="Иванов И.И.", student="Студент А")
    b = make_lesson(day=0, start="10:15", room="418", teacher="Петров П.П.", student="Студент Б")

    schedule = cabinets.build_room_schedule([a, b], "418")

    slot = schedule[0][0]
    assert slot["start"] == "10:15"
    assert slot["conflict_with"] is not None
    # Lesson не хэшируемый (dataclass с eq=True) — сравниваем без set()
    got = (slot["occupied_by"], slot["conflict_with"])
    assert got == (a, b) or got == (b, a)


def test_build_room_schedule_no_conflict_for_single_occupant(make_lesson):
    a = make_lesson(day=0, start="10:15", room="418")

    schedule = cabinets.build_room_schedule([a], "418")

    assert schedule[0][0]["conflict_with"] is None


def test_merge_time_axis_combines_times_across_days(make_lesson):
    a = make_lesson(day=0, start="10:15", room="101")
    b = make_lesson(day=1, start="11:00", room="101")

    schedule = cabinets.build_room_schedule([a, b], "101")

    assert cabinets.merge_time_axis(schedule) == ["10:15", "11:00"]


def test_index_by_time_allows_lookup_by_day_and_time(make_lesson):
    a = make_lesson(day=0, start="10:15", room="101")

    schedule = cabinets.build_room_schedule([a], "101")
    indexed = cabinets.index_by_time(schedule)

    assert indexed[0]["10:15"]["occupied_by"] is a
