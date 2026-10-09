"""Самообновление standalone .exe "на месте" — без второй копии рядом,
которую методисту пришлось бы вручную подкладывать вместо старой.

Windows не даёт перезаписать или удалить .exe, пока он запущен, поэтому
обновление идёт в два шага:

1. Пока приложение ещё работает: скачиваем новый .exe рядом со старым (под
   именем `CafedraSchedule.exe.new`), проверяем, что файл скачался целиком
   и это действительно программа для Windows, и пишем маленький
   .bat-скрипт-помощник.
2. Помощник запускается отдельным процессом и сразу переживает наш —
   он ждёт, пока текущий процесс (по PID) завершится, затем подменяет .exe
   и перезапускает программу (которая сама откроет браузер, см.
   desktop_app.py).

Системные программы (tasklist, find, ping) вызываются по ПОЛНОМУ пути: по голому
имени `find` в PATH может оказаться одноимённая утилита из Git (GNU find) — она
выдаёт ошибку, скрипт решал бы, что процесс уже закрылся, и подменял файл
раньше времени (реальный сбой, пойманный сквозным тестом).

Паузы в скрипте сделаны через `ping`, а не `timeout`: помощник запускается без
видимого окна, и `timeout` там сразу завершается ошибкой, не ожидая — ожидание
превратилось бы в «вертушку», а попытки подмены кончились бы мгновенно.

Подмена сделана с запасом прочности — от неё зависит, останется ли у
методиста рабочая программа:
  * Старый .exe не удаляется, а переименовывается в `.bak`; если подмена не
    удалась, он возвращается на место и запускается старая версия.
  * Файл может быть занят ещё какое-то время после выхода процесса (у
    PyInstaller-onefile родительский процесс-загрузчик закрывается позже
    дочернего, плюс антивирус проверяет файл), поэтому подмена повторяется
    до MAX_SWAP_TRIES раз с паузой в секунду.

Работает только для собранного PyInstaller-exe на Windows — при разработке
из исходников (`sys.frozen` нет) самообновление недоступно, там уже есть
`git pull` в "Обновить и запустить.bat".

Проверка сквозного сценария (с настоящим cmd и занятым файлом) —
tests/test_self_update_e2e.py (запускается на Windows).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request

from app.paths import is_frozen

MAX_SWAP_TRIES = 30
DOWNLOAD_CHUNK = 256 * 1024

# raw-строка: в путях обратные слэши (\System32\tasklist.exe), иначе \t и \f станут управляющими символами
_HELPER_SCRIPT = r"""@echo off
chcp 65001 >nul
set TRIES=0
:wait
"%SystemRoot%\System32\tasklist.exe" /fi "PID eq {pid}" /nh | "%SystemRoot%\System32\find.exe" "{pid}" >nul
if not errorlevel 1 (
  "%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul
  goto wait
)
:swap
set /a TRIES+=1
move /y "{exe_path}" "{bak_path}" >nul 2>&1
if errorlevel 1 goto retry
move /y "{new_path}" "{exe_path}" >nul 2>&1
if errorlevel 1 (
  move /y "{bak_path}" "{exe_path}" >nul 2>&1
  goto retry
)
start "" "{exe_path}"
"%SystemRoot%\System32\ping.exe" -n 4 127.0.0.1 >nul
del "{bak_path}" >nul 2>&1
(goto) 2>nul & del "%~f0"
:retry
if %TRIES% GEQ {max_tries} goto giveup
"%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul
goto swap
:giveup
del "{new_path}" >nul 2>&1
start "" "{exe_path}"
(goto) 2>nul & del "%~f0"
"""


def can_self_update() -> bool:
    return is_frozen() and sys.platform == "win32"


def independent_launch_env() -> dict[str, str]:
    """Окружение для запуска НОВОЙ копии программы из работающей.

    PyInstaller-onefile кладёт в окружение служебные переменные (_MEIPASS2, _PYI_*).
    Процесс, запущенный из программы с этими переменными, считает себя её дочерним
    и берёт временную папку родителя — а та удаляется, как только родитель закроется,
    поэтому обновлённая версия падала бы при старте, ничего не показав (поймано
    сквозным тестом на настоящей собранной программе). PYINSTALLER_RESET_ENVIRONMENT=1
    велит загрузчику распаковаться заново, как при обычном запуске."""
    env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2" and not k.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def build_helper_script(
    pid: int, new_path: str, exe_path: str, bak_path: str | None = None, max_tries: int = MAX_SWAP_TRIES
) -> str:
    return _HELPER_SCRIPT.format(
        pid=pid, new_path=new_path, exe_path=exe_path,
        bak_path=bak_path or exe_path + ".bak", max_tries=max_tries,
    )


def download_new_exe(download_url: str, dest_path: str, expected_size: int | None = None, progress=None) -> None:
    """Скачивает файл кусками (progress(скачано, всего) — для полосы загрузки) и проверяет, что он
    не обрезан и похож на .exe: иначе подмена испортила бы рабочую программу. Пишем во временный
    .part и только потом переименовываем — недокачанный файл никогда не лежит под именем .new."""
    req = urllib.request.Request(download_url, headers={"User-Agent": "cafedra-schedule-app"})
    part_path = dest_path + ".part"
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            headers = getattr(resp, "headers", None)
            declared = headers.get("Content-Length") if headers is not None else None
            declared_n = int(declared) if declared is not None and str(declared).isdigit() else None
            total = declared_n if declared_n is not None else expected_size
            done = 0
            first = True
            with open(part_path, "wb") as f:
                while True:
                    chunk = resp.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    if first:
                        if not chunk.startswith(b"MZ"):
                            raise ValueError("скачанный файл не похож на программу для Windows")
                        first = False
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if first:
            raise ValueError("скачанный файл пустой или не похож на программу для Windows")
        if declared_n is not None and declared_n != done:
            raise ValueError(f"файл скачался не полностью ({done} из {declared_n} байт)")
        if expected_size is not None and expected_size != done:
            raise ValueError(f"размер файла не совпадает с ожидаемым ({done} вместо {expected_size} байт)")
        os.replace(part_path, dest_path)
    except BaseException:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise


def start_update(
    download_url: str,
    expected_size: int | None = None,
    exe_path: str | None = None,
    pid: int | None = None,
    max_tries: int = MAX_SWAP_TRIES,
    progress=None,
) -> None:
    """Скачивает новую версию и готовит подмену + перезапуск. Текущий процесс
    должен вскоре после этого завершиться (см. schedule_exit) — иначе
    .bat-помощник будет ждать его окончания бесконечно.

    exe_path/pid/max_tries — для тестов; по умолчанию это текущая программа."""
    exe_path = os.path.abspath(exe_path or sys.executable)
    pid = pid if pid is not None else os.getpid()
    exe_dir = os.path.dirname(exe_path)
    new_path = exe_path + ".new"
    helper_path = os.path.join(exe_dir, "_cafedra_update.bat")

    download_new_exe(download_url, new_path, expected_size, progress)

    with open(helper_path, "w", encoding="utf-8") as f:
        f.write(build_helper_script(pid, new_path, exe_path, max_tries=max_tries))

    subprocess.Popen(
        ["cmd", "/c", helper_path],
        cwd=exe_dir,
        env=independent_launch_env(),  # без этого новая копия, запущенная помощником, падает при старте
        # CREATE_NO_WINDOW, а не DETACHED_PROCESS: без консоли ping/tasklist/find внутри .bat
        # зависают (проверено сквозным тестом); скрытая консоль работает и окно не мигает.
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
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
