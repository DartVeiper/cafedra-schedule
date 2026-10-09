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
from app import subjects, timegrid
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
                "subject": l.subject, "group": l.group_raw, "group_norm": l.group_normalized, "student": None, "accompanist": None,
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
                "student": l.student_name, "group": l.group_raw, "group_norm": l.group_normalized, "subject": l.subject,
            })
    return entries


def short_student(name: str | None) -> str:
    """'Авдеева Виктория' -> 'Авдеева В.'; уже сокращённое ('Витовтова Ю.') и одно слово не меняем."""
    if not name:
        return ""
    tokens = name.replace("ё", "е").replace("Ё", "Е").split()
    if len(tokens) < 2 or "-" in name or "," in name:
        return name.strip()
    given = tokens[1].strip(".")
    return f"{tokens[0]} {given[0].upper()}." if given else tokens[0]


def short_person(name: str | None) -> str:
    """Преподаватель: без звания; полное ФИО -> 'Фамилия И.О.'; 'Фамилия И.О.' остаётся как есть."""
    if not name:
        return ""
    name = strip_academic_title(name)
    tokens = name.split()
    if len(tokens) < 2 or tokens[1].endswith("."):
        return name
    return tokens[0] + " " + "".join(t[0].upper() + "." for t in tokens[1:3])


def entry_lines(e: dict, brief: bool = False) -> list[str]:
    """Строки текста записи. Первая строка — главное лицо (в Word выделяется жирным).

    brief=True — «кратко», как пишут в ручной раскладке: студент «Фамилия И.», группа в чистом виде
    («94Ф»), предмет коротким названием из словаря (subjects.py), концертмейстер «Фамилия И.О. (конц.)»."""
    subject = (subjects.short(e["subject"]) if brief else e["subject"]) or ""
    if e["kind"] == "group":
        if not e["first"]:
            return ["↑ пара" if brief else "↑ пара продолжается"]
        group = (e.get("group_norm") or e["group"] or "") if brief else (e["group"] or "")
        teacher = short_person(e["teacher"]) if brief else (strip_academic_title(e["teacher"]) if e["teacher"] else "")
        return [f"ПАРА {group}".strip(), subject, teacher]
    conc = "(конц.)" if brief else "(концертмейстер)"
    name = short_person if brief else (lambda n: strip_academic_title(n) if n else "")
    main = e["teacher"] or e["accompanist"]
    lines = [name(main) + ("" if e["teacher"] else f" {conc}") if main else "—"]
    student = short_student(e["student"]) if brief else (e["student"] or "")
    group = (e.get("group_norm") or e["group"]) if brief else e["group"]
    lines.append(f"{student} {group}" if brief and group else f"{student} · {group}" if group else student)
    if subject:
        lines.append(subject)
    if e["teacher"] and e["accompanist"]:
        lines.append(f"{name(e['accompanist'])} {conc}")
    return [x for x in lines if x]


def build_layout(
    lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None = None, days: list[int] | None = None,
    compact: bool = True,
) -> list[dict]:
    """[{day, name, slots:[{start, special}], rooms:[...], rows:[{start, special, cells:[{state, entries}]}]}]
    по каждому дню, где есть сетка. state: "free" | "busy" | "clash" | "special"."""
    grids = timegrid.build_day_grids(lessons)
    by_room_day: dict[tuple[str, int], list[Lesson]] = {}
    for l in lessons:
        if l.room_normalized in rooms:
            by_room_day.setdefault((l.room_normalized, l.day_of_week), []).append(l)

    result = []
    for day in sorted(grids):
        if days is not None and day not in days:
            continue
        starts = list(grids[day].slots)
        specials = {}
        for sp in special_slots or []:
            m = _to_minutes(sp["start"])
            if sp["day"] == day and m not in starts:
                specials[m] = sp["subject"].capitalize()
        starts = sorted(starts + list(specials))
        # Как в ручной раскладке: набор столбцов меняется по дням — показываем только кабинеты, где в этот день
        # есть занятия (иначе половина столбцов пустая, а текст в остальных мелко и тесно переносится).
        day_rooms = [r for r in rooms if (r, day) in by_room_day] if compact else list(rooms)
        if not day_rooms:
            day_rooms = list(rooms)
        rows = []
        for start in starts:
            end = start + INDIVIDUAL_LESSON_MINUTES
            cells = []
            for room in day_rooms:
                if start in specials:
                    cells.append({"state": "special", "entries": []})
                    continue
                here = [l for l in by_room_day.get((room, day), []) if _overlaps(start, end, l)]
                entries = _merge_cell(here, start)
                state = "free" if not entries else ("clash" if len(entries) > 1 else "busy")
                cells.append({"state": state, "entries": entries})
            rows.append({"start": timegrid.fmt_minutes(start), "special": specials.get(start), "cells": cells})
        result.append({"day": day, "name": DAY_NAMES_RU[day], "rooms": day_rooms, "rows": rows})
    return result


