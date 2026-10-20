@echo off
REM ============================================================================
REM PhotoPort - Windows Build and Packaging Script (Batch)
REM Creates a standalone Windows executable distribution using PyInstaller
REM ============================================================================

setlocal enabledelayedexpansion

echo ========================================================
echo   Building PhotoPort Windows Desktop Distribution
echo ========================================================

REM Step 1: Check Python installation
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.11 or later.
    pause
    exit /b 1
)

REM Step 2: Create / Activate Virtual Environment
if not exist ".venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv .venv
)

echo [INFO] Activating virtual environment...
call .venv\Scripts\activate.bat

REM Step 3: Upgrade pip and install dependencies
echo [INFO] Installing required dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller>=6.4.0

REM Step 4: Run PyInstaller
echo [INFO] Packaging with PyInstaller...
pyinstaller --clean --noconfirm PhotoPort.spec

if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller packaging failed!
    pause
    exit /b 1
)

echo ========================================================
echo [SUCCESS] Build complete!
echo Executable located in: dist\PhotoPort\PhotoPort.exe
echo ========================================================

pause
