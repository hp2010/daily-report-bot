import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TOPIC_ID = int(os.getenv("TOPIC_ID", "0")) or None    # ← NEW
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
DB_PATH = os.getenv("DB_PATH", "daily_report.db")

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Shanghai")
DEFAULT_FIRST_REMINDER = os.getenv("DEFAULT_FIRST_REMINDER", "10:00")
DEFAULT_SECOND_REMINDER = os.getenv("DEFAULT_SECOND_REMINDER", "11:00")
DEFAULT_SUMMARY_TIME = os.getenv("DEFAULT_SUMMARY_TIME", "12:00")
SUMMARY_TIMEZONE = os.getenv("SUMMARY_TIMEZONE", "Asia/Shanghai")