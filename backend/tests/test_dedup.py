"""Тесты на сведение дублей между листами/файлами Формата 1 — реальные кейсы
кафедры: 'Бланк расписания...xls' как скрытый дубль, и Топорова Е.П. с двумя
частично дублирующими друг друга листами книги."""
from __future__ import annotations

from app.models import PersonRole
from app.parsers.dedup import build_import


def test_blank_named_file_loses_even_with_equal_completeness(make_lesson, make_sheet_result):
    """Кейс 'Бланк расписания индивидуальных занятий.xls' vs 'Киселев А.Ф.
    ...xls': оба листа почти идентичны (>=80% совпадающих слотов), но файл с
    шаблонным именем 'Бланк...' должен проиграть нормально названному —
    независимо от того, у кого формально больше записей."""
    def build(source_file):
        return [
            make_lesson(day=0, start="08:30", student="Тоцкая Полина", group="94Ф", room="415", source_file=source_file),
            make_lesson(day=0, start="09:20", student="Тоцкая Полина", group="94Ф", room="415", source_file=source_file),
            make_lesson(day=1, start="08:30", student="Вьюшкова Анна", group="91Ф", room="415", source_file=source_file),
        ]

    blank_sheet = make_sheet_result(
        "Бланк расписания индивидуальных занятий.xls",
        build("Бланк расписания индивидуальных занятий.xls"),
        person_name="Киселев А.Ф.",
    )
    real_sheet = make_sheet_result(
        "Киселев А.Ф. 1 семестр.xls",
        build("Киселев А.Ф. 1 семестр.xls"),
        person_name="Киселев А.Ф.",
    )

    report = build_import([blank_sheet, real_sheet])

    assert len(report.lessons) == 3
    assert all(l.source.file_name == "Киселев А.Ф. 1 семестр.xls" for l in report.lessons)
    assert len(report.dropped_sheet_notes) == 1
    assert "Бланк расписания" in report.dropped_sheet_notes[0]
    assert "Киселев" in report.dropped_sheet_notes[0]


def test_unique_records_in_dropped_duplicate_are_reported_not_silently_lost(make_lesson, make_sheet_result):
    """Если у отброшенного (дублирующего) листа была запись, которой нет у
    победителя — не теряем её молча, а упоминаем в примечании для методиста."""
    shared = [
        make_lesson(day=0, start="08:30", student="Общий студент", group="91Ф"),
        make_lesson(day=0, start="09:20", student="Общий студент 2", group="91Ф"),
    ]
    only_in_blank = make_lesson(day=5, start="16:20", student="Лапенко Анна", group="93Ф", subject="доп.инструмент")

    blank_sheet = make_sheet_result("Бланк расписания.xls", shared + [only_in_blank], person_name="Киселев А.Ф.")
    real_sheet = make_sheet_result("Киселев А.Ф. 1 семестр.xls", shared, person_name="Киселев А.Ф.")

    report = build_import([blank_sheet, real_sheet])

    assert len(report.lessons) == 2  # уникальная запись из "Бланка" НЕ попала в итог
    assert "Лапенко Анна" in report.dropped_sheet_notes[0]
    assert "ВНИМАНИЕ" in report.dropped_sheet_notes[0]


def test_more_complete_sheet_wins_when_names_are_both_normal(make_lesson, make_sheet_result):
    """Кейс Топоровой Е.П.: Лист2 (черновик, сокращённые ФИО, без аудиторий,
    11 записей) и Лист3 (актуальный, полные ФИО, 33 записи) — оба нормально
    названы (не 'бланк'), выигрывает тот, где записи полнее/их больше."""
    draft = [
        make_lesson(day=3, start="08:30", student="Чебакова Е.", group="92ф", room=None, subject="конц. класс"),
        make_lesson(day=3, start="09:20", student="Турова В.", group="92ф", room="419", subject="конц. класс"),
    ]
    final = [
        make_lesson(day=3, start="08:30", student="Чебакова Екатерина", group="92ф", room="403",
                     subject="концертмейстерский класс"),
        make_lesson(day=3, start="09:20", student="Турова Виктория", group="92ф", room="419",
                     subject="концертмейстерский класс"),
        make_lesson(day=3, start="10:15", student="Сухойван Анна", group="93ф", room="418",
                     subject="концертмейстерский класс"),
    ]
    sheet2 = make_sheet_result("Топорова Е.П. 1 семестр.xls", draft, sheet_name="Лист2",
                                 role=PersonRole.ACCOMPANIST, person_name="Топорова Е. П.")
    sheet3 = make_sheet_result("Топорова Е.П. 1 семестр.xls", final, sheet_name="Лист3",
                                 role=PersonRole.ACCOMPANIST, person_name="Топорова Е. П.")

    report = build_import([sheet2, sheet3])

    assert len(report.lessons) == 3
    assert all(l.source.sheet_name == "Лист3" for l in report.lessons)


def test_single_sheet_per_person_passes_through_unchanged(make_lesson, make_sheet_result):
    lessons = [make_lesson(day=0, start="08:30"), make_lesson(day=0, start="09:20")]
    sheet = make_sheet_result("Ананьев А.А. 1 семестр.xls", lessons, person_name="Ананьев А.А.")

    report = build_import([sheet])

    assert report.lessons == lessons
    assert report.dropped_sheet_notes == []
    assert report.merge_notes == []


def test_low_overlap_sheets_both_survive_but_shared_slot_gets_deduped(make_lesson, make_sheet_result):
    """Если пересечение между листами низкое (< 80% слотов) — это не 'один
    файл дублирует другой целиком', оба листа считаются разными источниками
    и сохраняются, но если один и тот же слот (день/время/группа) всё же
    встретился в обоих — берём более полную запись."""
    shared_slot_incomplete = make_lesson(day=2, start="10:15", student="Общий", group="91Ф", room=None)
    shared_slot_complete = make_lesson(day=2, start="10:15", student="Общий", group="91Ф", room="216")

    sheet_a = make_sheet_result("Файл1.xls", [
        shared_slot_incomplete,
        make_lesson(day=0, start="08:30", student="Только в файле 1", group="91Ф"),
        make_lesson(day=0, start="09:20", student="Только в файле 1 бис", group="91Ф"),
    ])
    sheet_b = make_sheet_result("Файл2.xls", [
        shared_slot_complete,
        make_lesson(day=3, start="12:00", student="Только в файле 2", group="91Ф"),
        make_lesson(day=3, start="12:50", student="Только в файле 2 бис", group="91Ф"),
    ])

    report = build_import([sheet_a, sheet_b])

    assert report.dropped_sheet_notes == []  # никто не отброшен целиком
    assert len(report.lessons) == 5  # 3 + 3 - 1 задублированный слот
    assert len(report.merge_notes) == 1
    merged = next(l for l in report.lessons if l.day_of_week == 2 and l.student_name == "Общий")
    assert merged.room_raw == "216"  # выбрана более полная версия (с аудиторией)
