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


def test_download_new_exe_writes_response_bytes(tmp_path, monkeypatch):
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"fake-exe-bytes"

    monkeypatch.setattr(self_update.urllib.request, "urlopen", lambda req, timeout=60: _FakeResponse())

    dest = tmp_path / "CafedraSchedule.exe.new"
    self_update.download_new_exe("https://example/CafedraSchedule.exe", str(dest))

    assert dest.read_bytes() == b"fake-exe-bytes"
