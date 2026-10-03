"""Подсказки «много занятий в день» и «окно» у студентов."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import db, load_checks
from app import main as main_module
from app.models import LessonType


def _day(make_lesson, student, times, group="91Ф", day=0, teacher="Иванов И.И."):
    return [make_lesson(day=day, start=t, student=student, group=group, teacher=teacher, room=f"4{i}")
            for i, t in enumerate(times)]


def test_many_lessons_in_one_day_flagged_with_default_threshold(make_lesson):
    times = ["08:30", "09:20", "10:15", "11:05", "12:00", "12:50"]
    lessons = _day(make_lesson, "Загруженная Анна", times) + _day(make_lesson, "Спокойная Ольга", times[:3], group="92Ф")

    items = load_checks.find_load_issues(lessons)

    many = [i for i in items if i.kind == "many"]
    assert len(many) == 1 and many[0].student == "Загруженная Анна"
    assert "6 индивидуальных занятий" in many[0].text and "с 08:30 до 13:35" in many[0].text


def test_same_lesson_in_teacher_and_accompanist_files_is_counted_once(make_lesson):
    a = make_lesson(day=0, start="08:30", teacher="Иванов И.И.", student="Двойная Дарья", group="91Ф")
    b = make_lesson(day=0, start="08:30", teacher=None, accompanist="Смирнова А.А.", student="Двойная Дарья", group="91Ф")
    c = make_lesson(day=0, start="09:20", teacher="Иванов И.И.", student="Двойная Дарья", group="91Ф")

    assert load_checks.find_load_issues([a, b, c], max_lessons=3) == []  # это 2 занятия, а не 3


def test_typo_in_student_name_still_counts_as_one_student(make_lesson):
    times = ["08:30", "09:20", "10:15"]
    lessons = (_day(make_lesson, "Становкина Юлия", times[:2], teacher="А А.А.")
               + _day(make_lesson, "Становакина Юлия", times[2:], teacher="Б Б.Б."))

    items = load_checks.find_load_issues(lessons, max_lessons=3)

    assert len(items) == 1 and items[0].kind == "many"


def test_window_between_lessons_is_reported_but_group_lessons_close_it(make_lesson):
    lessons = _day(make_lesson, "Окошкина Вера", ["08:30", "18:15"])  # пауза с 09:15 до 18:15 = 9 ч

    items = load_checks.find_load_issues(lessons)
    assert [i.kind for i in items] == ["window"]
    assert "окно 9 ч 00 мин — между 09:15 и 18:15" in items[0].text

    # пара группы 91Ф днём закрывает окно: остаются паузы короче порога
    lessons.append(make_lesson(day=0, start="11:00", duration=90, lesson_type=LessonType.GROUP,
                               student=None, group="91Ф", teacher="Лектор Л.Л.", room="314"))
    lessons.append(make_lesson(day=0, start="14:00", duration=90, lesson_type=LessonType.GROUP,
                               student=None, group="91Ф", teacher="Лектор Л.Л.", room="314"))
    assert load_checks.find_load_issues(lessons) == []


def test_window_between_two_group_lessons_is_not_the_departments_problem(make_lesson):
    lessons = [
        make_lesson(day=0, start="08:30", student="Студент Тестовый", group="91Ф"),
        make_lesson(day=0, start="09:20", duration=90, lesson_type=LessonType.GROUP, student=None, group="91Ф", teacher="Л Л.Л."),
        make_lesson(day=0, start="19:00", duration=90, lesson_type=LessonType.GROUP, student=None, group="91Ф", teacher="Л Л.Л."),
    ]
    # окно 10:50–19:00 лежит между двумя парами — к индивидуальным занятиям отношения не имеет
    assert [i for i in load_checks.find_load_issues(lessons) if i.kind == "window"] == []


def test_load_page_renders_and_thresholds_are_clamped(tmp_path, monkeypatch, make_lesson):
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "imp", _day(make_lesson, "Окошкина Вера", ["08:30", "18:15"]), {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    client = TestClient(main_module.app)

    page = client.get("/report/imp/load").text
    assert "Окошкина Вера" in page and "окно 9 ч 00 мин" in page

    assert "Окошкина Вера" not in client.get("/report/imp/load?window_hours=12").text
    assert client.get("/report/imp/load?max_lessons=-5&window_hours=999&day=abc").status_code == 200
    assert client.get("/report/nope/load").status_code == 404
