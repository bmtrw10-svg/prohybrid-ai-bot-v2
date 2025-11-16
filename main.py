import os
import logging
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

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
import uvicorn

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))

if not all([BOT_TOKEN, OPENAI_API_KEY, WEBHOOK_URL]):
    raise ValueError("Missing env vars!")

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

async def stream_response(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, chat_id: int):
    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("⏳ 3 messages / 30s", parse_mode=ParseMode.MARKDOWN)
        return

    chat_memory[chat_id].append({"role": "user", "content": prompt})
    if len(chat_memory[chat_id]) > MAX_MEMORY:
        chat_memory[chat_id] = chat_memory[chat_id][-MAX_MEMORY:]

    msg = await update.message.reply_text("🤖 Thinking...", parse_mode=ParseMode.MARKDOWN)
    full_response = ""

    try:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Helpful AI. Short replies."}
            ] + [{"role": m["role"], "content": m["content"]} for m in chat_memory[chat_id]],
            stream=True,
            temperature=0.7,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
                if len(full_response) % 10 == 0:
                    await msg.edit_text(f"🤖 {full_response}...", parse_mode=ParseMode.MARKDOWN)

        await msg.edit_text(f"🤖 {full_response}", parse_mode=ParseMode.MARKDOWN)
        chat_memory[chat_id].append({"role": "assistant", "content": full_response})

    except Exception as e:
        logger.error(f"OpenAI: {e}")
        await msg.edit_text("❌ Try again.", parse_mode=ParseMode.MARKDOWN)

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *ProHybrid AI v2*\n\n"
        "• DM: full chat\n"
        "• Group: @me or /ask\n"
        "• Free • Fast",
        parse_mode=ParseMode.MARKDOWN
    )

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("`/ask hello`", parse_mode=ParseMode.MARKDOWN)
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

# === APP ===
application = Application.builder().token(BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ask", ask_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start"),
        BotCommand("ask", "Ask in group")
    ])
    logger.info("Commands set.")

application.post_init = post_init

# === WEBHOOK & SERVER ===
async def main():
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set: {WEBHOOK_URL}")
    await application.updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_URL.split("/")[-1],
        webhook_url=WEBHOOK_URL,
    )
    logger.info(f"Server running on port {PORT}")
    # Keep running
    await application.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
