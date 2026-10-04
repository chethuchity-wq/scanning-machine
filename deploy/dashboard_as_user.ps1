# Run the dashboard as a Windows user instead of SYSTEM, so PDF / Print works:
# Windows does not let Microsoft Word start under the SYSTEM account
# ("Access is denied"). Run by deploy\dashboard_as_user.bat (as administrator).
#
# Without a password (Enter) the task uses Windows' "do not store password"
# logon (S4U): it runs as the user while nobody is signed in, and keeps
# working when the password changes. With a password, the task stores it, and
# this must be run again whenever that password changes.

$ErrorActionPreference = "Stop"
$task = "Ultrasound Dashboard"
function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

Say "=== Dashboard as a Windows user (needed for PDF / Print) ===" Cyan
$user = "$env:USERDOMAIN\$env:USERNAME"
Say "The dashboard will run as $user."
Say "Press Enter to run it without storing a password (recommended), or type the"
Say "Windows password of $user if Windows asks for it at sign-in and Enter alone fails."
$secure = Read-Host "Password for $user (Enter = none)" -AsSecureString
$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

try {
    # Task Scheduler's COM interface: re-registers the existing task with only
    # its account changed, keeping the action, trigger and settings
    $service = New-Object -ComObject Schedule.Service
    $service.Connect()
    $folder = $service.GetFolder("\")
    $definition = $folder.GetTask($task).Definition
    $definition.Principal.RunLevel = 1                    # highest privileges
    if ($password) {
        $folder.RegisterTaskDefinition($task, $definition, 6, $user, $password, 1) | Out-Null   # 1 = stored password
    } else {
        $folder.RegisterTaskDefinition($task, $definition, 6, $user, $null, 2) | Out-Null       # 2 = S4U, no password
    }
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
