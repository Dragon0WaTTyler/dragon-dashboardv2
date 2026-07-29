@echo off
set "ROOT=C:\Users\walid\Desktop\DragonV2"
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "PORT=5053"

if not exist "%PY%" (
  echo Python runtime not found at "%PY%".
  pause
  exit /b 1
)

cd /d "%ROOT%"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>nul
)
start "DragonV2 Server" "%PY%" run.py
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:%PORT%"
