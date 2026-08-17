@echo off
REM ───────────────────────────────────────────────────────────────────────
REM Single start for Cookie Auto-Login ULTIMATE Pro (version_one)
REM   start.bat
REM Ensures venv + deps, then launches the GUI. Idempotent (safe to re-run).
REM ───────────────────────────────────────────────────────────────────────
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "PYTHON="

call :find_python
if not defined PYTHON (
    echo [!] Python 3.10+ not found.
    echo     Install from https://www.python.org/downloads/
    echo     and tick "Add python.exe to PATH".
    echo     Or set PY to the full path of python.exe and re-run.
    exit /b 1
)

echo [*] Using: !PYTHON!

REM 1) Create venv if missing
if not exist ".venv\Scripts\activate.bat" (
    echo [*] Creating virtualenv...
    "!PYTHON!" -m venv .venv
    if errorlevel 1 (
        echo [!] Failed to create virtualenv.
        exit /b 1
    )
)

REM 2) Activate
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [!] Failed to activate virtualenv.
    exit /b 1
)

REM 3) Ensure tkinter is importable (bundled with official Windows Python)
python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [!] tkinter is missing. Reinstall Python from https://www.python.org/downloads/
    echo     and keep "tcl/tk and IDLE" enabled.
    exit /b 1
)

REM 4) Install/refresh deps
echo [*] Checking dependencies...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [!] pip install failed.
    exit /b 1
)

REM 5) Launch
echo [*] Starting GUI...
python gui.py
set "ERR=!ERRORLEVEL!"
if not "!ERR!"=="0" (
    echo [!] GUI exited with code !ERR!.
    exit /b !ERR!
)
exit /b 0

REM ── find a real Python 3.10+ (skip Microsoft Store stubs) ──────────────
:find_python
if defined PY (
    call :try_python "%PY%"
    if defined PYTHON exit /b 0
)

call :try_python "%LocalAppData%\Python\bin\python.exe"
if defined PYTHON exit /b 0

call :try_python "%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if defined PYTHON exit /b 0

for /d %%D in ("%LocalAppData%\Python\pythoncore-*") do (
    call :try_python "%%~D\python.exe"
    if defined PYTHON exit /b 0
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
    call :try_python "%%~D\python.exe"
    if defined PYTHON exit /b 0
)

for /d %%D in ("%ProgramFiles%\Python*") do (
    call :try_python "%%~D\python.exe"
    if defined PYTHON exit /b 0
)

for /d %%D in ("%ProgramFiles(x86)%\Python*") do (
    call :try_python "%%~D\python.exe"
    if defined PYTHON exit /b 0
)

REM py launcher / python on PATH, but skip WindowsApps stubs
for %%C in (py python python3) do (
    for /f "delims=" %%P in ('where %%C 2^>nul') do (
        echo %%~P | find /i "\WindowsApps\" >nul
        if errorlevel 1 (
            call :try_python "%%~P"
            if defined PYTHON exit /b 0
        )
    )
)
exit /b 1

:try_python
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYTHON=%~1"
exit /b 0
