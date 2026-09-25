"""Конвертация legacy .doc (Word 97-2003, бинарный OLE-формат) в .docx.

python-docx умеет читать только .docx (это на самом деле zip+XML), а .doc —
совсем другой бинарный формат, так что читать его напрямую нельзя.

На машине методиста/кафедры обычно уже стоит MS Word — используем его через
COM-автоматизацию (pywin32), чтобы не тащить в проект отдельную установку
LibreOffice. Если Word не найден, используем LibreOffice (soffice --headless),
если он есть. Если нет ни того, ни другого — явная ошибка с понятной подсказкой.
"""
from __future__ import annotations

import os
import shutil
import subprocess

WD_FORMAT_DOCX = 16  # wdFormatXMLDocument


def convert_doc_to_docx(src_path: str, out_dir: str) -> str:
    """Конвертирует один .doc в .docx, кладёт результат в out_dir. Возвращает путь к .docx."""
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    out_path = os.path.join(out_dir, stem + ".docx")

    if _try_convert_with_word(src_path, out_path):
        return out_path
    if _try_convert_with_libreoffice(src_path, out_dir):
        return out_path
    raise RuntimeError(
        "Не удалось сконвертировать .doc в .docx: не найден ни MS Word (pywin32), "
        "ни LibreOffice (soffice --headless) в PATH."
    )


def _try_convert_with_word(src_path: str, out_path: str) -> bool:
    try:
        import win32com.client
    except ImportError:
        return False

    src_abs = os.path.abspath(src_path)
    out_abs = os.path.abspath(out_path)

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0  # wdAlertsNone
    try:
        doc = word.Documents.Open(src_abs, ReadOnly=True)
        try:
            doc.SaveAs2(out_abs, FileFormat=WD_FORMAT_DOCX)
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return os.path.exists(out_path)


def _try_convert_with_libreoffice(src_path: str, out_dir: str) -> bool:
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if not soffice:
        return False
    subprocess.run(
        [soffice, "--headless", "--convert-to", "docx", "--outdir", out_dir, src_path],
        check=True, capture_output=True,
    )
    return True
