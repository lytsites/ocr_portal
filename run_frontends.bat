@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"

echo [INFO] Starting single frontend process...
echo [INFO] Primary web origin: https://docs.e-qoldau.asia
echo [INFO] API origin: https://api.e-qoldau.asia
echo [INFO] Routes: /2-19 /2-43 /4-20 /5-52 /analytics
echo.

start /b "" cmd /c "cd /d ""%ROOT%apps\form-portal"" && npm.cmd run dev"

echo [INFO] All launch commands sent in current window.
echo [INFO] Press Ctrl+C to stop.
echo.
pause
endlocal
