# server.py — минимальная чистая база (PTB v20 + Flask 3)

import os
import logging
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---- логирование ----
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("portals-bot")

# ---- конфиг ----
BOT_TOKEN  = os.environ["BOT_TOKEN"]                         # зададим в Render
WEBAPP_URL = os.environ.get("WEBAPP_URL", "/webapp")         # поменяем после 1-го деплоя

# ---- Flask ----
app = Flask(__name__)

@app.get("/")
def home():
    return "Bot is running!"

# простой минималистичный WebApp (одна страница)
WEBAPP_HTML = """<!doctype html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Portals Watcher</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;background:#0f1115;color:#eaeef6;margin:0;padding:24px}
.card{max-width:560px;margin:0 auto;background:#151923;border:1px solid #23293a;border-radius:16px;padding:16px;box-shadow:0 8px 30px rgba(0,0,0,.2)}
h1{font-size:20px;margin:0 0 12px}
p{opacity:.8}
button{width:100%;padding:10px;border-radius:12px;border:1px solid #2a3042;background:#0f1320;color:#eaeef6;margin:6px 0}
</style>
</head><body>
  <div class="card">
    <h1>Portals Watcher</h1>
    <p>База работает. Дальше добавим функции: подписки и алерты.</p>
  </div>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
</body></html>"""

@app.get("/webapp")
def webapp():
    return WEBAPP_HTML

# ---- Telegram bot (PTB v20) ----
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Open WebApp", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await update.message.reply_text("Привет! Жми кнопку, чтобы открыть мини-апп.", reply_markup=kb)

def run_bot():
    log.info("Starting Telegram polling…")
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    app_.add_handler(CommandHandler("start", cmd_start))
    app_.run_polling(close_loop=False)

# ---- однократный запуск бота (без Flask хуков) ----
_started = False
def start_background_once():
    global _started
    if _started:
        return
    _started = True
    Thread(target=run_bot, daemon=True).start()

# запускаем фон сразу при импорте (без before_first_request, т.к. Flask 3 его убрали)
start_background_once()

# локальный запуск (Render использует gunicorn команду)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    log.info(f"HTTP on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
