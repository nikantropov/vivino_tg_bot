"""Vivino Contest Telegram Bot - main entry point."""

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
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
    get_all_screenshots, get_screenshots_by_week, get_screenshots_by_email,
    get_registered_user_ids, get_all_emails, week_key_to_display,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_EMAIL = 1
WAITING_SCREENSHOT = 2
ASK_ANOTHER = 3
WAITING_USER_EMAIL = 4


def is_admin(user_id):
    return user_id in config.ADMIN_IDS


def _parse_period_date(date_str, year, tz):
    """Parse 'DD.MM' string into datetime with timezone. Handles year rollover."""
    day, month = map(int, date_str.split("."))
    try:
        return datetime(year, month, day, tzinfo=tz)
    except ValueError:
        # month rolled over to next year (e.g. 27.12-02.01)
        return datetime(year + 1, month, day, tzinfo=tz)


def get_current_wine():
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    for period, wine in config.WINE_SCHEDULE.items():
        start_str, end_str = period.split("-")
        start = _parse_period_date(start_str, now.year, tz)
        end = _parse_period_date(end_str, now.year, tz).replace(
            hour=23, minute=59, second=59)
        if end < start:
            # Period crosses a month/year boundary (e.g. 27.07-02.08)
            if now >= start or now <= end:
                return wine
        else:
            if start <= now <= end:
                return wine
    return None


