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

echo [*] Building and starting container (detached, auto-restarts on crash/reboot)...
docker-compose up -d --build

echo.
docker-compose ps
echo.
echo [OK] Pipeline is running in the background.
echo      Reports will be saved to: .\reports\
echo.
echo      View live logs:   docker-compose logs -f
echo      Stop the service:  docker-compose down
echo      Re-run this script any time to deploy an updated version.
echo.
pause
