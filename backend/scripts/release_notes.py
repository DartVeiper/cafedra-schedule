"""Для автосборки релиза (.github/workflows/release.yml): проверяет, что тег совпадает с
APP_VERSION и что в app/changelog.py есть запись для этой версии, и печатает текст релиза.

    python scripts/release_notes.py v0.3.5 > notes.md

Код выхода 1 и понятное сообщение в stderr — если версия в коде не совпадает с тегом
или записи в changelog нет (тогда релиз собирать нельзя: людям нечего будет показать).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.changelog import release_notes_markdown  # noqa: E402
from app.update_check import _parse_version  # noqa: E402
from app.version import APP_VERSION  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Использование: release_notes.py vX.Y.Z", file=sys.stderr)
        return 2
    tag = sys.argv[1]
    if _parse_version(tag) != _parse_version(APP_VERSION):
        print(f"Тег {tag} не совпадает с APP_VERSION={APP_VERSION} в app/version.py — поднимите версию и пересоздайте тег.",
              file=sys.stderr)
        return 1
    try:
        sys.stdout.write(release_notes_markdown(tag))
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
