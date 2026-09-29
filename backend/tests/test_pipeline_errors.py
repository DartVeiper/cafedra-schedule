"""Один повреждённый/неподходящий файл не должен ронять весь импорт —
он пропускается, а причина попадает в failed_files."""
from __future__ import annotations

from app.pipeline import load_group_lessons, load_individual_lessons


def test_corrupt_individual_file_is_skipped_not_crashed(tmp_path):
    bad_file = tmp_path / "broken.xls"
    bad_file.write_bytes(b"this is not a real xls file, just some bytes")

    report = load_individual_lessons(str(tmp_path))

    assert report.lessons == []
    assert len(report.failed_files) == 1
    assert "broken.xls" in report.failed_files[0]


def test_one_bad_file_does_not_block_the_good_ones(tmp_path, make_lesson, monkeypatch):
    """Смешанная пачка: один битый файл + один нормальный — нормальный всё
    равно должен обработаться, битый просто уходит в failed_files."""
    import app.pipeline as pipeline_module

    (tmp_path / "broken.xls").write_bytes(b"garbage")
    (tmp_path / "good.xls").write_bytes(b"also not real, but we'll stub the parser")

    def fake_parse(path, known_groups=None):
        if "broken" in path:
            raise ValueError("повреждён")
        from app.models import PersonRole
        from app.parsers.individual import SheetParseResult
        return [SheetParseResult(
            file_name="good.xls", sheet_name="Лист1", role=PersonRole.TEACHER,
            person_name="Иванов И.И.", lessons=[make_lesson()], warnings=[], header_text="...",
        )]

    monkeypatch.setattr(pipeline_module, "parse_individual_workbook", fake_parse)

    report = load_individual_lessons(str(tmp_path))

    assert len(report.lessons) == 1
    assert len(report.failed_files) == 1
    assert "broken.xls" in report.failed_files[0]


def test_corrupt_group_docx_is_skipped_not_crashed(tmp_path):
    group_dir = tmp_path / "group"
    group_dir.mkdir()
    cache_dir = tmp_path / "cache"
    (group_dir / "broken.docx").write_bytes(b"not a real docx, just some bytes")

    lessons, warnings, failed = load_group_lessons(str(group_dir), str(cache_dir))

    assert lessons == []
    assert len(failed) == 1
    assert "broken.docx" in failed[0]


def test_corrupt_legacy_doc_is_skipped_not_crashed(tmp_path):
    """Реалистичный случай: методист загружает .doc, который на самом деле не
    документ Word (переименованный файл, битая закачка и т.п.). На практике
    Word довольно терпим — он "открывает" такой файл, молча заворачивая сырые
    байты в пустой .docx, вместо того чтобы упасть с ошибкой. Дальше это уже
    ловит сам парсер группового расписания: нет таблицы с расписанием —
    предупреждение, а не накладка/крэш. Главное — импорт не падает."""
    group_dir = tmp_path / "group"
    group_dir.mkdir()
    cache_dir = tmp_path / "cache"
    (group_dir / "broken.doc").write_bytes(b"not a real Word document at all")

    lessons, warnings, failed = load_group_lessons(str(group_dir), str(cache_dir))

    assert lessons == []
    assert not failed  # не "падение", а штатное предупреждение ниже
    assert any("не найдена таблица расписания" in w.label().lower() for w in warnings)
