@echo off
echo Запускаю TTS Auth Server...
pip install -r requirements.txt >nul 2>&1
python server.py
pause
