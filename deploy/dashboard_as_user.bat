@echo off
rem Run the dashboard as this Windows user so PDF / Print can use Microsoft
rem Word. Also run it after changing this user's Windows password.

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

title Dashboard as a Windows user
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard_as_user.ps1"
echo.
pause
