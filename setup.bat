@echo off
rem One-time setup: creates .venv next to this file and installs the dependencies.
setlocal
cd /d "%~dp0"

py -3.12 -c "" >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 is needed but wasn't found. Install it with:
    echo     winget install Python.Python.3.12
    echo or from https://www.python.org/downloads/ ^(tick "py launcher"^), then run setup.bat again.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    py -3.12 -m venv .venv || exit /b 1
)
echo Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || exit /b 1

echo.
echo Setup done. Next:
echo     run.bat --bind     press the key or wheel button to use for push-to-talk
echo     run.bat            start ^(the first start downloads the speech model, about 250 MB^)
