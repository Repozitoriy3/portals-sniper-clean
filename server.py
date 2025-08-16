import os
import logging
import asyncio
import sqlite3
import time
from threading import Thread
from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ------------------------------------------------
# Логирование
# ------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger("portals-bot")

# ------------------------------------------------
# Flask сервер для Render
# ------------------------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Portals Watcher is running."

@app.route("/webapp")
def webapp():
    return """
    <html><body style='background:#111;color:#eee;font-family:sans-serif;'>
    <h2>Portals Watcher</h2>
    <p>База работает. Дальше добавим подписки и алерты.</p>
    </body></html>
    """

# ------------------------------------------------
# Конфиг
# ------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = "data.db"

# ------------------------------------------------
# SQLite
# ------------------------------------------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions(
        user_id INTEGER NOT NULL,
        collection TEXT NOT NULL,
        threshold_pct REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, collection)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS seen_listings(
        listing_id TEXT PRIMARY KEY
    )
    """)
    conn.commit()
    conn.close()

db_init()

def add_subscription(user_id: int, collection: str, threshold_pct: float = 0.0) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO subscriptions(user_id, collection, threshold_pct) VALUES (?, ?, ?)",
        (user_id, collection.lower(), threshold_pct),
    )
    conn.commit()
    conn.close()

def remove_subscription(user_id: int, collection: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM subscriptions WHERE user_id=? AND collection=?",
                       (user_id, collection.lower()))
    conn.commit()
    conn.close()
    return cur.rowcount > 0

def list_subscriptions(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT collection, threshold_pct FROM subscriptions WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_seen(listing_id: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO seen_listings(listing_id) VALUES (?)", (listing_id,))
    conn.commit()
    conn.close()

def is_seen(listing_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT 1 FROM seen_listings WHERE listing_id=? LIMIT 1", (listing_id,))
    seen = cur.fetchone() is not None
    conn.close()
    return seen

# ------------------------------------------------
# Telegram Bot команды
# ------------------------------------------------
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /watch <collection> [процент]")
        return
    collection = context.args[0]
    thr = 0.0
    if len(context.args) > 1:
        try:
            thr = float(context.args[1])
            if thr < 0 or thr > 90:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("Процент должен быть числом от 0 до 90")
            return

    add_subscription(update.effective_user.id, collection, thr)
    await update.message.reply_text(f"Подписка на {collection} добавлена (порог {thr}%)")

async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /unwatch <collection>")
        return
    ok = remove_subscription(update.effective_user.id, context.args[0])
    await update.message.reply_text("Удалено." if ok else "Не было подписки.")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = list_subscriptions(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Подписок нет. Добавь: /watch <collection>")
        return
    text = "Твои подписки:\n" + "\n".join(f"• {c} (порог {thr}%)" for c, thr in rows)
    await update.message.reply_text(text)

# ==== CONFIG ДЛЯ ПОРТАЛС-БЕКЕНДА ====
PORTALS_API_BASE = os.environ.get("PORTALS_API_BASE", "").rstrip("/")  # например: https://your-backend.example/api
PORTALS_API_KEY  = os.environ.get("PORTALS_API_KEY", "")               # если нужен Bearer-токен
PORTALS_FAKE_MODE = os.environ.get("PORTALS_FAKE_MODE", "0") == "1"    # включи "1" для теста без бэка

import httpx

def _get_headers():
    h = {"Accept": "application/json"}
    if PORTALS_API_KEY:
        h["Authorization"] = f"Bearer {PORTALS_API_KEY}"
    return h

def _pick(d: dict, *names, default=None):
    """Безопасно достаём первое существующее поле из вариантов имён."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

# ---------- Реализация floor ----------
def get_collection_stats(slug: str):
    """
    Ожидается JSON с полем флора. Подойдёт любой из:
    floor, floor_price, floorPrice, stats.floor, metrics.floor и т.п.
    """
    if PORTALS_FAKE_MODE:
        # Фейковый «флор» для проверки
        return {"floor": 10.0}

    if not PORTALS_API_BASE:
        logging.warning("PORTALS_API_BASE не задан — вернуть пусто")
        return None

    url = f"{PORTALS_API_BASE}/collections/{slug}"
    try:
        with httpx.Client(timeout=8.0) as cli:
            r = cli.get(url, headers=_get_headers())
            r.raise_for_status()
            data = r.json()

        # пробуем разные варианты, плюс вложенные места
        floor = _pick(
            data,
            "floor", "floor_price", "floorPrice",
            default=_pick(_pick(data, "stats", "metrics", default={}), "floor", "floor_price", "floorPrice")
        )
        if floor is None:
            logging.warning("Не нашли поле floor в ответе для %s: %s", slug, list(data.keys()))
            return None
        return {"floor": float(floor)}
    except Exception:
        logging.exception("get_collection_stats(%s) failed", slug)
        return None

