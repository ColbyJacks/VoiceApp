@echo off
title Mic Modulator (Real-Time Voice Tray)
setlocal

if not exist env (
    echo [ERROR] Virtual environment 'env' not found. Please run run-install.bat first.
    pause
    exit /b 1
)

echo Starting Real-Time Voice Modulator...
env\python.exe voice_tray_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
