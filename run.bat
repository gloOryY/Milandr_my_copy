@echo off
cd /d "%~dp0"

python main.py

if errorlevel 1 (
    echo.
    echo Finished with error.
    pause
)