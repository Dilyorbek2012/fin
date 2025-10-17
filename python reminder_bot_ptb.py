import json
import uuid
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

REMINDERS_FILE = Path("reminders.json")

def load_reminders():
    if not REMINDERS_FILE.exists():
        return []
    with REMINDERS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_reminders(reminders):
    with REMINDERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот-напоминалка 🤖\n\n"
        "Отправь мне сообщение в формате:\n"
        "`18.10.2025 15:00 Встреча с друзьями`\n\n"
        "Команды:\n"
        "/list — показать все напоминания\n"
        "/cancel <id> — удалить напоминание\n",
        parse_mode="Markdown"
    )

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    reminders = [r for r in load_reminders() if r["chat_id"] == chat_id]
    if not reminders:
        await update.message.reply_text("📭 У вас нет напоминаний.")
        return
    lines = [
        f"🆔 `{r['id']}` — {datetime.fromisoformat(r['time']).strftime('%d.%m.%Y %H:%M')} — {r['text']}"
        for r in reminders
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /cancel <id>")
        return
    rid = args[1]
    reminders = load_reminders()
    reminders = [r for r in reminders if r["id"] != rid]
    save_reminders(reminders)
    await update.message.reply_text(f"✅ Напоминание {rid} удалено.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(" ", 2)
    if len(parts) < 3:
        await update.message.reply_text("⚠️ Формат: `дд.мм.гггг чч:мм текст`", parse_mode="Markdown")
        return
    date_str, time_str, reminder_text = parts
    try:
        remind_time = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
    except ValueError:
        await update.message.reply_text("⚠️ Неверный формат даты или времени.")
        return
    if remind_time < datetime.now():
        await update.message.reply_text("⏰ Укажи будущее время!")
        return
    reminder_id = str(uuid.uuid4())[:8]
    reminder = {
        "id": reminder_id,
        "chat_id": update.message.chat_id,
        "time": remind_time.isoformat(),
        "text": reminder_text
    }
    reminders = load_reminders()
    reminders.append(reminder)
    save_reminders(reminders)
    await update.message.reply_text(
        f"✅ Напоминание создано!\nID: `{reminder_id}`\nВремя: {date_str} {time_str}\nТекст: {reminder_text}",
        parse_mode="Markdown"
    )

async def send_due_reminders(app):
    while True:
        reminders = load_reminders()
        now = datetime.now()
        to_send = [r for r in reminders if datetime.fromisoformat(r["time"]) <= now]
        for r in to_send:
            try:
                await app.bot.send_message(chat_id=r["chat_id"], text=f"🔔 Напоминание: {r['text']}")
            except Exception as e:
                print("Ошибка при отправке:", e)
            reminders = [x for x in reminders if x["id"] != r["id"]]
            save_reminders(reminders)
        await asyncio.sleep(60)

import asyncio
import os

async def main():
    TOKEN = os.environ.get("TG_BOT_TOKEN") or "8362070525:AAHSZQDqJo3LhVS2rZ05UCvywQGxHyqdFpM"
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    asyncio.create_task(send_due_reminders(app))
    print("🤖 Бот запущен...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
