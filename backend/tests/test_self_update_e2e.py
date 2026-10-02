"""Сквозная проверка самообновления на настоящей Windows: настоящий cmd, настоящий
HTTP-скачивание, настоящая подмена файла — включая «файл ещё занят» (так бывает
после выхода программы: загрузчик PyInstaller/антивирус держат .exe лишнюю секунду).

Вместо настоящей программы подставляются маленькие системные .exe (whoami — «старая
версия», hostname — «новая»), поэтому тест быстрый и безопасный. Запускать после
ЛЮБОГО изменения app/self_update.py, update_check.py или сборки:

    cd backend && ..\\.venv\\Scripts\\python.exe -m pytest tests/test_self_update_e2e.py -v

Вне Windows пропускается.
"""
from __future__ import annotations

import http.server
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from app import self_update

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="нужны Windows и cmd")

SYSTEM32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
OLD_SRC = os.path.join(SYSTEM32, "whoami.exe")
NEW_SRC = os.path.join(SYSTEM32, "hostname.exe")


@pytest.fixture
def server():
    """Локальный «GitHub»: отдаёт «новую версию» по HTTP с Content-Length."""
    payload = open(NEW_SRC, "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{httpd.server_address[1]}/CafedraSchedule.exe", "payload": payload}
    httpd.shutdown()


@pytest.fixture
def app_dir(tmp_path):
    d = tmp_path / "Папка с программой"  # кириллица и пробелы в пути — как у реальных пользователей
    d.mkdir()
    shutil.copy(OLD_SRC, d / "CafedraSchedule.exe")
    return d


def _finished_process():
    """Процесс «приложения», который вот-вот завершится (его PID ждёт помощник)."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])


def _wait_until(predicate, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return False


def _leftovers(app_dir):
    names = {n.lower() for n in os.listdir(app_dir)}
    return names - {"cafedraschedule.exe"}


def test_update_replaces_exe_and_cleans_up(app_dir, server):
    exe = app_dir / "CafedraSchedule.exe"
    proc = _finished_process()

    self_update.start_update(server["url"], expected_size=len(server["payload"]), exe_path=str(exe), pid=proc.pid)

    assert _wait_until(lambda: exe.read_bytes() == server["payload"] and not _leftovers(app_dir)), (
        f"подмена не завершилась: {os.listdir(app_dir)}"
    )


def test_update_waits_while_exe_is_still_locked(app_dir, server):
    """Процесс уже вышел, но файл ещё занят несколько секунд — помощник должен
    подождать и повторить, а не бросить обновление и не сломать программу."""
    exe = app_dir / "CafedraSchedule.exe"
    lock = open(exe, "rb")  # открытый дескриптор без FILE_SHARE_DELETE не даёт переименовать файл
    threading.Timer(5.0, lock.close).start()
    proc = _finished_process()

    self_update.start_update(server["url"], expected_size=len(server["payload"]), exe_path=str(exe), pid=proc.pid)

    time.sleep(3)  # процесс уже вышел, файл всё ещё занят: старая версия на месте
    assert open(OLD_SRC, "rb").read() == _read_unlocked(exe)
    assert _wait_until(lambda: _read_unlocked(exe) == server["payload"] and not _leftovers(app_dir)), (
        f"после освобождения файла подмена не прошла: {os.listdir(app_dir)}"
    )


def _read_unlocked(path):
    with open(path, "rb") as f:
        return f.read()


def test_update_gives_up_cleanly_if_exe_stays_locked(app_dir, server):
    """Файл так и не освободился — остаётся рабочая старая версия, мусор убирается."""
    exe = app_dir / "CafedraSchedule.exe"
    old_bytes = _read_unlocked(exe)
    lock = open(exe, "rb")
    try:
        proc = _finished_process()
        self_update.start_update(
            server["url"], expected_size=len(server["payload"]), exe_path=str(exe), pid=proc.pid, max_tries=3,
        )
        assert _wait_until(lambda: not _leftovers(app_dir)), (
            f"помощник не убрал за собой: {os.listdir(app_dir)}"
        )
    finally:
        lock.close()
    assert _read_unlocked(exe) == old_bytes


def test_corrupted_download_never_touches_the_installed_exe(app_dir, server):
    exe = app_dir / "CafedraSchedule.exe"
    old_bytes = _read_unlocked(exe)

    with pytest.raises(ValueError):
        self_update.start_update(server["url"], expected_size=len(server["payload"]) + 5, exe_path=str(exe), pid=1)

    assert _read_unlocked(exe) == old_bytes and not _leftovers(app_dir)
