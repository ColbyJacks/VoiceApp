@echo off
rem Starts Voice App. The first run installs the app's Node packages (~100 MB).
setlocal
cd /d "%~dp0app"

where node >nul 2>nul
if errorlevel 1 (
    echo Voice App needs Node.js: https://nodejs.org
    pause
    exit /b 1
)

if not exist "node_modules\electron\package.json" (
    echo Installing Voice App, first run only...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

node scripts\ensure-electron.js
if errorlevel 1 (
    pause
    exit /b 1
)

start "" "node_modules\electron\dist\electron.exe" .
