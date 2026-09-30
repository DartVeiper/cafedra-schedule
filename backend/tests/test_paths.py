"""Расположение данных в собранном .exe: %LOCALAPPDATA%\\CafedraSchedule вместо
папки рядом с самим .exe (рабочий стол легко случайно снести целиком), плюс
разовый перенос уже накопленных data/ и config/ со старого места (см.
app/paths.py)."""
from __future__ import annotations

import sys

from app import paths


def test_appdata_base_dir_uses_localappdata_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert paths._appdata_base_dir() == str(tmp_path / "CafedraSchedule")


def test_appdata_base_dir_falls_back_to_exe_dir_without_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    exe_dir = tmp_path / "wherever"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "executable", str(exe_dir / "CafedraSchedule.exe"))

    assert paths._appdata_base_dir() == str(exe_dir)


def _make_legacy_layout(base) -> None:
    (base / "data" / "db").mkdir(parents=True)
    (base / "data" / "db" / "cafedra.sqlite3").write_text("old-db-content", encoding="utf-8")
    (base / "config").mkdir()
    (base / "config" / "cabinets.json").write_text('{"rooms": ["418"]}', encoding="utf-8")


def test_migrate_legacy_storage_moves_data_and_config(monkeypatch, tmp_path):
    legacy_base = tmp_path / "legacy"
    legacy_base.mkdir()
    _make_legacy_layout(legacy_base)
    appdata = tmp_path / "appdata"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(legacy_base / "CafedraSchedule.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))

    paths.migrate_legacy_storage()

    new_base = appdata / "CafedraSchedule"
    assert (new_base / "data" / "db" / "cafedra.sqlite3").read_text(encoding="utf-8") == "old-db-content"
    assert (new_base / "config" / "cabinets.json").exists()
    assert not (legacy_base / "data").exists()
    assert not (legacy_base / "config").exists()


def test_migrate_legacy_storage_does_not_overwrite_existing_new_data(monkeypatch, tmp_path):
    legacy_base = tmp_path / "legacy"
    legacy_base.mkdir()
    _make_legacy_layout(legacy_base)
    appdata = tmp_path / "appdata"
    new_base = appdata / "CafedraSchedule"
    (new_base / "data").mkdir(parents=True)
    (new_base / "data" / "marker.txt").write_text("already migrated", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(legacy_base / "CafedraSchedule.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))

    paths.migrate_legacy_storage()

    assert (legacy_base / "data").exists()  # не тронуто — в новом месте уже что-то есть
    assert (new_base / "data" / "marker.txt").exists()


def test_migrate_legacy_storage_is_noop_when_not_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    legacy_base = tmp_path / "legacy"
    legacy_base.mkdir()
    _make_legacy_layout(legacy_base)

    paths.migrate_legacy_storage()

    assert (legacy_base / "data").exists()  # ничего не переносим вне frozen-режима
