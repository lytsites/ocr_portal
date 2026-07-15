@echo off
setlocal
set "REPO_ROOT=%~dp0"
set "PYTHON_EXE=%REPO_ROOT%.venv\Scripts\python.exe"

cd /d "%~dp0backend"
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -m workers
) else (
  python -m workers
)

endlocal
