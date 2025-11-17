import os
import logging
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)
from telegram.constants import ParseMode
from openai import AsyncOpenAI
from dotenv import load_dotenv

# === INIT ===
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not all([BOT_TOKEN, OPENAI_API_KEY, WEBHOOK_URL]):
    raise ValueError("Missing BOT_TOKEN, OPENAI_API_KEY, or WEBHOOK_URL!")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# === MEMORY & RATE LIMIT ===
chat_memory = defaultdict(list)
MAX_MEMORY = 5
user_requests = defaultdict(list)
RATE_LIMIT = 3
TIME_WINDOW = 30

def is_rate_limited(user_id: int) -> bool:
    now = datetime.now()
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < timedelta(seconds=TIME_WINDOW)]
    if len(user_requests[user_id]) >= RATE_LIMIT:
        return True
    user_requests[user_id].append(now)
    return False

# === AI RESPONSE (FAST + 15s TIMEOUT) ===
async def stream_response(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, chat_id: int):
    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("⏳ 3/30s", parse_mode=ParseMode.MARKDOWN)
        return

    chat_memory[chat_id].append({"role": "user", "content": prompt})
    if len(chat_memory[chat_id]) > MAX_MEMORY:
        chat_memory[chat_id] = chat_memory[chat_id][-MAX_MEMORY:]

    msg = await update.message.reply_text("🤖 Thinking...", parse_mode=ParseMode.MARKDOWN)
    full_response = ""

    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Fast. 1-2 sentences. Bullet points."}
                ] + [{"role": m["role"], "content": m["content"]} for m in chat_memory[chat_id]],
                stream=True,
                temperature=0.7,
            ),
            timeout=15.0
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
                if len(full_response) > 50:
                    await msg.edit_text(f"🤖 {full_response}...", parse_mode=ParseMode.MARKDOWN)

        await msg.edit_text(f"🤖 {full_response}", parse_mode=ParseMode.MARKDOWN)
        chat_memory[chat_id].append({"role": "assistant", "content": full_response})

    except asyncio.TimeoutError:
        await msg.edit_text("❌ Too slow. Try again.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"OpenAI: {e}")
        await msg.edit_text("❌ AI error.", parse_mode=ParseMode.MARKDOWN)

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *ProHybrid AI v3*\n\n"
        "• DM: full chat\n"
        "• Group: @me or /ask\n"
        "• Made in 🇪🇹 Ethiopia",
        parse_mode=ParseMode.MARKDOWN
    )

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: `/ask hi`", parse_mode=ParseMode.MARKDOWN)
        return
    await stream_response(update, context, " ".join(context.args), update.effective_chat.id)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    chat = update.effective_chat

    if chat.type == "private" and text.strip():
        await stream_response(update, context, text, chat.id)
        return

    bot = await context.bot.get_me()
    if f"@{bot.username}" in text:
        clean_text = text.replace(f"@{bot.username}", "").strip()
        if clean_text:
            await stream_response(update, context, clean_text, chat.id)

# === FASTAPI + PTB ===
app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ask", ask_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await application.initialize()  # ← FIXED: NO MORE RuntimeError
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set: {WEBHOOK_URL}")
