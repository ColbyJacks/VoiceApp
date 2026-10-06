@echo off
title VoiceAppStudio (Voice Trainer)
setlocal
call "%~dp0studio\applio\_studio_env.bat" || exit /b 1

echo Starting VoiceAppStudio...
"%PYTHON%" voice_trainer_studio.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo VoiceAppStudio exited with error code %ERRORLEVEL%.
    pause
)
