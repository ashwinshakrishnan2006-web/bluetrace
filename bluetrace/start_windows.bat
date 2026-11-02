@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Open http://127.0.0.1:8000 in your browser.
.venv\Scripts\python.exe server.py
pause
exit /b
:fail
echo Setup failed. Install Python 3.12 and check your internet connection.
pause
