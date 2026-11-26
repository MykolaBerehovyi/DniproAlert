@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Backend virtual environment was not found.
    pause
    exit /b 1
)

docker compose up -d db
if errorlevel 1 (
    echo Could not start PostgreSQL. Check that Docker Desktop is running.
    pause
    exit /b 1
)

curl.exe -fsS http://127.0.0.1:8001/healthz >nul 2>&1
if errorlevel 1 (
    start "Dnipro Alert API" cmd /k ""%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
) else (
    echo API is already responding on port 8001.
)

if exist "%CD%\telegram.session" (
    start "Dnipro Alert Worker" cmd /k ""%PYTHON%" -m app.worker"
) else (
    echo Telegram worker was not started because telegram.session is missing.
    echo Authorize Telegram once with: .venv\Scripts\python.exe -m app.authorize_telegram
)

echo Backend startup requested. Start_ngrok.bat opens the public tunnel.
pause
