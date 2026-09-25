"""SQLite-хранилище одного импорта (набора занятий) на время анализа.

Схема простая (одна пачка занятий = один import_id): это не многопользовательская
СУБД с историей версий, а рабочее хранилище на время сессии анализа расписания,
как и требовалось в ТЗ — "SQLite для хранения на время анализа".
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import time
from typing import Iterator

from app.models import Lesson, LessonType, SourceRef

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    notes_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id TEXT NOT NULL,
    lesson_type TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    teacher_name TEXT,
    accompanist_name TEXT,
    student_name TEXT,
    group_raw TEXT,
    group_normalized TEXT,
    subject TEXT,
    room_raw TEXT,
    room_normalized TEXT,
    source_file TEXT NOT NULL,
    source_sheet TEXT,
    source_row INTEGER,
    FOREIGN KEY (import_id) REFERENCES imports(id)
);
CREATE INDEX IF NOT EXISTS idx_lessons_import ON lessons(import_id);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_import(conn: sqlite3.Connection, import_id: str, lessons: list[Lesson], notes: dict) -> None:
    conn.execute(
        "INSERT INTO imports (id, created_at, notes_json) VALUES (?, datetime('now'), ?)",
        (import_id, json.dumps(notes, ensure_ascii=False)),
    )
    conn.executemany(
        """
        INSERT INTO lessons (
            import_id, lesson_type, day_of_week, start_time, duration_minutes,
            teacher_name, accompanist_name, student_name, group_raw, group_normalized,
            subject, room_raw, room_normalized, source_file, source_sheet, source_row
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                import_id, l.lesson_type.value, l.day_of_week, l.start_time.strftime("%H:%M"),
                l.duration_minutes, l.teacher_name, l.accompanist_name, l.student_name,
                l.group_raw, l.group_normalized, l.subject, l.room_raw, l.room_normalized,
                l.source.file_name, l.source.sheet_name, l.source.row_index,
            )
            for l in lessons
        ],
    )


def load_lessons(conn: sqlite3.Connection, import_id: str) -> list[Lesson]:
    rows = conn.execute("SELECT * FROM lessons WHERE import_id = ?", (import_id,)).fetchall()
    lessons = []
    for row in rows:
        hh, mm = row["start_time"].split(":")
        lessons.append(
            Lesson(
                lesson_type=LessonType(row["lesson_type"]),
                day_of_week=row["day_of_week"],
                start_time=time(hour=int(hh), minute=int(mm)),
                duration_minutes=row["duration_minutes"],
                teacher_name=row["teacher_name"],
                accompanist_name=row["accompanist_name"],
                student_name=row["student_name"],
                group_raw=row["group_raw"],
                group_normalized=row["group_normalized"],
                subject=row["subject"],
                room_raw=row["room_raw"],
                room_normalized=row["room_normalized"],
                source=SourceRef(
                    file_name=row["source_file"],
                    sheet_name=row["source_sheet"],
                    row_index=row["source_row"],
                ),
            )
        )
    return lessons


def load_notes(conn: sqlite3.Connection, import_id: str) -> dict:
    row = conn.execute("SELECT notes_json FROM imports WHERE id = ?", (import_id,)).fetchone()
    if row is None:
        return {}
    return json.loads(row["notes_json"])


def import_exists(conn: sqlite3.Connection, import_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM imports WHERE id = ?", (import_id,)).fetchone()
    return row is not None


def list_imports(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, created_at FROM imports ORDER BY created_at DESC").fetchall()