async def start_command(update, context):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("\U0001f4e7 Зарегистрировать email", callback_data="register_email")],
        [InlineKeyboardButton("\U0001f4f8 Загрузить скриншот", callback_data="upload_screenshot")],
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("\u2699\ufe0f Админ-панель", callback_data="admin_panel")])

    wine = get_current_wine()
    wine_text = f"\U0001f377 Вино недели: <b>{wine}</b>\n\n" if wine else ""

    stats = await get_user_stats(user.id)
    if stats and stats["this_week"] > 0:
        await update.message.reply_text(
            "\U0001f389 Спасибо за участие! Загрузить ещё скриншот?")

    await update.message.reply_text(
        f"{wine_text}Добро пожаловать в конкурс Vivino от Luding Group!\n\n"
        "Vivino — один из главных ориентиров при выборе вина, как для покупателей в магазине, так и для наших корпоративных клиентов. "
        "Каждая ваша оценка помогает винам недели быть заметнее — а нам не за что краснеть перед продуктом, который мы сами выбрали. \U0001f60a\n\n"
        "\U0001f4cb <b>Как участвовать:</b>\n"
        "1. Зарегистрируйте рабочий email (\u0434\u043e\u043c\u0435\u043d luding.ru)\n"
        "2. Загрузите скриншот с оценкой вина недели из приложения Vivino\n"
        "3. Каждый понедельник — розыгрыш среди участников \U0001f377\n\n"
        "Каждый скриншот = один шанс в розыгрыше \U0001f3b2",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def my_stats_command(update, context):
    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    if not stats:
        await update.message.reply_text("Вы ещё не зарегистрированы. Нажмите «Зарегистрировать email».")
        return

    rank_str = f"#{stats['week_rank']}" if stats['week_rank'] else "нет"
    text = (
        f"\U0001f4ca <b>Ваша статистика</b>\n\n"
        f"\U0001f4e7 Email: {stats['email']}\n"
        f"\U0001f4f8 Всего скриншотов: {stats['total_screenshots']}\n"
        f"\U0001f4c5 Эта неделя: {stats['this_week']} скр.\n"
        f"\U0001f3c6 Побед: {stats['wins']}\n"
        f"\U0001f4c8 Рейтинг недели: {rank_str} из {stats['week_participants']}\n"
        f"\U0001f5d3 Активных недель: {stats['weeks_active']}\n"
        f"\U0001f4c5 Текущая неделя: {week_key_to_display(stats['week_key'])}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def screenshots_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    week_key = context.args[0] if context.args else get_current_week_key()
    shots = await get_screenshots_by_week(week_key)
    if not shots:
        await update.message.reply_text(f"\U0001f4f8 Нет скриншотов за неделю {week_key_to_display(week_key)}.")
        return
    lines = [f"\U0001f4f8 <b>Скриншоты за {week_key_to_display(week_key)}</b> ({len(shots)} шт.):\n"]
    for i, s in enumerate(shots, 1):
        dt = s["submitted_at"][:16].replace("T", " ")
        username = f"@{s['username']}" if s.get("username") else ""
        lines.append(f"{i}. {s['email']} {username} - {dt}")
    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4000] + "\n..."
    await update.message.reply_text(text, parse_mode="HTML")


async def export_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    week_key = context.args[0] if context.args else get_current_week_key()
    screenshots = await get_screenshots_by_week(week_key)
    if not screenshots:
        await update.message.reply_text(f"Нет данных за {week_key_to_display(week_key)}.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "user_id", "username", "submitted_at", "week_key", "file_id"])
    for s in screenshots:
        writer.writerow([
            s["email"], s["user_id"], s.get("username", ""),
            s["submitted_at"], s["week_key"], s["file_id"]])
    output.seek(0)
    await update.message.reply_document(
        document=InputFile(output, filename=f"vivino_export_{week_key_to_display(week_key).replace('.', '_')}.csv"),
        caption=f"\U0001f4ca Экспорт за {week_key_to_display(week_key)}: {len(screenshots)} записей")

    chat_id = update.effective_chat.id
    await update.message.reply_text("\U0001f4f8 Скриншоты \u2b07")
    for batch_start in range(0, len(screenshots), 10):
        batch = screenshots[batch_start:batch_start + 10]
        media = []
        for s in batch:
            dt = s["submitted_at"][:16].replace("T", " ")
            caption = f"{s['email']} - {dt}\nНеделя: {week_key_to_display(s['week_key'])}"
            media.append(InputMediaPhoto(media=s["file_id"], caption=caption))
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media)
        except Exception as e:
            logger.error(f"[EXPORT] Failed to send photo batch: {e}")
            await update.message.reply_text("\u26a0\ufe0f Не удалось отправить часть фото")


async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "wine_of_week":
        wine = get_current_wine()
        if wine:
            await query.edit_message_text(
                f"\U0001f377 <b>Вино этой недели:</b> {wine}\n\n"
                "Сделайте скриншот оценки этого вина в приложении Vivino и отправьте его боту!",
                parse_mode="HTML")
        else:
            await query.edit_message_text("Сейчас нет активного вина недели.", parse_mode="HTML")

    elif data == "register_email":
        await query.edit_message_text(
            "\U0001f4e7 Введите ваш рабочий email (\u0434\u043e\u043c\u0435\u043d luding.ru):\n\n"
            "<i>Пример: ivan@luding.ru</i>",
            parse_mode="HTML")
        context.user_data["state"] = WAITING_EMAIL

    elif data == "upload_screenshot":
        if not await is_user_registered(user.id):
            await query.edit_message_text(
                "\u274c Сначала зарегистрируйте email!\nНажмите «Зарегистрировать email».",
                parse_mode="HTML")
            return
        wine = get_current_wine()
        if not wine:
            await query.edit_message_text("Сейчас нет активного вина недели.", parse_mode="HTML")
            return
        await query.edit_message_text(
            f"\U0001f4f8 Отправьте скриншот с оценкой вина <b>{wine}</b> из Vivino.\n\n"
            "Поддерживаются форматы: JPG, PNG.",
            parse_mode="HTML")
        context.user_data["state"] = WAITING_SCREENSHOT

    elif data == "admin_panel":
        if not is_admin(user.id):
            await query.edit_message_text("\u26d4 Доступ запрещён.", parse_mode="HTML")
            return
        keyboard = [
            [InlineKeyboardButton("\U0001f4ca Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("\U0001f3c6 Розыгрыш", callback_data="admin_raffle")],
            [InlineKeyboardButton("\U0001f4cb Таблица лидеров", callback_data="admin_leaderboard")],
            [InlineKeyboardButton("\U0001f4f8 Скриншоты недели", callback_data="admin_screenshots")],
            [InlineKeyboardButton("\U0001f465 Участники", callback_data="admin_participants")],
            [InlineKeyboardButton("\U0001f4e4 Экспорт CSV + фото", callback_data="admin_export")],
            [InlineKeyboardButton("\U0001f4f7 Скриншоты пользователя", callback_data="admin_user_screenshots")],
            [InlineKeyboardButton("\U0001f4dc История победителей", callback_data="admin_winners")],
            [InlineKeyboardButton("\U0001f519 Назад", callback_data="back_to_main")],
        ]
        await query.edit_message_text(
            "\u2699\ufe0f <b>Админ-панель</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML")

    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("\U0001f4e7 Зарегистрировать email", callback_data="register_email")],
            [InlineKeyboardButton("\U0001f4f8 Загрузить скриншот", callback_data="upload_screenshot")],
        ]
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("\u2699\ufe0f Админ-панель", callback_data="admin_panel")])
        wine = get_current_wine()
        wine_text = f"\U0001f377 Вино недели: <b>{wine}</b>\n\n" if wine else ""
        await query.edit_message_text(
            f"{wine_text}Добро пожаловать в конкурс Vivino от Luding Group!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML")

    elif data == "admin_stats":
        if not is_admin(user.id):
            return
        stats = await get_stats()
        await query.edit_message_text(
            f"\U0001f4ca <b>Статистика бота</b>\n\n"
            f"\U0001f465 Пользователей: {stats['total_users']}\n"
            f"\U0001f4f8 Скриншотов: {stats['total_screenshots']}\n"
            f"\U0001f4c5 Активных недель: {stats['active_weeks']}\n"
            f"\U0001f3c6 Победителей: {stats['total_winners']}\n"
            f"\U0001f4cb Участников на этой неделе: {stats['this_week_participants']}\n"
            f"\U0001f4c5 Текущая неделя: {week_key_to_display(stats['current_week'])}",
            parse_mode="HTML")

    elif data == "admin_leaderboard":
        if not is_admin(user.id):
            return
        week_key = get_current_week_key()
        lb = await get_week_leaderboard(week_key)
        if not lb:
            await query.edit_message_text(f"Нет данных за {week_key_to_display(week_key)}.", parse_mode="HTML")
            return
        lines = [f"\U0001f3c6 <b>Лидеры недели {week_key_to_display(week_key)}</b>\n"]
        for i, p in enumerate(lb, 1):
            lines.append(f"{i}. {p['email']} - {p['screenshot_count']} скр.")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML")

    elif data == "admin_screenshots":
        if not is_admin(user.id):
            return
        week_key = get_current_week_key()
        shots = await get_screenshots_by_week(week_key)
        if not shots:
            await query.edit_message_text(
                f"\U0001f4f8 Нет скриншотов за {week_key_to_display(week_key)}.", parse_mode="HTML")
            return
        lines = [f"\U0001f4f8 <b>Скриншоты за {week_key_to_display(week_key)}</b> ({len(shots)} шт.):\n"]
        for i, s in enumerate(shots, 1):
            dt = s["submitted_at"][:16].replace("T", " ")
            username = f"@{s['username']}" if s.get("username") else ""
            lines.append(f"{i}. {s['email']} {username} - {dt}")
        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4000] + "\n..."
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "admin_participants":
        if not is_admin(user.id):
            return
        parts = await get_all_participants()
        if not parts:
            await query.edit_message_text("Нет участников.", parse_mode="HTML")
            return
        lines = ["\U0001f465 <b>Все участники</b>\n"]
        for p in parts:
            wins = p.get("win_count", 0) or 0
            lines.append(f"\u2022 {p['email']} - {p['total_screenshots']} скр., {p['weeks_active']} нед., {wins} побед")
        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4000] + "\n..."
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "admin_export":
        if not is_admin(user.id):
            return
        await query.edit_message_text(
            "\U0001f4e4 Используйте команды:\n"
            "<code>/export</code> - текущая неделя (CSV + фото)\n"
            "<code>/export 2026-W27</code> - конкретная неделя\n"
            "<code>/screenshots</code> - список скриншотов (текст)\n"
            "<code>/screenshots 2026-W27</code> - за неделю",
            parse_mode="HTML")

    elif data == "admin_winners":
        if not is_admin(user.id):
            return
        winners = await get_all_winners()
        if not winners:
            await query.edit_message_text("Победителей пока нет.", parse_mode="HTML")
            return
        lines = ["\U0001f4dc <b>История победителей</b>\n"]
        for w in winners:
            lines.append(f"\U0001f4c5 {week_key_to_display(w['week_key'])}: {w['email']}")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML")

    elif data == "admin_raffle":
        if not is_admin(user.id):
            return
        keyboard = [
            [InlineKeyboardButton(
                f"\U0001f4c5 Прошлая неделя ({week_key_to_display(get_previous_week_key())})",
                callback_data="raffle_week:previous")],
            [InlineKeyboardButton(
                f"\U0001f4c5 Текущая неделя ({week_key_to_display(get_current_week_key())})",
                callback_data="raffle_week:current")],
            [InlineKeyboardButton("\U0001f519 Назад", callback_data="admin_panel")],
        ]
        await query.edit_message_text(
            "\U0001f3b0 <b>Розыгрыш</b>\n\nВыберите неделю:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML")

    elif data and data.startswith("raffle_week:"):
        if not is_admin(user.id):
            return
        week_type = data.split(":")[1]
        week_key = get_previous_week_key() if week_type == "previous" else get_current_week_key()
        participants = await get_week_participants(week_key)
        if not participants:
            await query.edit_message_text(
                f"Нет участников за {week_key_to_display(week_key)}.",
                parse_mode="HTML")
            return
        context.user_data["raffle_participants"] = participants
        context.user_data["raffle_week_key"] = week_key
        await _show_raffle_result(query, context, week_key, participants)

    elif data == "reroll_raffle":
        if not is_admin(user.id):
            return
        participants = context.user_data.get("raffle_participants")
        week_key = context.user_data.get("raffle_week_key")
        if not participants or not week_key:
            await query.edit_message_text("Данные розыгрыша утеряны. Начните заново.", parse_mode="HTML")
            return
        await _show_raffle_result(query, context, week_key, participants)

    elif data == "confirm_raffle":
        if not is_admin(user.id):
            return
        pw = context.user_data.get("pending_winner")
        if not pw:
            await query.edit_message_text("Нет данных для подтверждения.", parse_mode="HTML")
            return
        await save_winner(pw["user_id"], pw["email"], pw["week_key"])
        keyboard = [
            [InlineKeyboardButton("\U0001f4e8 Да, отправить", callback_data="notify_winner:yes")],
            [InlineKeyboardButton("\U0001f6ab Нет", callback_data="notify_winner:no")],
        ]
        await query.edit_message_text(
            f"\u2705 Победитель <b>{pw['email']}</b> за неделю {week_key_to_display(pw['week_key'])} сохранён!\n\n"
            f"Отправить результат победителю?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML")

    elif data and data.startswith("notify_winner:"):
        if not is_admin(user.id):
            return
        pw = context.user_data.get("pending_winner")
        if not pw:
            await query.edit_message_text("Данные утеряны.", parse_mode="HTML")
            return
        notify = data.split(":")[1]
        if notify == "yes":
            try:
                await context.bot.send_message(
                    chat_id=pw["user_id"],
                    text=f"\U0001f389 Поздравляем! Вы выиграли розыгрыш за неделю {week_key_to_display(pw['week_key'])}!\n"
                         f"Ваше количество скриншотов: {pw['count']} \U0001f37b")
                result_text = "Уведомление отправлено."
            except Exception as e:
                logger.error(f"Failed to notify winner: {e}")
                result_text = "\u26a0\ufe0f Не удалось отправить уведомление (возможно, бот заблокирован)."
        else:
            result_text = "Без уведомления победителя."
        await query.edit_message_text(
            f"\u2705 Победитель <b>{pw['email']}</b> за неделю {week_key_to_display(pw['week_key'])} утверждён!\n"
            f"{result_text}",
            parse_mode="HTML")
        context.user_data.pop("pending_winner", None)
        context.user_data.pop("raffle_participants", None)
        context.user_data.pop("raffle_week_key", None)

    elif data == "admin_user_screenshots":
        if not is_admin(user.id):
            return
        await query.edit_message_text(
            "\U0001f4f7 <b>Скриншоты пользователя</b>\n\n"
            "Введите email участника (домен luding.ru):",
            parse_mode="HTML")
        context.user_data["state"] = WAITING_USER_EMAIL

    elif data == "cancel_raffle":
        if not is_admin(user.id):
            return
        context.user_data.pop("pending_winner", None)
        context.user_data.pop("raffle_participants", None)
        context.user_data.pop("raffle_week_key", None)
        await query.edit_message_text("Розыгрыш отменён.", parse_mode="HTML")


