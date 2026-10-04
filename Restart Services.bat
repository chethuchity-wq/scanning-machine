@echo off
rem Double-click to restart Orthanc, the report pipeline and the dashboard,
rem and check they are running. Asks for administrator rights.

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

title Restart ultrasound reporting services
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\restart_services.ps1"
echo.
pause
