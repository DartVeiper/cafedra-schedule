"""Сборка полного набора занятий из каталогов Формата 1 и Формата 2."""
from __future__ import annotations

import os
import re

from app.models import Lesson, ParseWarning
from app.parsers.dedup import ImportReport, build_import
from app.parsers.doc_convert import convert_doc_to_docx
from app.parsers.group import parse_group_docx
from app.parsers.individual import parse_individual_workbook

_GROUP_FROM_FILENAME_RE = re.compile(r"^(\d{2})\s*([А-Яа-я]+)")


def known_groups_from_filenames(group_dir: str) -> set[str]:
    groups = set()
    for name in os.listdir(group_dir):
        m = _GROUP_FROM_FILENAME_RE.match(name)
        if m:
            groups.add((m.group(1) + m.group(2)).upper())
    return groups


def load_individual_lessons(individual_dir: str, known_groups: set[str] | None = None) -> ImportReport:
    all_sheet_results = []
    for name in sorted(os.listdir(individual_dir)):
        path = os.path.join(individual_dir, name)
        all_sheet_results.extend(parse_individual_workbook(path, known_groups=known_groups))
    return build_import(all_sheet_results)


def load_group_lessons(
    group_dir: str, group_docx_cache_dir: str
) -> tuple[list[Lesson], list[ParseWarning]]:
    os.makedirs(group_docx_cache_dir, exist_ok=True)
    lessons: list[Lesson] = []
    warnings: list[ParseWarning] = []
    for name in sorted(os.listdir(group_dir)):
        src = os.path.join(group_dir, name)
        ext = os.path.splitext(name)[1].lower()
        if ext == ".doc":
            docx_path = convert_doc_to_docx(src, group_docx_cache_dir)
        elif ext == ".docx":
            docx_path = src
        else:
            continue
        result = parse_group_docx(docx_path)
        lessons.extend(result.lessons)
        warnings.extend(result.warnings)
    return lessons, warnings


def load_all_lessons(
    individual_dir: str, group_dir: str, group_docx_cache_dir: str
) -> tuple[list[Lesson], ImportReport, list[ParseWarning]]:
    known_groups = known_groups_from_filenames(group_dir)
    individual_report = load_individual_lessons(individual_dir, known_groups=known_groups)
    group_lessons, group_warnings = load_group_lessons(group_dir, group_docx_cache_dir)
    all_lessons = list(individual_report.lessons) + group_lessons
    return all_lessons, individual_report, group_warnings
