"""Крошечный безопасный разбор «markdown-лайт» для текста релиза из GitHub:
заголовки (#), маркированные списки (- / *), **жирный**, абзацы. Всё прочее —
обычный текст. Любой HTML в исходнике экранируется, поэтому текст релиза
нельзя использовать для подстановки разметки/скриптов в окно программы.
"""
from __future__ import annotations

import re

from markupsafe import Markup, escape

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    return _BOLD_RE.sub(r"<b>\1</b>", str(escape(text)))


def render_markdown_lite(text: str | None) -> Markup:
    if not text:
        return Markup("")
    out: list[str] = []
    in_list = False
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush_para()
            close_list()
        elif re.match(r"^[-*]\s+", line):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + _inline(re.sub(r"^[-*]\s+", "", line)) + "</li>")
        elif line.startswith("#"):
            flush_para()
            close_list()
            out.append("<h4>" + _inline(line.lstrip("#").strip()) + "</h4>")
        else:
            close_list()
            para.append(line)
    flush_para()
    close_list()
    return Markup("".join(out))