async def _show_raffle_result(query, context, week_key, participants):
    """Pick a random winner and show result with action buttons."""
    weights = [p["screenshot_count"] for p in participants]
    winner = random.choices(participants, weights=weights, k=1)[0]
    context.user_data["pending_winner"] = {
        "week_key": week_key,
        "user_id": winner["user_id"],
        "email": winner["email"],
        "count": winner["screenshot_count"],
    }
    keyboard = [
        [InlineKeyboardButton("\u2705 Подтвердить", callback_data="confirm_raffle")],
        [InlineKeyboardButton("\U0001f504 Выбрать заново", callback_data="reroll_raffle")],
        [InlineKeyboardButton("\u274c Отмена", callback_data="cancel_raffle")],
    ]
    await query.edit_message_text(
        f"\U0001f3b0 <b>Розыгрыш {week_key_to_display(week_key)}</b>\n\n"
        f"Участников: {len(participants)}\n\n"
        f"\U0001f3c6 Победитель: <b>{winner['email']}</b>\n"
        f"Скриншотов: {winner['screenshot_count']}\n\n"
        "Подтвердить или выбрать заново?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML")


async def handle_screenshot(update, context, user_id, email):
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("\u274c Это не фото. Отправьте скриншот (JPG/PNG).")
        return

    file = photos[-1]
    file_unique_id = file.file_unique_id

    if await is_duplicate_screenshot(user_id, file_unique_id):
        await update.message.reply_text("\u26a0\ufe0f Этот скриншот уже был загружен!")
        return

    try:
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        file_obj = await file.get_file()
        file_path = os.path.join(config.SCREENSHOTS_DIR, f"{file_unique_id}.jpg")
        await file_obj.download_to_drive(file_path)
    except Exception as e:
        logger.error(f"Download error: {e}")
        await update.message.reply_text("\u274c Ошибка сохранения. Попробуйте снова.")
        return

    week_key = get_current_week_key()
    if await save_screenshot(user_id, email, file.file_id, file_unique_id, file_path, week_key):
        count = await get_week_screenshots_count(week_key)
        wine = get_current_wine()
        await update.message.reply_text(
            f"\u2705 Скриншот принят! ({wine})\n"
            f"\U0001f4f8 Всего за неделю: {count}\n"
            f"Отправить ещё? Или нажмите /start для меню.",
            parse_mode="HTML")
        await update.message.reply_text(
            "\U0001f389 Спасибо за участие! Результаты розыгрыша огласим в понедельник. Удачи! \U0001f340")
    else:
        await update.message.reply_text("\u26a0\ufe0f Ошибка дублирования.")


