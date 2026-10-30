@echo off
title Will I Make It - Tests and Diagnostics
echo ========================================================
echo       Will I Make It - Test Suite and Diagnostics
echo ========================================================
echo.

cd /d "%~dp0backend"

:: Detect Python executable with test dependencies installed
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

echo [1/2] Running Pytest Unit and Integration Tests (25 tests)...
echo ------------------------------------------------------------
"%PYTHON_CMD%" -m pytest tests/test_energy.py -v
echo.

echo [2/2] Running Neo4j Connection Diagnostic...
echo ------------------------------------------------------------
"%PYTHON_CMD%" test_neo4j.py
echo.

echo ========================================================
echo Test execution finished.
echo ========================================================
pause
