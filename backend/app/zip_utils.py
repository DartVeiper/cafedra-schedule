"""Распаковка ZIP-архивов с расписанием, с автоисправлением кодировки имён файлов.

Если архив собран без флага UTF-8 (обычное дело для ZIP из Windows-проводника),
Python decode-ит имена файлов как cp437 по умолчанию. Если реальные байты имени
были в cp866 (частый вариант для файлов с кириллицей из старых инструментов) —
получается "кракозябры". Чиним, перекодируя обратно в байты (cp437) и заново
декодируя как cp866; если не получилось — пробуем cp1251; если и это не сошлось —
оставляем как есть и предупреждаем пользователя.
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field


@dataclass
class ExtractResult:
    extracted_paths: list[str] = field(default_factory=list)
    renamed_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fix_filename(info: zipfile.ZipInfo) -> tuple[str, bool]:
    """Возвращает (имя_файла, было_ли_исправлено)."""
    if info.flag_bits & 0x800:  # архив сам пометил имя как UTF-8 — не трогаем
        return info.filename, False
    raw = info.filename
    for enc in ("cp866", "cp1251"):
        try:
            fixed = raw.encode("cp437").decode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != raw and _looks_like_cyrillic_text(fixed):
            return fixed, True
    return raw, False


def _looks_like_cyrillic_text(s: str) -> bool:
    return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in s)


def extract_zip(zip_path: str, out_dir: str) -> ExtractResult:
    os.makedirs(out_dir, exist_ok=True)
    result = ExtractResult()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            fixed_name, was_fixed = _fix_filename(info)
            base_name = os.path.basename(fixed_name)  # без вложенных папок архива
            if not base_name:
                continue
            if was_fixed:
                result.renamed_notes.append(f"{info.filename!r} -> {base_name!r} (исправлена кодировка имени)")
            out_path = os.path.join(out_dir, base_name)
            with z.open(info) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
            result.extracted_paths.append(out_path)
    return result
