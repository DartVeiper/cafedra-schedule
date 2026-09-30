"""Разбор ответа GitHub Releases API: сравнение версий и поиск .exe-ассета
для самообновления (см. app/self_update.py)."""
from __future__ import annotations

import json

from app import update_check


def _fake_urlopen_factory(payload: dict | None, raise_error: Exception | None = None):
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    def _fake_urlopen(req, timeout=3):
        if raise_error:
            raise raise_error
        return _FakeResponse()

    return _fake_urlopen


def _reset_cache(monkeypatch):
    monkeypatch.setattr(update_check, "_cache", {"checked_at": 0.0, "result": None})


def test_finds_exe_asset_download_url(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(update_check, "APP_VERSION", "0.1.0")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen_factory({
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/x/y/releases/tag/v0.2.0",
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://x/checksums.txt"},
            {"name": "CafedraSchedule.exe", "browser_download_url": "https://x/CafedraSchedule.exe"},
        ],
    }))

    result = update_check.check_for_update(force=True)

    assert result == {
        "version": "v0.2.0",
        "url": "https://github.com/x/y/releases/tag/v0.2.0",
        "download_url": "https://x/CafedraSchedule.exe",
    }


def test_no_exe_asset_gives_none_download_url(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(update_check, "APP_VERSION", "0.1.0")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen_factory({
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/x/y/releases/tag/v0.2.0",
        "assets": [{"name": "source.zip", "browser_download_url": "https://x/source.zip"}],
    }))

    result = update_check.check_for_update(force=True)

    assert result["download_url"] is None


def test_up_to_date_returns_none(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(update_check, "APP_VERSION", "0.2.0")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen_factory({
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/x/y/releases/tag/v0.2.0",
        "assets": [],
    }))

    assert update_check.check_for_update(force=True) is None


def test_network_error_returns_none(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(update_check, "APP_VERSION", "0.1.0")
    monkeypatch.setattr(
        update_check.urllib.request, "urlopen",
        _fake_urlopen_factory(None, raise_error=OSError("no network")),
    )

    assert update_check.check_for_update(force=True) is None
