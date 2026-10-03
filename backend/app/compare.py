"""Сравнение двух проверок: что исправили преподаватели с прошлой загрузки, а что
появилось нового.

Накладки сопоставляются по conflict_key (кто, когда, где, какой предмет), а не по
файлу/строке — поэтому сравнение переживает сдвиги строк в файлах. Если занятие
изменили (перенесли, сменили кабинет), старая накладка считается исправленной, а
если от этого появилась другая — новой.

Пары «преподаватель + концертмейстер» (ACCOMPANIST_PAIRING) — не накладки и в
сравнение не входят.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.conflicts import conflict_key
from app.models import Conflict, ConflictType


@dataclass
class Comparison:
    prev_id: str
    prev_created: str            # как в БД ("2026-09-30 14:05:00")
    prev_lessons: int
    cur_lessons: int
    new_keys: set[str]           # ключи накладок, которых не было в прошлой проверке
    fixed: list[Conflict]        # были в прошлой проверке, в этой — нет
    same: int                    # осталось без изменений

    @property
    def new_count(self) -> int:
        return len(self.new_keys)

    @property
    def fixed_count(self) -> int:
        return len(self.fixed)

    @property
    def lessons_differ_a_lot(self) -> bool:
        """Загрузили заметно другой набор файлов — цифры «исправлено» могут быть
        обманчивы (накладки исчезли не потому, что их поправили, а потому что файлов меньше)."""
        if not self.prev_lessons:
            return False
        return abs(self.cur_lessons - self.prev_lessons) / self.prev_lessons > 0.1


def _real(conflicts: list[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if c.type != ConflictType.ACCOMPANIST_PAIRING]


def pick_previous(imports: list, current_id: str, explicit: str = "") -> object | None:
    """Строка из db.list_imports (новые сверху), с которой сравниваем.
    explicit: "" — предыдущая по времени, "off" — не сравнивать, иначе id нужной проверки."""
    if explicit == "off":
        return None
    ids = [r["id"] for r in imports]
    if current_id not in ids:
        return None
    if explicit and explicit != current_id and explicit in ids:
        return imports[ids.index(explicit)]
    i = ids.index(current_id)
    return imports[i + 1] if i + 1 < len(imports) else None


def compare(
    current: list[Conflict], previous: list[Conflict],
    prev_id: str, prev_created: str, prev_lessons: int, cur_lessons: int,
) -> Comparison:
    cur_real, prev_real = _real(current), _real(previous)
    cur_keys = {conflict_key(c) for c in cur_real}
    prev_by_key = {conflict_key(c): c for c in prev_real}
    new_keys = cur_keys - prev_by_key.keys()
    fixed = [c for k, c in prev_by_key.items() if k not in cur_keys]
    return Comparison(
        prev_id, prev_created, prev_lessons, cur_lessons,
        new_keys=new_keys, fixed=fixed, same=len(cur_keys & prev_by_key.keys()),
    )
