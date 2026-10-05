"""Пробник для сквозного теста самообновления НАСТОЯЩЕЙ собранной программы
(tests/test_self_update_frozen_e2e.py). Собирается PyInstaller'ом в один .exe — как
настоящее приложение, — и ведёт себя как оно по кнопке «Скачать и установить»:

    Probe.exe --update <url>   — первый запуск: пишет отметку в starts.log, запускает
                                  настоящий self_update.start_update(<url>) и завершается;
    Probe.exe                  — запуск «после обновления»: пишет отметку и выходит.

В starts.log каждая строка — «PID|путь к exe|временная папка PyInstaller». По двум
строкам тест видит, что новая версия действительно запустилась (а не упала при
старте) и распаковалась в свою папку, а не залезла в папку уже закрывшейся старой.
"""
import os
import sys
import time

from app import self_update

state_dir = os.environ["PROBE_STATE_DIR"]
with open(os.path.join(state_dir, "starts.log"), "a", encoding="utf-8") as f:
    f.write(f"{os.getpid()}|{sys.executable}|{getattr(sys, '_MEIPASS', '')}\n")

if len(sys.argv) >= 3 and sys.argv[1] == "--update":
    try:
        self_update.start_update(sys.argv[2])
    except Exception as e:  # noqa: BLE001 — тесту нужна причина, а не просто «не обновилось»
        with open(os.path.join(state_dir, "error.log"), "w", encoding="utf-8") as f:
            f.write(repr(e))
        raise
    self_update.schedule_exit()
    time.sleep(120)  # «работаем», пока schedule_exit не завершит процесс — как настоящее приложение
