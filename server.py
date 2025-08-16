import os
import logging
from threading import Thread

from flask import Flask, Response, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ----------------------- settings -----------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEBAPP_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Portals Watcher</title></head>
  <body style="background:#0b1220;color:#e6e8ef;font-family:system-ui,Segoe UI,Roboto,Arial;padding:40px">
    <div style="max-width:760px;margin:0 auto;background:#0e1426;border-radius:16px;padding:24px;box-shadow:0 10px 30px rgba(0,0,0,.3)">
      <h1 style="margin:0 0 8px 0">Portals Watcher</h1>
      <p style="margin:0;opacity:.8">База работает. Дальше добавим подписки и алерты.</p>
    </div>
  </body>
</html>
"""

# ----------------------- logging ------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("portals-bot")

# ----------------------- telegram -----------------------
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")
    app = Application.builder().token(BOT_TOKEN).build()

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Привет! Я запущен ✅")

    async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("pong")

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    return app


def run_bot() -> None:
    """Запуск polling в отдельном потоке с собственным event loop."""
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is empty; skip bot start.")
        return
    try:
        import asyncio

        # 🔧 НАДЁЖНЫЙ СПОСОБ: создаём цикл через policy и назначаем его текущим
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
        policy.set_event_loop(loop)

        application = build_app()
        log.info("Starting Telegram polling…")
        # В PTB 20+ это синхронный вызов, который внутри использует асинхронный раннер
        application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)
    except Exception as e:
        log.exception("Bot crashed: %s", e)


_started = False

def start_background_once() -> None:
    global _started
    if _started:
        return
    _started = True
    Thread(target=run_bot, daemon=True, name="bot-runner").start()
    log.info("Background bot thread started.")


# ------------------------- flask ------------------------
app = Flask(__name__)

@app.before_request
def _kickoff():
    # гарантируем, что бот поднимется один раз
    start_background_once()

@app.get("/")
def root() -> Response:
    return Response("Bot is running!", mimetype="text/plain; charset=utf-8")

@app.get("/webapp")
def webapp():
    return Response(WEBAPP_HTML, mimetype="text/html; charset=utf-8")

@app.get("/healthz")
def health():
    return jsonify(ok=True)


if __name__ == "__main__":
    # локальный запуск (не используется на Render с gunicorn)
    start_background_once()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
