import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")
DB_PATH = os.getenv("DB_PATH", "daily_report.db")

# Schedule (UTC+8)
FIRST_REMINDER_HOUR = 10
FIRST_REMINDER_MINUTE = 0
SECOND_REMINDER_HOUR = 11
SECOND_REMINDER_MINUTE = 0
SUMMARY_HOUR = 12
SUMMARY_MINUTE = 0