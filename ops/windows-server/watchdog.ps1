Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\shared.ps1"

function Ensure-FrontendBuild {
  param([hashtable]$Config)
  $distPath = Join-Path $Config.frontend_workdir "dist"
  if (Test-Path -LiteralPath $distPath) {
    return
  }
  Write-WatchdogLog "Frontend dist not found. Running production build."
  & $Config.npm_cmd "run" "build" | Out-Null
}

function Ensure-Backend {
  param([hashtable]$Config)
  if (Test-ListeningPort -Port ([int]$Config.backend_port)) {
    return
  }
  Write-WatchdogLog "Backend is down. Starting uvicorn on port $($Config.backend_port)."
  Start-BackgroundProcess `
    -FilePath $Config.py_cmd `
    -ArgumentList @("-3", "-m", "uvicorn", "app:app", "--host", $Config.backend_host, "--port", [string]$Config.backend_port) `
    -WorkingDirectory $Config.backend_workdir `
    -StdOutPath (Join-Path $Config.log_dir "backend.out.log") `
    -StdErrPath (Join-Path $Config.log_dir "backend.err.log")
}

function Ensure-Workers {
  param([hashtable]$Config)
  if (Test-ProcessCommandLine -Pattern $Config.workers_match) {
    return
  }
  Write-WatchdogLog "Workers are down. Starting background workers."
  Start-BackgroundProcess `
    -FilePath $Config.py_cmd `
    -ArgumentList @("-3", "-m", "workers") `
    -WorkingDirectory $Config.backend_workdir `
    -StdOutPath (Join-Path $Config.log_dir "workers.out.log") `
    -StdErrPath (Join-Path $Config.log_dir "workers.err.log")
}

function Ensure-Frontend {
  param([hashtable]$Config)
  if (Test-ListeningPort -Port ([int]$Config.frontend_port)) {
    return
  }
  Ensure-FrontendBuild -Config $Config
  Write-WatchdogLog "Frontend preview is down. Starting preview server on port $($Config.frontend_port)."
  Start-BackgroundProcess `
    -FilePath "cmd.exe" `
    -ArgumentList @("/c", "`"$($Config.npm_cmd)`" run preview -- --host $($Config.frontend_host) --port $($Config.frontend_port)") `
    -WorkingDirectory $Config.frontend_workdir `
    -StdOutPath (Join-Path $Config.log_dir "frontend.out.log") `
    -StdErrPath (Join-Path $Config.log_dir "frontend.err.log")
}

$config = Load-ServiceConfig
Ensure-Directory -Path $config.log_dir

try {
  Write-WatchdogLog "Watchdog check started."
  Ensure-Backend -Config $config
  Ensure-Workers -Config $config
  Ensure-Frontend -Config $config
  Write-WatchdogLog "Watchdog check finished."
} catch {
  Write-WatchdogLog $_.Exception.Message "ERROR"
  throw
}
