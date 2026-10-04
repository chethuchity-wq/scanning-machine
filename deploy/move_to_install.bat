@echo off
rem Move a system running from a development (git) folder onto a normal
rem installation in C:\scanning-machine. See move_to_install.ps1.

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

title Move to the installed copy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0move_to_install.ps1"
echo.
pause
