@echo off
rem Shared setup for the Studio launchers: Studio code on PYTHONPATH and
rem studio\applio as the working folder (models, logs, datasets live here).
set "ROOT=%~dp0..\..\"
if not exist "%ROOT%env\python.exe" (
    echo [ERROR] Python environment not found. Run run-install.bat first.
    pause
    exit /b 1
)
set "PYTHONPATH=%ROOT%core\src;%ROOT%studio\engine\src"
set "PYTHON=%ROOT%env\python.exe"
cd /d "%~dp0"
if not exist "assets\config.json" copy /y "assets\config_template.json" "assets\config.json" >nul
exit /b 0
