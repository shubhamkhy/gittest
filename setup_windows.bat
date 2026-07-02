@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Indian Minervini Screener - Windows Setup
echo ============================================
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python was not found.
        echo Install Python 3.10+ from https://www.python.org/downloads/
        echo Make sure "Add Python to PATH" is checked during install.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

echo Using: %PYTHON%
%PYTHON% --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 1
)

echo Upgrading pip...
python -m pip install --upgrade pip

echo Installing screener with live Yahoo Finance support...
python -m pip install -e ".[live]"
if errorlevel 1 (
    echo ERROR: Installation failed.
    pause
    exit /b 1
)

echo.
echo Running tests...
python -m unittest discover -s tests
if errorlevel 1 (
    echo WARNING: Some tests failed, but install completed.
) else (
    echo Tests passed.
)

if not exist "examples\nse_all_symbols.txt" (
    echo ERROR: Full NSE symbol list is missing: examples\nse_all_symbols.txt
    pause
    exit /b 1
)

for /f %%A in ('find /c /v "" ^< examples\nse_all_symbols.txt') do set SYMBOL_COUNT=%%A
echo.
echo Setup complete.
echo Full NSE symbol list: examples\nse_all_symbols.txt (!SYMBOL_COUNT! symbols)
echo.
echo Next step: double-click run_screener.bat
echo Or run from this folder after setup:
echo   run_screener.bat
echo.
pause
