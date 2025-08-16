# server.py
# -*- coding: utf-8 -*-
import os
import logging
from threading import Thread
from typing import Final

from flask import Flask, Response

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# -----------------------------
# ЛОГИРОВАНИЕ
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("portals-bot")


# -----------------------------
# НАСТРОЙКИ / ENV
# -----------------------------
BOT_TOKEN: Final[str] = os.environ.get("BOT_TOKEN", "").strip()
WEBAPP_URL: Final[str] = os.environ.get("WEBAPP_URL", "").strip()

if not BOT_TOKEN:
    log.error("ENV BOT_TOKEN is empty! Bot will not start.")
if not WEBAPP_URL:
    # не критично; просто кнопка /start будет без WebApp
    log.warning("ENV WEBAPP_URL is empty; /start button will open nothing.")


# -----------------------------
# FLASK (web часть)
# -----------------------------
app = Flask(__name__)

WEBAPP_HTML = f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Portals Watcher</title>
    <style>
      :root {{
        color-scheme: dark;
      }}
      body {{
        margin:0; padding:0;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
        background:#0f141a; color:#e6edf3;
      }}
      .wrap {{
        max-width: 960px; margin: 64px auto; padding: 0 16px;
      }}
      .card {{
        background:#111820; border:1px solid #1f2a35; border-radius:16px;
        padding:24px 28px; box-shadow: 0 8px 28px rgba(0,0,0,.35);
      }}
      h1 {{ margin: 0 0 12px 0; font-size: 28px; }}
      p {{ margin: 0; opacity: .9; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Portals Watcher</h1>
        <p>База работает. Дальше добавим подписки и алерты.</p>
      </div>
    </div>
  </body>
</html>
"""

@app.get("/")
def home() -> Response:
    return Response("Bot is running!", mimetype="text/plain")

@app.get("/healthz")
def healthz() -> Response:
    return Response("ok", mimetype="text/plain")

@app.get("/webapp")
def webapp_page() -> Response:
    return Response(WEBAPP_HTML, mimetype="text/html")


# -----------------------------
# TELEGRAM (bot часть)
# -----------------------------

# /start
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = []
    if WEBAPP_URL:
        kb = [[InlineKeyboardButton("Open WebApp", web_app=WebAppInfo(url=WEBAPP_URL))]]
    text = (
        "Привет! Я слежу за листингами Portals и смогу присылать алерты.\n"
        "Пока тут базовый тест. Попробуй /ping.\n"
    )
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
    )

# /ping — быстрый тест
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("PING from user %s", update.effective_user.id if update.effective_user else "?")
    await update.message.reply_text("pong")

def build_app() -> Application:
    """Создаём PTB Application и навешиваем хендлеры."""
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("ping", cmd_ping))
    return application

def run_bot() -> None:
    """Запускаем polling (в окрем потоке)."""
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is empty; skip bot start.")
        return
    try:
        application = build_app()
        log.info("Starting Telegram polling…")
        # allowed_updates=Update.ALL_TYPES чтобы ловить любые апдейты
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        log.exception("Bot crashed: %s", e)


# -----------------------------
# АВТОЗАПУСК БОТА В BACKGROUND
# -----------------------------
_started = False

def start_background_once() -> None:
    """Запускаем run_bot() один раз в фоне (для gunicorn-воркера)."""
    global _started
    if _started:
        return
    _started = True
    Thread(target=run_bot, daemon=True).start()
    log.info("Background bot thread started.")

# ВАЖНО: дергаем при импорте модуля, чтобы не ждать первого HTTP-запроса
start_background_once()


# -----------------------------
# ЛОКАЛЬНЫЙ ЗАПУСК (python server.py)
# -----------------------------
if __name__ == "__main__":
    # локально: Flask + сразу бот
    port = int(os.environ.get("PORT", "10000"))
    log.info("Starting Flask dev server on 0.0.0.0:%s", port)
    app.run(host="0.0.0.0", port=port)
