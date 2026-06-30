@echo off
REM ============================================================
REM  Ultrasound DICOM Reporting Pipeline - Windows Installer
REM  Double-click this file to set up everything.
REM ============================================================

echo.
echo ============================================================
echo   Ultrasound DICOM Reporting Pipeline - Setup
echo   Ganesh Healthcare
echo ============================================================
echo.

REM --- Check if Python is installed ---
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Python not found. Please install Python 3.10+ from:
    echo     https://www.python.org/downloads/
    echo.
    echo     IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

REM --- Create virtual environment ---
echo [*] Creating virtual environment...
if not exist ".venv" (
    python -m venv .venv
)
echo [OK] Virtual environment ready.
echo.

REM --- Activate venv and install dependencies ---
echo [*] Installing Python dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
echo.
echo [OK] Dependencies installed.
echo.

REM --- Check Tesseract ---
tesseract --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Tesseract OCR not found.
    echo     The pipeline works WITHOUT Tesseract (using SR data only).
    echo     For OCR support, install from:
    echo     https://github.com/UB-Mannheim/tesseract/wiki
    echo.
    echo     After installing, update TESSERACT_CMD in config.py
    echo.
) else (
    echo [OK] Tesseract OCR found.
)

REM --- Create output directories ---
if not exist "reports" mkdir reports
if not exist "measurements" mkdir measurements
if not exist "dicom_cache" mkdir dicom_cache

echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo   To process a DICOM folder:
echo     run.bat folder "D:\DICOM_Export"
echo.
echo   To watch Orthanc for new studies:
echo     run.bat watch
echo.
echo   To list studies on Orthanc:
echo     run.bat list
echo.
echo   Edit config.py to set your Orthanc server IP and clinic info.
echo.
pause
