@echo off
cd /d "%~dp0backend"
py -3 -m workers