def cell_paragraphs(cell: dict, brief: bool = False) -> list[tuple[str, bool, bool]]:
    """Абзацы ячейки: (текст, жирный, тревожный цвет). Запись — строки entry_lines, между записями
    «— — —», накладка помечена первой строкой."""
    out: list[tuple[str, bool, bool]] = []
    if cell["state"] == "clash":
        out.append(("⚠ НАКЛАДКА", True, True))
    for k, e in enumerate(cell["entries"]):
        if k:
            out.append(("— — —", False, False))
        out.extend((line, i == 0, False) for i, line in enumerate(entry_lines(e, brief)))
    return out


def room_title(room: str, labels: dict | None) -> str:
    """Заголовок столбца: '423' -> 'Малый зал (423)', если для кабинета задана подпись."""
    label = (labels or {}).get(room)
    return f"{label} ({room})" if label else room


def _cell_text(cell: dict, brief: bool = False) -> str:
    if cell["state"] == "special":
        return ""
    blocks = ["\n".join(entry_lines(e, brief)) for e in cell["entries"]]
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


def build_xlsx(
    lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None, title: str,
    days: list[int] | None = None, compact: bool = True, brief: bool = False, room_labels: dict | None = None,
) -> bytes:
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

    for d in build_layout(lessons, rooms, special_slots, days, compact):
        ws = wb.create_sheet(d["name"])
        ws.cell(1, 1, f"{title} — {d['name']}").font = Font(bold=True, size=13)
        ws.cell(2, 1, "Время").font = Font(bold=True)
        for j, room in enumerate(d["rooms"], start=2):
            c = ws.cell(2, j, room_title(room, room_labels))
            c.font, c.fill, c.alignment = Font(bold=True), head, Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(j)].width = 24
        ws.cell(2, 1).fill = head
        ws.column_dimensions["A"].width = 16
        for i, row in enumerate(d["rows"], start=3):
            ws.cell(i, 1, row["start"] + (f"\n{row['special']}" if row["special"] else "")).alignment = wrap
            for j, cell in enumerate(row["cells"], start=2):
                text = _cell_text(cell, brief)
                c = ws.cell(i, j, text)
                c.alignment = wrap
                if cell["state"] == "clash":
                    c.fill = red
                elif cell["state"] == "special":
                    c.fill = grey
            # Высоту строк с текстом НЕ задаём: Excel сам подгоняет её под перенос длинных слов по ширине
            # столбца (ручной расчёт по числу строк обрезал нижние строки в ячейках). Пустым слотам даём
            # нормальную минимальную высоту, чтобы они выглядели «коробочками», а не линиями.
            if all(not _cell_text(c, brief) for c in row["cells"]):
                ws.row_dimensions[i].height = 30
        ws.freeze_panes = "B3"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0   # по ширине — на страницу, по высоте — сколько понадобится
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


MAX_COLUMNS_PER_TABLE = 12   # шире — таблица становится мелкой кашей; делим на две части (как две страницы ручной раскладки)


