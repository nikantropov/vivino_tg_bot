import os

# Telegram Bot Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Admin Telegram IDs (comma-separated in env var)
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "1214258573,472343594").split(",") if x.strip()]

# Database — persistent disk on Render
DB_PATH = os.environ.get("DB_PATH", "/data/vivino_bot.db")

# Screenshots storage
SCREENSHOTS_DIR = os.environ.get("SCREENSHOTS_DIR", "/data/screenshots")

# Raffle settings
RAFFLE_DAY_OF_WEEK = 0  # Monday
RAFFLE_HOUR = 10         # 10:00 MSK
RAFFLE_MINUTE = 0

# Channel for winner announcements
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@proLuding")

# Reminder settings (Friday 18:00 MSK)
REMINDER_DAY_OF_WEEK = 4
REMINDER_HOUR = 18
REMINDER_MINUTE = 0

# Wine of the Week schedule
WINE_SCHEDULE = {
    "01.01-19.07": "Urban Sun",
}

# Uncomment below for full schedule after test period:
# WINE_SCHEDULE = {
#     "13.07-19.07": "Urban Sun",
#     "20.07-26.07": "High Roof",
#     "27.07-02.08": "Adagum",
#     "03.08-09.08": "Idolo",
#     "10.08-16.08": "Авторское",
# }