async def handle_message(update, context):
    state = context.user_data.get("state")

    if state == WAITING_EMAIL:
        email = update.message.text.strip()
        if not email.endswith("@luding.ru"):
            await update.message.reply_text(
                "\u274c Допускаются только рабочие email домена luding.ru!\nПопробуйте снова:")
            return
        success, msg = await register_user(
            update.effective_user.id, update.effective_user.username, email)
        await update.message.reply_text(msg, parse_mode="HTML")
        wine = get_current_wine()
        if wine:
            await update.message.reply_text(
                f"\U0001f4f8 Отправьте скриншот с оценкой вина <b>{wine}</b> из Vivino.\n\n"
                "Поддерживаются форматы: JPG, PNG.",
                parse_mode="HTML")
            context.user_data["state"] = WAITING_SCREENSHOT
        else:
            context.user_data["state"] = None

    elif state == WAITING_SCREENSHOT:
        user_id = update.effective_user.id
        email = await get_user_email(user_id)
        if not email:
            await update.message.reply_text("\u274c Email не найден. Зарегистрируйтесь заново.")
            context.user_data["state"] = None
            return
        await handle_screenshot(update, context, user_id, email)
        context.user_data["state"] = ASK_ANOTHER

    elif state == WAITING_USER_EMAIL:
        email = update.message.text.strip()
        context.user_data["state"] = None
        shots = await get_screenshots_by_email(email)
        if not shots:
            await update.message.reply_text(
                f"\U0001f4f8 У пользователя <b>{email}</b> нет скриншотов.",
                parse_mode="HTML")
            return
        lines = [f"\U0001f4f8 <b>Скриншоты {email}</b> ({len(shots)} шт.):\n"]
        for i, s in enumerate(shots, 1):
            dt = s["submitted_at"][:16].replace("T", " ")
            lines.append(f"{i}. {week_key_to_display(s['week_key'])} - {dt}")
        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4000] + "\n..."
        await update.message.reply_text(text, parse_mode="HTML")

        chat_id = update.effective_chat.id
        await update.message.reply_text("\U0001f4f8 Фото \u2b07")
        for batch_start in range(0, len(shots), 10):
            batch = shots[batch_start:batch_start + 10]
            media = []
            for s in batch:
                caption = f"{email} - {week_key_to_display(s['week_key'])}"
                media.append(InputMediaPhoto(media=s["file_id"], caption=caption))
            try:
                await context.bot.send_media_group(chat_id=chat_id, media=media)
            except Exception as e:
                logger.error(f"[USER_SHOTS] Failed to send photo batch: {e}")
                await update.message.reply_text("\u26a0\ufe0f Не удалось отправить часть фото")

    elif state == ASK_ANOTHER:
        if update.message.photo:
            user_id = update.effective_user.id
            email = await get_user_email(user_id)
            if not email:
                await update.message.reply_text("\u274c Email не найден.")
                context.user_data["state"] = None
                return
            await handle_screenshot(update, context, user_id, email)
        else:
            await update.message.reply_text("Отправьте фото или нажмите /start для меню.")


