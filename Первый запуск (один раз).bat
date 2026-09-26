@echo off
setlocal
cd /d "%~dp0"

echo === First-time setup ===
echo Creating Python virtual environment...
py -3 -m venv .venv
if errorlevel 1 (
    echo.
    echo ERROR: Python not found. Install Python 3.11+ from python.org first
    echo ^(check "Add python.exe to PATH" during install^), then run this again.
    pause
    exit /b 1
)

echo Installing dependencies, this can take a minute...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt --quiet

echo.
echo === Done ===
echo Now use "Обновить и запустить.bat" every time you want to run the app.
pause
