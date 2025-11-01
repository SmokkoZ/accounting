@echo off
REM Launch script for Surebet Accounting System
REM This sets up the Python path and runs Streamlit

echo.
echo ======================================
echo  Surebet Accounting System Launcher
echo ======================================
echo.

REM Set the project root directory
cd /d "%~dp0"

REM Set PYTHONPATH to include project root
set PYTHONPATH=%CD%

echo [INFO] Project root: %CD%
echo [INFO] PYTHONPATH set to: %PYTHONPATH%
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.8+ and add to PATH.
    pause
    exit /b 1
)

REM Check if Streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Streamlit not installed! Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies!
        pause
        exit /b 1
    )
)

REM Check if rapidfuzz is installed (required for Story 2.3)
python -c "import rapidfuzz" >nul 2>&1
if errorlevel 1 (
    echo [INFO] rapidfuzz not found, installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies!
        pause
        exit /b 1
    )
)

REM Launch Streamlit using Python launcher script
echo [INFO] Starting Streamlit app...
echo.
python run_app.py

pause
