"""
Запускает сервер и бота в одном процессе (для Railway)
"""
import threading, os
from dotenv import load_dotenv

load_dotenv()

def run_bot():
    import bot
    bot.bot.infinity_polling()

def run_server():
    from server import app, init_db
    port = int(os.getenv("PORT", 5055))
    init_db()
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_bot.start()
    run_server()
