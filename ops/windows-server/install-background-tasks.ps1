Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\shared.ps1"

$taskName = "OCR Portal Watchdog"
$repoRoot = Get-RepoRoot
$runRoot = Get-RunRoot
$logDir = Join-Path $repoRoot "backend\logs"
$frontendWorkdir = Join-Path $repoRoot "apps\form-portal"
$backendWorkdir = Join-Path $repoRoot "backend"
$watchdogPath = Join-Path $PSScriptRoot "watchdog.ps1"

if (-not (Test-IsAdministrator)) {
  throw "Run this script as Administrator. Scheduled task registration for background startup needs elevated rights."
}

Ensure-Directory -Path $runRoot
Ensure-Directory -Path $logDir

$config = @{
  repo_root = $repoRoot
  py_cmd = Resolve-CommandPath "py"
  npm_cmd = Resolve-CommandPath "npm.cmd"
  backend_host = "0.0.0.0"
  backend_port = 9000
  frontend_host = "0.0.0.0"
  frontend_port = 5175
  backend_workdir = $backendWorkdir
  frontend_workdir = $frontendWorkdir
  log_dir = $logDir
  workers_match = "-m workers"
}
Save-ServiceConfig -Config $config

Push-Location $frontendWorkdir
try {
  if (-not (Test-Path -LiteralPath (Join-Path $frontendWorkdir "node_modules"))) {
    & $config.npm_cmd "install"
  }
  & $config.npm_cmd "run" "build"
} finally {
  Pop-Location
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogPath`""
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger @($startupTrigger, $repeatTrigger) `
  -Principal $principal `
  -Settings $settings `
  -Description "Keeps OCR Portal backend, workers and frontend running in background after reboot and without user login." `
  -Force | Out-Null

& $watchdogPath

Write-Host "[OK] Scheduled task installed: $taskName"
Write-Host "[OK] Watchdog config: $(Get-ConfigPath)"
Write-Host "[OK] Logs: $logDir"
