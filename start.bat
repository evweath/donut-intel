@echo off
REM Start the Donut Intel server. Leave this window open while using the app.
REM Then open https://localhost:8743 in your browser.
cd /d "%~dp0"
python start.py
pause
