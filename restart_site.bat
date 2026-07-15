@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"

if not exist "%ROOT%ops\windows-server\restart-site.ps1" (
  echo [ERROR] Run this batch from the repo root.
  pause
  exit /b 1
)

net session >nul 2>&1
if errorlevel 1 (
  echo [INFO] Requesting administrator privileges...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)

echo [1/3] Stopping leftover backend, workers and frontend processes...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%ops\windows-server\restart-site.ps1"
if errorlevel 1 goto :fail

echo [2/3] Current status...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%ops\windows-server\status.ps1"
if errorlevel 1 goto :fail

echo [3/3] Restart finished.
pause
exit /b 0

:fail
echo.
echo [ERROR] Site restart failed.
pause
exit /b 1
