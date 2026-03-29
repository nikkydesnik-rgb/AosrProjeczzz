@echo off
chcp 65001 >nul 2>&1
REM Launch local web app for generating documentation
REM Creates venv (if missing), installs dependencies, and runs app.py

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment .venv ...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo Installing dependencies ...
python -m pip install --upgrade pip
pip install --retries 10 --timeout 120 --no-cache-dir -r requirements.txt

echo Starting application ...
start "" "http://127.0.0.1:5000/"
python app.py

echo.
echo Application should be available at http://127.0.0.1:5000/
echo Press any key to close this window.
pause >nul
