import os, logging, asyncio, aiohttp
from collections import defaultdict
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))
if not all([BOT_TOKEN, OPENAI_KEY, WEBHOOK_URL]):
    raise RuntimeError("Missing BOT_TOKEN, OPENAI_API_KEY, or WEBHOOK_URL")

# memory: chat_id -> list of {"role":"user"/"assistant","content":...}
chat_memory = defaultdict(list)
MAX_MEMORY = 5

async def openai_chat(messages):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {"model":"gpt-3.5-turbo","messages":messages, "temperature":0.7}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()

async def stream_response(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    chat_id = update.effective_chat.id
    chat_memory[chat_id].append({"role":"user","content":prompt})
    chat_memory[chat_id] = chat_memory[chat_id][-MAX_MEMORY:]
    system = {"role":"system","content":"You are a concise helpful assistant."}
    messages = [system] + [{"role":m["role"], "content":m["content"]} for m in chat_memory[chat_id]]
    reply = await openai_chat(messages)
    await update.message.reply_text(reply)
    chat_memory[chat_id].append({"role":"assistant","content":reply})
    chat_memory[chat_id] = chat_memory[chat_id][-MAX_MEMORY:]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ProHybrid AI — DM me or mention me in groups (or use /ask).")

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask your question")
        return
    await stream_response(update, context, " ".join(context.args))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    if update.effective_chat.type == "private":
        await stream_response(update, context, text)
        return
    bot = await context.bot.get_me()
    mention = f"@{bot.username}"
    if text.startswith("/ask") or mention in text:
        clean = text.replace(mention, "").replace("/ask", "").strip()
        if clean:
            await stream_response(update, context, clean)

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    return app

app = build_app()

async def set_webhook():
    await app.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    asyncio.run(set_webhook())
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="warning")
