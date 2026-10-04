# Restart everything the reporting system needs, then check it is working:
#   1. Orthanc (Windows service) - receives the scans from the scanner
#   2. Ultrasound Pipeline (scheduled task) - makes the reports
#   3. Ultrasound Dashboard (scheduled task) - http://localhost:8000
# Run by "Restart Services.bat" (as administrator: the running pipeline and
# dashboard can only be stopped from an admin shell).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$tasks = "Ultrasound Pipeline", "Ultrasound Dashboard"

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

function Wait-Url($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            # Any HTTP answer (even 401/404) means the server is up
            if ($_.Exception.Response) { return $true }
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-OurPython {
    # The pipeline and dashboard python processes (the venv launcher and the
    # interpreter it starts both carry the command line)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "pipeline\.py\s+watch|webapp\.main:app" }
}

Say "=== Restarting the ultrasound reporting services ===" Cyan
Say ""

# --- Stop -------------------------------------------------------------------
Say "Stopping pipeline and dashboard..."
foreach ($t in $tasks) { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }
Get-OurPython | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# Anything still holding the dashboard's port
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
if (Get-OurPython) { Say "  Warning: some processes did not stop" Yellow } else { Say "  Stopped." }

# --- Orthanc ----------------------------------------------------------------
Say "Restarting Orthanc..."
Restart-Service -Name Orthanc -Force -ErrorAction SilentlyContinue
$orthancOk = Wait-Url "http://localhost:8042/system" 60

# --- Start ------------------------------------------------------------------
Say "Starting pipeline and dashboard..."
foreach ($t in $tasks) {
    Enable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
    Start-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
}
$dashboardOk = Wait-Url "http://localhost:8000/" 90

# The pipeline is up once its log says it is watching Orthanc again
$pipelineOk = $false
$logStart = (Get-Item "data\pipeline.log" -ErrorAction SilentlyContinue).Length
for ($i = 0; $i -lt 90 -and -not $pipelineOk; $i++) {
    Start-Sleep -Seconds 1
    $running = (Get-ScheduledTask -TaskName "Ultrasound Pipeline").State -eq "Running"
    $log = Get-Content "data\pipeline.log" -Tail 15 -ErrorAction SilentlyContinue
    $pipelineOk = $running -and ($log -match "Watching Orthanc") -and
        ((Get-Item "data\pipeline.log").Length -ne $logStart)
}

# --- Report -----------------------------------------------------------------
Say ""
Say "=== Status ===" Cyan
$all = $true
foreach ($item in @(
        @("Orthanc (scanner receiver)", $orthancOk, "service 'Orthanc' - check Services, or its log in C:\Program Files\Orthanc Server\Logs"),
        @("Pipeline (makes reports)", $pipelineOk, "see data\pipeline.log"),
        @("Dashboard (localhost:8000)", $dashboardOk, "see data\dashboard.log"))) {
    if ($item[1]) { Say ("  OK      " + $item[0]) Green }
    else { Say ("  FAILED  " + $item[0] + "  -> " + $item[2]) Red; $all = $false }
}
Say ""
if ($all) {
    Say "All services are running." Green
    Start-Process "http://localhost:8000/"
} else {
    Say "Last lines of the logs:" Yellow
    foreach ($f in "data\pipeline.log", "data\dashboard.log") {
        Say "--- $f" Yellow
        Get-Content $f -Tail 8 -ErrorAction SilentlyContinue | ForEach-Object { Say "  $_" }
    }
}