# ---------- Реализация новых листингов ----------
def get_recent_listings(slug: str, limit: int = 10):
    """
    Ожидается список объектов с полями id/price/title/url (имена полей гибко распознаются).
    Подходит JSON в форматах:
      { items: [ ... ] }  или  [ ... ]
    """
    if PORTALS_FAKE_MODE:
        # Вернём «дешёвый» листинг, чтобы проверить оповещения
        return [{
            "id": f"fake-{int(time.time())}",
            "price": 7.5,
            "title": f"Test listing for {slug}",
            "url": f"https://example.com/{slug}/listing/test"
        }]

    if not PORTALS_API_BASE:
        return []

    url = f"{PORTALS_API_BASE}/collections/{slug}/listings?limit={int(limit)}"
    try:
        with httpx.Client(timeout=8.0) as cli:
            r = cli.get(url, headers=_get_headers())
            r.raise_for_status()
            data = r.json()

        rows = data.get("items", data) if isinstance(data, dict) else data
        out = []
        for row in rows[:limit]:
            lid   = str(_pick(row, "id", "listing_id", "uuid", default=""))
            price = _pick(row, "price", "listing_price", "listingPrice", "amount", default=None)
            title = _pick(row,
                          "title", "name", "token_name",
                          default=f"{slug} #{_pick(row, 'token_id', 'tokenId', default='?')}")
            url_  = _pick(row, "url", "link", "permalink", default=f"https://example.com/{slug}")
            if not lid or price is None:
                continue
            out.append({
                "id": lid,
                "price": float(price),
                "title": str(title),
                "url": str(url_),
            })
        return out
    except Exception:
        logging.exception("get_recent_listings(%s) failed", slug)
        return []


# ------------------------------------------------
# Мониторинг
# ------------------------------------------------
async def monitoring_loop(application: Application):
    bot = application.bot
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute("SELECT DISTINCT collection FROM subscriptions")
            collections = [row[0] for row in cur.fetchall()]
            conn.close()

            for slug in collections:
                stats = get_collection_stats(slug)
                if not stats or "floor" not in stats:
                    continue
                floor = float(stats["floor"])

                listings = get_recent_listings(slug, limit=20)
                for item in listings:
                    lid = str(item.get("id"))
                    if not lid or is_seen(lid):
                        continue
                    price = float(item.get("price") or 0)

                    # подписчики этой коллекции
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.execute("SELECT user_id, threshold_pct FROM subscriptions WHERE collection=?", (slug,))
                    subs = cur.fetchall()
                    conn.close()

                    for user_id, thr in subs:
                        border = floor * (1.0 - thr/100.0)
                        if price <= border:
                            text = (
                                f"⚡️ Листинг ниже флора в {slug}\n"
                                f"Цена: {price} (floor {floor}, порог {thr}%)\n"
                                f"{item.get('title','')}\n"
                                f"{item.get('url','')}"
                            )
                            try:
                                await bot.send_message(user_id, text, disable_web_page_preview=True)
                            except Exception as e:
                                log.warning("send fail: %s", e)

                    mark_seen(lid)

        except Exception:
            log.exception("monitoring error")

        await asyncio.sleep(6)

# ------------------------------------------------
# Запуск бота в отдельном потоке
# ------------------------------------------------
_application_ref = None

def run_bot():
    global _application_ref
    application = Application.builder().token(BOT_TOKEN).build()
    _application_ref = application

    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(CommandHandler("watch", cmd_watch))
    application.add_handler(CommandHandler("unwatch", cmd_unwatch))
    application.add_handler(CommandHandler("list", cmd_list))

    # параллельно мониторинг
    async def runner():
        asyncio.create_task(monitoring_loop(application))
        await application.run_polling(allowed_updates=Update.ALL_TYPES)

    asyncio.run(runner())

_started = False
def start_background_once():
    global _started
    if _started:
        return
    _started = True
    Thread(target=run_bot, daemon=True).start()

# ------------------------------------------------
# Flask событие старта
# ------------------------------------------------
@app.before_request
def activate_bot():
    start_background_once()

# ------------------------------------------------
# Запуск (локально)
# ------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    start_background_once()
    app.run(host="0.0.0.0", port=port)
