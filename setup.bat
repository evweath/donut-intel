@echo off
REM First-time setup for Donut Intel on Windows.
REM Creates the .venv, installs dependencies + browser engines, makes TLS certs.
cd /d "%~dp0"
python setup_env.py
echo.
echo Setup finished. You can now run start.bat
pause
