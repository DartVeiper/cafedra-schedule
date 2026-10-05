"""Логика самообновления, которую можно проверить без реальной Windows/exe:
доступность фичи (только для frozen exe на Windows) и содержимое
bat-помощника, который подменяет файл после выхода текущего процесса."""
from __future__ import annotations

from app import self_update


def test_can_self_update_false_in_dev_mode():
    # В тестах приложение не собрано PyInstaller'ом (sys.frozen не выставлен) —
    # самообновление должно быть недоступно, чтобы не ломать разработку из исходников.
    assert self_update.can_self_update() is False


def test_helper_script_contains_pid_and_paths():
    script = self_update.build_helper_script(
        pid=4242,
        new_path=r"C:\Cafedra\CafedraSchedule.exe.new",
        exe_path=r"C:\Cafedra\CafedraSchedule.exe",
    )

    assert "4242" in script
    assert r'"C:\Cafedra\CafedraSchedule.exe.new"' in script
    assert r'"C:\Cafedra\CafedraSchedule.exe"' in script
    assert script.startswith("@echo off")
    # Помощник должен дожидаться завершения процесса, а не подменять файл сразу
    assert "tasklist" in script
    assert script.index("tasklist") < script.index("move /y")


class _FakeResponse:
    def __init__(self, data: bytes, content_length: str | None = None):
        self._data = data
        self.headers = {"Content-Length": content_length} if content_length is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _serve(monkeypatch, data: bytes, content_length: str | None = None):
    monkeypatch.setattr(
        self_update.urllib.request, "urlopen",
        lambda req, timeout=60: _FakeResponse(data, content_length),
    )


def test_download_new_exe_writes_response_bytes(tmp_path, monkeypatch):
    _serve(monkeypatch, b"MZ-fake-exe-bytes", content_length="17")

    dest = tmp_path / "CafedraSchedule.exe.new"
    self_update.download_new_exe("https://example/CafedraSchedule.exe", str(dest), expected_size=17)

    assert dest.read_bytes() == b"MZ-fake-exe-bytes"
    assert not (tmp_path / "CafedraSchedule.exe.new.part").exists()


def test_truncated_download_is_rejected_and_leaves_no_file(tmp_path, monkeypatch):
    """Оборванная загрузка (Content-Length больше, чем пришло) не должна становиться .new —
    иначе подмена заменила бы рабочую программу битым файлом."""
    _serve(monkeypatch, b"MZ-half", content_length="5000")
    dest = tmp_path / "x.exe.new"

    try:
        self_update.download_new_exe("https://example/x.exe", str(dest))
    except ValueError as e:
        assert "не полностью" in str(e)
    else:
        raise AssertionError("ожидали ValueError")
    assert not dest.exists() and not (tmp_path / "x.exe.new.part").exists()


def test_download_with_wrong_expected_size_is_rejected(tmp_path, monkeypatch):
    _serve(monkeypatch, b"MZ-12345")
    try:
        self_update.download_new_exe("https://example/x.exe", str(tmp_path / "x.exe.new"), expected_size=999)
    except ValueError as e:
        assert "размер" in str(e)
    else:
        raise AssertionError("ожидали ValueError")


def test_download_that_is_not_an_exe_is_rejected(tmp_path, monkeypatch):
    """Страница ошибки GitHub вместо файла (HTML) — не программа."""
    _serve(monkeypatch, b"<html>Not Found</html>")
    try:
        self_update.download_new_exe("https://example/x.exe", str(tmp_path / "x.exe.new"))
    except ValueError as e:
        assert "не похож на программу" in str(e)
    else:
        raise AssertionError("ожидали ValueError")


def test_helper_script_keeps_backup_and_retries_swap():
    script = self_update.build_helper_script(1, r"C:\A\a.exe.new", r"C:\A\a.exe")

    # старый exe сначала уходит в .bak, и только потом на его место встаёт новый
    assert script.index(r'move /y "C:\A\a.exe" "C:\A\a.exe.bak"') < script.index(r'move /y "C:\A\a.exe.new" "C:\A\a.exe"')
    # если новый не встал — старый возвращается
    assert r'move /y "C:\A\a.exe.bak" "C:\A\a.exe"' in script
    # подмена повторяется, а не падает с первой попытки (файл бывает занят после выхода процесса)
    assert ":retry" in script and f"GEQ {self_update.MAX_SWAP_TRIES}" in script


def test_independent_launch_env_drops_pyinstaller_service_vars(monkeypatch):
    """Новая копия, запущенная из работающей onefile-программы, не должна унаследовать
    служебные переменные PyInstaller — иначе она считает себя дочерним процессом старой
    и падает при старте (поймано сквозным тестом на настоящей собранной программе)."""
    monkeypatch.setenv("_MEIPASS2", r"C:\Temp\_MEI123")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI123")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("CAFEDRA_KEEP_ME", "yes")

    env = self_update.independent_launch_env()

    assert "_MEIPASS2" not in env
    assert not [k for k in env if k.startswith("_PYI_")]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["CAFEDRA_KEEP_ME"] == "yes"  # остальное окружение (PATH, SystemRoot...) сохраняется
