@echo off
title Applio (web UI, part of VoiceAppStudio)
setlocal
call "%~dp0studio\applio\_studio_env.bat" || exit /b 1

"%PYTHON%" app.py --open
echo.
pause
