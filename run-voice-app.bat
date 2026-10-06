@echo off
title Voice App (Real-Time Voice Tray)
setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%env\python.exe" (
    echo [ERROR] Python environment not found. Run "run-install.bat voiceapp" first.
    pause
    exit /b 1
)

rem Voice App code: the shared core. Its data lives in voiceapp\tray\
rem (models\ for your .pth voices, rvc\models\ for the base models).
set "PYTHONPATH=%ROOT%core\src;%ROOT%voiceapp\engine\src"
cd /d "%ROOT%voiceapp\tray"

if not exist "rvc\models\predictors\rmvpe.pt" (
    echo Downloading the base models Voice App needs, first run only...
    "%ROOT%env\python.exe" -c "from rvc.lib.tools.prerequisites_download import prequisites_download_pipeline as p; p(False, True, False)"
)

echo Starting Voice App...
"%ROOT%env\python.exe" voice_tray_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Voice App exited with error code %ERRORLEVEL%.
    pause
)
