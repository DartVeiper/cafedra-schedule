"""Сборка полного набора занятий из каталогов Формата 1 и Формата 2.

Каждый файл читается независимо: если один файл повреждён, не в том формате
или Word не смог его открыть — это не должно ронять весь импорт. Такой файл
просто пропускается, а причина попадает в failed_files, чтобы показать
пользователю понятное сообщение вместо падения всей страницы с "Internal
Server Error".
"""
from __future__ import annotations

import os
import re

from app.models import Lesson, ParseWarning
from app.parsers.dedup import ImportReport, build_import
from app.parsers.doc_convert import convert_doc_to_docx
from app.parsers.group import parse_group_docx
from app.parsers.individual import parse_individual_workbook

_GROUP_FROM_FILENAME_RE = re.compile(r"^(\d{2})\s*([А-Яа-я]+)")


def _short_error(e: Exception) -> str:
    """Короткое объяснение причины ошибки — без стек-трейса, но и без вранья."""
    name = type(e).__name__
    msg = str(e).strip()
    if not msg:
        return name
    if len(msg) > 150:
        msg = msg[:150] + "..."
    return f"{name}: {msg}"


def known_groups_from_filenames(group_dir: str) -> set[str]:
    groups = set()
    for name in os.listdir(group_dir):
        m = _GROUP_FROM_FILENAME_RE.match(name)
        if m:
            groups.add((m.group(1) + m.group(2)).upper())
    return groups


def load_individual_lessons(individual_dir: str, known_groups: set[str] | None = None) -> ImportReport:
    all_sheet_results = []
    failed_files: list[str] = []
    for name in sorted(os.listdir(individual_dir)):
        path = os.path.join(individual_dir, name)
        try:
            all_sheet_results.extend(parse_individual_workbook(path, known_groups=known_groups))
        except Exception as e:  # файл повреждён, не тот формат, защищён паролем и т.п.
            failed_files.append(f"{name}: не удалось прочитать файл ({_short_error(e)})")
    report = build_import(all_sheet_results)
    report.failed_files.extend(failed_files)
    return report


def load_group_lessons(
    group_dir: str, group_docx_cache_dir: str, special_slots_out: list | None = None
) -> tuple[list[Lesson], list[ParseWarning], list[str]]:
    """special_slots_out — необязательный список, куда добавляются служебные
    слоты групповых файлов (кураторский час и т.п.): словари
    {"day": 0, "start": "14:25", "subject": "КУРАТОРСКИЙ ЧАС"}, без повторов."""
    os.makedirs(group_docx_cache_dir, exist_ok=True)
    lessons: list[Lesson] = []
    warnings: list[ParseWarning] = []
    failed_files: list[str] = []
    for name in sorted(os.listdir(group_dir)):
        src = os.path.join(group_dir, name)
        ext = os.path.splitext(name)[1].lower()
        if ext not in (".doc", ".docx"):
            continue
        try:
            docx_path = convert_doc_to_docx(src, group_docx_cache_dir) if ext == ".doc" else src
            result = parse_group_docx(docx_path)
        except Exception as e:  # Word не смог открыть файл, файл повреждён и т.п.
            failed_files.append(f"{name}: не удалось прочитать файл ({_short_error(e)})")
            continue
        lessons.extend(result.lessons)
        warnings.extend(result.warnings)
        if special_slots_out is not None:
            for day, start, subject in result.special_event_slots:
                item = {"day": day, "start": start.strftime("%H:%M"), "subject": subject}
                if item not in special_slots_out:
                    special_slots_out.append(item)
    if special_slots_out is not None:
        special_slots_out.sort(key=lambda s: (s["day"], s["start"], s["subject"]))
    return lessons, warnings, failed_files


def load_all_lessons(
    individual_dir: str, group_dir: str, group_docx_cache_dir: str
) -> tuple[list[Lesson], ImportReport, list[ParseWarning], list[str]]:
    known_groups = known_groups_from_filenames(group_dir)
    individual_report = load_individual_lessons(individual_dir, known_groups=known_groups)
    group_lessons, group_warnings, group_failed = load_group_lessons(group_dir, group_docx_cache_dir)
    all_lessons = list(individual_report.lessons) + group_lessons
    failed_files = list(individual_report.failed_files) + group_failed
    return all_lessons, individual_report, group_warnings, failed_files
