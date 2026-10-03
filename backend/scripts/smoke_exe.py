"""Дымовая проверка собранного .exe: запускается в песочнице (своя LOCALAPPDATA, браузер не
открывается), отвечает на главную страницу, отдаёт стили и резервную копию, показывает
нужную версию. Только стандартная библиотека. Используется и в GitHub Actions, и вручную:

    python scripts/smoke_exe.py dist/CafedraSchedule.exe
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# На GitHub Actions консоль Windows в cp1252 — русские слова в print упали бы с UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.version import APP_VERSION  # noqa: E402

BASE = "http://127.0.0.1:8000"


def get(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:  # 404 и т.п. — это ответ программы, а не «не запустилась»
        return e.code, e.read()


def _backup_ok() -> bool:
    status, body = get("/backup/download")
    return status == 200 and json.loads(body).get("app") == "CafedraSchedule"


def main() -> int:
    exe = os.path.abspath(sys.argv[1])
    env = dict(os.environ, LOCALAPPDATA=tempfile.mkdtemp(prefix="cafedra_smoke_"), BROWSER="cmd /c exit")
    proc = subprocess.Popen([exe], env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(60):
            try:
                status, body = get("/")
                break
            except OSError:
                time.sleep(1)
        else:
            print("FAIL: программа не запустилась за 60 секунд")
            return 1
        page = body.decode("utf-8")
        checks = {
            "главная отвечает": status == 200,
            f"на странице версия {APP_VERSION}": f"версия {APP_VERSION}" in page,
            "есть кнопка «Что нового»": "whatsnew-btn" in page,
            "стили отдаются": get("/static/style.css")[0] == 200,
            "резервная копия отдаётся": _backup_ok(),
        }
        for name, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + name)
        return 0 if all(checks.values()) else 1
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
