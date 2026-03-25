from datetime import datetime
import re
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from telegram.constants import ParseMode

import config
import database as db
from handlers import user_label

TICK_INTERVAL_SECONDS = 30


def esc(text: str) -> str:
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special)}])', r'\\\1', str(text))


async def tick(ctx):
    users = db.get_active_users()

    for user in users:
        user_tz = pytz.timezone(user["timezone"] or config.DEFAULT_TIMEZONE)
        user_now = datetime.now(user_tz)
        user_date = user_now.strftime("%Y-%m-%d")
        user_hm = user_now.strftime("%H:%M")

        if not db.should_remind_user(user["user_id"], user_date):
            continue

        existing = db.get_today_report(user["user_id"], user_date)
        if existing:
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
        summary_date = summary_now.strftime("%Y-%m-%d")
        already_key = f"summary_posted_{summary_date}"

        conn = db.get_conn()
        already = conn.execute("SELECT 1 FROM settings WHERE key = ?", (already_key,)).fetchone()
        conn.close()

        if not already:
            posted = await post_daily_summary(ctx, summary_date)
            if posted:
                db.set_setting(already_key, "1")


async def post_daily_summary(ctx, report_date: str) -> bool:
    min_reports = int(db.get_setting("summary_min_reports", "2"))
    expected = db.get_active_expected_users(report_date)
    reports = db.get_reports_for_date(report_date)

    if len(reports) < min_reports:
        print(f"[Summary] Skipped {report_date}: only {len(reports)} report(s), need >= {min_reports}")
        return False

    submitted_ids = {r["user_id"] for r in reports}

    lines = [f"📊 *Daily Summary — {esc(report_date)}*\n"]

    lines.append(f"✅ *Submitted \\({len(reports)}/{len(expected)}\\):*")
    if reports:
        for r in reports:
            name = r["display_name"] or r["username"] or str(r["user_id"])
            lines.append(f"  • {esc(name)}")
    else:
        lines.append("  \\(none\\)")

    missing = [u for u in expected if u["user_id"] not in submitted_ids]
    lines.append(f"\n❌ *Missing \\({len(missing)}\\):*")
    if missing:
        for u in missing:
            lines.append(f"  • {esc(user_label(u))}")
    else:
        lines.append("  🎉 Everyone submitted\\!")

    lines.append(f"\n📈 *Completion: {len(reports)}/{len(expected)}*")

    try:
        await ctx.bot.send_message(
            chat_id=config.CHANNEL_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2,
	message_thread_id=config.TOPIC_ID 
        )
        print(f"[Summary] Posted for {report_date}")
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