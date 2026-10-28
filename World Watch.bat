@echo off
rem World Watch - double-click to start. It catches up on whatever happened while the PC was off,
rem builds Morning Recon, opens it, and keeps collecting until you close this window.
title World Watch
cd /d "%~dp0"
py -3.13 -m worldwatch start
rem 0: stopped cleanly. 2: already running in another window (the message shows for 5 s).
rem Anything else, negative crash codes included: keep the window open to read the error.
if "%errorlevel%"=="0" exit /b 0
if "%errorlevel%"=="2" (timeout /t 5 >nul & exit /b 2)
pause
