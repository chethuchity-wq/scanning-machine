@echo off
REM ============================================================
REM  Build the release zip to send to a clinic (run on YOUR PC).
REM
REM  Packs the last commit with `git archive`, so the zip holds
REM  only tracked files: never config_local.py, data\, reports\
REM  or .venv. Output: dist\scanning-machine-<commit>.zip
REM
REM  At the clinic: extract it, double-click setup.bat.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0.."

set "DIRTY="
for /f %%L in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo [!] You have uncommitted changes. The zip contains only the LAST COMMIT:
    git status --short
    echo.
    choice /m "Build the zip from the last commit anyway"
    if errorlevel 2 exit /b 1
)

for /f %%H in ('git rev-parse --short HEAD') do set "HASH=%%H"
if not exist dist mkdir dist
set "ZIP=dist\scanning-machine-%HASH%.zip"
git archive --format=zip --prefix=scanning-machine/ -o "%ZIP%" HEAD
if errorlevel 1 (
    echo [!] git archive failed.
    pause
    exit /b 1
)

echo.
echo [OK] Built %CD%\%ZIP%
echo      Send it to the clinic PC, extract it, and double-click setup.bat.
pause
