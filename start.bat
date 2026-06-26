@echo off
cd /d "%~dp0"
".conda\python.exe" -m app.server
pause
