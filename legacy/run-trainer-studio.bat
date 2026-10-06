@echo off
title Voice Trainer Studio
setlocal

if not exist env (
    echo [ERROR] Virtual environment 'env' not found. Please run run-install.bat first.
    pause
    exit /b 1
)

echo Starting Voice Trainer Studio...
env\python.exe voice_trainer_studio.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
