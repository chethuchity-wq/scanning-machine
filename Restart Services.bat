@echo off
rem Double-click to restart Orthanc, the report pipeline and the dashboard,
rem and check they are running. Asks for administrator rights.
rem Works from any folder: a copy of this file outside the program folder
rem uses the program at C:\scanning-machine (setup.bat's install folder) or
rem C:\Donttouch\scanning-machine.

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "SCRIPT=%~dp0tools\restart_services.ps1"
if not exist "%SCRIPT%" set "SCRIPT=C:\scanning-machine\tools\restart_services.ps1"
if not exist "%SCRIPT%" set "SCRIPT=C:\Donttouch\scanning-machine\tools\restart_services.ps1"
if not exist "%SCRIPT%" (
    echo Cannot find the program folder C:\scanning-machine
    pause
    exit /b 1
)

title Restart ultrasound reporting services
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
pause
