"""Сквозная проверка самообновления НАСТОЯЩЕЙ собранной программы на Windows.

test_self_update_e2e.py проверяет подмену на подставных системных программах
(whoami/hostname) — они не PyInstaller-onefile, поэтому не ловят то, что бывает
только у настоящей программы: у onefile два процесса (загрузчик и сама программа
с другим PID), своя временная папка у каждого запуска, а при запуске новой копии
из старой наследуются служебные переменные окружения PyInstaller. Здесь собирается
крошечный пробник (tests/frozen_updater_probe.py), настоящим start_update он
скачивает «новую версию» по HTTP, и тест ждёт, что новая копия реально ЗАПУСТИЛАСЬ
из того же места, а старый мусор убрался.

Сборка пробника — около 30 секунд. Вне Windows пропускается.
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

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="нужны Windows и PyInstaller")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def probe_exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("probe_build")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", "Probe",
            "--paths", BACKEND_DIR,
            "--distpath", str(out / "dist"), "--workpath", str(out / "work"), "--specpath", str(out),
            os.path.join(BACKEND_DIR, "tests", "frozen_updater_probe.py"),
        ],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return out / "dist" / "Probe.exe"


@pytest.fixture
def server(probe_exe):
    """Локальный «GitHub»: отдаёт ту же программу как «новую версию»."""
    payload = probe_exe.read_bytes()

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
    yield f"http://127.0.0.1:{httpd.server_address[1]}/Probe.exe"
    httpd.shutdown()


def _read_log(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.strip().split("|") for line in f if line.strip()]


def _wait_until(predicate, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def test_real_frozen_app_updates_itself_and_new_copy_starts(tmp_path, probe_exe, server):
    app_dir = tmp_path / "Папка с программой"  # кириллица и пробел в пути — как у реальных пользователей
    app_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    exe = app_dir / "Probe.exe"
    shutil.copy(probe_exe, exe)
    log = state_dir / "starts.log"

    env = dict(os.environ, PROBE_STATE_DIR=str(state_dir))
    proc = subprocess.Popen([str(exe), "--update", server], env=env, cwd=str(app_dir),
                            creationflags=subprocess.CREATE_NO_WINDOW)  # скрытая консоль: как у настоящей
                            # программы (она консольная), но без видимого окна — тест не зависит от состояния
                            # рабочего стола (с CREATE_NEW_CONSOLE он зависал, когда сеанс Windows простаивал)
    try:
        ok = _wait_until(lambda: len(_read_log(log)) >= 2)
        starts = _read_log(log)
        diag = (
            f"запуски: {starts}; папка: {sorted(os.listdir(app_dir))}; "
            f"ошибка пробника: {(state_dir / 'error.log').read_text(encoding='utf-8') if (state_dir / 'error.log').exists() else '-'}"
        )
        assert ok, f"после обновления новая копия не запустилась. {diag}"

        first, second = starts[0], starts[1]
        assert os.path.normcase(second[1]) == os.path.normcase(str(exe)), f"запустилась не из того же места. {diag}"
        assert first[2] != second[2], f"новая копия не распаковалась в свою папку. {diag}"

        assert _wait_until(lambda: {n.lower() for n in os.listdir(app_dir)} == {"probe.exe"}, timeout=40), (
            f"остался мусор после обновления: {sorted(os.listdir(app_dir))}"
        )
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/IM", "Probe.exe"], capture_output=True)
        proc.kill()
