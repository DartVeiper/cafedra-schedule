@echo off
setlocal
cd /d "%~dp0"

echo === Building CafedraSchedule.exe ===
"..\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --name CafedraSchedule --onefile ^
  --add-data "app/templates;app/templates" ^
  --add-data "app/static;app/static" ^
  desktop_app.py

echo.
echo === Done ===
echo Result: backend\dist\CafedraSchedule.exe
pause
