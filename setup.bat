@echo off
REM ============================================================
REM  Ultrasound DICOM Reporting Pipeline - one-step clinic setup
REM
REM  Extract the release zip anywhere (e.g. Downloads), then
REM  double-click this file. It will:
REM    1. ask for administrator rights
REM    2. stop the running pipeline/dashboard (when updating)
REM    3. copy the program to C:\scanning-machine
REM       (config_local.py, data, reports and watch_state.json
REM        there are never overwritten)
REM    4. install Python 3.11 if no 3.11/3.12 is present
REM    5. create .venv and install requirements.txt
REM    6. run deploy\setup_helper.py: clinic config, Orthanc
REM       check, firewall, power settings, auto-start tasks,
REM       first-login setup token
REM
REM  Run it again with a newer zip to update - same steps.
REM ============================================================
setlocal EnableExtensions
set "INSTALL_DIR=C:\scanning-machine"
set "PY_VERSION=3.11.9"
cd /d "%~dp0"

if not exist "requirements.txt" (
    echo [!] requirements.txt not found next to setup.bat.
    echo     Extract the whole zip first ^(right-click - Extract All^),
    echo     then run setup.bat from the extracted folder.
    pause
    exit /b 1
)

REM --- Elevate: scheduled tasks, firewall and Python install need admin ---
net session >nul 2>&1
if errorlevel 1 (
    echo Asking for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ============================================================
echo   Ultrasound DICOM Reporting Pipeline - Setup
if exist "VERSION" for /f "usebackq delims=" %%V in ("VERSION") do echo   Version %%V
echo   Installing to %INSTALL_DIR%
echo ============================================================
echo.

REM --- 1. Stop running services so files and packages can be replaced ---
call :stop_services

REM --- 2. Copy program files into the install folder ---
set "SRC=%~dp0"
set "SRC=%SRC:~0,-1%"
if /i "%SRC%"=="%INSTALL_DIR%" goto :copied
echo [*] Copying program files to %INSTALL_DIR% ...
robocopy "%SRC%" "%INSTALL_DIR%" /E /XD .venv .git data reports measurements dicom_cache dicom_input logs dist __pycache__ /XF config_local.py watch_state.json /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo [!] Copy to %INSTALL_DIR% failed.
    pause
    exit /b 1
)
:copied
cd /d "%INSTALL_DIR%"
echo [OK] Program files in %INSTALL_DIR%
echo.

REM --- 3. Python 3.11 / 3.12 ---
set "PY="
call :find_python
if not defined PY call :install_python
if not defined PY (
    echo [!] Could not find or install Python 3.11. Install it by hand from
    echo     https://www.python.org/downloads/windows/ ^(tick "Add python.exe to PATH"^)
    echo     and run setup.bat again.
    pause
    exit /b 1
)
echo [OK] Using Python: %PY%
echo.

REM --- 4. Virtual environment + dependencies ---
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [!] Creating .venv failed.
        pause
        exit /b 1
    )
)
echo [*] Installing Python packages ^(first run takes a few minutes^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo [!] Package install failed - check the internet connection and run setup.bat again.
    pause
    exit /b 1
)
echo [OK] Packages installed.
echo.

REM --- 5. Configuration, Orthanc check, auto-start tasks ---
".venv\Scripts\python.exe" deploy\setup_helper.py
echo.
pause
exit /b 0


REM ============================================================
:stop_services
schtasks /End /TN "Ultrasound Pipeline" >nul 2>&1
schtasks /End /TN "Ultrasound Dashboard" >nul 2>&1
REM Ending a task does not always kill its child python.exe; kill those too.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'service_pipeline|service_dashboard|pipeline\.py.+watch|webapp\.main:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
exit /b 0

:find_python
REM Dockerfile pins 3.11; very new Pythons regularly break compiled dependencies.
py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11" && exit /b 0
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12" && exit /b 0
if exist "%ProgramFiles%\Python311\python.exe" set PY="%ProgramFiles%\Python311\python.exe"& exit /b 0
python -c "import sys; sys.exit(sys.version_info[:2] not in ((3, 11), (3, 12)))" >nul 2>&1 && set "PY=python"
exit /b 0

:install_python
echo [*] Python 3.11/3.12 not found - downloading Python %PY_VERSION% ^(about 25 MB^)...
set "PYINST=%TEMP%\python-%PY_VERSION%-amd64.exe"
curl.exe -L --fail --silent --show-error -o "%PYINST%" "https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
if errorlevel 1 (
    echo [!] Download failed.
    exit /b 0
)
echo [*] Installing Python %PY_VERSION% for all users...
"%PYINST%" /quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0
del "%PYINST%" >nul 2>&1
call :find_python
exit /b 0