async def reminder_job(context):
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
                    text=f"\u23f0 Напоминание!\n\n"
                         f"Эта неделя ещё без вашего скриншота! \U0001f377\n"
                         f"Вино недели: {wine}\n"
                         f"Отправьте скриншот оценки из Vivino, чтобы участвовать в розыгрыше.\n"
                         f"Удачи! \U0001f3b2")
                notified += 1
            except Exception as e:
                logger.error(f"Reminder failed for {uid}: {e}")
    logger.info(f"Reminder job: notified {notified}/{len(user_ids)} users")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass


async def post_init(application):
    await init_db()
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)

    job_queue = application.job_queue
    job_queue.run_daily(
        reminder_job,
        time=datetime(2024, 1, 1, config.REMINDER_HOUR, config.REMINDER_MINUTE).time(),
        days=(config.REMINDER_DAY_OF_WEEK,),
        name="weekly_reminder",
    )
    logger.info(
        f"[INIT] Reminder scheduled: Friday {config.REMINDER_HOUR}:{config.REMINDER_MINUTE:02d} MSK")


def main():
    if not config.BOT_TOKEN:
        print("[ERROR] BOT_TOKEN not set!")
        return

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("my", my_stats_command))
    app.add_handler(CommandHandler("screenshots", screenshots_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("[BOT] Starting Vivino Contest Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    httpd = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[HEALTH] Health-check server on 0.0.0.0:{port} (responds to / and /health)")
    main()
