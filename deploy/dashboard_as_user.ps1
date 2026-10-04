# Run the dashboard as a Windows user instead of SYSTEM, so PDF / Print works:
# Windows does not let Microsoft Word start under the SYSTEM account
# ("Access is denied"). Run by deploy\dashboard_as_user.bat (as administrator).
# Run it again whenever that user's Windows password changes - the dashboard
# cannot start with an old password.

$ErrorActionPreference = "Stop"
$task = "Ultrasound Dashboard"
function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

Say "=== Dashboard as a Windows user (needed for PDF / Print) ===" Cyan
$user = "$env:USERDOMAIN\$env:USERNAME"
Say "The dashboard will run as $user. Enter that user's Windows password."
Say "(It is kept by Windows Task Scheduler, the same as for any scheduled task.)"
$secure = Read-Host "Password for $user" -AsSecureString
$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

try {
    Set-ScheduledTask -TaskName $task -User $user -Password $password | Out-Null
} catch {
    Say "Could not change the task: $($_.Exception.Message)" Red
    Say "Check the password and run this again." Red
    exit 1
}
Say "  The dashboard now runs as $user." Green

Say "Restarting the dashboard..."
Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "webapp\.main:app" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $task

for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 3 | Out-Null; $up = $true; break }
    catch { if ($_.Exception.Response) { $up = $true; break } }
    Start-Sleep -Seconds 1
}
if ($up) {
    Say "  Dashboard is running. Open a report and try PDF / Print." Green
} else {
    Say "  The dashboard did not start - see C:\scanning-machine\logs\dashboard.log" Red
}
