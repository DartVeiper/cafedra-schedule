"""Фоновая установка обновления с видимым прогрессом.

Раньше запрос «Скачать и установить» висел, пока файл (~26 МБ) скачивается, и человек видел
пустое окно браузера — непонятно, идёт ли что-то вообще (методист так и закрывала вкладку).
Теперь скачивание идёт в фоновом потоке, а страница обновления опрашивает /api/update/status:
этапы «скачиваем (N из M МБ) → устанавливаем и перезапускаем → готово» и понятная ошибка.
"""
from __future__ import annotations

import threading
import urllib.error

from app import self_update

_lock = threading.Lock()
_state: dict = {"state": "idle", "done": 0, "total": 0, "message": "", "version": ""}


def snapshot() -> dict:
    with _lock:
        return dict(_state)


def reset() -> None:
    with _lock:
        _state.update(state="idle", done=0, total=0, message="", version="")


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def friendly_error(e: BaseException) -> str:
    """Короткое объяснение сбоя человеческим языком (технические детали — в конце)."""
    detail = f"{type(e).__name__}: {e}"
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return f"Не удалось скачать файл: нет связи с GitHub или она пропала. Проверьте интернет и попробуйте ещё раз. ({detail})"
    if isinstance(e, ValueError):
        return f"Скачанный файл повреждён или неполный — установка отменена, программа осталась прежней. ({detail})"
    if isinstance(e, PermissionError):
        return f"Нет прав записать файл рядом с программой — положите программу в обычную папку (не Program Files). ({detail})"
    return f"Не удалось подготовить обновление. ({detail})"


def _on_progress(done: int, total: int | None) -> None:
    _set(done=done, total=total or 0)


def _run(download_url: str, expected_size: int | None) -> None:
    try:
        self_update.start_update(download_url, expected_size=expected_size, progress=_on_progress)
    except Exception as e:  # любая причина — человеку понятное сообщение, а не молчание
        _set(state="error", message=friendly_error(e))
        return
    _set(state="installing")
    # Даём странице время увидеть этап «устанавливаем», прежде чем программа закроется.
    self_update.schedule_exit(delay_seconds=4.0)


def start(download_url: str, version: str, expected_size: int | None = None) -> bool:
    """Запускает скачивание в фоне. False — уже идёт (повторное нажатие кнопки не плодит потоки)."""
    with _lock:
        if _state["state"] in ("downloading", "installing"):
            return False
        _state.update(state="downloading", done=0, total=expected_size or 0, message="", version=version)
    threading.Thread(target=_run, args=(download_url, expected_size), daemon=True).start()
    return True
