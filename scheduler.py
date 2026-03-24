from datetime import time
import pytz
from telegram.ext import Application

import config
import database as db
from handlers import send_reminders, yesterday_str, today_str, user_label
from telegram.constants import ParseMode

tz = pytz.timezone(config.TIMEZONE)


async def first_reminder(ctx):
    count = await send_reminders(ctx, round_num=1)
    print(f"[10:00] 1st reminder sent to {count} users")


async def second_reminder(ctx):
    count = await send_reminders(ctx, round_num=2)
    print(f"[11:00] 2nd reminder sent to {count} users")


async def daily_summary(ctx):
    """Post yesterday's summary to the channel at 12:00"""
    date = yesterday_str()
    users = db.get_active_users()
    reports = db.get_reports_for_date(date)
    unsubmitted_today = db.get_unsubmitted_users(today_str())

    submitted_ids = {r["user_id"] for r in reports}

    lines = [f"📊 *Daily Summary — {date}*\n"]

    # Submitted
    lines.append(f"✅ *Submitted ({len(reports)}/{len(users)}):*")
    if reports:
        for r in reports:
            name = r["display_name"] or r["username"] or str(r["user_id"])
            lines.append(f"  • {name}")
    else:
        lines.append("  (none)")

    # Missing
    missing = [u for u in users if u["user_id"] not in submitted_ids]
    lines.append(f"\n❌ *Missing ({len(missing)}):*")
    if missing:
        for u in missing:
            lines.append(f"  • {user_label(u)}")
    else:
        lines.append("  🎉 Everyone submitted!")

    lines.append(f"\n📈 *Completion: {len(reports)}/{len(users)}*")

    try:
        await ctx.bot.send_message(
            chat_id=config.CHANNEL_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"[Summary] Failed: {e}")


def setup_scheduler(app: Application):
    jq = app.job_queue

    jq.run_daily(
        first_reminder,
        time=time(hour=config.FIRST_REMINDER_HOUR, minute=config.FIRST_REMINDER_MINUTE, tzinfo=tz),
        name="1st_reminder"
    )

    jq.run_daily(
        second_reminder,
        time=time(hour=config.SECOND_REMINDER_HOUR, minute=config.SECOND_REMINDER_MINUTE, tzinfo=tz),
        name="2nd_reminder"
    )

    jq.run_daily(
        daily_summary,
        time=time(hour=config.SUMMARY_HOUR, minute=config.SUMMARY_MINUTE, tzinfo=tz),
        name="daily_summary"
    )

    print(f"[Scheduler] 1st reminder  → {config.FIRST_REMINDER_HOUR:02d}:{config.FIRST_REMINDER_MINUTE:02d}")
    print(f"[Scheduler] 2nd reminder  → {config.SECOND_REMINDER_HOUR:02d}:{config.SECOND_REMINDER_MINUTE:02d}")
    print(f"[Scheduler] Daily summary → {config.SUMMARY_HOUR:02d}:{config.SUMMARY_MINUTE:02d}")