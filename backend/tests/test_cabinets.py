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


def test_grid_rows_align_days_by_slot_number_not_clock_time(make_lesson):
    a = make_lesson(day=0, start="10:15", room="101")
    b = make_lesson(day=1, start="11:00", room="101")

    schedule = cabinets.build_room_schedule([a, b], "101")
    rows = cabinets.grid_rows(schedule, [0, 1])

    assert len(rows) == 1
    assert rows[0][0]["start"] == "10:15" and rows[0][1]["start"] == "11:00"
    assert rows[0][0]["occupied_by"] is a


def test_grid_rows_pads_shorter_days_with_none(make_lesson):
    lessons = [
        make_lesson(day=0, start="10:15", room="101"),
        make_lesson(day=0, start="11:05", room="101", student="Другой"),
        make_lesson(day=1, start="10:15", room="101", student="Третий"),
    ]
    schedule = cabinets.build_room_schedule(lessons, "101")
    rows = cabinets.grid_rows(schedule, [0, 1])

    assert len(rows) == 2 and rows[1][1] is None


def _full_day(make_lesson, day=1):
    """Достаточно занятий, чтобы сетка дня считалась надёжной (20+, слоты по 3+ раза)."""
    out = []
    for t in ["08:30", "09:20", "10:15"]:
        for k in range(8):
            out.append(make_lesson(day=day, start=t, teacher=f"П{k}", student=f"С{t}{k}", room=f"1{k}"))
    return out


def test_department_rooms_are_only_the_registry_rooms_normalized(make_lesson):
    """Кабинеты кафедры — только то, что методист добавил; остальные аудитории колледжа не угадываем."""
    assert cabinets.department_rooms(["202", " 101 ", "ауд. 417", "418.0", "", "101"]) == ["101", "202", "417", "418"]
    assert cabinets.department_rooms([]) == [] and cabinets.department_rooms(None) == []


def test_add_room_stores_normalized_form():
    config = cabinets.load_config("/нет/такого/файла.json")
    cabinets.add_room(config, " ауд. 417 ")
    cabinets.add_room(config, "417.0")  # то же самое — не дублируется
    assert cabinets.get_rooms(config) == ["417"]


def test_group_rooms_by_floor():
    groups = cabinets.group_rooms_by_floor(["421", "417", "305", "м/ф", "4.27", "418"])
    assert groups == [("3 этаж", ["305"]), ("4 этаж", ["417", "418", "421"]), ("Прочие", ["4.27", "м/ф"])]


def test_free_rooms_day_marks_busy_free_and_counts(make_lesson):
    lessons = _full_day(make_lesson)
    rooms = cabinets.department_rooms([f"1{k}" for k in range(8)])  # кабинеты 10..17

    view = cabinets.free_rooms_day(lessons, 1, rooms)

    assert [s["start"] for s in view["slots"]] == ["08:30", "09:20", "10:15"]
    assert all(s["free"] == 0 for s in view["slots"])  # в каждом слоте заняты все 8 кабинетов
    assert view["rows"][0]["cells"][0]["state"] == "busy" and view["rows"][0]["cells"][0]["who"] == ["П0"]

    extra = cabinets.free_rooms_day(lessons, 1, rooms + ["999"])
    assert all(s["free"] == 1 for s in extra["slots"])
    assert extra["rows"][-1]["cells"][0] == {"state": "free", "who": []}


def test_free_rooms_day_group_lesson_blocks_two_slots_and_clash_is_shown(make_lesson):
    lessons = _full_day(make_lesson)
    lessons.append(make_lesson(day=1, start="08:30", teacher="Группа Г.Г.", room="10",
                               lesson_type=LessonType.GROUP, duration=90, student=None))
    view = cabinets.free_rooms_day(lessons, 1, ["10"])

    cells = view["rows"][0]["cells"]
    assert cells[0]["state"] == "clash" and cells[1]["state"] == "clash"  # пара 08:30–10:00 перекрывает два слота
    assert cells[2]["state"] == "busy"


def test_free_rooms_day_curator_hour_is_special(make_lesson):
    lessons = _full_day(make_lesson)
    view = cabinets.free_rooms_day(lessons, 1, ["10"], [{"day": 1, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}])

    assert [s["start"] for s in view["slots"]][-1] == "14:25"
    assert view["slots"][-1]["special"] == "Кураторский час"
    assert view["rows"][0]["cells"][-1]["state"] == "special"
