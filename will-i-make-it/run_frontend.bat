@echo off
title Will I Make It - Frontend
echo ========================================================
echo       Will I Make It - Frontend UI
echo ========================================================
echo.

cd /d "%~dp0frontend"

echo Checking node_modules...
if not exist "node_modules\" (
    echo Installing npm dependencies...
    call npm install
)

echo.
echo Starting Vite Dev Server on http://localhost:5173...
echo.

call npm run dev

pause
