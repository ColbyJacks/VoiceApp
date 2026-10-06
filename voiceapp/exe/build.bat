@echo off
rem Builds dist\VoiceApp\VoiceApp.exe with PyInstaller.
rem
rem   build.bat [python.exe] [folder with rvc\models to copy]
rem
rem python.exe: an environment with voiceapp\requirements.txt and pyinstaller
rem             installed (default: ..\..\env\python.exe).
rem rvc\models source: where the base models already are, so the exe works
rem             offline on first run (default: ..\tray). Skipped if missing;
rem             the exe then offers to download them.
setlocal
set "HERE=%~dp0"
set "PY=%~1"
if "%PY%"=="" set "PY=%HERE%..\..\env\python.exe"
set "MODELS_SRC=%~2"
if "%MODELS_SRC%"=="" set "MODELS_SRC=%HERE%..\tray"

"%PY%" "%HERE%make_icon.py" || exit /b 1
"%PY%" -m PyInstaller --noconfirm --clean --distpath "%HERE%dist" --workpath "%HERE%build" "%HERE%voiceapp.spec" || exit /b 1

set "OUT=%HERE%dist\VoiceApp"
if not exist "%OUT%\models" mkdir "%OUT%\models"
for %%D in (embedders predictors formant) do (
    if exist "%MODELS_SRC%\rvc\models\%%D" robocopy "%MODELS_SRC%\rvc\models\%%D" "%OUT%\rvc\models\%%D" /E /NFL /NDL /NJH /NJS /NP >nul
)
echo.
echo Built %OUT%\VoiceApp.exe
echo Put your .pth and .index voices in %OUT%\models
