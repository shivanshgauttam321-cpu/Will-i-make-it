@echo off
title Will I Make It - Backend
echo ========================================================
echo       Will I Make It - Backend Server
echo ========================================================
echo.

cd /d "%~dp0backend"

:: Detect Python executable with fastapi installed
set "PYTHON_CMD="
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    set "PYTHON_CMD=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
) else if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PYTHON_CMD=%USERPROFILE%\anaconda3\python.exe"
) else (
    set "PYTHON_CMD=python"
)

echo Using Python: %PYTHON_CMD%
echo.

echo Starting Uvicorn on http://127.0.0.1:8000...
echo API Docs will be available at http://127.0.0.1:8000/docs
echo.

"%PYTHON_CMD%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
