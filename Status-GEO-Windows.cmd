@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\geo-personal.ps1" status
set "rc=%errorlevel%"
pause
exit /b %rc%
