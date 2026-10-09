"""Раскладка расписания по кабинетам целиком — в Word и Excel, в том виде, к которому
привыкли на кафедре: на каждый день своя таблица, строки — время занятий, столбцы —
кабинеты, в ячейке «преподаватель / студент / предмет» и концертмейстер в скобках
(как в «Раскладке 1 семестр …»). Плюс плоский список всех занятий в Excel — для
фильтров и поиска.

Данные те же, что на экране «Свободные кабинеты» (cabinets.free_rooms_day): сетка
времени у каждого дня своя, кураторский час стоит отдельной серой строкой.
"""
from __future__ import annotations

import io

from app import conflicts as C
from app import timegrid
from app.cabinets import _to_minutes
from app.models import DAY_NAMES_RU, INDIVIDUAL_LESSON_MINUTES, Lesson, LessonType
from app.parsers.common import strip_academic_title


def _overlaps(a_start: int, a_end: int, l: Lesson) -> bool:
    return a_start < l.end_minutes and l.start_minutes < a_end


def _merge_cell(here: list[Lesson], slot_start: int) -> list[dict]:
    """Занятия одного кабинета в одном слоте -> записи для ячейки. Преподаватель и концертмейстер
    у одного студента — одна запись (как в ручной раскладке), а не две."""
    entries: list[dict] = []
    for l in sorted(here, key=lambda x: (x.start_minutes, x.lesson_type.value, x.teacher_name or "", x.accompanist_name or "")):
        if l.lesson_type == LessonType.GROUP:
            entries.append({
                "kind": "group", "first": l.start_minutes >= slot_start, "teacher": l.teacher_name,
                "subject": l.subject, "group": l.group_raw, "student": None, "accompanist": None,
            })
            continue
        for e in entries:
            if e["kind"] == "ind" and e["start"] == l.start_minutes and C._names_similar(e["student_key"], C._student_key(l)):
                if l.teacher_name and not e["teacher"]:
                    e["teacher"] = l.teacher_name
                if l.accompanist_name and not e["accompanist"]:
                    e["accompanist"] = l.accompanist_name
                e["subject"] = e["subject"] or l.subject
                break
        else:
            entries.append({
                "kind": "ind", "start": l.start_minutes, "student_key": C._student_key(l),
                "teacher": l.teacher_name, "accompanist": l.accompanist_name,
                "student": l.student_name, "group": l.group_raw, "subject": l.subject,
            })
    return entries


def entry_lines(e: dict) -> list[str]:
    """Строки текста записи. Первая строка — главное лицо (в Word выделяется жирным)."""
    if e["kind"] == "group":
        if not e["first"]:
            return ["↑ пара продолжается"]
        return [f"ПАРА {e['group'] or ''}".strip(), e["subject"] or "", strip_academic_title(e["teacher"]) if e["teacher"] else ""]
    main = e["teacher"] or e["accompanist"]
    lines = [strip_academic_title(main) + ("" if e["teacher"] else " (концертмейстер)") if main else "—"]
    student = e["student"] or ""
    lines.append(f"{student} · {e['group']}" if e["group"] else student)
    if e["subject"]:
        lines.append(e["subject"])
    if e["teacher"] and e["accompanist"]:
        lines.append(f"{strip_academic_title(e['accompanist'])} (концертмейстер)")
    return [x for x in lines if x]


