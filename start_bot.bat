@echo off
echo Запускаю Telegram бот...
pip install -r requirements.txt >nul 2>&1
python bot.py
pause
