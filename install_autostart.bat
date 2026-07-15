@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"

if not exist "%ROOT%ops\windows-server\install-background-tasks.ps1" (
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

echo [1/2] Installing autostart...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%ops\windows-server\install-background-tasks.ps1"
if errorlevel 1 goto :fail

echo [2/2] Current status...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%ops\windows-server\status.ps1"
if errorlevel 1 goto :fail

echo.
echo [OK] Autostart installed.
pause
exit /b 0

:fail
echo.
echo [ERROR] Autostart installation failed.
pause
exit /b 1
