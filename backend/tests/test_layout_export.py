"""Раскладка расписания по кабинетам — Word и Excel (как ручная «Раскладка …»)."""
from __future__ import annotations

from io import BytesIO

import openpyxl
from docx import Document
from fastapi.testclient import TestClient

from app import cabinets, db, layout_export
from app import main as main_module
from app.models import LessonType


def _week(make_lesson):
    """Вторник: сетка из 3 слотов (по 8 занятий в каждом — сетка считается надёжной)."""
    out = []
    for t in ["08:30", "09:20", "10:15"]:
        for k in range(8):
            out.append(make_lesson(day=1, start=t, teacher=f"Преп{k} П.П.", student=f"Студент{t}{k}", room=f"4{k}", subject="спец. инструмент"))
    return out


def test_teacher_and_accompanist_are_one_entry_with_concertmaster_in_parentheses(make_lesson):
    lessons = _week(make_lesson)
    lessons.append(make_lesson(day=1, start="08:30", teacher=None, accompanist="Шейна О.С.", student="Студент08:300", room="40",
                               subject="спец. инструмент"))

    layout = layout_export.build_layout(lessons, ["40"])

    cell = layout[0]["rows"][0]["cells"][0]
    assert cell["state"] == "busy" and len(cell["entries"]) == 1
    lines = layout_export.entry_lines(cell["entries"][0])
    assert lines[0] == "Преп0 П.П."                      # преподаватель — первая (жирная) строка
    assert lines[1].startswith("Студент08:300")
    assert lines[-1] == "Шейна О.С. (концертмейстер)"


def test_clash_group_lessons_and_curator_hour_in_layout(make_lesson):
    lessons = _week(make_lesson)
    lessons.append(make_lesson(day=1, start="08:30", teacher="Другой Д.Д.", student="Иной Студент", room="40"))  # накладка
    lessons.append(make_lesson(day=1, start="09:20", duration=90, lesson_type=LessonType.GROUP, student=None,
                               teacher="доц. Лектор Л.Л.", group="92Ф", subject="История", room="41"))
    special = [{"day": 1, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}]

    layout = layout_export.build_layout(lessons, ["40", "41"], special)
    rows = layout[0]["rows"]

    assert rows[0]["cells"][0]["state"] == "clash"
    texts = layout_export._cell_text(rows[0]["cells"][0])
    assert texts.startswith("⚠ НАКЛАДКА") and "— — —" in texts
    group_first = layout_export.entry_lines(rows[1]["cells"][1]["entries"][0])
    assert group_first[0] == "ПАРА 92Ф" and group_first[2] == "Лектор Л.Л."          # звание убрано
    assert layout_export.entry_lines(rows[2]["cells"][1]["entries"][0]) == ["↑ пара продолжается"]
    assert rows[-1]["start"] == "14:25" and rows[-1]["special"] == "Кураторский час"
    assert rows[-1]["cells"][0]["state"] == "special"


def test_word_file_has_a_table_per_day_with_rooms_as_columns(make_lesson):
    lessons = _week(make_lesson) + [make_lesson(day=3, start=t, teacher=f"Ч{k} Ч.Ч.", student=f"С{t}{k}", room=f"4{k}")
                                    for t in ["08:30", "09:20"] for k in range(12)]
    data = layout_export.build_docx(lessons, ["40", "41", "42"], [], "Раскладка по кабинетам")

    doc = Document(BytesIO(data))
    assert len(doc.tables) == 2                                   # вторник и четверг
    header = [c.text for c in doc.tables[0].rows[0].cells]
    assert header == ["Часы", "40", "41", "42"]
    assert doc.tables[0].rows[1].cells[0].text == "08:30"
    assert "Преп0 П.П." in doc.tables[0].rows[1].cells[1].text
    assert any("Раскладка по кабинетам — Вторник" in p.text for p in doc.paragraphs)
    section = doc.sections[0]
    assert section.page_width > section.page_height               # альбомная страница


def test_excel_has_sheet_per_day_and_flat_list(make_lesson):
    lessons = _week(make_lesson)
    wb = openpyxl.load_workbook(BytesIO(layout_export.build_xlsx(lessons, ["40", "41"], [], "Раскладка")))

    assert wb.sheetnames == ["Вторник", "Все занятия"]
    day = wb["Вторник"]
    assert [day.cell(2, c).value for c in (1, 2, 3)] == ["Время", "40", "41"]
    assert "Преп0 П.П." in day.cell(3, 2).value
    flat = wb["Все занятия"]
    assert flat.max_row == 1 + len(lessons)                       # заголовок + все занятия (в т.ч. вне выбранных кабинетов)
    assert [c.value for c in flat[1]][:5] == ["День", "Начало", "Конец", "Кабинет", "Тип"]
    assert flat.auto_filter.ref is not None


