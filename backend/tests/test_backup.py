"""Резервная копия настроек: кабинеты и пометки «это не накладка»."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import backup, cabinets, dismissed
from app import main as main_module


@pytest.fixture
def paths(tmp_path, monkeypatch):
    cab, dis = str(tmp_path / "config" / "cabinets.json"), str(tmp_path / "config" / "dismissed.json")
    monkeypatch.setattr(main_module, "CABINETS_PATH", cab)
    monkeypatch.setattr(main_module, "DISMISSED_PATH", dis)
    return cab, dis


def _seed(cab, dis):
    config = cabinets.load_config(cab)
    cabinets.add_room(config, "418")
    cabinets.add_room(config, "104")
    cabinets.save_config(cab, config)
    dismissed.dismiss(dis, "0123456789abcdef", "Иванов × Петров")


def test_roundtrip_restores_into_empty_install(paths, tmp_path):
    cab, dis = paths
    _seed(cab, dis)
    data = backup.build_backup(cab, dis, "0.3.0")
    assert data["app"] == "CafedraSchedule" and data["version"] == "0.3.0"

    new_cab, new_dis = str(tmp_path / "new" / "c.json"), str(tmp_path / "new" / "d.json")  # «новый компьютер»
    result = backup.restore_backup(json.loads(json.dumps(data)), new_cab, new_dis)

    assert result == {"rooms": 2, "marks": 1}
    assert cabinets.get_rooms(cabinets.load_config(new_cab)) == ["104", "418"]
    assert dismissed.load_dismissed(new_dis)["0123456789abcdef"]["label"] == "Иванов × Петров"


def test_restore_merges_and_never_deletes_current_data(paths):
    cab, dis = paths
    config = cabinets.load_config(cab)
    cabinets.add_room(config, "999")
    cabinets.save_config(cab, config)
    dismissed.dismiss(dis, "aaaaaaaaaaaaaaaa", "моя пометка")
    data = {
        "app": "CafedraSchedule", "format": 1,
        "cabinets": {"departments": {"default": {"rooms": ["999", "418"]}}},
        "dismissed": {"bbbbbbbbbbbbbbbb": {"label": "из копии", "at": "2026-10-01"}, "aaaaaaaaaaaaaaaa": {"label": "перезапись?"}},
    }

    result = backup.restore_backup(data, cab, dis)

    assert result == {"rooms": 1, "marks": 1}           # 999 уже был; пометка aaaa уже была
    assert cabinets.get_rooms(cabinets.load_config(cab)) == ["418", "999"]
    marks = dismissed.load_dismissed(dis)
    assert marks["aaaaaaaaaaaaaaaa"]["label"] == "моя пометка"   # текущее не перезаписывается
    assert "bbbbbbbbbbbbbbbb" in marks


def test_garbage_entries_are_skipped_and_foreign_files_rejected(paths):
    cab, dis = paths
    data = {
        "app": "CafedraSchedule", "format": 1,
        "cabinets": {"departments": {"default": {"rooms": ["ok", 5, None, "x" * 100, "  "]}, "bad": 7}},
        "dismissed": {"../../etc/passwd": {}, "short": {}, "cccccccccccccccc": "не словарь", "dddddddddddddddd": {"label": 5}},
    }
    result = backup.restore_backup(data, cab, dis)
    assert result == {"rooms": 1, "marks": 2}
    assert dismissed.load_dismissed(dis)["dddddddddddddddd"]["label"] == ""

    for bad in ({}, [], "строка", {"app": "другая"}, {"app": "CafedraSchedule", "format": 99}):
        with pytest.raises(backup.BackupError):
            backup.restore_backup(bad, cab, dis)


def test_download_and_restore_routes(paths):
    cab, dis = paths
    _seed(cab, dis)
    client = TestClient(main_module.app)

    resp = client.get("/backup/download")
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    saved = resp.content
    assert json.loads(saved)["cabinets"]["departments"]["default"]["rooms"]

    # на «чистой» установке — восстановление добавляет всё
    import os
    os.remove(cab); os.remove(dis)
    page = client.post("/backup/restore", files={"file": ("copy.json", saved, "application/json")}).text
    assert "Копия восстановлена: добавлено кабинетов — 2, пометок «это не накладка» — 1" in page
    assert cabinets.get_rooms(cabinets.load_config(cab)) == ["104", "418"]

    bad = client.post("/backup/restore", files={"file": ("x.json", b"not json", "application/json")}).text
    assert "не читается" in bad
    foreign = client.post("/backup/restore", files={"file": ("x.json", b'{"hello": 1}', "application/json")}).text
    assert "не копия настроек" in foreign
    huge = client.post("/backup/restore", files={"file": ("x.json", b" " * 2_100_000, "application/json")}).text
    assert "слишком большой" in huge
