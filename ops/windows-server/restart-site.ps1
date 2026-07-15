Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\shared.ps1"

if (-not (Test-IsAdministrator)) {
  throw "Run this script as Administrator."
}

$ports = @(9000, 5175)
$patterns = @(
  '(?i)\-m\s+uvicorn\s+app:app',
  '(?i)\-m\s+workers',
  '(?i)run preview -- --host',
  '(?i)vite preview'
)

$processIds = New-Object System.Collections.Generic.HashSet[int]

foreach ($port in $ports) {
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    [void]$processIds.Add([int]$listener.OwningProcess)
  }
}

$processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
foreach ($process in $processes) {
  $cmd = $process.CommandLine
  if (-not $cmd) {
    continue
  }

  foreach ($pattern in $patterns) {
    if ($cmd -match $pattern) {
      [void]$processIds.Add([int]$process.ProcessId)
      break
    }
  }
}

foreach ($processId in @($processIds)) {
  try {
    Stop-Process -Id $processId -Force -ErrorAction Stop
  } catch {
    continue
  }
}

Write-Host ("Stopped {0} process(es)." -f $processIds.Count)

$deadline = (Get-Date).AddSeconds(20)
while ((Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }).Count -gt 0) {
  if ((Get-Date) -ge $deadline) {
    break
  }
  Start-Sleep -Milliseconds 500
}

& "$PSScriptRoot\watchdog.ps1"
