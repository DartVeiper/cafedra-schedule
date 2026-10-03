"""Сравнение двух проверок: что исправили, что появилось нового."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import compare as compare_module
from app import db
from app import main as main_module
from app.conflicts import find_conflicts


def _clash(make_lesson, room="101", day=0, start="10:00"):
    return [
        make_lesson(day=day, start=start, teacher="Иванов И.И.", student="С1", room=room),
        make_lesson(day=day, start=start, teacher="Петров П.П.", student="С2", room=room),
    ]


def test_fixed_and_new_are_detected_by_content_not_by_file_row(make_lesson):
    old = _clash(make_lesson, room="101") + _clash(make_lesson, room="202", day=1)
    # преподаватели поправили первую накладку (развели по кабинетам) и «создали» новую в среду
    new = (
        [make_lesson(day=0, start="10:00", teacher="Иванов И.И.", student="С1", room="101"),
         make_lesson(day=0, start="10:00", teacher="Петров П.П.", student="С2", room="105")]
        + _clash(make_lesson, room="202", day=1)
        + _clash(make_lesson, room="303", day=2)
    )
    for l in new:
        l.source.row_index = 77  # строки в файлах сдвинулись — на сравнение это не влияет

    cmp = compare_module.compare(find_conflicts(new), find_conflicts(old), "old", "2026-09-30 10:00:00", len(old), len(new))

    assert cmp.fixed_count == 1 and cmp.fixed[0].lesson_a.room_normalized == "101"
    assert cmp.new_count == 1
    assert cmp.same == 1


def test_pairings_do_not_count_as_changes(make_lesson):
    pair = [
        make_lesson(teacher="Иванов И.И.", student="С1", room="101"),
        make_lesson(teacher=None, accompanist="Смирнова А.А.", student="С1", room="101"),
    ]
    cmp = compare_module.compare(find_conflicts(pair), [], "o", "2026-09-30 10:00:00", 0, 2)
    assert cmp.new_count == 0 and cmp.fixed_count == 0


def test_pick_previous():
    rows = [{"id": "c"}, {"id": "b"}, {"id": "a"}]  # новые сверху, как отдаёт db.list_imports
    assert compare_module.pick_previous(rows, "c")["id"] == "b"
    assert compare_module.pick_previous(rows, "a") is None          # самая старая — не с чем
    assert compare_module.pick_previous(rows, "c", "a")["id"] == "a"  # выбрали вручную
    assert compare_module.pick_previous(rows, "c", "off") is None
    assert compare_module.pick_previous(rows, "c", "нет-такой")["id"] == "b"
    assert compare_module.pick_previous(rows, "missing") is None


def test_lessons_differ_a_lot_warning(make_lesson):
    cmp = compare_module.compare([], [], "o", "x", prev_lessons=100, cur_lessons=60)
    assert cmp.lessons_differ_a_lot
    assert not compare_module.compare([], [], "o", "x", 100, 98).lessons_differ_a_lot


def _two_imports(tmp_path, monkeypatch, make_lesson):
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "first", _clash(make_lesson, room="101") + _clash(make_lesson, room="202", day=1), {})
    conn.execute("UPDATE imports SET created_at = '2026-09-01 10:00:00' WHERE id = 'first'")
    db.save_import(conn, "second", _clash(make_lesson, room="202", day=1) + _clash(make_lesson, room="303", day=2), {})
    conn.execute("UPDATE imports SET created_at = '2026-09-02 10:00:00' WHERE id = 'second'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    return TestClient(main_module.app)


def test_report_shows_comparison_and_new_filter(tmp_path, monkeypatch, make_lesson):
    client = _two_imports(tmp_path, monkeypatch, make_lesson)

    page = client.get("/report/second").text
    assert "Сравнение с проверкой от" in page and "исправлено <b>1</b>" in page and "новых <b>1</b>" in page
    assert "НОВАЯ" in page

    only_new = main_module._build_report_context("second", main_module._Filters(changes="new"))
    shown = [c for g in only_new["conflict_groups"] for c in g["conflicts"]]
    assert len(shown) == 1 and shown[0].lesson_a.room_normalized == "303"

    # выгрузка и API учитывают тот же фильтр
    assert len(client.get("/api/report/second?changes=new").json()["conflicts"]) == 1
    assert len(client.get("/api/report/second").json()["conflicts"]) == 2


def test_first_import_has_nothing_to_compare(tmp_path, monkeypatch, make_lesson):
    client = _two_imports(tmp_path, monkeypatch, make_lesson)
    page = client.get("/report/first").text
    assert "Это первая проверка" in page

    off = client.get("/report/second?compare=off").text
    assert "Сравнение с проверкой от" not in off
