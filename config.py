# Telegram Bot Configuration
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Admin Telegram IDs
ADMIN_IDS = [1214258573, 472343594]

# PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Screenshots storage
SCREENSHOTS_DIR = os.environ.get("SCREENSHOTS_DIR", "./data/screenshots")

# Raffle settings
RAFFLE_DAY_OF_WEEK = 0  # Monday
RAFFLE_HOUR = 10
RAFFLE_MINUTE = 0

# Channel for winner announcements
CHANNEL_ID = "@proLuding"

# Reminder settings (Friday 18:00 MSK)
REMINDER_DAY_OF_WEEK = 4  # Friday
REMINDER_HOUR = 18
REMINDER_MINUTE = 0

# Wine of the Week schedule
WINE_SCHEDULE = {
    "01.01-19.07": "Urban Sun",
}
