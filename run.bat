@echo off
title ReviZoR FranK
cd /d "%~dp0"

echo.
echo  =========================================
echo   ReviZoR FranK - CV Optimization Engine
echo  =========================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".env" (
    echo [WARNING] .env file not found. Creating from template...
    copy .env.example .env >nul
    echo [INFO] Please edit .env and add your ANTHROPIC_API_KEY, then restart.
    echo Opening .env for editing...
    notepad .env
    echo.
    pause
)

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo [INFO] Installing / updating dependencies...
pip install -r requirements.txt -q

echo.
echo [INFO] Starting ReviZoR FranK...
echo [INFO] The application will open in your browser automatically.
echo [INFO] To stop the app, close this window or press Ctrl+C.
echo.

python -m streamlit run revizor_frank/app.py --server.headless=false --browser.gatherUsageStats=false

pause
