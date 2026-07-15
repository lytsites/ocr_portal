Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\shared.ps1"

$taskName = "OCR Portal Watchdog"
$config = Load-ServiceConfig

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
  $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
  Write-Host "Task: $taskName"
  Write-Host "State: $($task.State)"
  Write-Host "LastRunTime: $($taskInfo.LastRunTime)"
  Write-Host "LastTaskResult: $($taskInfo.LastTaskResult)"
} else {
  Write-Host "Task: not installed"
}

Write-Host ""
Write-Host "Backend port $($config.backend_port): $([bool](Test-ListeningPort -Port ([int]$config.backend_port)))"
Write-Host "Frontend port $($config.frontend_port): $([bool](Test-ListeningPort -Port ([int]$config.frontend_port)))"
Write-Host "Workers running: $([bool](Test-ProcessCommandLine -Pattern $config.workers_match))"
Write-Host "Config: $(Get-ConfigPath)"
Write-Host "Logs: $($config.log_dir)"
