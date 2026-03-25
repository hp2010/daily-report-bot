from datetime import datetime, timedelta
from collections import defaultdict
import re
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from telegram.constants import ParseMode

import config
import database as db
from handlers import user_label, user_tz

TICK_INTERVAL_SECONDS = 30


def esc(text: str) -> str:
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special)}])', r'\\\1', str(text))


async def tick(ctx):
    users = db.get_active_users()

    for user in users:
        user_timezone = pytz.timezone(user["timezone"] or config.DEFAULT_TIMEZONE)
        user_now = datetime.now(user_timezone)
        user_date = user_now.strftime("%Y-%m-%d")
        user_hm = user_now.strftime("%H:%M")

        if not db.should_remind_user(user["user_id"], user_date):
            continue
        if db.get_report(user["user_id"], user_date):
            continue

        first = user["first_reminder"] or config.DEFAULT_FIRST_REMINDER
        second = user["second_reminder"] or config.DEFAULT_SECOND_REMINDER

        round_num = None
        if user_hm == first:
            round_num = 1
        elif user_hm == second:
            round_num = 2
        if round_num is None:
            continue

        conn = db.get_conn()
        already = conn.execute(
            "SELECT 1 FROM reminders WHERE user_id = ? AND remind_date = ? AND round = ?",
            (user["user_id"], user_date, round_num)
        ).fetchone()
        conn.close()
        if already:
            continue

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Write Report", callback_data="write_report")]
        ])
        messages = {
            1: "⏰ *Good morning\\!*\n\nTime to write your daily report for today\\.\nTap the button below or send /report to get started\\.",
            2: "⏰ *Second reminder\\!*\n\nYou haven't submitted today's daily report yet\\.\nPlease submit ASAP 🙏",
        }
        try:
            await ctx.bot.send_message(
                chat_id=user["user_id"],
                text=messages[round_num],
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard
            )
            db.record_reminder(user["user_id"], user_date, round_num)
            print(f"[Tick] Reminded {user['user_id']} (round {round_num})")
        except Exception as e:
            print(f"[Tick] Failed to remind {user['user_id']}: {e}")

    # ── Summary check ──
    summary_time_str = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
    summary_tz_str = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
    summary_tz = pytz.timezone(summary_tz_str)
    summary_now = datetime.now(summary_tz)
    summary_hm = summary_now.strftime("%H:%M")

    if summary_hm == summary_time_str:
        summary_key_date = summary_now.strftime("%Y-%m-%d")
        already_key = f"summary_posted_{summary_key_date}"

        conn = db.get_conn()
        already = conn.execute("SELECT 1 FROM settings WHERE key = ?", (already_key,)).fetchone()
        conn.close()

        if not already:
            posted = await post_daily_summary(ctx)
            if posted:
                db.set_setting(already_key, "1")


async def post_daily_summary(ctx) -> bool:
    min_reports = int(db.get_setting("summary_min_reports", "2"))
    users = db.get_active_users()

    collected = []
    missing_users = []

    for user in users:
        tz = user_tz(user)
        user_yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")

        if not db.should_remind_user(user["user_id"], user_yesterday):
            continue

        report = db.get_report(user["user_id"], user_yesterday)
        if report:
            collected.append((user_yesterday, user, report))
        else:
            missing_users.append(user)

    total_expected = len(collected) + len(missing_users)

    if len(collected) < min_reports:
        print(f"[Summary] Skipped: only {len(collected)} report(s), need >= {min_reports}")
        return False

    by_date = defaultdict(list)
    for report_date, user, report in collected:
        by_date[report_date].append((user, report))

    summary_tz_str = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
    summary_tz = pytz.timezone(summary_tz_str)
    now_str = datetime.now(summary_tz).strftime("%Y-%m-%d %H:%M")

    lines = [f"📊 *Daily Status*"]
    lines.append(f"_Collected at {esc(now_str)} \\({esc(summary_tz_str)}\\)_\n")

    for date_str in sorted(by_date.keys(), reverse=True):
        entries = by_date[date_str]
        lines.append(f"📅 *{esc(date_str)}*")
        for user, report in entries:
            name = user_label(user)
            catch_up = " \\(catch\\-up\\)" if report.get("is_yesterday") else ""
            lines.append(f"  ✅ {esc(name)}{catch_up}")
        lines.append("")

    if missing_users:
        lines.append(f"❌ *Missing \\({len(missing_users)}\\):*")
        for u in missing_users:
            lines.append(f"  • {esc(user_label(u))}")
        lines.append("")

    lines.append(f"📈 *Completion: {len(collected)}/{total_expected}*")

    try:
        send_kwargs = {
            "chat_id": config.CHANNEL_ID,
            "text": "\n".join(lines),
            "parse_mode": ParseMode.MARKDOWN_V2,
        }
        topic_id = config.get_topic_id()
        if topic_id:
            send_kwargs["message_thread_id"] = topic_id

        await ctx.bot.send_message(**send_kwargs)
        print(f"[Summary] Posted ({len(collected)} reports)")
        return True
    except Exception as e:
        print(f"[Summary] Failed: {e}")
        return False


def setup_scheduler(app: Application):
    app.job_queue.run_repeating(
        tick,
        interval=TICK_INTERVAL_SECONDS,
        first=5,
        name="global_tick"
    )
    print(f"[Scheduler] Global tick every {TICK_INTERVAL_SECONDS}s")