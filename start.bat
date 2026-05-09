@echo off
setlocal EnableExtensions

title Linux.do Helper Launcher

cd /d "%~dp0"

if not exist "linux_do_gui.py" (
    echo [ERROR] linux_do_gui.py was not found.
    echo Project directory: "%CD%"
    echo Please put start.bat in the project root directory.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt was not found.
    echo Project directory: "%CD%"
    pause
    exit /b 1
)

echo [1/4] Checking Python 3...
set "PY_CMD=py -3"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 (
    set "PY_CMD=python"
    python --version >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python 3 was not found.
        echo Please install Python 3.8 or newer, then run this file again.
        pause
        exit /b 1
    )
)
%PY_CMD% --version

echo [2/4] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        pause
        exit /b 1
    )
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment Python was not found.
    echo Expected: "%VENV_PY%"
    pause
    exit /b 1
)

echo [3/4] Installing dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo [4/4] Starting GUI...
"%VENV_PY%" "linux_do_gui.py"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo [ERROR] Application exited with code %APP_EXIT%.
    pause
    exit /b %APP_EXIT%
)

exit /b 0
