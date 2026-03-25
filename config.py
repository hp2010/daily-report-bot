import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TOPIC_ID = os.getenv("TOPIC_ID")  # ← 改成跟 .env 一致
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
DB_PATH = os.getenv("DB_PATH", "daily_report.db")

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Shanghai")
DEFAULT_FIRST_REMINDER = os.getenv("DEFAULT_FIRST_REMINDER", "10:00")
DEFAULT_SECOND_REMINDER = os.getenv("DEFAULT_SECOND_REMINDER", "11:00")
DEFAULT_SUMMARY_TIME = os.getenv("DEFAULT_SUMMARY_TIME", "12:00")
SUMMARY_TIMEZONE = os.getenv("SUMMARY_TIMEZONE", "Asia/Shanghai")


def get_topic_id():
    """Returns int or None."""
    val = TOPIC_ID
    if val and val.strip():
        try:
            return int(val.strip())
        except ValueError:
            pass
    return None