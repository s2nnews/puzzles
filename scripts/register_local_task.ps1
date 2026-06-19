# Registers a daily Windows Scheduled Task that runs the FULL Index
# collection locally — including eBay, which needs this PC's residential IP.
# Run once from the repo root (no elevation needed for a per-user task):
#     powershell -ExecutionPolicy Bypass -File scripts\register_local_task.ps1
#
# The task runs run_daily.py at 10:30 local daily (inside normal working
# hours so the PC is on; StartWhenAvailable catches up if you start later).
# run_daily.py decides which
# sources are due (Amazon + eBay daily, stock Mon/Wed/Fri, Reddit Mon,
# Trends Thu, Global Fri) and rebuilds index.json + the dashboards. It runs as
# long as the PC is on and awake at the trigger time.
#
# Uses the project's .venv so dependencies are pinned and independent of
# whatever Python is on PATH (a PATH mismatch is what broke the cloud run).
# Create it first if missing:  python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing $python. Create it: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}
$log    = Join-Path $repo "data\raw\run_daily.log"

# Run through cmd so stdout+stderr land in a log for an unattended task.
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"`"$python`" run_daily.py >> `"$log`" 2>&1`"" `
    -WorkingDirectory $repo
# Two triggers for reliability on a machine that isn't always on at a set
# time: a daily 10:30 run, AND an at-logon run (5 min after you sign in) so
# it also fires whenever you start the PC. run_daily skips any source already
# collected today, so whichever trigger fires first does the work and the
# rest are cheap no-ops. StartWhenAvailable also catches up a missed run.
$daily = New-ScheduledTaskTrigger -Daily -At 10:30AM
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT5M"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "PremiumPuzzlesIndex" `
    -Action $action -Trigger @($daily, $logon) -Settings $settings `
    -Description "Daily Premium Puzzles Index collection + build" -Force

Write-Host "Registered task 'PremiumPuzzlesIndex' (daily 06:05)."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName PremiumPuzzlesIndex"
Write-Host "Logs/raw data under: $repo\data\raw"
