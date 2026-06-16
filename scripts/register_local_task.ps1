# Registers a daily Windows Scheduled Task that runs the FULL Index
# collection locally — including eBay, which needs this PC's residential IP.
# Run once from the repo root (no elevation needed for a per-user task):
#     powershell -ExecutionPolicy Bypass -File scripts\register_local_task.ps1
#
# The task runs run_daily.py at 06:05 local daily. run_daily.py decides which
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
# 06:05 local; run_daily handles cadence. Adjust -At to taste.
$trigger = New-ScheduledTaskTrigger -Daily -At 6:05AM
# -StartWhenAvailable catches up if the PC was off at 06:05.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "PremiumPuzzlesIndex" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily Premium Puzzles Index collection + build" -Force

Write-Host "Registered task 'PremiumPuzzlesIndex' (daily 06:05)."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName PremiumPuzzlesIndex"
Write-Host "Logs/raw data under: $repo\data\raw"
