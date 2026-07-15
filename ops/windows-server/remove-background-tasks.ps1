Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\shared.ps1"

$taskName = "OCR Portal Watchdog"

if (-not (Test-IsAdministrator)) {
  throw "Run this script as Administrator."
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Host "[OK] Scheduled task removed: $taskName"
} else {
  Write-Host "[INFO] Task not found: $taskName"
}
