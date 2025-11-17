import os, logging, aiohttp
from collections import defaultdict
from importlib import metadata
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# --- safety checks for conflicting packages ---
try:
    metadata.version("telegram")
    raise RuntimeError("Conflicting package 'telegram' is installed. Uninstall it (pip uninstall telegram).")
except metadata.PackageNotFoundError:
    pass

try:
    ptb_ver = metadata.version("python-telegram-bot")
except metadata.PackageNotFoundError:
    raise RuntimeError("python-telegram-bot not installed. Add it to requirements.txt")

if int(ptb_ver.split(".")[0]) < 20:
    raise RuntimeError(f"python-telegram-bot>=20 required (found {ptb_ver}). Pin to 20.x in requirements.txt")

# --- normal bot code ---
load_dotenv()
logging.basicConfig(level=logging.WARNING)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))
if not all([BOT_TOKEN, OPENAI_KEY, WEBHOOK_URL]):
    raise RuntimeError("Missing BOT_TOKEN, OPENAI_API_KEY, or WEBHOOK_URL")

memory = defaultdict(list)
MAX_MEMORY = 5

async def openai_chat(messages):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {"model":"gpt-3.5-turbo","messages":messages,"temperature":0.7}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers, timeout=30) as r:
            data = await r.json()
            return data["choices"][0]["message"]["content"].strip()

async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    cid = update.effective_chat.id
    memory[cid].append({"role":"user","content":text})
    memory[cid] = memory[cid][-MAX_MEMORY:]
    system = {"role":"system","content":"You are a concise helpful assistant."}
    msgs = [system] + [{"role":m["role"], "content":m["content"]} for m in memory[cid]]
    reply = await openai_chat(msgs)
    await update.message.reply_text(reply)
    memory[cid].append({"role":"assistant","content":reply})
    memory[cid] = memory[cid][-MAX_MEMORY:]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ProHybrid AI — DM me or mention me in groups (or use /ask).")

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask your question")
        return
    await respond(update, context, " ".join(context.args))

async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text: return
    if update.effective_chat.type == "private":
        await respond(update, context, text); return
    bot = await context.bot.get_me()
    mention = f"@{bot.username}"
    if text.startswith("/ask") or mention in text:
        clean = text.replace(mention, "").replace("/ask", "").strip()
        if clean: await respond(update, context, clean)

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    return app

if __name__ == "__main__":
    app = build_app()
    app.run_webhook(listen="0.0.0.0", port=PORT, webhook_path="/webhook", webhook_url=WEBHOOK_URL)
