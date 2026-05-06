@echo off
REM MT5 Test Bot — Windows one-click launcher.
REM
REM Default: paper mode (демо акаунт). Live горим хэрэгтэй бол:
REM     start.bat live
REM Эсвэл шууд:
REM     python run.py live --symbol EURUSD

setlocal

REM Move to script directory
cd /d "%~dp0"

REM Pick python
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not in PATH. Install Python 3.11+ from python.org
    exit /b 1
)

REM Create venv on first run
if not exist ".venv\Scripts\python.exe" (
    echo First run — creating venv and installing dependencies...
    python run.py setup
    if errorlevel 1 exit /b 1
)

REM Default subcommand = paper; pass through user args
if "%~1"=="" (
    .venv\Scripts\python.exe run.py paper
) else (
    .venv\Scripts\python.exe run.py %*
)
