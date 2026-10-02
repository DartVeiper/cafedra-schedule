"""Пометки «это не накладка» — накладки, которые методист разобрал и признал
нормальными (например, концертмейстер реально успевает, или запись в файле
устарела). Хранятся в config/dismissed_conflicts.json отдельно от проверок
(см. paths.dismissed_conflicts_path), ключ — conflicts.conflict_key.
"""
from __future__ import annotations

import json
import os
from datetime import datetime


def load_dismissed(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    items = data.get("dismissed") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def _save(path: str, items: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"dismissed": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def dismiss(path: str, key: str, label: str = "") -> None:
    items = load_dismissed(path)
    items[key] = {"label": label, "at": datetime.now().isoformat(timespec="seconds")}
    _save(path, items)


def restore(path: str, key: str) -> None:
    items = load_dismissed(path)
    if items.pop(key, None) is not None:
        _save(path, items)


def restore_all(path: str) -> None:
    if load_dismissed(path):
        _save(path, {})
