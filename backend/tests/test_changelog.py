"""«Что нового»: у текущей версии должна быть запись (иначе после релиза у людей в
окне не будет описания), а текст релиза с GitHub не должен позволять подмешать HTML."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import changelog, update_check
from app import main as main_module
from app.mdlite import render_markdown_lite
from app.update_check import _parse_version
from app.version import APP_VERSION


def test_current_version_has_changelog_entry():
    versions = [e["version"] for e in changelog.CHANGELOG]
    assert any(_parse_version(v) == _parse_version(APP_VERSION) for v in versions), (
        f"Для версии {APP_VERSION} нет записи в app/changelog.py — добавьте её перед релизом"
    )


def test_changelog_entries_are_well_formed_and_unique():
    versions = [e["version"] for e in changelog.CHANGELOG]
    assert len(versions) == len(set(versions))
    for e in changelog.CHANGELOG:
        assert e["sections"], e["version"]
        for title, items in e["sections"]:
            assert title and items and all(isinstance(i, str) and i for i in items)


def test_entries_for_display_are_newest_first_with_flags():
    entries = changelog.entries_for_display()
    parsed = [_parse_version(e["version"]) for e in entries]
    assert parsed == sorted(parsed, reverse=True)
    assert sum(1 for e in entries if e["installed"]) == 1


def test_markdown_lite_renders_lists_bold_and_escapes_html():
    html = str(render_markdown_lite("Что нового:\n\n- **Кабинеты** и сетка\n- <script>alert(1)</script>\n\nКонец"))

    assert "<ul><li><b>Кабинеты</b> и сетка</li>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<p>Конец</p>" in html


def test_whats_new_button_and_dialog_on_every_page(monkeypatch):
    monkeypatch.setattr(update_check, "_cache", {"checked_at": 0.0, "result": None})
    monkeypatch.setattr(main_module, "check_for_update", lambda force=False: None)
    page = TestClient(main_module.app).get("/").text

    assert 'id="whatsnew-btn"' in page and 'id="whatsnew"' in page
    assert f"Версия {APP_VERSION}" in page and "установлена" in page


def test_update_banner_shows_release_notes_and_dialog_has_them(monkeypatch):
    info = {
        "version": "v9.9.9", "url": "https://github.com/x/y/releases/tag/v9.9.9",
        "download_url": "https://x/CafedraSchedule.exe", "size": 10,
        "notes": "Что нового:\n- новая **кнопка**",
    }
    monkeypatch.setattr(update_check, "_cache", {"checked_at": 0.0, "result": info})
    monkeypatch.setattr(main_module, "check_for_update", lambda force=False: info)
    monkeypatch.setattr(main_module.self_update, "can_self_update", lambda: True)
    page = TestClient(main_module.app).get("/").text

    assert "v9.9.9" in page and "новая <b>кнопка</b>" in page
    assert 'action="/update/apply"' in page and "Скачать и установить" in page
    assert 'id="wn-update"' in page  # то же описание — в окне «Что нового»


def test_release_notes_are_rendered_from_the_changelog_entry():
    text = changelog.release_notes_markdown("v0.3.0")

    assert text.startswith("Что нового с v0.2.0:")
    assert "- Фильтры отчёта по дню недели и по кабинету." in text
    assert "\nИсправлено:\n" in text and "- Опечатка в фамилии студента" in text
    assert "«Скачать и установить»" in text and "CafedraSchedule.exe" in text   # подвал: как обновиться / установить


def test_release_notes_for_unknown_version_is_an_error():
    import pytest
    with pytest.raises(KeyError):
        changelog.release_notes_markdown("v9.9.9")


def test_release_script_checks_tag_against_version(monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"

    ok = subprocess.run([sys.executable, str(script), f"v{APP_VERSION}"], capture_output=True, encoding="utf-8")
    assert ok.returncode == 0 and ok.stdout.startswith("Что нового")

    bad = subprocess.run([sys.executable, str(script), "v9.9.9"], capture_output=True, encoding="utf-8")
    assert bad.returncode == 1 and "не совпадает с APP_VERSION" in bad.stderr


def test_api_version_and_update_progress_page(monkeypatch):
    info = {"version": "v9.9.9", "url": "https://github.com/x/y/releases/tag/v9.9.9",
            "download_url": "https://x/CafedraSchedule.exe", "size": 10, "notes": ""}
    monkeypatch.setattr(main_module, "check_for_update", lambda force=False: info)
    monkeypatch.setattr(main_module.self_update, "can_self_update", lambda: True)
    monkeypatch.setattr(main_module.self_update, "start_update", lambda url, expected_size=None: None)
    monkeypatch.setattr(main_module.self_update, "schedule_exit", lambda: None)
    client = TestClient(main_module.app)

    assert client.get("/api/version").json() == {"version": APP_VERSION}

    page = client.post("/update/apply").text
    assert "Устанавливаем версию v9.9.9" in page
    assert "/api/version" in page and '"v9.9.9"' in page                      # страница следит за перезапуском
    assert "https://github.com/x/y/releases/tag/v9.9.9" in page and "CafedraSchedule.exe" in page   # ручной способ


def test_update_banner_has_manual_download_fallback(monkeypatch):
    info = {"version": "v9.9.9", "url": "https://github.com/x/y/releases/tag/v9.9.9",
            "download_url": "https://x/CafedraSchedule.exe", "size": 10, "notes": ""}
    monkeypatch.setattr(update_check, "_cache", {"checked_at": 0.0, "result": info})
    monkeypatch.setattr(main_module, "check_for_update", lambda force=False: info)
    monkeypatch.setattr(main_module.self_update, "can_self_update", lambda: True)

    page = TestClient(main_module.app).get("/").text

    assert "Скачать и установить" in page and "Скачать вручную" in page
