"""Сведение результатов парсинга нескольких листов/файлов Формата 1 в единый список занятий.

Решения по методике (согласованы с методистом кафедры):
  1. Личность в файле определяется по шапке листа (Преподаватель/Концертмейстер),
     а не по имени файла.
  2. Если два листа/файла одного и того же человека почти дублируют друг друга
     (совпадают день/время/группа, отличаются только полнота ФИО студента или
     заполненность аудитории) — берём более полную запись и пишем это в отчёт
     о слиянии, конфликт по ним не создаём.
  3. Если один файл целиком дублирует уже загруженный (как "Бланк расписания...xls"
     дублирует "Киселев А.Ф. ...xls") — файл пропускается при импорте, в отчёте
     об импорте остаётся пояснение, что и почему пропущено.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.models import Lesson, ParseWarning, PersonRole
from app.parsers.individual import SheetParseResult

FULL_DUPLICATE_OVERLAP_THRESHOLD = 0.8  # доля совпавших слотов, начиная с которой лист считается дублем
_BLANK_FILENAME_RE = re.compile(r"бланк", re.IGNORECASE)


def _looks_like_blank_filename(file_name: str) -> bool:
    return bool(_BLANK_FILENAME_RE.search(file_name))


@dataclass
class ImportReport:
    lessons: list[Lesson] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    dropped_sheet_notes: list[str] = field(default_factory=list)
    merge_notes: list[str] = field(default_factory=list)
    skipped_sheet_notes: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)  # файл вообще не удалось прочитать


def build_import(sheet_results: list[SheetParseResult]) -> ImportReport:
    report = ImportReport()

    groups: dict[tuple[PersonRole, str], list[SheetParseResult]] = defaultdict(list)
    for sr in sheet_results:
        report.warnings.extend(sr.warnings)
        if sr.person_name is None:
            if sr.header_text is not None or sr.lessons:
                report.skipped_sheet_notes.append(
                    f"{sr.file_name} / {sr.sheet_name}: не определён преподаватель/концертмейстер — лист пропущен"
                )
            continue
        if not sr.lessons:
            report.skipped_sheet_notes.append(
                f"{sr.file_name} / {sr.sheet_name} ({sr.role.value}: {sr.person_name}): "
                "занятий не найдено — лист пуст, пропущен"
            )
            continue
        groups[(sr.role, sr.person_name)].append(sr)

    for (role, name), srs in groups.items():
        lessons, drop_notes, merge_notes = _resolve_person_sheets(role, name, srs)
        report.lessons.extend(lessons)
        report.dropped_sheet_notes.extend(drop_notes)
        report.merge_notes.extend(merge_notes)

    return report


def _slot_key(lesson: Lesson) -> tuple:
    return (lesson.day_of_week, lesson.start_minutes, lesson.group_normalized)


def _completeness_score(lesson: Lesson) -> tuple:
    return (
        1 if lesson.room_normalized else 0,
        len(lesson.subject or ""),
        len(lesson.student_name or ""),
    )


def _overlap_ratio(a: list[Lesson], b: list[Lesson]) -> float:
    keys_a = {_slot_key(l) for l in a}
    keys_b = {_slot_key(l) for l in b}
    if not keys_a or not keys_b:
        return 0.0
    smaller = min(len(keys_a), len(keys_b))
    return len(keys_a & keys_b) / smaller


def _resolve_person_sheets(
    role: PersonRole, name: str, srs: list[SheetParseResult]
) -> tuple[list[Lesson], list[str], list[str]]:
    drop_notes: list[str] = []
    merge_notes: list[str] = []

    if len(srs) == 1:
        return list(srs[0].lessons), drop_notes, merge_notes

    # Шаг 1: найти листы/файлы, целиком дублирующие другой лист/файл этого же человека.
    survivors = list(srs)
    dropped_ids: set[int] = set()
    for i in range(len(srs)):
        if id(srs[i]) in dropped_ids:
            continue
        for j in range(i + 1, len(srs)):
            if id(srs[j]) in dropped_ids:
                continue
            ratio = _overlap_ratio(srs[i].lessons, srs[j].lessons)
            if ratio < FULL_DUPLICATE_OVERLAP_THRESHOLD:
                continue

            i_blank = _looks_like_blank_filename(srs[i].file_name)
            j_blank = _looks_like_blank_filename(srs[j].file_name)
            if i_blank != j_blank:
                # Файл с шаблонным именем ("Бланк расписания...") всегда проигрывает
                # нормально названному файлу, даже если в нём формально больше строк —
                # так решил методист для случая "Бланк..." vs "Киселев А.Ф. ...xls".
                loser, winner = (srs[i], srs[j]) if i_blank else (srs[j], srs[i])
                reason = "имя файла похоже на неочищенный шаблон бланка"
            else:
                score_i = (len(srs[i].lessons), sum(sum(_completeness_score(l)) for l in srs[i].lessons))
                score_j = (len(srs[j].lessons), sum(sum(_completeness_score(l)) for l in srs[j].lessons))
                loser, winner = (srs[j], srs[i]) if score_j <= score_i else (srs[i], srs[j])
                reason = "у второго источника записи полнее (аудитория/ФИО указаны подробнее)"

            dropped_ids.add(id(loser))
            note = (
                f"{loser.file_name} / {loser.sheet_name} ({role.value}: {name}): "
                f"пропущен как дубликат {winner.file_name} / {winner.sheet_name} "
                f"(совпадение слотов {ratio:.0%}; {reason})"
            )

            winner_keys = {_slot_key(l) for l in winner.lessons}
            unique_to_loser = [l for l in loser.lessons if _slot_key(l) not in winner_keys]
            if unique_to_loser:
                details = "; ".join(
                    f"{l.student_name} гр.{l.group_raw} {l.subject!r} "
                    f"(день {l.day_of_week} {l.start_time.strftime('%H:%M')})"
                    for l in unique_to_loser
                )
                note += (
                    f" -- ВНИМАНИЕ: в отброшенном листе было {len(unique_to_loser)} "
                    f"записей, которых нет в оставленном источнике — они НЕ попали "
                    f"в итоговые данные, проверьте вручную: {details}"
                )
            drop_notes.append(note)

    survivors = [sr for sr in survivors if id(sr) not in dropped_ids]

    # Шаг 2: среди оставшихся листов слить почти-дубли занятий по ключу (день, время, группа),
    # оставляя наиболее полную запись.
    candidates: dict[tuple, list[Lesson]] = defaultdict(list)
    for sr in survivors:
        for lesson in sr.lessons:
            candidates[_slot_key(lesson)].append(lesson)

    final_lessons: list[Lesson] = []
    for key, options in candidates.items():
        if len(options) == 1:
            final_lessons.append(options[0])
            continue
        best = max(options, key=_completeness_score)
        others = [o for o in options if o is not best]
        sources = ", ".join(o.source.label() for o in options)
        merge_notes.append(
            f"{role.value.capitalize()} {name}: слот "
            f"(день {best.day_of_week}, {best.start_time.strftime('%H:%M')}, группа {best.group_raw}) "
            f"встретился в нескольких источниках ({sources}) — оставлена наиболее полная запись "
            f"из {best.source.label()}"
        )
        final_lessons.append(best)

    return final_lessons, drop_notes, merge_notes
