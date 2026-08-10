@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\geo-personal.ps1" start
set "rc=%errorlevel%"
if not "%rc%"=="0" pause
exit /b %rc%
