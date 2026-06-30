@echo off
REM ============================================================
REM  Deploy with Docker (alternative to install.bat)
REM  Requires: Docker Desktop installed
REM ============================================================

echo.
echo ============================================================
echo   Ultrasound DICOM Pipeline - Docker Deployment
echo ============================================================
echo.

docker --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Docker not found. Install Docker Desktop from:
    echo     https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo [*] Building container...
docker-compose build

echo.
echo [*] Starting pipeline in watch mode...
echo     Reports will be saved to: .\reports\
echo     Press Ctrl+C to stop.
echo.
docker-compose up
