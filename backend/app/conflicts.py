"""Поиск накладок (конфликтов) в едином списке занятий.

Вместо сравнения всех занятий друг с другом (O(n^2) по всей базе) группируем
по (день недели, ключ конфликта) — преподаватель/концертмейстер, аудитория или
студент — и внутри каждой группы ищем пересечения интервалов проходом по
отсортированному списку (sweep line): раз список отсортирован по времени
начала, как только текущая запись начинается позже, чем заканчивается
записи-кандидат на пересечение, дальше по списку пересечений с ней уже не будет.

Особый случай — "студент в двух местах": индивидуальное занятие пересекается
с ГРУППОВЫМ занятием его группы. Если предмет группового занятия помечен как
"(N подгруппа)", мы не знаем, входит ли конкретный студент именно в эту
подгруппу (ростер подгрупп не приходит ни в одном из форматов) — такой
конфликт помечается is_certain=False, чтобы методист перепроверил вручную,
а не как жёсткая ошибка.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import defaultdict

from app.models import Conflict, ConflictType, Lesson, LessonType
from app.parsers.common import strip_academic_title

_SUBGROUP_RE = re.compile(r"подгруппа", re.IGNORECASE)


def find_conflicts(lessons: list[Lesson]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    conflicts.extend(_find_by_key(lessons, _person_key, ConflictType.TEACHER_DOUBLE_BOOKED))
    conflicts.extend(_find_by_key(lessons, lambda l: l.room_normalized, ConflictType.ROOM_DOUBLE_BOOKED))
    conflicts.extend(_find_student_individual_conflicts(lessons))
    conflicts.extend(_find_student_vs_group_conflicts(lessons))
    # Стабильная сортировка: внутри каждого типа накладки идут по дню и времени
    # (а не в порядке чтения файлов) — так их удобно сверять с расписанием.
    conflicts.sort(key=lambda c: (c.day_of_week, min(c.lesson_a.start_minutes, c.lesson_b.start_minutes)))
    return conflicts


def _overlaps(a: Lesson, b: Lesson) -> bool:
    return a.start_minutes < b.end_minutes and b.start_minutes < a.end_minutes


def _person_key(lesson: Lesson) -> str | None:
    """Ключ для сопоставления 'один и тот же человек' между записями. Убираем
    учёное звание/должность (доц./проф./ст.преп./асс.) и регистр — иначе
    'Долгачева С.А.' (Формат 1) и 'доц. Долгачева С.А.' (Формат 2, тот же
    человек) считались бы разными людьми и реальная накладка пропускалась бы."""
    name = lesson.teacher_name or lesson.accompanist_name
    if name is None:
        return None
    return strip_academic_title(name).casefold()


def _lesson_role(lesson: Lesson) -> str | None:
    if lesson.teacher_name:
        return "teacher"
    if lesson.accompanist_name:
        return "accompanist"
    return None


def _student_key(lesson: Lesson) -> str | None:
    if not lesson.student_name:
        return None
    return re.sub(r"\s+", " ", lesson.student_name).strip().lower()


def _surnames_similar(a: str, b: str) -> bool:
    """Фамилии совпали точно либо различаются опечаткой ('Становакина' /
    'Становкина'). Фамилии, где одна — начало другой ('Иванов' / 'Иванова',
    'Петров' / 'Петрова'), опечаткой НЕ считаем: это, скорее всего, два
    разных человека (например, брат и сестра)."""
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5 or a.startswith(b) or b.startswith(a):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def _names_similar(a: str | None, b: str | None) -> bool:
    """Сравнение ФИО студента с допуском на опечатки между файлами разных
    преподавателей (реально встретилось: 'Малиновская Мариэтта' / 'Мариэта',
    'Медведева Ананда' / 'Анада', 'Становакина Юлия' / 'Становкина Юлия').
    Остальная часть ФИО должна быть достаточно похожей, а фамилия — совпасть
    или отличаться только опечаткой (см. _surnames_similar), иначе рискуем
    перепутать двух разных студентов."""
    if not a or not b:
        return False
    if a == b:
        return True
    a_tokens, b_tokens = a.split(), b.split()
    if not a_tokens or not b_tokens or not _surnames_similar(a_tokens[0], b_tokens[0]):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _is_joint_teacher_accompanist_lesson(a: Lesson, b: Lesson) -> bool:
    """Один и тот же студент одновременно у преподавателя-специалиста и у
    концертмейстера, в одной аудитории — обычная практика (аккомпанемент на
    уроке специальности/ансамбля), а НЕ накладка. Без этого исключения почти
    каждое такое совместное занятие ложно засчитывалось бы и как "студент в
    двух местах", и как "аудитория занята дважды" — на реальных данных кафедры
    это оказалось самым массовым источником ложных срабатываний."""
    if a.lesson_type != LessonType.INDIVIDUAL or b.lesson_type != LessonType.INDIVIDUAL:
        return False
    if not _names_similar(_student_key(a), _student_key(b)):
        return False
    if not a.room_normalized or a.room_normalized != b.room_normalized:
        return False
    return {_lesson_role(a), _lesson_role(b)} == {"teacher", "accompanist"}


def _find_by_key(lessons: list[Lesson], key_fn, ctype: ConflictType) -> list[Conflict]:
    buckets: dict[tuple, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        key = key_fn(lesson)
        if key is None:
            continue
        buckets[(lesson.day_of_week, key)].append(lesson)

    out: list[Conflict] = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda l: l.start_minutes)
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group[j].start_minutes >= group[i].end_minutes:
                    break  # отсортировано по началу — дальше пересечений с i не будет
                if not _overlaps(group[i], group[j]):
                    continue
                if _is_joint_teacher_accompanist_lesson(group[i], group[j]):
                    continue
                out.append(Conflict(ctype, group[i].day_of_week, group[i], group[j]))
    return out


def _subjects_similar(a: str | None, b: str | None) -> bool:
    a, b = (a or "").casefold().strip(), (b or "").casefold().strip()
    if not a or not b:
        return True  # нечего сравнивать — не придираемся
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _make_pairing(a: Lesson, b: Lesson) -> Conflict:
    """Преподаватель + концертмейстер у одного студента в одном кабинете — не
    накладка, а пара для сверки. Если предметы расходятся (или это "специальный
    инструмент", где концертмейстера обычно нет) — помечаем is_certain=False,
    чтобы такие пары бросались в глаза на фоне обычных."""
    teacher_lesson, accomp_lesson = (a, b) if a.teacher_name else (b, a)
    note = None
    subject_text = f"{teacher_lesson.subject or ''} {accomp_lesson.subject or ''}".casefold()
    if "специальн" in subject_text:
        note = ("Концертмейстер указан на занятии по специальному инструменту — "
                "обычно там без концертмейстера, проверьте")
    elif not _subjects_similar(teacher_lesson.subject, accomp_lesson.subject):
        note = (f"Предметы разные: «{teacher_lesson.subject}» у преподавателя и "
                f"«{accomp_lesson.subject}» у концертмейстера — проверьте, что концертмейстер "
                "указан у нужного занятия")
    return Conflict(
        ConflictType.ACCOMPANIST_PAIRING, teacher_lesson.day_of_week, teacher_lesson, accomp_lesson,
        is_certain=note is None, note=note,
    )


def _find_student_individual_conflicts(lessons: list[Lesson]) -> list[Conflict]:
    # Группируем только по дню (не по точному ФИО) и сравниваем во временном
    # скользящем окне — иначе опечатка в ФИО студента между файлами двух
    # преподавателей ('Ананда' / 'Анада') развела бы одну и ту же запись по
    # разным корзинам и реальная накладка/совместное занятие была бы пропущена.
    by_day: dict[int, list[Lesson]] = defaultdict(list)
    for l in lessons:
        if l.lesson_type == LessonType.INDIVIDUAL and l.student_name:
            by_day[l.day_of_week].append(l)

    out: list[Conflict] = []
    for day, group in by_day.items():
        group.sort(key=lambda l: l.start_minutes)
        for i in range(len(group)):
            a = group[i]
            for j in range(i + 1, len(group)):
                b = group[j]
                if b.start_minutes >= a.end_minutes:
                    break
                if not _overlaps(a, b):
                    continue
                if not _names_similar(_student_key(a), _student_key(b)):
                    continue
                if _is_joint_teacher_accompanist_lesson(a, b):
                    out.append(_make_pairing(a, b))
                    continue
                role_a, role_b = _lesson_role(a), _lesson_role(b)
                if role_a and role_b and role_a != role_b:
                    # Преподаватель + концертмейстер одновременно, но НЕ в одной
                    # аудитории (или аудитория не указана хотя бы у одного) — похоже
                    # на то же совместное занятие с опечаткой/пропуском в номере
                    # кабинета, но не исключено, что это реальная накладка.
                    out.append(Conflict(
                        ConflictType.STUDENT_DOUBLE_BOOKED, a.day_of_week, a, b,
                        is_certain=False,
                        note=(
                            "Преподаватель и концертмейстер одновременно, но аудитории "
                            "не совпадают (или не указаны) — возможно, это то же "
                            "совместное занятие с опечаткой в кабинете, а не реальная накладка"
                        ),
                    ))
                    continue
                out.append(Conflict(ConflictType.STUDENT_DOUBLE_BOOKED, a.day_of_week, a, b))
    return out


def _find_student_vs_group_conflicts(lessons: list[Lesson]) -> list[Conflict]:
    individual = [
        l for l in lessons
        if l.lesson_type == LessonType.INDIVIDUAL and l.student_name and l.group_normalized
    ]
    group_lessons = [l for l in lessons if l.lesson_type == LessonType.GROUP]

    by_day_group: dict[tuple[int, str], list[Lesson]] = defaultdict(list)
    for gl in group_lessons:
        by_day_group[(gl.day_of_week, gl.group_normalized)].append(gl)
    for v in by_day_group.values():
        v.sort(key=lambda l: l.start_minutes)

    out: list[Conflict] = []
    for il in individual:
        candidates = by_day_group.get((il.day_of_week, il.group_normalized), [])
        for gl in candidates:
            if gl.start_minutes >= il.end_minutes:
                break
            if not _overlaps(il, gl):
                continue
            is_subgroup = bool(_SUBGROUP_RE.search(gl.subject or ""))
            out.append(
                Conflict(
                    ConflictType.STUDENT_VS_GROUP,
                    il.day_of_week,
                    il,
                    gl,
                    is_certain=not is_subgroup,
                    note=(
                        "Групповое занятие помечено как подгруппа — нет данных о "
                        "составе подгрупп, проверьте, входит ли студент именно в неё"
                        if is_subgroup else None
                    ),
                )
            )
    return out


def _lesson_signature(l: Lesson) -> list:
    return [
        l.lesson_type.value, l.start_minutes, l.duration_minutes,
        _person_key(l), _student_key(l), l.group_normalized, l.room_normalized,
        (l.subject or "").casefold(),
    ]


def conflict_key(c: Conflict) -> str:
    """Стабильный ключ накладки — по содержанию двух занятий (кто, когда, где,
    что), а НЕ по файлу/строке, откуда они прочитаны: так пометка «это не
    накладка» переживает повторную загрузку тех же файлов (строки в них
    могли сдвинуться). Порядок A/B не важен. Если методист поправит
    расписание и занятие изменится — ключ изменится и накладка вернётся
    в отчёт сама, как и должно быть."""
    sigs = sorted([_lesson_signature(c.lesson_a), _lesson_signature(c.lesson_b)], key=json.dumps)
    raw = json.dumps([c.type.value, c.day_of_week, sigs], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
