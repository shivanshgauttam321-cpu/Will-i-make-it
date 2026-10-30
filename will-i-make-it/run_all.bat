@echo off
title Will I Make It - Launcher
echo ========================================================
echo       Will I Make It - EV Route Planner
echo       Starting Backend and Frontend Servers...
echo ========================================================
echo.

cd /d "%~dp0"

:: Start Backend in a separate window
echo [1/2] Starting Backend API Server (FastAPI on http://127.0.0.1:8000)...
start "Will I Make It - Backend API" cmd /k "call run_backend.bat"

:: Small delay to allow backend to initialize
timeout /t 3 /nobreak >nul

:: Start Frontend in a separate window
echo [2/2] Starting Frontend Dashboard (Vite on http://localhost:5173)...
start "Will I Make It - Frontend UI" cmd /k "call run_frontend.bat"

:: Small delay and open browser
timeout /t 3 /nobreak >nul
echo.
echo Opening browser to http://localhost:5173...
start http://localhost:5173

echo.
echo ========================================================
echo Both servers are running!
echo - Frontend:  http://localhost:5173
echo - Backend:   http://127.0.0.1:8000
echo - Swagger:   http://127.0.0.1:8000/docs
echo.
echo Press any key to close this launcher window (servers will remain running).
echo ========================================================
pause >nul
