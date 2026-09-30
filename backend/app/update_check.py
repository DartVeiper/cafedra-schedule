"""Проверка новых версий через GitHub Releases.

Показывает баннер на странице загрузки, если вышла версия новее той, что
сейчас запущена — методисту не нужно самому следить за GitHub. Если сети
нет, репозиторий ещё без релизов, или GitHub недоступен — просто ничего не
показываем, приложение работает как обычно (это не критичная функция).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.version import APP_VERSION, GITHUB_REPO

_CACHE_TTL_SECONDS = 3600  # не дёргаем GitHub API на каждое открытие страницы
_cache: dict = {"checked_at": 0.0, "result": None}


def _parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3); нечисловой мусор в компоненте считаем нулём."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_for_update(force: bool = False) -> dict | None:
    """{'version': 'v0.2.0', 'url': 'https://github.com/.../releases/tag/v0.2.0',
    'download_url': 'https://github.com/.../CafedraSchedule.exe'} если есть более
    новый релиз, иначе None. 'download_url' — None, если к релизу не приложен
    .exe (например, релиз только с исходниками). Результат кэшируется на час."""
    now = time.time()
    if not force and now - _cache["checked_at"] < _CACHE_TTL_SECONDS:
        return _cache["result"]

    _cache["checked_at"] = now
    result = _fetch_latest_release()
    _cache["result"] = result
    return result


def _fetch_latest_release() -> dict | None:
    if not GITHUB_REPO:
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "cafedra-schedule-app"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return None

    tag = data.get("tag_name")
    html_url = data.get("html_url")
    if not tag or not html_url:
        return None
    if not _is_newer(tag, APP_VERSION):
        return None

    download_url = None
    for asset in data.get("assets") or []:
        if str(asset.get("name", "")).lower().endswith(".exe"):
            download_url = asset.get("browser_download_url")
            break

    return {"version": tag, "url": html_url, "download_url": download_url}
