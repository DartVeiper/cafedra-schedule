"""FastAPI-приложение: загрузка файлов расписания, поиск накладок, отчёт в браузере.

Доступно в локальной сети кафедры без установки на компьютеры пользователей —
достаточно открыть http://<адрес-сервера>:8000 в браузере.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.conflicts import find_conflicts
from app.models import DAY_NAMES_RU, ConflictType
from app.paths import app_package_dir, runtime_data_dir
from app.pipeline import known_groups_from_filenames, load_group_lessons, load_individual_lessons
from app.zip_utils import extract_zip

APP_DIR = app_package_dir()
DATA_DIR = runtime_data_dir()
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "db", "cafedra.sqlite3")

INDIVIDUAL_EXTS = {".xls", ".xlsx"}
GROUP_EXTS = {".doc", ".docx"}

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = FastAPI(title="Кафедра фортепиано — поиск накладок в расписании")
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

CONFLICT_LABELS = {
    ConflictType.TEACHER_DOUBLE_BOOKED: "Преподаватель/концертмейстер в двух местах",
    ConflictType.ROOM_DOUBLE_BOOKED: "Аудитория занята дважды",
    ConflictType.STUDENT_DOUBLE_BOOKED: "Студент на двух индивидуальных одновременно",
    ConflictType.STUDENT_VS_GROUP: "Студент: индивидуальное пересекается с групповым",
}


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    conn = db.get_connection(DB_PATH)
    try:
        recent = db.list_imports(conn)[:10]
    finally:
        conn.close()
    return templates.TemplateResponse(request, "upload.html", {"recent": recent})


@app.post("/import")
async def do_import(request: Request, files: list[UploadFile] = File(...)):
    import_id = uuid.uuid4().hex[:12]
    work_dir = os.path.join(UPLOADS_DIR, import_id)
    individual_dir = os.path.join(work_dir, "individual")
    group_dir = os.path.join(work_dir, "group")
    group_docx_dir = os.path.join(work_dir, "group_docx")
    zip_staging_dir = os.path.join(work_dir, "_zip_extracted")
    for d in (individual_dir, group_dir, group_docx_dir, zip_staging_dir):
        os.makedirs(d, exist_ok=True)

    upload_warnings: list[str] = []
    zip_rename_notes: list[str] = []

    for uf in files:
        name = uf.filename or "файл_без_имени"
        ext = os.path.splitext(name)[1].lower()
        raw_bytes = await uf.read()

        if ext == ".zip":
            tmp_zip_path = os.path.join(work_dir, name)
            with open(tmp_zip_path, "wb") as f:
                f.write(raw_bytes)
            result = extract_zip(tmp_zip_path, zip_staging_dir)
            zip_rename_notes.extend(result.renamed_notes)
            for extracted_path in result.extracted_paths:
                ext2 = os.path.splitext(extracted_path)[1].lower()
                if ext2 in INDIVIDUAL_EXTS:
                    shutil.copy(extracted_path, os.path.join(individual_dir, os.path.basename(extracted_path)))
                elif ext2 in GROUP_EXTS:
                    shutil.copy(extracted_path, os.path.join(group_dir, os.path.basename(extracted_path)))
                else:
                    upload_warnings.append(f"В архиве {name}: файл '{os.path.basename(extracted_path)}' — неизвестный формат, пропущен")
        elif ext in INDIVIDUAL_EXTS:
            with open(os.path.join(individual_dir, name), "wb") as f:
                f.write(raw_bytes)
        elif ext in GROUP_EXTS:
            with open(os.path.join(group_dir, name), "wb") as f:
                f.write(raw_bytes)
        else:
            upload_warnings.append(f"Файл '{name}' — неизвестный формат (ожидались .zip/.xls/.xlsx/.doc/.docx), пропущен")

    known_groups = known_groups_from_filenames(group_dir) if os.listdir(group_dir) else set()

    individual_report = None
    if os.listdir(individual_dir):
        individual_report = load_individual_lessons(individual_dir, known_groups=known_groups)

    group_lessons, group_warnings = [], []
    if os.listdir(group_dir):
        group_lessons, group_warnings = load_group_lessons(group_dir, group_docx_dir)

    all_lessons = list(individual_report.lessons if individual_report else []) + group_lessons

    notes = {
        "upload_warnings": upload_warnings,
        "zip_rename_notes": zip_rename_notes,
        "parse_warnings": [w.label() for w in (individual_report.warnings if individual_report else [])] + [w.label() for w in group_warnings],
        "dropped_sheet_notes": individual_report.dropped_sheet_notes if individual_report else [],
        "merge_notes": individual_report.merge_notes if individual_report else [],
        "skipped_sheet_notes": individual_report.skipped_sheet_notes if individual_report else [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "individual_files": sorted(os.listdir(individual_dir)),
        "group_files": sorted(os.listdir(group_dir)),
    }

    conn = db.get_connection(DB_PATH)
    try:
        db.save_import(conn, import_id, all_lessons, notes)
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url=f"/report/{import_id}", status_code=303)


def _involves_accompanist(c) -> bool:
    return bool(c.lesson_a.accompanist_name or c.lesson_b.accompanist_name)


def _build_report_context(import_id: str, hide_accompanist: bool = False) -> dict | None:
    conn = db.get_connection(DB_PATH)
    try:
        if not db.import_exists(conn, import_id):
            return None
        lessons = db.load_lessons(conn, import_id)
        notes = db.load_notes(conn, import_id)
    finally:
        conn.close()

    conflicts = find_conflicts(lessons)
    if hide_accompanist:
        conflicts = [c for c in conflicts if not _involves_accompanist(c)]
    by_type: dict[str, list] = {}
    for c in conflicts:
        by_type.setdefault(c.type.value, []).append(c)

    certain_count = sum(1 for c in conflicts if c.is_certain)
    review_count = sum(1 for c in conflicts if not c.is_certain)

    individual_count = sum(1 for l in lessons if l.lesson_type.value == "individual")
    group_count = len(lessons) - individual_count

    return {
        "import_id": import_id,
        "notes": notes,
        "lesson_count": len(lessons),
        "individual_count": individual_count,
        "group_count": group_count,
        "certain_count": certain_count,
        "review_count": review_count,
        "hide_accompanist": hide_accompanist,
        "conflict_groups": [
            {"type": ctype, "label": CONFLICT_LABELS[ctype], "conflicts": by_type.get(ctype.value, [])}
            for ctype in ConflictType
        ],
        "day_names": DAY_NAMES_RU,
    }


@app.get("/report/{import_id}", response_class=HTMLResponse)
def report(request: Request, import_id: str, hide_accompanist: bool = False):
    ctx = _build_report_context(import_id, hide_accompanist=hide_accompanist)
    if ctx is None:
        return HTMLResponse("<h1>Импорт не найден</h1><p><a href='/'>На главную</a></p>", status_code=404)
    return templates.TemplateResponse(request, "report.html", ctx)


@app.get("/api/report/{import_id}")
def api_report(import_id: str, hide_accompanist: bool = False):
    conn = db.get_connection(DB_PATH)
    try:
        if not db.import_exists(conn, import_id):
            return {"error": "import not found"}
        lessons = db.load_lessons(conn, import_id)
    finally:
        conn.close()
    conflicts = find_conflicts(lessons)
    if hide_accompanist:
        conflicts = [c for c in conflicts if not _involves_accompanist(c)]

    def lesson_json(l):
        return {
            "type": l.lesson_type.value, "day_of_week": l.day_of_week,
            "start_time": l.start_time.strftime("%H:%M"), "duration_minutes": l.duration_minutes,
            "teacher_name": l.teacher_name, "accompanist_name": l.accompanist_name,
            "student_name": l.student_name, "group": l.group_raw, "subject": l.subject,
            "room": l.room_raw, "source": l.source.label(),
        }

    return {
        "import_id": import_id,
        "lesson_count": len(lessons),
        "conflicts": [
            {
                "type": c.type.value, "day_of_week": c.day_of_week, "is_certain": c.is_certain,
                "note": c.note, "a": lesson_json(c.lesson_a), "b": lesson_json(c.lesson_b),
            }
            for c in conflicts
        ],
    }


@app.get("/report/{import_id}/export.xlsx")
def export_xlsx(import_id: str, hide_accompanist: bool = False):
    import openpyxl
    from openpyxl.utils import get_column_letter

    conn = db.get_connection(DB_PATH)
    try:
        if not db.import_exists(conn, import_id):
            return HTMLResponse("Импорт не найден", status_code=404)
        lessons = db.load_lessons(conn, import_id)
    finally:
        conn.close()
    conflicts = find_conflicts(lessons)
    if hide_accompanist:
        conflicts = [c for c in conflicts if not _involves_accompanist(c)]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Накладки"
    headers = [
        "Тип накладки", "Требует проверки", "День", "Примечание",
        "A: время", "A: кто", "A: студент", "A: группа", "A: предмет", "A: аудитория", "A: источник",
        "B: время", "B: кто", "B: студент", "B: группа", "B: предмет", "B: аудитория", "B: источник",
    ]
    ws.append(headers)
    for c in conflicts:
        a, b = c.lesson_a, c.lesson_b

        def person(l):
            return l.teacher_name or l.accompanist_name or ""

        def timespan(l):
            end = l.start_minutes + l.duration_minutes
            return f"{l.start_time.strftime('%H:%M')}-{end // 60:02d}:{end % 60:02d}"

        ws.append([
            CONFLICT_LABELS[c.type], "да" if not c.is_certain else "", DAY_NAMES_RU[c.day_of_week], c.note or "",
            timespan(a), person(a), a.student_name or "", a.group_raw or "", a.subject or "", a.room_raw or "", a.source.label(),
            timespan(b), person(b), b.student_name or "", b.group_raw or "", b.subject or "", b.room_raw or "", b.source.label(),
        ])
    for i, _ in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 20

    import io
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=nakladki_{import_id}.xlsx"},
    )
