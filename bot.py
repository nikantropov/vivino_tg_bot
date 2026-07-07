"""Vivino Contest Telegram Bot — main entry point."""

import csv
import io
import logging
import os
import random
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

import config
from database import (
    init_db, get_current_week_key, get_previous_week_key,
    register_user, save_screenshot, is_duplicate_screenshot,
    get_user_email, is_user_registered, get_user_stats,
    get_week_participants, get_week_screenshots_count,
    save_winner, is_winner_already_chosen, get_all_winners,
    get_stats, get_week_leaderboard, get_all_participants,
    get_all_screenshots, get_screenshots_by_week,
    get_registered_user_ids,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_EMAIL = 1
CONFIRM_RAFFLE = 2
WAITING_SCREENSHOT = 3
ASK_ANOTHER = 4


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def get_current_wine() -> str | None:
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    for period, wine in config.WINE_SCHEDULE.items():
        start_str, end_str = period.split("-")
        start = datetime.strptime(f"{now.year}.{start_str}", "%Y.%d.%m").replace(tzinfo=tz)
        end = datetime.strptime(f"{now.year}.{end_str}", "%Y.%d.%m").replace(
            tzinfo=tz, hour=23, minute=59, second=59)
        if start <= now <= end:
            return wine
    return None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🍷 Вино недели", callback_data="wine_of_week")],
        [InlineKeyboardButton("📧 Зарегистрировать email", callback_data="register_email")],
        [InlineKeyboardButton("📸 Загрузить скриншот", callback_data="upload_screenshot")],
    ]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])

    wine = get_current_wine()
    wine_text = f"🍷 Вино недели: <b>{wine}</b>\n\n" if wine else ""

    await update.message.reply_text(
        f"{wine_text}Добро пожаловать в конкурс Vivino от Luding!\n\n"
        "📋 <b>Как участвовать:</b>\n"
        "1. Зарегистрируйте рабочий email (@luding.ru)\n"
        "2. Загрузите скриншот с оценкой вина Vivino\n"
        "3. Каждый понедельник — розыгрыш среди участников!\n\n"
        " Cada скриншот = один шанс в розыгрыше 🎲",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    if not stats:
        await update.message.reply_text("Вы ещё не зарегистрированы. Нажмите «Зарегистрировать email».")
        return

    rank_str = f"#{stats['week_rank']}" if stats['week_rank'] else "нет"
    text = (
        f"📊 <b>Ваша статистика</b>\n\n"
        f"📧 Email: {stats['email']}\n"
        f"📸 Всего скриншотов: {stats['total_screenshots']}\n"
        f"📅 Эта неделя: {stats['this_week']} скр.\n"
        f"🏆 Побед: {stats['wins']}\n"
        f"📈 Рейтинг недели: {rank_str} из {stats['week_participants']}\n"
        f"🗓 Активных недель: {stats['weeks_active']}\n"
        f"📅 Текущая неделя: {stats['week_key']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")
  async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "wine_of_week":
        wine = get_current_wine()
        if wine:
            await query.edit_message_text(
                f"🍷 <b>Вино этой недели:</b> {wine}\n\n"
                "Сделайте скриншот оценки этого вина в приложении Vivino и отправьте его боту!",
                parse_mode="HTML")
        else:
            await query.edit_message_text("Сейчас нет активного вина недели.", parse_mode="HTML")

    elif data == "register_email":
        await query.edit_message_text(
            "📧 Введите ваш рабочий email (@luding.ru):\n\n"
            "<i>Пример: ivan@luding.ru</i>",
            parse_mode="HTML")
        context.user_data["state"] = WAITING_EMAIL

    elif data == "upload_screenshot":
        if not await is_user_registered(user.id):
            await query.edit_message_text(
                "❌ Сначала зарегистрируйте email!\nНажмите «Зарегистрировать email».",
                parse_mode="HTML")
            return
        wine = get_current_wine()
        if not wine:
            await query.edit_message_text("Сейчас нет активного вина недели.", parse_mode="HTML")
            return
        await query.edit_message_text(
            f"📸 Отправьте скриншот с оценкой вина <b>{wine}</b> из Vivino.\n\n"
            "Поддерживаются форматы: JPG, PNG.",
            parse_mode="HTML")
        context.user_data["state"] = WAITING_SCREENSHOT

    elif data == "admin_panel":
        if not is_admin(user.id):
            await query.edit_message_text("⛔ Доступ запрещён.", parse_mode="HTML")
            return
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("🏆 Розыгрыш", callback_data="admin_raffle")],
            [InlineKeyboardButton("📋 Таблица лидеров", callback_data="admin_leaderboard")],
            [InlineKeyboardButton("👥 Участники", callback_data="admin_participants")],
            [InlineKeyboardButton("📤 Экспорт CSV", callback_data="admin_export")],
            [InlineKeyboardButton("📜 История победителей", callback_data="admin_winners")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
        ]
        await query.edit_message_text(
            "⚙️ <b>Админ-панель</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("🍷 Вино недели", callback_data="wine_of_week")],
            [InlineKeyboardButton("📧 Зарегистрировать email", callback_data="register_email")],
            [InlineKeyboardButton("📸 Загрузить скриншот", callback_data="upload_screenshot")],
        ]
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        wine = get_current_wine()
        wine_text = f"🍷 Вино недели: <b>{wine}</b>\n\n" if wine else ""
        await query.edit_message_text(
            f"{wine_text}Добро пожаловать в конкурс Vivino от Luding!",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # Admin sub-menus
    elif data == "admin_stats":
        if not is_admin(user.id): return
        stats = await get_stats()
        await query.edit_message_text(
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"📸 Скриншотов: {stats['total_screenshots']}\n"
            f"🗓 Активных недель: {stats['active_weeks']}\n"
            f"🏆 Победителей: {stats['total_winners']}\n"
            f"📋 Участников на этой неделе: {stats['this_week_participants']}\n"
            f"📅 Текущая неделя: {stats['current_week']}",
            parse_mode="HTML")

    elif data == "admin_leaderboard":
        if not is_admin(user.id): return
        week_key = get_current_week_key()
        lb = await get_week_leaderboard(week_key)
        if not lb:
            await query.edit_message_text(f"Нет данных за {week_key}.", parse_mode="HTML")
            return
        lines = [f"🏆 <b>Лидеры недели {week_key}</b>\n"]
        for i, p in enumerate(lb, 1):
            lines.append(f"{i}. {p['email']} — {p['screenshot_count']} скр.")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML")

    elif data == "admin_participants":
        if not is_admin(user.id): return
        parts = await get_all_participants()
        if not parts:
            await query.edit_message_text("Нет участников.", parse_mode="HTML")
            return
        lines = ["👥 <b>Все участники</b>\n"]
        for p in parts:
            wins = p.get("win_count", 0) or 0
            lines.append(f"• {p['email']} — {p['total_screenshots']} скр., {p['weeks_active']} нед., {wins} побед")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n..."
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "admin_export":
        if not is_admin(user.id): return
        await query.edit_message_text(
            "📤 Используйте команду:\n<code>/export</code> — текущая неделя\n<code>/export 2026-W26</code> — конкретная неделя",
            parse_mode="HTML")

    elif data == "admin_winners":
        if not is_admin(user.id): return
        winners = await get_all_winners()
        if not winners:
            await query.edit_message_text("Победителей пока нет.", parse_mode="HTML")
            return
        lines = ["📜 <b>История победителей</b>\n"]
        for w in winners:
            lines.append(f"📅 {w['week_key']}: {w['email']}")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML")

    elif data == "admin_raffle":
        if not is_admin(user.id): return
        week_key = get_previous_week_key()
        if await is_winner_already_chosen(week_key):
            await query.edit_message_text(f"Победитель за {week_key} уже выбран!", parse_mode="HTML")
            return
        participants = await get_week_participants(week_key)
        if not participants:
            await query.edit_message_text(f"Нет участников за {week_key}.", parse_mode="HTML")
            return
        weights = [p["screenshot_count"] for p in participants]
        winner = random.choices(participants, weights=weights, k=1)[0]
        context.user_data["pending_winner"] = {
            "week_key": week_key, "user_id": winner["user_id"],
            "email": winner["email"], "count": winner["screenshot_count"],
        }
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_raffle")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_raffle")],
        ]
        await query.edit_message_text(
            f"🎰 <b>Предварительный результат розыгрыша {week_key}</b>\n\n"
            f"Участников: {len(participants)}\n\n"
            f"🏆 Победитель: <b>{winner['email']}</b>\n"
            f"Скриншотов: {winner['screenshot_count']}\n\n"
            "Подтвердить?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "confirm_raffle":
        if not is_admin(user.id): return
        pw = context.user_data.get("pending_winner")
        if not pw:
            await query.edit_message_text("Нет данных для подтверждения.", parse_mode="HTML")
            return
        await save_winner(pw["user_id"], pw["email"], pw["week_key"])
        try:
            await context.bot.send_message(
                chat_id=pw["user_id"],
                text=f"🎉 Поздравляем! Вы выиграли розыгрыш за неделю {pw['week_key']}!\n"
                     f"Ваше количество скриншотов: {pw['count']} 🍾")
        except Exception as e:
            logger.error(f"Failed to notify winner: {e}")
        await query.edit_message_text(
            f"✅ Победитель <b>{pw['email']}</b> за неделю {pw['week_key']} утверждён!\n"
            f"Уведомление отправлено.",
            parse_mode="HTML")
        context.user_data.pop("pending_winner", None)

    elif data == "cancel_raffle":
        if not is_admin(user.id): return
        context.user_data.pop("pending_winner", None)
        await query.edit_message_text("Розыгрыш отменён.", parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == WAITING_EMAIL:
        email = update.message.text.strip()
        if not email.endswith("@luding.ru"):
            await update.message.reply_text(
                "❌ Допускаются только рабочие email @luding.ru!\nПопробуйте снова:")
            return
        success, msg = await register_user(update.effective_user.id, update.effective_user.username, email)
        await update.message.reply_text(msg, parse_mode="HTML")
        if success:
            context.user_data["state"] = None

    elif state == WAITING_SCREENSHOT:
        user_id = update.effective_user.id
        email = await get_user_email(user_id)
        if not email:
            await update.message.reply_text("❌ Email не найден. Зарегистрируйтесь заново.")
            context.user_data["state"] = None
            return

        photos = update.message.photo
        if not photos:
            await update.message.reply_text("❌ Это не фото. Отправьте скриншот (JPG/PNG).")
            return

        file = photos[-1]
        file_unique_id = file.file_unique_id

        if await is_duplicate_screenshot(user_id, file_unique_id):
            await update.message.reply_text("⚠️ Этот скриншот уже был загружен!")
            return

        try:
            os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
            file_obj = await file.get_file()
            file_path = os.path.join(config.SCREENSHOTS_DIR, f"{file_unique_id}.jpg")
            await file_obj.download_to_drive(file_path)
        except Exception as e:
            logger.error(f"Download error: {e}")
            await update.message.reply_text("❌ Ошибка сохранения. Попробуйте снова.")
            return

        week_key = get_current_week_key()
        if await save_screenshot(user_id, email, file.file_id, file_unique_id, file_path, week_key):
            count = await get_week_screenshots_count(week_key)
            wine = get_current_wine()
            await update.message.reply_text(
                f"✅ Скриншот принят! ({wine})\n"
                f"📸 Всего за неделю: {count}\n"
                f"Отправить ещё? Или нажмите /start для меню.",
                parse_mode="HTML")
        else:
            await update.message.reply_text("⚠️ Ошибка дублирования.")
        context.user_data["state"] = ASK_ANOTHER

    elif state == ASK_ANOTHER:
        if update.message.photo:
            user_id = update.effective_user.id
            email = await get_user_email(user_id)
            if not email:
                await update.message.reply_text("❌ Email не найден.")
                context.user_data["state"] = None
                return
            photos = update.message.photo
            file = photos[-1]
            file_unique_id = file.file_unique_id
            if await is_duplicate_screenshot(user_id, file_unique_id):
                await update.message.reply_text("⚠️ Этот скриншот уже был загружен!")
                return
            try:
                os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
                file_obj = await file.get_file()
                file_path = os.path.join(config.SCREENSHOTS_DIR, f"{file_unique_id}.jpg")
                await file_obj.download_to_drive(file_path)
            except Exception as e:
                logger.error(f"Download error: {e}")
                await update.message.reply_text("❌ Ошибка сохранения.")
                return
            week_key = get_current_week_key()
            if await save_screenshot(user_id, email, file.file_id, file_unique_id, file_path, week_key):
                count = await get_week_screenshots_count(week_key)
                await update.message.reply_text(f"✅ Ещё один скриншот! Всего за неделю: {count}")
            else:
                await update.message.reply_text("⚠️ Ошибка дублирования.")
        else:
            await update.message.reply_text("Отправьте фото или нажмите /start для меню.")
          async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    week_key = context.args[0] if context.args else get_current_week_key()
    screenshots = await get_screenshots_by_week(week_key)
    if not screenshots:
        await update.message.reply_text(f"Нет данных за {week_key}.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "user_id", "username", "submitted_at", "week_key", "file_id"])
    for s in screenshots:
        writer.writerow([s["email"], s["user_id"], s.get("username", ""), s["submitted_at"], s["week_key"], s["file_id"]])

    output.seek(0)
    await update.message.reply_document(
        document=InputFile(output, filename=f"vivino_export_{week_key}.csv"),
        caption=f"📊 Экспорт за {week_key}: {len(screenshots)} записей")


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Friday 18:00 MSK — remind users with 0 screenshots this week."""
    user_ids = await get_registered_user_ids()
    week_key = get_current_week_key()
    wine = get_current_wine() or "текущее вино"
    notified = 0
    for uid in user_ids:
        stats = await get_user_stats(uid)
        if stats and stats["this_week"] == 0:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"⏰ Напоминание!\n\n"
                         f"Эта неделя ещё без вашего скриншота! 🍷\n"
                         f"Вино недели: {wine}\n"
                         f"Отправьте скриншот оценки из Vivino, чтобы участвовать в розыгрыше.\n"
                         f"Удачи! 🎲")
                notified += 1
            except Exception as e:
                logger.error(f"Reminder failed for {uid}: {e}")
    logger.info(f"Reminder job: notified {notified}/{len(user_ids)} users")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass  # Suppress health-check logs


async def post_init(application):
    await init_db()
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)

    # Reminder job: every Friday at 18:00 MSK
    job_queue = application.job_queue
    job_queue.run_daily(
        reminder_job,
        time=datetime(2024, 1, 1, config.REMINDER_HOUR, config.REMINDER_MINUTE).time(),
        days=(config.REMINDER_DAY_OF_WEEK,),
        name="weekly_reminder",
    )
    logger.info(f"[INIT] Reminder job scheduled: day={config.REMINDER_DAY_OF_WEEK} "
                f"time={config.REMINDER_HOUR}:{config.REMINDER_MINUTE:02d} MSK")


def main():
    if not config.BOT_TOKEN:
        print("[ERROR] BOT_TOKEN environment variable is not set!")
        return

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("my", my_stats_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("[BOT] Starting Vivino Contest Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Health-check HTTP server for Render.com
    port = int(os.environ.get("PORT", 10000))
    httpd = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[HEALTH] Health-check server on port {port}")
    main()
