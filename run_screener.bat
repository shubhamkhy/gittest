@echo off
setlocal

echo ============================================
echo  Indian Minervini Screener - Full NSE Scan
echo ============================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Installing now...
    where python >nul 2>&1 && set PYTHON=python || set PYTHON=py
    %PYTHON% -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -e ".[live]"
    if errorlevel 1 (
        echo ERROR: Setup failed. Run setup_windows.bat manually.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate virtual environment.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

if not exist "examples\nse_all_symbols.txt" (
    echo ERROR: Missing full symbol list: examples\nse_all_symbols.txt
    pause
    exit /b 1
)

for /f %%A in ('find /c /v "" ^< examples\nse_all_symbols.txt') do set SYMBOL_COUNT=%%A

echo Scanning full NSE list: !SYMBOL_COUNT! symbols
echo This usually takes 2-5 minutes depending on your internet speed.
echo Results will be shown below and saved in the results\ folder.
echo.

python scripts\scan_nse_full.py --symbols-file examples\nse_all_symbols.txt --output table
set SCAN_EXIT=%ERRORLEVEL%

echo.
if %SCAN_EXIT%==0 (
    echo Scan finished successfully.
) else (
    echo Scan failed with exit code %SCAN_EXIT%.
)
echo.
pause
exit /b %SCAN_EXIT%
