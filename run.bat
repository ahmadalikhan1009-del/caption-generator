@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title AI Viral Shorts Studio

:: All output also written to run_log.txt so errors are never lost
set LOG="%~dp0run_log.txt"
echo. > %LOG%

call :log "==================================================="
call :log "  AI Viral Shorts Studio - Quick Launcher"
call :log "==================================================="
call :log ""

:: ── Step 1: Find a working Python interpreter ────────────────────────────────
set PYTHON_EXE=

for %%P in (
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python310\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python315\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python315\python.exe"
) do (
    if exist %%P (
        if not defined PYTHON_EXE set PYTHON_EXE=%%~P
    )
)

if not defined PYTHON_EXE (
    call :log "[ERROR] No Python installation found."
    call :log "        Please install Python 3.11+ from https://www.python.org/downloads/"
    call :log "        Log saved to: run_log.txt"
    pause
    exit /b 1
)
call :log "[OK] Found Python: %PYTHON_EXE%"

:: ── Step 2: Check if the venv home path is still valid ───────────────────────
set VENV_OK=0

if exist "venv\Scripts\python.exe" (
    if exist "venv\pyvenv.cfg" (
        set "VENV_HOME="
        for /f "tokens=1,* delims==" %%A in ('type "venv\pyvenv.cfg" 2^>nul') do (
            set "KEY=%%A"
            set "KEY=!KEY: =!"
            if /i "!KEY!"=="home" (
                set "VENV_HOME=%%B"
                set "VENV_HOME=!VENV_HOME:~1!"
            )
        )
        call :log "[..] Venv was built with Python home: !VENV_HOME!"
        if exist "!VENV_HOME!\python.exe" (
            set VENV_OK=1
            call :log "[OK] Venv home Python is valid."
        ) else (
            call :log "[!!] Venv home Python NOT found - venv is from another machine."
            call :log "[..] Will rebuild the virtual environment."
        )
    ) else (
        call :log "[!!] pyvenv.cfg missing - venv is invalid."
    )
) else (
    call :log "[..] No venv found - will create one."
)

:: ── Step 3: Rebuild venv if needed ───────────────────────────────────────────
if "!VENV_OK!"=="0" (
    if exist "venv" (
        call :log "[*] Removing old broken virtual environment..."
        rmdir /s /q "venv"
    )

    call :log "[*] Creating new virtual environment..."
    "%PYTHON_EXE%" -m venv venv >> %LOG% 2>&1
    if !ERRORLEVEL! neq 0 (
        call :log "[ERROR] Failed to create virtual environment. See run_log.txt."
        pause
        exit /b 1
    )
    call :log "[OK] Virtual environment created."

    call :log "[*] Upgrading pip..."
    "venv\Scripts\python.exe" -m pip install --upgrade pip >> %LOG% 2>&1

    call :log "[*] Installing dependencies (this may take several minutes)..."
    call :log "    Please wait - downloading PyTorch and Whisper packages..."
    "venv\Scripts\python.exe" -m pip install -r requirements.txt >> %LOG% 2>&1
    if !ERRORLEVEL! neq 0 (
        call :log "[ERROR] Dependency install FAILED. Check run_log.txt for details."
        pause
        exit /b 1
    )
    call :log "[OK] All dependencies installed successfully."
)

:: ── Step 4: Launch the server ─────────────────────────────────────────────────
call :log ""
call :log "[*] Starting server - opening http://127.0.0.1:8000 in your browser..."
call :log "    (If browser opens before the server is ready, wait 5 seconds and refresh)"
call :log ""
echo.
echo    Server is starting... keep this window open.
echo    App URL: http://127.0.0.1:8000
echo    To stop: press Ctrl+C in this window.
echo.
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000

"venv\Scripts\python.exe" main.py
set SERVER_EXIT=!ERRORLEVEL!

echo.
if !SERVER_EXIT! neq 0 (
    call :log "[ERROR] Server exited with code !SERVER_EXIT!"
    echo [ERROR] The server stopped with an error (code !SERVER_EXIT!).
    echo         Check run_log.txt in the project folder for details.
) else (
    call :log "[OK] Server stopped cleanly."
    echo Server stopped cleanly.
)

echo.
echo Full log: %~dp0run_log.txt
pause
exit /b !SERVER_EXIT!

:: ── Logging helper ────────────────────────────────────────────────────────────
:log
echo %~1
echo %~1 >> %LOG%
goto :eof