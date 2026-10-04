@echo off
REM ============================================================
REM  Run by the "Ultrasound Pipeline" scheduled task (setup.bat
REM  creates it). Keeps `pipeline.py watch` alive: if it exits
REM  for any reason it is restarted after 30 seconds.
REM  Output goes to logs\pipeline.log.
REM ============================================================
cd /d "%~dp0.."
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1

:loop
REM Keep one old log, so the file cannot fill the disk
for %%F in (logs\pipeline.log) do if %%~zF GTR 10000000 move /y logs\pipeline.log logs\pipeline.old.log >nul
echo [%date% %time%] starting pipeline watch>> logs\pipeline.log
".venv\Scripts\python.exe" pipeline.py watch >> logs\pipeline.log 2>&1
echo [%date% %time%] pipeline exited with code %errorlevel%, restarting in 30s>> logs\pipeline.log
REM `timeout` fails without a console (task runs as SYSTEM); ping waits instead
ping -n 31 127.0.0.1 >nul
goto loop
