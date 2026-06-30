@echo off
REM ============================================================
REM  Run the Ultrasound DICOM Reporting Pipeline
REM  Usage:
REM    run.bat folder "D:\DICOM_Export"
REM    run.bat watch
REM    run.bat list
REM    run.bat study <study-id>
REM    run.bat search --name "Kumar*"
REM ============================================================

if not exist ".venv\Scripts\activate.bat" (
    echo [!] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python pipeline.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [!] Pipeline exited with an error.
    pause
)