def test_layout_rooms_use_registry_else_all_individual_rooms(make_lesson):
    lessons = _week(make_lesson)
    assert cabinets.layout_rooms(lessons, ["41", "40"]) == ["40", "41"]
    assert cabinets.layout_rooms(lessons, []) == [f"4{k}" for k in range(8)]


def test_layout_routes(tmp_path, monkeypatch, make_lesson):
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "imp", _week(make_lesson), {"special_slots": []})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    client = TestClient(main_module.app)

    word = client.get("/report/imp/layout.docx")
    assert word.status_code == 200 and word.content[:2] == b"PK"
    assert len(Document(BytesIO(word.content)).tables) == 1
    xl = client.get("/report/imp/layout.xlsx")
    assert xl.status_code == 200 and openpyxl.load_workbook(BytesIO(xl.content)).sheetnames == ["Вторник", "Все занятия"]
    assert client.get("/report/nope/layout.docx").status_code == 404
    assert client.get("/report/nope/layout.xlsx").status_code == 404
    assert "/report/imp/layout" in client.get("/report/imp").text   # кнопка на странице отчёта


def test_docx_with_one_room_is_not_stretched_and_empty_slots_keep_height(make_lesson):
    """Жалоба методиста: при одном кабинете в списке таблица растягивалась на всю страницу, а пустые
    слоты схлопывались в тонкие линии."""
    from docx.shared import Cm
    from docx.enum.table import WD_ROW_HEIGHT_RULE

    data = layout_export.build_docx(_week(make_lesson), ["40"], [], "Раскладка")
    table = Document(BytesIO(data)).tables[0]

    assert table.rows[1].cells[1].width <= Cm(4.7)                       # столбец кабинета ограничен
    assert table.rows[1].cells[0].width >= Cm(2.0)                       # колонка времени не узкая
    data_rows = table.rows[1:]
    assert all(r.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST and r.height >= Cm(1.2) for r in data_rows)


def test_days_filter_and_custom_title(make_lesson):
    lessons = _week(make_lesson) + [make_lesson(day=3, start=t, teacher=f"Ч{k} Ч.Ч.", student=f"С{t}{k}", room=f"4{k}")
                                    for t in ["08:30", "09:20", "10:15"] for k in range(8)]

    only_thu = Document(BytesIO(layout_export.build_docx(lessons, ["40"], [], "КАФЕДРА 2026-2027", [3])))
    assert len(only_thu.tables) == 1
    assert any("КАФЕДРА 2026-2027 — Четверг" in p.text for p in only_thu.paragraphs)
    wb = openpyxl.load_workbook(BytesIO(layout_export.build_xlsx(lessons, ["40"], [], "КАФЕДРА", [3])))
    assert wb.sheetnames == ["Четверг", "Все занятия"]


def test_layout_settings_page_and_download_with_chosen_rooms_days_title(tmp_path, monkeypatch, make_lesson):
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "imp", _week(make_lesson), {"special_slots": []})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))
    client = TestClient(main_module.app)

    page = client.get("/report/imp/layout").text
    assert 'name="rooms" value="40"' in page and "весь этаж" in page and 'name="title"' in page
    assert page.count('name="rooms"') == 8 and page.count("checked") >= 8   # список кабинетов кафедры пуст -> отмечены все

    word = client.get("/report/imp/layout.docx", params={"title": "Моя  раскладка", "rooms": ["41", "40"], "days": ["1"]})
    doc = Document(BytesIO(word.content))
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["Часы", "40", "41"]       # порядок — по возрастанию
    assert any("Моя раскладка — Вторник" in p.text for p in doc.paragraphs)           # лишние пробелы убраны

    other_day = client.get("/report/imp/layout.docx", params={"days": ["4"]})
    assert len(Document(BytesIO(other_day.content)).tables) == 0                      # у пятницы нет сетки
    assert client.get("/report/nope/layout").status_code == 404


def test_word_cell_properties_follow_schema_order(make_lesson):
    """В tcPr заливка (shd) обязана идти раньше выравнивания (vAlign) — иначе строгий Word ругается на файл."""
    from docx.oxml.ns import qn
    lessons = _week(make_lesson) + [make_lesson(day=1, start="08:30", teacher="Другой Д.Д.", student="Иной Студент", room="40")]
    doc = Document(BytesIO(layout_export.build_docx(lessons, ["40", "41"], [{"day": 1, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}], "t")))

    checked = 0
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tags = [c.tag for c in cell._tc.tcPr] if cell._tc.tcPr is not None else []
                if qn("w:shd") in tags and qn("w:vAlign") in tags:
                    assert tags.index(qn("w:shd")) < tags.index(qn("w:vAlign"))
                    checked += 1
    assert checked >= 3          # шапка, накладка, кураторский час