def build_layout(lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None = None) -> list[dict]:
    """[{day, name, slots:[{start, special}], rooms:[...], rows:[{start, special, cells:[{state, entries}]}]}]
    по каждому дню, где есть сетка. state: "free" | "busy" | "clash" | "special"."""
    grids = timegrid.build_day_grids(lessons)
    by_room_day: dict[tuple[str, int], list[Lesson]] = {}
    for l in lessons:
        if l.room_normalized in rooms:
            by_room_day.setdefault((l.room_normalized, l.day_of_week), []).append(l)

    days = []
    for day in sorted(grids):
        starts = list(grids[day].slots)
        specials = {}
        for sp in special_slots or []:
            m = _to_minutes(sp["start"])
            if sp["day"] == day and m not in starts:
                specials[m] = sp["subject"].capitalize()
        starts = sorted(starts + list(specials))
        rows = []
        for start in starts:
            end = start + INDIVIDUAL_LESSON_MINUTES
            cells = []
            for room in rooms:
                if start in specials:
                    cells.append({"state": "special", "entries": []})
                    continue
                here = [l for l in by_room_day.get((room, day), []) if _overlaps(start, end, l)]
                entries = _merge_cell(here, start)
                state = "free" if not entries else ("clash" if len(entries) > 1 else "busy")
                cells.append({"state": state, "entries": entries})
            rows.append({"start": timegrid.fmt_minutes(start), "special": specials.get(start), "cells": cells})
        days.append({"day": day, "name": DAY_NAMES_RU[day], "rooms": rooms, "rows": rows})
    return days


def cell_paragraphs(cell: dict) -> list[tuple[str, bool, bool]]:
    """Абзацы ячейки: (текст, жирный, тревожный цвет). Запись — строки entry_lines, между записями
    «— — —», накладка помечена первой строкой."""
    out: list[tuple[str, bool, bool]] = []
    if cell["state"] == "clash":
        out.append(("⚠ НАКЛАДКА", True, True))
    for k, e in enumerate(cell["entries"]):
        if k:
            out.append(("— — —", False, False))
        out.extend((line, i == 0, False) for i, line in enumerate(entry_lines(e)))
    return out


def _cell_text(cell: dict) -> str:
    if cell["state"] == "special":
        return ""
    blocks = ["\n".join(entry_lines(e)) for e in cell["entries"]]
    text = "\n— — —\n".join(blocks)
    return ("⚠ НАКЛАДКА\n" + text) if cell["state"] == "clash" else text


def _flat_rows(lessons: list[Lesson]) -> list[list]:
    rows = []
    for l in sorted(lessons, key=lambda x: (x.day_of_week, x.start_minutes, x.room_normalized or "", x.teacher_name or x.accompanist_name or "")):
        rows.append([
            DAY_NAMES_RU[l.day_of_week], timegrid.fmt_minutes(l.start_minutes), timegrid.fmt_minutes(l.end_minutes),
            l.room_raw or "", "групповое" if l.lesson_type == LessonType.GROUP else "индивидуальное",
            strip_academic_title(l.teacher_name) if l.teacher_name else "",
            strip_academic_title(l.accompanist_name) if l.accompanist_name else "",
            l.student_name or "", l.group_raw or "", l.subject or "", l.source.label(),
        ])
    return rows


FLAT_HEADERS = ["День", "Начало", "Конец", "Кабинет", "Тип", "Преподаватель", "Концертмейстер",
                "Студент", "Группа", "Предмет", "Источник (файл)"]


