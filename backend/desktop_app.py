"""Точка входа для «настольного» режима — это то, что запускает PyInstaller-exe.

Поднимает веб-сервер локально и сам открывает браузер — методисту не нужно
ничего знать про Python, командную строку или порты.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from app.main import app

HOST = "127.0.0.1"
PORT = 8000


def _open_browser_when_ready() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    print("Запускается расписание кафедры фортепиано...")
    print(f"Если браузер не откроется сам, зайдите на http://{HOST}:{PORT}")
    print("Чтобы остановить программу — закройте это окно.")
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
