@echo off
REM Запуск локального веб-приложения генератора исполнительной документации
REM Скрипт создаёт venv (если нет), устанавливает зависимости и запускает app.py.

cd /d "%~dp0"

if not exist ".venv" (
    echo Создаю виртуальное окружение .venv ...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo Устанавливаю зависимости ...
pip install -r requirements.txt

echo Запускаю приложение ...
start "" "http://127.0.0.1:5000/"
python app.py

echo.
echo Приложение должно быть доступно по адресу http://127.0.0.1:5000/
echo Нажмите любую клавишу для завершения окна.
pause >nul

