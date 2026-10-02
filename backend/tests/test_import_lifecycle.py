"""Жизненный цикл проверки: очистка сырых загруженных файлов после импорта
(накопление реальных ФИО на диске без ограничения — реальная проблема при
ежедневном использовании), удаление старой проверки, человекочитаемая дата
в списке "Недавние проверки" и экспорт отчёта в Word."""
from __future__ import annotations

import asyncio
import os

from app import db
from app import main as main_module


class _FakeUpload:
    """Заменяет starlette UploadFile — do_import обращается только к .filename
    и await .read(), так что настоящий UploadFile тут не нужен."""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def test_import_removes_raw_uploaded_files_after_saving_to_db(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    db_path = tmp_path / "db" / "cafedra.sqlite3"
    os.makedirs(uploads_dir, exist_ok=True)
    os.makedirs(db_path.parent, exist_ok=True)
    monkeypatch.setattr(main_module, "UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))

    files = [_FakeUpload("broken.xls", b"not a real xls file")]

    asyncio.run(main_module.do_import(request=None, files=files))

    assert list(uploads_dir.iterdir()) == []  # рабочая папка импорта удалена

    conn = db.get_connection(str(db_path))
    try:
        imports = db.list_imports(conn)
    finally:
        conn.close()
    assert len(imports) == 1  # но сам импорт (с failed_files в notes) в БД остался


def test_delete_import_removes_lessons_and_import_row(tmp_path, make_lesson):
    db_path = tmp_path / "test.sqlite3"
    conn = db.get_connection(str(db_path))
    try:
        db.save_import(conn, "abc123", [make_lesson()], {})
        conn.commit()
        assert db.import_exists(conn, "abc123")

        db.delete_import(conn, "abc123")
        conn.commit()

        assert not db.import_exists(conn, "abc123")
        assert db.load_lessons(conn, "abc123") == []
    finally:
        conn.close()


def test_delete_import_route_removes_data_and_redirects_home(tmp_path, monkeypatch, make_lesson):
    db_path = tmp_path / "test.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "xyz", [make_lesson()], {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))

    resp = main_module.delete_import(import_id="xyz")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    conn = db.get_connection(str(db_path))
    try:
        assert not db.import_exists(conn, "xyz")
    finally:
        conn.close()


def test_format_ru_datetime_human_readable():
    assert main_module._format_ru_datetime("2026-09-30 14:05:00") == "30 сентября 2026, 14:05"


def test_format_ru_datetime_falls_back_on_unexpected_input():
    assert main_module._format_ru_datetime("garbage") == "garbage"


def test_lesson_line_includes_key_fields(make_lesson):
    l = make_lesson(teacher="Иванов И.И.", student="Петров П.П.", group="91Ф", room="418")

    line = main_module._lesson_line(l)

    assert "Иванов И.И." in line
    assert "Петров П.П." in line
    assert "91Ф" in line
    assert "418" in line


def test_docx_export_lists_conflicts_and_summary(tmp_path, make_lesson, monkeypatch):
    db_path = tmp_path / "t.sqlite3"
    conn = db.get_connection(str(db_path))
    a = make_lesson(day=0, start="10:00", teacher="Иванов И.И.", room="101")
    b = make_lesson(day=0, start="10:15", teacher="Иванов И.И.", room="101")
    db.save_import(conn, "demo", [a, b], {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))

    ctx = main_module._build_report_context("demo")
    doc = main_module._build_conflict_docx(ctx)

    paragraph_text = "\n".join(p.text for p in doc.paragraphs)
    table_text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert "Иванов И.И." in table_text
    assert "явных накладок" in paragraph_text.lower()


def test_docx_export_shows_all_clear_message_when_person_has_no_conflicts(tmp_path, make_lesson, monkeypatch):
    db_path = tmp_path / "t2.sqlite3"
    conn = db.get_connection(str(db_path))
    db.save_import(conn, "demo2", [make_lesson(teacher="Петров П.П.")], {})
    conn.commit()
    conn.close()
    monkeypatch.setattr(main_module, "DB_PATH", str(db_path))

    ctx = main_module._build_report_context("demo2", main_module._Filters(person="Петров П.П."))
    doc = main_module._build_conflict_docx(ctx)

    paragraph_text = "\n".join(p.text for p in doc.paragraphs)
    assert "всё в порядке" in paragraph_text
