@echo off
rem Double-click to install or update LMU Voice Chat. The work is done by install.ps1.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
