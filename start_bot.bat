@echo off
REM Start Telegram Bot for Surebet Accounting System

echo.
echo ==============================================
echo   Surebet Telegram Bot Launcher (Windows)
echo ==============================================
echo.

REM Move to project root (folder of this script)
cd /d "%~dp0"

REM Try to activate a virtual environment if present
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
  echo [INFO] Activated virtualenv: .venv
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
  echo [INFO] Activated virtualenv: venv
) else (
  echo [WARN] No virtualenv found. Using system Python.
)

REM Ensure Python is available
python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found! Please install Python 3.10+ and add to PATH.
  pause
  exit /b 1
)

REM Set PYTHONPATH to project root
set PYTHONPATH=%CD%
echo [INFO] Project root: %CD%
echo [INFO] PYTHONPATH set to: %PYTHONPATH%
echo.

REM Ensure .env exists
if not exist ".env" (
  echo [WARN] .env not found. Creating from .env.example...
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [ACTION REQUIRED] Open .env and set TELEGRAM_BOT_TOKEN before running.
  ) else (
    echo [ERROR] .env.example missing. Cannot create .env automatically.
  )
  pause
  exit /b 1
)

REM Check required package (python-telegram-bot). Install deps if missing.
python -c "import telegram" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Installing dependencies from requirements.txt ...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
  )
)

REM Initialize database schema + seed data (idempotent)
echo [INFO] Ensuring database is initialized...
python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('.').resolve())); from src.core.database import initialize_database; from src.core.config import Config; initialize_database(); print('[OK] Database ready at:', Config.DB_PATH)" 1>nul 2>nul
if errorlevel 1 (
  echo [WARN] Database initialization skipped or failed (continuing).
)

REM Start the Telegram bot
echo.
echo [INFO] Starting Telegram bot...
echo.
python -m src.integrations.telegram_bot

echo.
pause

