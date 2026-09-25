@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Not set up yet. Run setup.bat first.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0lmu_chat.py" %*
