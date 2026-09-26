@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Please run "Первый запуск (один раз).bat" first.
    pause
    exit /b 1
)

echo === Checking for updates ===
git pull
if errorlevel 1 (
    echo.
    echo Could not update from GitHub ^(no internet, or git not installed^).
    echo Continuing with the version already on this computer...
    echo.
)

echo === Checking dependencies ===
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt --quiet

echo === Starting the app ===
echo Opening in your browser: http://127.0.0.1:8000
echo Close this window to stop the app.
start "" http://127.0.0.1:8000
".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --app-dir backend

pause
