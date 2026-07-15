@echo off
setlocal

cd /d "%~dp0backend"
if errorlevel 1 (
  echo [ERROR] Failed to open backend directory.
  pause
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher not found in PATH.
  pause
  exit /b 1
)

echo [INFO] Running sample PDF verification...
py -3 verify_form_samples.py

if errorlevel 1 (
  echo [ERROR] Verification failed with code %errorlevel%.
  pause
  exit /b %errorlevel%
)

echo [INFO] Reports saved to docs\verification
endlocal
