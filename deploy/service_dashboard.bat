@echo off
REM ============================================================
REM  Run by the "Ultrasound Dashboard" scheduled task (setup.bat
REM  creates it). Keeps the dashboard alive on port 8000: if it
REM  exits for any reason it is restarted after 30 seconds.
REM  Output goes to logs\dashboard.log.
REM ============================================================
cd /d "%~dp0.."
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1

:loop
for %%F in (logs\dashboard.log) do if %%~zF GTR 10000000 move /y logs\dashboard.log logs\dashboard.old.log >nul
echo [%date% %time%] starting dashboard>> logs\dashboard.log
".venv\Scripts\python.exe" -m uvicorn webapp.main:app --host 0.0.0.0 --port 8000 >> logs\dashboard.log 2>&1
echo [%date% %time%] dashboard exited with code %errorlevel%, restarting in 30s>> logs\dashboard.log
ping -n 31 127.0.0.1 >nul
goto loop
