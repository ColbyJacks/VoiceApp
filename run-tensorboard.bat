@echo off
title Tensorboard
setlocal
call "%~dp0studio\applio\_studio_env.bat" || exit /b 1

"%PYTHON%" core.py tensorboard
echo.
pause
