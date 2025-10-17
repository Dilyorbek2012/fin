import json
import uuid
from datetime import datetime, timedelta
import asyncio
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


def parse_datetime_from_text(date_part: str, time_part: str) -> datetime:
    """
    Поддерживаем формат:
      dd.mm.YYYY HH:MM
    Возвращает datetime.
    """
    return datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот-напоминалка.\n\n"
        "Отправь сообщение в формате:\n"
        "`18.10.2025 15:00 Встреча с друзьями`\n\n"
        "Команды:\n"
        "/list — показать ваши напоминания\n"
        "/cancel <id> — отменить напоминание\n\n"
        "Пример: `18.10.2025 15:00 позвонить маме`",
        parse_mode="Markdown"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def schedule_job(application, reminder):
    """
    reminder: dict {id, chat_id, time_iso, text}
    Создаёт задачу (Job) в JobQueue для отправки напоминания.
    """
    remind_time = datetime.fromisoformat(reminder["time_iso"])
    delay = (remind_time - datetime.now()).total_seconds()
    if delay <= 0:
        # время уже прошло — отправим сразу (в фоне)
        await application.bot.send_message(
            chat_id=reminder["chat_id"],
            text=f"🔔 (прошедшее время) Напоминание: {reminder['text']}"
        )
        # и не запланируем далее; удаление будет обработано при старте/списке
        return

    # job callback
    async def job_callback(context: ContextTypes.DEFAULT_TYPE):
        try:
            await context.bot.send_message(
                chat_id=reminder["chat_id"],
                text=f"🔔 Напоминание: {reminder['text']}"
            )
        except Exception as e:
            print("Ошибка при отправке напоминания:", e)

        # после отправки удаляем из файла (persist)
        reminders = load_reminders()
        reminders = [r for r in reminders if r["id"] != reminder["id"]]
        save_reminders(reminders)

    # schedule
    application.job_queue.run_once(job_callback, when=delay)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # ожидаем минимум: date time message
    # split на 3 части: date, time, rest
    parts = text.split(" ", 2)
    if len(parts) < 2:
        await update.message.reply_text(
            "Неверный формат. Используйте: `dd.mm.YYYY HH:MM текст`",
            parse_mode="Markdown"
        )
        return

    date_part = parts[0]
    time_part = parts[1]
    reminder_text = parts[2] if len(parts) > 2 else "Напоминание"

    try:
        remind_dt = parse_datetime_from_text(date_part, time_part)
    except ValueError:
        await update.message.reply_text(
            "Неверный формат даты/времени. Ожидается `dd.mm.YYYY HH:MM`.\n"
            "Пример: `18.10.2025 15:00 встреча`",
            parse_mode="Markdown"
        )
        return

    if (remind_dt - datetime.now()).total_seconds() <= 0:
        await update.message.reply_text("❗ Время уже прошло — укажите время в будущем.")
        return

    # создаём запись
    reminder_id = str(uuid.uuid4())[:8]
    reminder = {
        "id": reminder_id,
        "chat_id": update.message.chat_id,
        "time_iso": remind_dt.isoformat(),
        "text": reminder_text,
    }

    # сохранить в файл
    reminders = load_reminders()
    reminders.append(reminder)
    save_reminders(reminders)

    # запланировать
    await schedule_job(context.application, reminder)

    await update.message.reply_text(
        f"✅ Напоминание установлено\nID: `{reminder_id}`\n"
        f"Время: {remind_dt.strftime('%d.%m.%Y %H:%M')}\nТекст: {reminder_text}",
        parse_mode="Markdown"
    )


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r["chat_id"] == chat_id]
    if not user_reminders:
        await update.message.reply_text("У вас нет сохранённых напоминаний.")
        return

    lines = []
    for r in user_reminders:
        dt = datetime.fromisoformat(r["time_iso"])
        lines.append(f"ID: `{r['id']}` — {dt.strftime('%d.%m.%Y %H:%M')} — {r['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("Использование: /cancel <id>")
        return
    rid = parts[1].strip()

    reminders = load_reminders()
    before_count = len(reminders)
    reminders = [r for r in reminders if not (r["id"] == rid and r["chat_id"] == update.message.chat_id)]
    after_count = len(reminders)

    if before_count == after_count:
        await update.message.reply_text("Напоминание не найдено (проверьте ID).")
        return

    save_reminders(reminders)
    await update.message.reply_text(f"✅ Напоминание `{rid}` удалено.", parse_mode="Markdown")


async def on_startup(application):
    print("Загружаем и планируем сохранённые напоминания...")
    reminders = load_reminders()
    # планируем только те, у которых время в будущем
    count = 0
    for r in reminders:
        try:
            remind_time = datetime.fromisoformat(r["time_iso"])
        except Exception:
            continue
        if (remind_time - datetime.now()).total_seconds() > 0:
            # schedule
            await schedule_job(application, r)
            count += 1
    print(f"Запланировано {count} напоминаний.")


def main():
    import os
    TOKEN = os.environ.get("TG_BOT_TOKEN") or "8362070525:AAHSZQDqJo3LhVS2rZ05UCvywQGxHyqdFpM"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # startup tasks: загрузить и запланировать
    app.post_init = on_startup

    print("Запуск бота...")
    app.run_polling()


if __name__ == "__main__":
    main()