def split_columns(rooms: list[str], limit: int = MAX_COLUMNS_PER_TABLE) -> list[list[str]]:
    """Кабинеты дня -> группы не шире limit столбцов, поровну (14 -> 7+7, а не 12+2)."""
    if len(rooms) <= limit:
        return [list(rooms)]
    parts = -(-len(rooms) // limit)
    size = -(-len(rooms) // parts)
    return [list(rooms[i:i + size]) for i in range(0, len(rooms), size)]


def build_docx(
    lessons: list[Lesson], rooms: list[str], special_slots: list[dict] | None, title: str,
    days: list[int] | None = None, compact: bool = True, brief: bool = False, room_labels: dict | None = None,
) -> bytes:
    """Word: альбомная страница, на каждый день — своя таблица (время × кабинеты), как в ручной раскладке.

    Оформление рассчитано на любое число кабинетов (от 1 до 15+): ширина столбца кабинета
    ограничена сверху (иначе при 1–3 кабинетах таблица растягивалась на всю страницу), у каждой
    строки времени есть минимальная высота (иначе пустые слоты схлопывались в тонкие линии),
    шрифт крупнее, когда кабинетов мало."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE
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
    normal.font.size = Pt(8)

    time_col_cm = 2.2
    usable_cm = 29.7 - 2.0 - time_col_cm
    row_cm = 1.35                                      # минимальная высота строки времени (пустые слоты — «коробочки»)

    def sizes(n_rooms: int) -> tuple[float, float]:
        """(ширина столбца кабинета, шрифт) для таблицы с n кабинетами."""
        col = min(4.6, usable_cm / max(1, n_rooms))     # не растягиваем 1–3 кабинета на всю страницу
        return col, (8.5 if col >= 3.6 else 7.5 if col >= 2.4 else 6.5)

    def shade(cell, hex_fill: str) -> None:
        # В схеме Word свойства ячейки идут строго по порядку (… shd, noWrap, tcMar, …, vAlign), иначе
        # строгий Word может счесть файл повреждённым — вставляем заливку ПЕРЕД выравниванием и т.п.
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        later = [qn(f"w:{t}") for t in ("noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark")]
        for child in tcPr:
            if child.tag in later:
                child.addprevious(shd)
                return
        tcPr.append(shd)

    def set_cell_margins(table) -> None:
        tblPr = table._tbl.tblPr
        mar = OxmlElement("w:tblCellMar")
        for side, twips in (("top", 40), ("left", 80), ("bottom", 40), ("right", 80)):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(twips))
            el.set(qn("w:type"), "dxa")
            mar.append(el)
        tblPr.append(mar)

    def write(cell, paragraphs: list[tuple[str, bool, bool]]) -> None:
        cell.text = ""
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        for i, (text, bold, alarm) in enumerate(paragraphs):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            run = p.add_run(text)
            run.font.size = Pt(font_pt[0])
            run.bold = bold
            if alarm:
                run.font.color.rgb = RGBColor(0xB0, 0x20, 0x2A)

    font_pt = [8.0]          # меняется для каждого дня (см. ниже) — write() читает текущее значение
    layout = build_layout(lessons, rooms, special_slots, days, compact)
    if not layout:
        doc.add_paragraph("Нет данных для раскладки — не найдено индивидуальных занятий.")
    tables_done = 0
    for d in layout:
        for part, chunk in enumerate(split_columns(d["rooms"])):
            if tables_done:
                doc.add_page_break()
            tables_done += 1
            h = doc.add_paragraph()
            suffix = f" (кабинеты {chunk[0]}–{chunk[-1]})" if len(d["rooms"]) > len(chunk) else ""
            r = h.add_run(f"{title} — {d['name']}{suffix}")
            r.bold = True
            r.font.size = Pt(13)
            col_cm, font_pt[0] = sizes(len(chunk))
            idx = [d["rooms"].index(room) for room in chunk]
            table = doc.add_table(rows=1, cols=1 + len(chunk))
            table.style = "Table Grid"
            table.autofit = False
            set_cell_margins(table)
            hdr = table.rows[0].cells
            write(hdr[0], [("Часы", True, False)])
            shade(hdr[0], "DDE3F5")
            for j, room in enumerate(chunk, start=1):
                write(hdr[j], [(room_title(room, room_labels), True, False)])
                shade(hdr[j], "DDE3F5")
            trPr = table.rows[0]._tr.get_or_add_trPr()   # шапка повторяется на каждой странице
            flag = OxmlElement("w:tblHeader")
            flag.set(qn("w:val"), "true")
            trPr.append(flag)
            for row in d["rows"]:
                tr = table.add_row()
                tr.height, tr.height_rule = Cm(row_cm), WD_ROW_HEIGHT_RULE.AT_LEAST
                cant = OxmlElement("w:cantSplit")        # строка целиком на одной странице
                cant.set(qn("w:val"), "true")
                tr._tr.get_or_add_trPr().append(cant)
                cells = tr.cells
                write(cells[0], [(row["start"], True, False)] + ([(row["special"], False, False)] if row["special"] else []))
                for j, k in enumerate(idx, start=1):
                    cell = row["cells"][k]
                    cells[j].vertical_alignment = WD_ALIGN_VERTICAL.TOP
                    if cell["state"] == "special":
                        shade(cells[j], "E9ECEF")
                        continue
                    if not cell["entries"]:
                        continue
                    if cell["state"] == "clash":
                        shade(cells[j], "F8D7DA")
                    write(cells[j], cell_paragraphs(cell, brief))
            for row in table.rows:
                row.cells[0].width = Cm(time_col_cm)
                for c in row.cells[1:]:
                    c.width = Cm(col_cm)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
