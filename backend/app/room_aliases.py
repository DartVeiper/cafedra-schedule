"""«Один кабинет — несколько названий».

Преподаватели пишут один и тот же кабинет по-разному: малый зал называют «423», «м/ф» (малое фойе) и
«Малый зал». Для программы это три разных кабинета — поэтому накладки по нему терялись (один преподаватель
в «423», другой в «м/ф» в то же время). Список псевдонимов сводит такие названия к одному кабинету.

Применяется при ЗАГРУЗКЕ проверки из базы (а не при разборе файла), поэтому действует и на старые
проверки, и сразу после правки списка. Хранится в config/room_aliases.json (переживает обновления).
Пока файла нет, действует список по умолчанию — помещения колледжа, одинаковые для всех кафедр здания:
  * Малый зал = «423» (эти названия — одно помещение);
  * «м/ф» = «мф» = «малое фойе» — ОТДЕЛЬНЫЙ кабинет (малое фойе), не малый зал.
"""
from __future__ import annotations

import copy
import json
import os

from app.models import Lesson
from app.parsers.common import normalize_room

# {настоящий кабинет: {"label": как показывать, "names": [как ещё его пишут]}}
DEFAULT_ALIASES: dict[str, dict] = {
    "423": {"label": "Малый зал", "names": ["малый зал"]},
    "м/ф": {"label": "Малое фойе", "names": ["мф", "малое фойе", "фойе малое"]},
}


def load_aliases(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return copy.deepcopy(DEFAULT_ALIASES)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_ALIASES)
    items = data.get("rooms") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return copy.deepcopy(DEFAULT_ALIASES)
    out: dict[str, dict] = {}
    for key, v in items.items():
        if isinstance(key, str) and isinstance(v, dict):
            names = [n for n in v.get("names", []) if isinstance(n, str) and n.strip()]
            out[key] = {"label": v.get("label", "") if isinstance(v.get("label", ""), str) else "", "names": names}
    return out


def save_aliases(path: str, aliases: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"rooms": aliases}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def mapping(aliases: dict[str, dict]) -> dict[str, str]:
    """{нормализованное название: настоящий кабинет}."""
    out: dict[str, str] = {}
    for key, v in aliases.items():
        target = normalize_room(key) or key
        for name in v.get("names", []):
            n = normalize_room(name)
            if n and n != target:
                out[n] = target
    return out


def canonical(room: str | None, aliases: dict[str, dict]) -> str | None:
    if not room:
        return room
    return mapping(aliases).get(room, room)


def apply(lessons: list[Lesson], aliases: dict[str, dict]) -> None:
    """Сводит названия кабинетов к настоящему (меняет room_normalized у занятий на месте)."""
    m = mapping(aliases)
    if not m:
        return
    for l in lessons:
        if l.room_normalized in m:
            l.room_normalized = m[l.room_normalized]


def labels(aliases: dict[str, dict]) -> dict[str, str]:
    """{кабинет: подпись}, напр. {'423': 'Малый зал'} — для заголовков столбцов."""
    return {(normalize_room(k) or k): v["label"] for k, v in aliases.items() if v.get("label")}


def display(room: str, aliases: dict[str, dict]) -> str:
    """'423' -> 'Малый зал (423)'; кабинет без подписи — как есть."""
    label = labels(aliases).get(room)
    return f"{label} ({room})" if label else room


def add_name(aliases: dict[str, dict], name: str, room: str, label: str = "") -> bool:
    """Добавляет «name — это тот же кабинет, что room». False — пустые/некорректные данные."""
    name_n, room_n = normalize_room(name), normalize_room(room)
    if not name_n or not room_n or name_n == room_n:
        return False
    entry = aliases.setdefault(room_n, {"label": "", "names": []})
    if label.strip():
        entry["label"] = label.strip()[:40]
    known = {normalize_room(n) for n in entry["names"]}
    if name_n not in known:
        entry["names"].append(name.strip())
    # то же название не должно числиться у другого кабинета
    for key, v in aliases.items():
        if key != room_n:
            v["names"] = [n for n in v["names"] if normalize_room(n) != name_n]
    return True


def remove_name(aliases: dict[str, dict], name: str) -> None:
    name_n = normalize_room(name)
    for key in list(aliases):
        aliases[key]["names"] = [n for n in aliases[key]["names"] if normalize_room(n) != name_n]
        if not aliases[key]["names"] and not aliases[key].get("label"):
            del aliases[key]
