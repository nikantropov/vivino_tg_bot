import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "1214258573,472343594").split(",") if x.strip()]

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SCREENSHOTS_DIR = os.environ.get("SCREENSHOTS_DIR", "./data/screenshots")

RAFFLE_DAY_OF_WEEK = 0
RAFFLE_HOUR = 10
RAFFLE_MINUTE = 0

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@proLuding")

REMINDER_DAY_OF_WEEK = 4
REMINDER_HOUR = 18
REMINDER_MINUTE = 0

WINE_SCHEDULE = {
    "01.01-19.07": "Urban Sun",
}
