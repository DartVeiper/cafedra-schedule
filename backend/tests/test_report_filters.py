"""Фильтры отчёта по дню/кабинету и пометка «это не накладка»."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import db
from app import main as main_module
from app.conflicts import conflict_key, find_conflicts


def _setup(tmp_path, monkeypatch, make_lesson, import_id="imp1"):
    db_path = tmp_path / "t.sqlite3"
    # понедельник кабинет 101 и пятница кабинет 202 — по одной накладке на каждый
    lessons = [
        make_lesson(day=0, start="10:00", teacher="Иванов И.И.", student="С1", room="101"),
        make_lesson(day=0, start="10:15", teacher="Петров П.П.", student="С2", room="101"),
        make_lesson(day=4, start="12:00", teacher="Сидоров С.С.", student="С3", room="202"),
        make_lesson(day=4, start="12:15", teacher="Орлов О.О.", student="С4", room="202"),
    ]
    conn = db.get_connection(str(db_path))
    db.save_import(conn, import_id, lessons, {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    return lessons


def _room_conflicts(import_id, f):
    ctx = main_module._build_report_context(import_id, f)
    return [c for g in ctx["conflict_groups"] for c in g["conflicts"]], ctx


def test_filter_by_day_and_room(tmp_path, monkeypatch, make_lesson):
    _setup(tmp_path, monkeypatch, make_lesson)
    F = main_module._Filters

    everything, ctx = _room_conflicts("imp1", F())
    assert len(everything) == 2
    assert ctx["day_counts"] == {0: 1, 4: 1}

    monday, _ = _room_conflicts("imp1", F(day="0"))
    assert [c.day_of_week for c in monday] == [0]

    room202, ctx = _room_conflicts("imp1", F(room="202"))
    assert [c.lesson_a.room_normalized for c in room202] == ["202"]
    # счётчики по дням учитывают выбранный кабинет
    assert ctx["day_counts"] == {4: 1}

    none, _ = _room_conflicts("imp1", F(day="0", room="202"))
    assert none == []


def test_bad_day_value_is_ignored(tmp_path, monkeypatch, make_lesson):
    _setup(tmp_path, monkeypatch, make_lesson)
    found, _ = _room_conflicts("imp1", main_module._Filters(day="abc"))
    assert len(found) == 2


def test_dismiss_hides_conflict_and_restore_brings_it_back(tmp_path, monkeypatch, make_lesson):
    lessons = _setup(tmp_path, monkeypatch, make_lesson)
    key = conflict_key(find_conflicts(lessons)[0])
    client = TestClient(main_module.app)

    resp = client.post("/report/imp1/dismiss", data={"key": key, "qs": "day=0"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/report/imp1?day=0"

    shown, ctx = _room_conflicts("imp1", main_module._Filters())
    assert len(shown) == 1
    assert ctx["dismissed_total"] == 1

    shown_dismissed = main_module._build_report_context("imp1", main_module._Filters(show_dismissed=True))
    assert sum(len(g["conflicts"]) for g in shown_dismissed["dismissed_groups"]) == 1

    client.post("/report/imp1/restore", data={"key": key}, follow_redirects=False)
    shown, _ = _room_conflicts("imp1", main_module._Filters())
    assert len(shown) == 2


def test_dismiss_json_mode_and_bad_key_ignored(tmp_path, monkeypatch, make_lesson):
    _setup(tmp_path, monkeypatch, make_lesson)
    client = TestClient(main_module.app)

    resp = client.post("/report/imp1/dismiss", data={"key": "../../etc"}, headers={"x-requested-with": "fetch"})
    assert resp.json() == {"ok": True}
    shown, _ = _room_conflicts("imp1", main_module._Filters())
    assert len(shown) == 2  # мусорный ключ ничего не скрыл


def test_conflict_key_is_stable_across_order_and_source_rows(make_lesson):
    a = make_lesson(day=0, start="10:00", teacher="Иванов И.И.", student="С1", room="101")
    b = make_lesson(day=0, start="10:15", teacher="Петров П.П.", student="С2", room="101")
    c1 = find_conflicts([a, b])[0]
    b.source.row_index = 99  # строка в файле сместилась после правки
    c2 = find_conflicts([b, a])[0]

    assert conflict_key(c1) == conflict_key(c2)


def test_exports_exclude_dismissed(tmp_path, monkeypatch, make_lesson):
    lessons = _setup(tmp_path, monkeypatch, make_lesson)
    client = TestClient(main_module.app)
    client.post("/report/imp1/dismiss", data={"key": conflict_key(find_conflicts(lessons)[0])})

    resp = client.get("/api/report/imp1")

    assert len(resp.json()["conflicts"]) == 1


def test_report_and_cabinet_pages_show_irregular_time(tmp_path, monkeypatch, make_lesson):
    """Нестандартное время должно попасть и в блок «Стоит проверить» отчёта, и в
    страницу/список кабинетов (сквозная проверка шаблонов на синтетических данных)."""
    lessons = []
    for t in ["08:30", "09:20", "10:15", "11:05"]:
        for k in range(8):
            lessons.append(make_lesson(day=1, start=t, teacher=f"П{k}", student=f"С{t}{k}", room=f"3{k}"))
    lessons.append(make_lesson(day=1, start="10:22", teacher="Толмачева Э.Г.", student="Габриэлян София", room="417"))
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "imp9", lessons, {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    client = TestClient(main_module.app)

    report = client.get("/report/imp9").text
    page = client.get("/report/imp9/cabinets/417").text
    listing = client.get("/report/imp9/cabinets").text

    assert "Нестандартное время начала: 1" in report and "10:22" in report and "ближайшее по сетке — 10:15" in report
    assert "нестандартное время" in page and "cell-irregular" in page
    assert listing  # страница списка рендерится без ошибок



def test_free_rooms_page_shows_only_department_rooms_and_tab_hidden_until_set(tmp_path, monkeypatch, make_lesson):
    """Вкладка «Свободные кабинеты» и сама страница работают только по списку кабинетов кафедры."""
    from app import cabinets
    lessons = []
    for t in ["08:30", "09:20", "10:15"]:
        for k in range(8):
            lessons.append(make_lesson(day=1, start=t, teacher=f"П{k}", student=f"С{t}{k}", room=f"4{k}"))
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "imp", lessons, {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    client = TestClient(main_module.app)

    # список пуст: вкладки в меню нет, а страница просит указать кабинеты
    report_page = client.get("/report/imp").text
    assert "/free-rooms" not in report_page
    page = client.get("/report/imp/free-rooms?day=1").text
    assert "Сначала укажите кабинеты вашей кафедры" in page and "fr-grid" not in page

    # выбрали 2 кабинета пачкой (форма с этажами) — они и только они в таблице, вкладка появилась
    resp = client.post("/report/imp/cabinets/add-many", data={"rooms": ["40", "41"]}, follow_redirects=False)
    assert resp.status_code == 303
    assert cabinets.get_rooms(cabinets.load_config(main_module.CABINETS_PATH)) == ["40", "41"]
    assert "/free-rooms" in client.get("/report/imp").text
    page = client.get("/report/imp/free-rooms?day=1").text
    assert "Показаны кабинеты вашей кафедры: 2" in page
    assert page.count('class="fr-room"') == 2 and ">40</a>" in page and ">47</a>" not in page

    # страница выбора показывает кабинеты из проверки, сгруппированные по этажам (чекбоксы)
    picker = client.get("/report/imp/cabinets").text
    assert 'name="rooms"' in picker and "весь этаж" in picker
