@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Not set up yet. Run "Install LMU Voice Chat.bat" first.
    exit /b 1
)
rem No arguments: start in the tray without a console window. With arguments
rem (--list-drivers, --console, ...): run in this console.
if "%~1"=="" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0lmu_chat.py"
) else (
    "%~dp0.venv\Scripts\python.exe" "%~dp0lmu_chat.py" %*
)
