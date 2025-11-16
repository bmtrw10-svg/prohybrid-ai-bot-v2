import asyncio

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
        # ADD TIMEOUT: 15 seconds max
        stream = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are fast. Reply in 1-2 sentences. Use bullet points."}
                ] + [{"role": m["role"], "content": m["content"]} for m in chat_memory[chat_id]],
                stream=True,
                temperature=0.7,
            ),
            timeout=15.0  # MAX 15 SEC
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
                if len(full_response) > 50:  # Show partial after 50 chars
                    await msg.edit_text(f"🤖 {full_response}...", parse_mode=ParseMode.MARKDOWN)

        await msg.edit_text(f"🤖 {full_response}", parse_mode=ParseMode.MARKDOWN)
        chat_memory[chat_id].append({"role": "assistant", "content": full_response})

    except asyncio.TimeoutError:
        await msg.edit_text("❌ OpenAI too slow. Try again.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        await msg.edit_text("❌ AI error. Try simpler question.", parse_mode=ParseMode.MARKDOWN)
