Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Get-RunRoot {
  return Join-Path (Get-RepoRoot) "runtime\windows-server"
}

function Ensure-Directory {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
  }
}

function Resolve-CommandPath {
  param([Parameter(Mandatory = $true)][string]$Name)
  $cmd = Get-Command $Name -ErrorAction Stop
  return $cmd.Source
}

function Resolve-PythonCommand {
  foreach ($candidate in @("python.exe", "python", "py")) {
    try {
      $cmd = Get-Command $candidate -ErrorAction Stop
      if ($cmd.Source) {
        return $cmd.Source
      }
      if ($cmd.Path) {
        return $cmd.Path
      }
      if ($cmd.Name) {
        return $cmd.Name
      }
    } catch {
      continue
    }
  }
  throw "Python executable not found in PATH."
}

function Get-ConfigPath {
  return Join-Path (Get-RunRoot) "service-config.json"
}

function ConvertTo-HashtableDeep {
  param([Parameter(Mandatory = $true)]$Value)
  if ($null -eq $Value) {
    return $null
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $out = @{}
    foreach ($key in $Value.Keys) {
      $out[$key] = ConvertTo-HashtableDeep -Value $Value[$key]
    }
    return $out
  }
  if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
    $items = @()
    foreach ($item in $Value) {
      $items += ,(ConvertTo-HashtableDeep -Value $item)
    }
    return $items
  }
  $props = @($Value.PSObject.Properties)
  if ($Value -is [psobject] -and $props.Count -gt 0) {
    $out = @{}
    foreach ($prop in $props) {
      $out[$prop.Name] = ConvertTo-HashtableDeep -Value $prop.Value
    }
    return $out
  }
  return $Value
}

function Save-ServiceConfig {
  param([Parameter(Mandatory = $true)][hashtable]$Config)
  $runRoot = Get-RunRoot
  Ensure-Directory -Path $runRoot
  $json = $Config | ConvertTo-Json -Depth 10
  Set-Content -LiteralPath (Get-ConfigPath) -Value $json -Encoding UTF8
}

function Load-ServiceConfig {
  $path = Get-ConfigPath
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Service config not found: $path"
  }
  $obj = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
  return ConvertTo-HashtableDeep -Value $obj
}

function Write-WatchdogLog {
  param(
    [Parameter(Mandatory = $true)][string]$Message,
    [string]$Level = "INFO"
  )
  $runRoot = Get-RunRoot
  Ensure-Directory -Path $runRoot
  $logPath = Join-Path $runRoot "watchdog.log"
  $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level.ToUpperInvariant(), $Message
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Test-ListeningPort {
  param([Parameter(Mandatory = $true)][int]$Port)
  $result = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  return [bool]$result
}

function Test-ProcessCommandLine {
  param([Parameter(Mandatory = $true)][string]$Pattern)
  $matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match $Pattern)
  }
  return [bool]($matches | Select-Object -First 1)
}

function Start-BackgroundProcess {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$StdOutPath,
    [Parameter(Mandatory = $true)][string]$StdErrPath
  )
  Ensure-Directory -Path ([System.IO.Path]::GetDirectoryName($StdOutPath))
  Ensure-Directory -Path ([System.IO.Path]::GetDirectoryName($StdErrPath))
  Start-Process `
    -FilePath $FilePath `
    -ArgumentList $ArgumentList `
    -WorkingDirectory $WorkingDirectory `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdOutPath `
    -RedirectStandardError $StdErrPath | Out-Null
}

function Test-IsAdministrator {
  $current = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = [Security.Principal.WindowsPrincipal]::new($current)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
