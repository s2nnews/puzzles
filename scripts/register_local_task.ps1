# Registers a daily Windows Scheduled Task that runs the FULL Index
# collection locally — including eBay, which needs this PC's residential IP.
# Run once, in an elevated PowerShell, from anywhere:
#     powershell -ExecutionPolicy Bypass -File scripts\register_local_task.ps1
#
# The task runs run_daily.py at 06:05 Sydney daily. run_daily.py decides which
# sources are due (Amazon + eBay daily, stock Mon/Wed/Fri, Reddit Mon,
# Trends Thu) and rebuilds index.json. It runs whether or not you're logged in,
# as long as the PC is on and awake.

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
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
