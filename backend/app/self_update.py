"""Самообновление standalone .exe "на месте" — без второй копии рядом,
которую методисту пришлось бы вручную подкладывать вместо старой.

Windows не даёт перезаписать или удалить .exe, пока он запущен, поэтому
обновление идёт в два шага:

1. Пока приложение ещё работает: скачиваем новый .exe рядом со старым (под
   именем `CafedraSchedule.exe.new`) и пишем маленький .bat-скрипт-помощник.
2. Помощник запускается отдельным процессом и сразу переживает наш —
   он ждёт, пока текущий процесс (по PID) действительно завершится и
   освободит файл, затем подменяет .exe и перезапускает программу
   (которая сама откроет браузер, см. desktop_app.py).

Работает только для собранного PyInstaller-exe на Windows — при разработке
из исходников (`sys.frozen` нет) самообновление недоступно, там уже есть
`git pull` в "Обновить и запустить.bat".
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request

from app.paths import is_frozen

_HELPER_SCRIPT = """@echo off
chcp 65001 >nul
:wait
tasklist /fi "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
move /y "{new_path}" "{exe_path}" >nul
start "" "{exe_path}"
del "%~f0"
"""


def can_self_update() -> bool:
    return is_frozen() and sys.platform == "win32"


def build_helper_script(pid: int, new_path: str, exe_path: str) -> str:
    return _HELPER_SCRIPT.format(pid=pid, new_path=new_path, exe_path=exe_path)


def download_new_exe(download_url: str, dest_path: str) -> None:
    req = urllib.request.Request(download_url, headers={"User-Agent": "cafedra-schedule-app"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)


def start_update(download_url: str) -> None:
    """Скачивает новую версию и готовит подмену + перезапуск. Текущий процесс
    должен вскоре после этого завершиться (см. schedule_exit) — иначе
    .bat-помощник будет ждать его окончания бесконечно."""
    exe_path = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(exe_path)
    new_path = exe_path + ".new"
    helper_path = os.path.join(exe_dir, "_cafedra_update.bat")

    download_new_exe(download_url, new_path)

    with open(helper_path, "w", encoding="utf-8") as f:
        f.write(build_helper_script(os.getpid(), new_path, exe_path))

    subprocess.Popen(
        ["cmd", "/c", helper_path],
        cwd=exe_dir,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def schedule_exit(delay_seconds: float = 1.5) -> None:
    """Даёт HTTP-ответу время дойти до браузера, потом завершает процесс —
    после этого .bat-помощник обнаруживает, что PID исчез, и доделывает
    подмену файла."""

    def _exit() -> None:
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
