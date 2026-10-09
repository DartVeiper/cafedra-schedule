"""Установка обновления в фоне с видимым прогрессом (страница «Обновляем программу…»)."""
from __future__ import annotations

import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import update_job


@pytest.fixture(autouse=True)
def _clean_job():
    update_job.reset()
    yield
    update_job.reset()


def _wait_for(state: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = update_job.snapshot()
        if snap["state"] == state:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"не дождались состояния {state}: {update_job.snapshot()}")


def test_job_goes_downloading_to_installing_and_schedules_exit(monkeypatch):
    exits = []

    def fake_start_update(url, expected_size=None, progress=None, **kw):
        progress(100, 400)
        progress(400, 400)

    monkeypatch.setattr(update_job.self_update, "start_update", fake_start_update)
    monkeypatch.setattr(update_job.self_update, "schedule_exit", lambda delay_seconds=1.5: exits.append(delay_seconds))

    assert update_job.start("https://x/a.exe", "v9.9.9", expected_size=400) is True
    snap = _wait_for("installing")

    assert (snap["done"], snap["total"], snap["version"]) == (400, 400, "v9.9.9")
    assert exits == [4.0]            # странице оставляем время увидеть этап «устанавливаем»


def test_second_start_while_running_is_ignored(monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr(update_job.self_update, "start_update", lambda *a, **k: gate.wait(2))
    monkeypatch.setattr(update_job.self_update, "schedule_exit", lambda delay_seconds=1.5: None)

    assert update_job.start("https://x/a.exe", "v1") is True
    assert update_job.start("https://x/a.exe", "v1") is False
    gate.set()
    _wait_for("installing")


@pytest.mark.parametrize("error, expected", [
    (urllib.error.URLError("handshake"), "нет связи с GitHub"),
    (ValueError("файл скачался не полностью"), "повреждён или неполный"),
    (PermissionError("denied"), "Нет прав записать файл"),
    (RuntimeError("boom"), "Не удалось подготовить обновление"),
])
def test_errors_become_friendly_messages(monkeypatch, error, expected):
    def failing(*a, **k):
        raise error

    monkeypatch.setattr(update_job.self_update, "start_update", failing)
    update_job.start("https://x/a.exe", "v1")

    snap = _wait_for("error")
    assert expected in snap["message"] and type(error).__name__ in snap["message"]
    assert update_job.start("https://x/a.exe", "v1") is True     # после ошибки можно попробовать снова


def test_routes_show_progress_page_and_status(monkeypatch):
    info = {"version": "v9.9.9", "url": "https://github.com/x/y/releases/tag/v9.9.9",
            "download_url": "https://x/a.exe", "size": 400, "notes": ""}
    monkeypatch.setattr(main_module, "check_for_update", lambda force=False: info)
    monkeypatch.setattr(main_module.self_update, "can_self_update", lambda: True)
    monkeypatch.setattr(update_job.self_update, "start_update", lambda url, expected_size=None, progress=None, **k: progress(200, 400))
    monkeypatch.setattr(update_job.self_update, "schedule_exit", lambda delay_seconds=1.5: None)
    client = TestClient(main_module.app)

    assert client.get("/api/update/status").json()["state"] == "idle"
    page = client.post("/update/apply").text           # страница открывается сразу, не дожидаясь скачивания

    assert "Обновляем программу до версии v9.9.9" in page and 'id="upd-bar"' in page and "/api/update/status" in page
    _wait_for("installing")
    status = client.get("/api/update/status").json()
    assert status["state"] == "installing" and status["done"] == 200 and status["total"] == 400
