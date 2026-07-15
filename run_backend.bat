@echo off
setlocal
set "BACKEND_HOST=%BACKEND_HOST%"
if "%BACKEND_HOST%"=="" set "BACKEND_HOST=0.0.0.0"
set "BACKEND_PORT=%BACKEND_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=9000"

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

netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo [INFO] Backend already running on :%BACKEND_PORT%
  echo [INFO] Public API: https://api.e-qoldau.asia
  pause
  exit /b 0
)

echo [INFO] Starting backend on %BACKEND_HOST%:%BACKEND_PORT% ...
echo [INFO] Expected public API: https://api.e-qoldau.asia
python -m uvicorn app:app --host %BACKEND_HOST% --port %BACKEND_PORT%

if errorlevel 1 (
  echo [ERROR] Backend exited with error code %errorlevel%.
  pause
  exit /b %errorlevel%
)

endlocal
