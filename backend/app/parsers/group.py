"""Парсер Формата 2: групповые занятия (Word, .doc — один файл на учебную группу).

.doc — старый бинарный формат Word, python-docx его не читает; сначала конвертируем
в .docx через doc_convert.convert_doc_to_docx (использует уже установленный на
машине MS Word через COM-автоматизацию, либо LibreOffice, если Word не найден).

Реальная структура (проверено на всех 11 файлах кафедры):
  - Одна из таблиц документа — расписание: первая строка-заголовок
    ['ДАТА/ВРЕМЯ', 'ДАТА/ВРЕМЯ', 'Дисциплина', 'ФИО преподавателя', 'ауд.']
    (первые два столбца — это одна объединённая ячейка 'ДАТА/ВРЕМЯ' в Word,
    python-docx превращает её в два столбца с одинаковым текстом в заголовке,
    но по факту в данных первый — день недели, второй — время).
  - День недели в первом столбце — объединённая по вертикали ячейка, python-docx
    просто повторяет её текст в каждой строке блока, так что дополнительная
    логика поиска блоков дней (как в Формате 1) не нужна — день просто читается
    из каждой строки.
  - Время — строка вида '8-30', '10-15' (часы-минуты через дефис, не двоеточие).
  - Пустая 'Дисциплина' = свободный слот, пропускаем.
  - 'Индивидуальные занятия' в 'Дисциплина' — детали не в этом файле, а в
    Формате 1; строка сохраняется как индивидуальный маркер (occupied_slot=True,
    teacher/room не заполняются), чтобы можно было потом сопоставить со
    студентами группы по времени.
  - Аудитория — 'корпус №5 ауд.314' или 'корпус №5 С/з' и т.п.: здание (корпус)
    ОБЯЗАТЕЛЬНО учитываем в нормализации, это другое здание, чем кабинеты
    кафедры из Формата 1 (там корпус не указан вовсе).
  - Номер/название группы — из абзаца 'группа NN X' в начале документа; в паре
    файлов (12МИИ, 22МИИ) этого абзаца нет — тогда берём группу из имени файла.
  - "Полторы пары" и подобное: сетка тайм-слотов дня фиксированная (8-30,
    10-15, 12-00, 14-25/15-10, 16-55, 17-45, 18-40), а реальная пара иногда
    длиннее одного слота. В таблице это оформлено НЕ одной строкой с большей
    длительностью, а повтором той же дисциплины/преподавателя/аудитории в
    двух (или более) идущих подряд строках сетки — реальный пример с кафедры:
    'Музыкальная литература' у Иванченко О.М. стоит и в 15-10, и в 16-55 —
    это ОДНО занятие "пара + пол пары" (135 мин, 15:10-17:25), а не два
    отдельных по 90 минут. Без склейки такое занятие ошибочно "накладывалось"
    на следующее за ним по сетке индивидуальное занятие в 17:45, хотя реально
    к этому времени пара уже закончилась. Склеиваем такие подряд идущие
    одинаковые строки в одно занятие (см. _merge_consecutive_runs).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import docx

from app.models import Lesson, LessonType, ParseWarning, SourceRef, GROUP_LESSON_MINUTES
from app.parsers.common import DAY_NAME_TO_INDEX, normalize_group, normalize_room, normalize_subject, normalize_person_name

_TIME_RE = re.compile(r"^(\d{1,2})-(\d{2})$")
_GROUP_PARA_RE = re.compile(r"группа\s+(.+)", re.IGNORECASE)
_ROOM_BUILDING_RE = re.compile(r"корпус\s*№?\s*(\S+)\s*(.*)", re.IGNORECASE)
_FILENAME_TAIL_RE = re.compile(r"\s*\d+\s*семестр.*$", re.IGNORECASE)
INDIVIDUAL_MARKER = "индивидуальные занятия"


@dataclass
class GroupParseResult:
    file_name: str
    group_raw: str | None
    group_normalized: str | None
    lessons: list[Lesson] = field(default_factory=list)
    individual_marker_slots: list[tuple[int, object]] = field(default_factory=list)  # (day, time) когда группа на индивид. занятиях
    special_event_slots: list[tuple[int, object, str]] = field(default_factory=list)  # (day, time, label) — куратор.час и т.п.
    warnings: list[ParseWarning] = field(default_factory=list)


def parse_group_docx(path: str) -> GroupParseResult:
    file_name = os.path.basename(path)
    d = docx.Document(path)

    group_raw = _find_group_name(d, file_name)
    group_norm = normalize_group(group_raw)

    table = _find_schedule_table(d)
    if table is None:
        warnings = [ParseWarning(file_name, None, "Не найдена таблица расписания (ожидался заголовок 'ДАТА/ВРЕМЯ')")]
        return GroupParseResult(file_name, group_raw, group_norm, [], [], [], warnings)

    table_rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    return rows_to_group_result(table_rows, file_name, group_raw, group_norm)


def rows_to_group_result(
    table_rows: list[list[str]], file_name: str, group_raw: str | None, group_norm: str | None
) -> GroupParseResult:
    """Основная логика разбора таблицы расписания — принимает уже извлечённый
    текст ячеек (как в реальном .docx: table_rows[0] — строка заголовка,
    остальные — данные), без зависимости от python-docx. Вынесено отдельно от
    parse_group_docx специально для юнит-тестов на простых списках строк —
    не нужно собирать настоящий .docx, чтобы проверить склейку "полутора пар"
    или распознавание служебных строк."""
    warnings: list[ParseWarning] = []
    raw_rows: list[dict] = []
    for row_idx, cells in enumerate(table_rows[1:], start=1):
        if len(cells) < 5:
            continue
        day_raw, time_raw, subject_raw, teacher_raw, room_raw = cells[:5]

        day_idx = DAY_NAME_TO_INDEX.get(day_raw.strip().lower())
        if day_idx is None:
            warnings.append(ParseWarning(file_name, table_sheet_label(), f"Не распознан день недели '{day_raw}'", row_idx))
            continue

        time_val = _parse_time(time_raw)
        if time_val is None:
            warnings.append(ParseWarning(file_name, table_sheet_label(), f"Не распознано время '{time_raw}'", row_idx))
            continue

        raw_rows.append({
            "row_idx": row_idx, "day_idx": day_idx, "time": time_val,
            "subject_raw": subject_raw, "teacher_raw": teacher_raw, "room_raw": room_raw,
        })

    lessons: list[Lesson] = []
    marker_slots: list[tuple[int, object]] = []
    special_slots: list[tuple[int, object, str]] = []

    i = 0
    while i < len(raw_rows):
        r = raw_rows[i]
        subject_raw, teacher_raw, room_raw = r["subject_raw"], r["teacher_raw"], r["room_raw"]
        subject = normalize_subject(subject_raw)
        if not subject:
            i += 1
            continue  # свободный слот

        # Служебные строки (куратор.час и т.п.) в реальных файлах записаны так, что
        # 'Дисциплина' = 'ФИО преподавателя' = 'ауд.' — это не настоящий преподаватель
        # и не настоящая аудитория, и учитывать их в поиске накладок нельзя: иначе
        # все группы, у которых куратор.час в одно и то же время, дадут ложную
        # накладку "преподаватель в двух местах" и "аудитория занята дважды".
        if subject_raw.strip().lower() == teacher_raw.strip().lower() == room_raw.strip().lower():
            special_slots.append((r["day_idx"], r["time"], subject))
            i += 1
            continue

        if subject.lower() == INDIVIDUAL_MARKER:
            marker_slots.append((r["day_idx"], r["time"]))
            i += 1
            continue

        run_end = _extend_run(raw_rows, i, subject)
        run_length = run_end - i + 1
        duration = GROUP_LESSON_MINUTES + (GROUP_LESSON_MINUTES // 2) * (run_length - 1)

        teacher = normalize_person_name(teacher_raw)
        building, room_num = _split_room(room_raw)
        room_norm = normalize_room(room_num, building=building) if room_num else None

        lessons.append(
            Lesson(
                lesson_type=LessonType.GROUP,
                day_of_week=r["day_idx"],
                start_time=r["time"],
                duration_minutes=duration,
                teacher_name=teacher,
                group_raw=group_raw,
                group_normalized=group_norm,
                subject=subject,
                room_raw=room_raw or None,
                room_normalized=room_norm,
                source=SourceRef(file_name=file_name, sheet_name=None, row_index=r["row_idx"]),
            )
        )
        i = run_end + 1

    return GroupParseResult(file_name, group_raw, group_norm, lessons, marker_slots, special_slots, warnings)


def _extend_run(raw_rows: list[dict], start: int, subject: str) -> int:
    """Индекс последней строки серии подряд идущих одинаковых слотов (та же
    дисциплина/преподаватель/аудитория, тот же день, физически следующая строка
    таблицы) — см. пояснение про "полторы пары" в начале модуля."""
    r = raw_rows[start]
    end = start
    while (
        end + 1 < len(raw_rows)
        and raw_rows[end + 1]["row_idx"] == raw_rows[end]["row_idx"] + 1
        and raw_rows[end + 1]["day_idx"] == r["day_idx"]
        and normalize_subject(raw_rows[end + 1]["subject_raw"]) == subject
        and raw_rows[end + 1]["teacher_raw"].strip() == r["teacher_raw"].strip()
        and raw_rows[end + 1]["room_raw"].strip() == r["room_raw"].strip()
    ):
        end += 1
    return end


def table_sheet_label() -> str:
    return "расписание"


def _find_group_name(d: docx.Document, file_name: str) -> str | None:
    for p in d.paragraphs[:10]:
        m = _GROUP_PARA_RE.search(p.text)
        if m:
            return m.group(1).strip()
    # Резерв: не у всех файлов есть абзац "группа ..." (напр. 12МИИ, 22МИИ) — берём из имени файла.
    stem = os.path.splitext(file_name)[0]
    stem = _FILENAME_TAIL_RE.sub("", stem).strip()
    return stem or None


def _find_schedule_table(d: docx.Document):
    for table in d.tables:
        if not table.rows:
            continue
        first_cell = table.rows[0].cells[0].text.strip().upper()
        if first_cell.startswith("ДАТА"):
            return table
    return None


def _parse_time(raw: str):
    from datetime import time
    m = _TIME_RE.match(raw.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def _split_room(raw: str) -> tuple[str | None, str | None]:
    """'корпус №5 ауд.314' -> ('5', 'ауд.314'); без 'корпус' -> (None, raw)."""
    if not raw:
        return None, None
    m = _ROOM_BUILDING_RE.match(raw.strip())
    if not m:
        return None, raw.strip()
    building, rest = m.group(1), m.group(2).strip()
    return building, (rest or raw.strip())