def build_xlsx(lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None, title: str) -> bytes:
    """Книга Excel: лист на каждый день (раскладка по кабинетам) + лист «Все занятия» (список с фильтрами)."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    red = PatternFill("solid", fgColor="FFF8D7DA")
    grey = PatternFill("solid", fgColor="FFE9ECEF")
    head = PatternFill("solid", fgColor="FFDDE3F5")
    wrap = Alignment(wrap_text=True, vertical="top")

    for d in build_layout(lessons, rooms, special_slots):
        ws = wb.create_sheet(d["name"])
        ws.cell(1, 1, f"{title} — {d['name']}").font = Font(bold=True, size=13)
        ws.cell(2, 1, "Время").font = Font(bold=True)
        for j, room in enumerate(d["rooms"], start=2):
            c = ws.cell(2, j, room)
            c.font, c.fill, c.alignment = Font(bold=True), head, Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(j)].width = 24
        ws.cell(2, 1).fill = head
        ws.column_dimensions["A"].width = 16
        for i, row in enumerate(d["rows"], start=3):
            ws.cell(i, 1, row["start"] + (f"\n{row['special']}" if row["special"] else "")).alignment = wrap
            max_lines = 1
            for j, cell in enumerate(row["cells"], start=2):
                text = _cell_text(cell)
                c = ws.cell(i, j, text)
                c.alignment = wrap
                if cell["state"] == "clash":
                    c.fill = red
                elif cell["state"] == "special":
                    c.fill = grey
                max_lines = max(max_lines, text.count("\n") + 1)
            ws.row_dimensions[i].height = max(18, 13 * max_lines)
        ws.freeze_panes = "B3"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)

    flat = wb.create_sheet("Все занятия")
    flat.append(FLAT_HEADERS)
    for c in flat[1]:
        c.font, c.fill = Font(bold=True), head
    for row in _flat_rows(lessons):
        flat.append(row)
    for j, w in enumerate([13, 8, 8, 18, 14, 22, 22, 26, 10, 34, 46], start=1):
        flat.column_dimensions[get_column_letter(j)].width = w
    flat.freeze_panes = "A2"
    flat.auto_filter.ref = flat.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_docx(lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None, title: str) -> bytes:
    """Word: альбомная страница, на каждый день — своя таблица (время × кабинеты), как в ручной раскладке."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(1.0))
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(7)

    def shade(cell, hex_fill: str) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        tcPr.append(shd)

    def write(cell, lines: list[str], bold_first: bool = True) -> None:
        cell.text = ""
        first = True
        for i, line in enumerate(lines):
            p = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            run = p.add_run(line)
            run.font.size = Pt(7)
            run.bold = bold_first and i == 0

    layout = build_layout(lessons, rooms, special_slots)
    if not layout:
        doc.add_paragraph("Нет данных для раскладки — не найдено индивидуальных занятий.")
    usable_cm = 29.7 - 2.0 - 2.0
    for n, d in enumerate(layout):
        if n:
            doc.add_page_break()
        h = doc.add_paragraph()
        r = h.add_run(f"{title} — {d['name']}")
        r.bold = True
        r.font.size = Pt(12)
        table = doc.add_table(rows=1, cols=1 + len(d["rooms"]))
        table.style = "Table Grid"
        table.autofit = False
        col_w = Cm(usable_cm / max(1, len(d["rooms"])))
        hdr = table.rows[0].cells
        write(hdr[0], ["Часы"])
        shade(hdr[0], "DDE3F5")
        for j, room in enumerate(d["rooms"], start=1):
            write(hdr[j], [room])
            shade(hdr[j], "DDE3F5")
        trPr = table.rows[0]._tr.get_or_add_trPr()   # шапка повторяется на каждой странице
        flag = OxmlElement("w:tblHeader")
        flag.set(qn("w:val"), "true")
        trPr.append(flag)
        for row in d["rows"]:
            cells = table.add_row().cells
            write(cells[0], [row["start"]] + ([row["special"]] if row["special"] else []))
            for j, cell in enumerate(row["cells"], start=1):
                if cell["state"] == "special":
                    shade(cells[j], "E9ECEF")
                    continue
                if not cell["entries"]:
                    continue
                if cell["state"] == "clash":
                    shade(cells[j], "F8D7DA")
                paragraphs = cell_paragraphs(cell)
                cells[j].text = ""
                for i, (text, bold, alarm) in enumerate(paragraphs):
                    p = cells[j].paragraphs[0] if i == 0 else cells[j].add_paragraph()
                    p.paragraph_format.space_after = Pt(0)
                    run = p.add_run(text)
                    run.font.size = Pt(7)
                    run.bold = bold
                    if alarm:
                        run.font.color.rgb = RGBColor(0xB0, 0x20, 0x2A)
        for row in table.rows:
            row.cells[0].width = Cm(2.0)
            for c in row.cells[1:]:
                c.width = col_w
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
