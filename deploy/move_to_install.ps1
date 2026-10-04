# Move a system that runs straight from a development (git) folder onto a
# normal installation in C:\scanning-machine, made by setup.bat. Run by
# deploy\move_to_install.bat (as administrator).
#
#   1. builds the release zip from the last commit and extracts it
#   2. stops the pipeline and dashboard
#   3. copies this installation's data into C:\scanning-machine - settings
#      (config_local.py), database (data\), local reports (reports\) and the
#      Orthanc position (watch_state.json); setup.bat never overwrites these
#   4. runs setup.bat from the release: it installs the program next to that
#      data and re-registers the scheduled tasks for C:\scanning-machine
#
# The development folder is left as it was, so the move can be undone (see
# the end of this script's output).

$ErrorActionPreference = "Stop"
$dev = Split-Path -Parent $PSScriptRoot
$dest = "C:\scanning-machine"
$work = Join-Path $env:TEMP "scanning-machine-release"

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

Say "=== Move to an installed copy in $dest ===" Cyan
Say "From: $dev"
Say ""

# --- 1. Release from the last commit ---------------------------------------
Say "Building the release from the last commit..."
Set-Location $dev
$dirty = git status --porcelain
if ($dirty) {
    Say "  Note: uncommitted changes are NOT included:" Yellow
    $dirty | ForEach-Object { Say "    $_" Yellow }
}
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory $work | Out-Null
git archive --format=zip --prefix=scanning-machine/ -o "$work\release.zip" HEAD
Expand-Archive "$work\release.zip" -DestinationPath $work
Say ("  Version " + (Get-Content "$work\scanning-machine\VERSION"))

# --- 2. Stop the running system ---------------------------------------------
Say "Stopping the pipeline and dashboard..."
foreach ($t in "Ultrasound Pipeline", "Ultrasound Dashboard") {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "pipeline\.py\s+watch|webapp\.main:app" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# --- 3. Copy the data -------------------------------------------------------
if (Test-Path "$dest\data\app.db") {
    Say "  $dest already has a database - keeping it, not copying the data again." Yellow
} else {
    Say "Copying settings, database, reports and Orthanc position to $dest..."
    New-Item -ItemType Directory $dest -Force | Out-Null
    foreach ($f in "config_local.py", "watch_state.json") {
        if (Test-Path "$dev\$f") { Copy-Item "$dev\$f" "$dest\$f" -Force }
    }
    foreach ($d in "data", "reports") {
        if (Test-Path "$dev\$d") {
            robocopy "$dev\$d" "$dest\$d" /E /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "Copying $d failed (robocopy $LASTEXITCODE)" }
        }
    }
    Say "  Copied." Green
}

# --- 4. Install -------------------------------------------------------------
Say ""
Say "Running setup.bat - answer Y to 'Keep the existing configuration?'" Cyan
Say ""
& cmd.exe /c "`"$work\scanning-machine\setup.bat`""

# The old Desktop shortcut pointed at the development folder; setup.bat put
# a new one for C:\scanning-machine on the shared Desktop
$old = Join-Path ([Environment]::GetFolderPath("Desktop")) "Restart Ultrasound Services.lnk"
if (Test-Path $old) {
    $target = (New-Object -ComObject WScript.Shell).CreateShortcut($old).TargetPath
    if ($target -like "$dev*") { Remove-Item $old -Force }
}

Say ""
Say "=== Done ===" Cyan
Say "Check now:"
Say "  1. Open the dashboard - yesterday's and today's scans are listed."
Say "  2. Open a report, click PDF / Print - the print window opens."
Say "  3. Send one scan from the scanner - its report appears."
Say ""
Say "To go back to running from $dev, tell Claude - the development"
Say "folder is unchanged and the old tasks can be registered again."
