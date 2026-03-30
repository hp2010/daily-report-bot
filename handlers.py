from datetime import datetime, timedelta
from collections import defaultdict
import re
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
import database as db


# ──────────────────── Escape helper ────────────────────

def esc(text: str) -> str:
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special)}])', r'\\\1', str(text))


# ──────────────────── Date format helper ────────────────────

def format_date(date_str: str) -> str:
    """Convert '2026-03-24' → 'Tue, Mar 24 2026'"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%a, %b %d %Y")


# ──────────────────── Helpers ────────────────────

def user_tz(user_row):
    return pytz.timezone(user_row["timezone"] if user_row else config.DEFAULT_TIMEZONE)


def user_tz_abbrev(user_row) -> str:
    tz = user_tz(user_row)
    now = datetime.now(tz)
    offset = now.utcoffset()
    total_seconds = int(offset.total_seconds())
    hours = total_seconds // 3600
    minutes = abs(total_seconds) % 3600 // 60
    if minutes:
        return f"UTC{hours:+d}:{minutes:02d}"
    return f"UTC{hours:+d}"


def today_for_user(user_id: int) -> str:
    u = db.get_user(user_id)
    tz = user_tz(u)
    return datetime.now(tz).strftime("%Y-%m-%d")


def yesterday_for_user(user_id: int) -> str:
    u = db.get_user(user_id)
    tz = user_tz(u)
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")


def now_for_user(user_id: int) -> str:
    u = db.get_user(user_id)
    tz = user_tz(u)
    return datetime.now(tz).strftime("%H:%M:%S")


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def is_active_user(user_id: int) -> bool:
    u = db.get_user(user_id)
    return u is not None and u["is_active"]


def get_display_name(user) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def user_label(row) -> str:
    return row["display_name"] or (f"@{row['username']}" if row["username"] else str(row["user_id"]))


def parse_time_str(s: str) -> tuple:
    try:
        parts = s.strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except (ValueError, IndexError):
        pass
    return None


# ──────────────────── User resolution ────────────────────

async def resolve_user(identifier: str, update: Update) -> dict | None:
    identifier = identifier.strip()
    try:
        uid = int(identifier)
        user = db.get_user(uid)
        if user:
            return dict(user)
    except ValueError:
        pass
    matches = db.find_users_by_name(identifier, active_only=False)
    if len(matches) == 0:
        await update.message.reply_text(f"❌ No user found matching `{esc(identifier)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return None
    if len(matches) == 1:
        return dict(matches[0])
    lines = [f"⚠️ Multiple users match `{esc(identifier)}`\\. Please be more specific:\n"]
    for m in matches:
        status = "✅" if m["is_active"] else "❌ inactive"
        lines.append(f"• *{esc(user_label(m))}* — `{m['user_id']}` \\({esc(status)}\\)")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
    return None


async def resolve_active_user(identifier: str, update: Update) -> dict | None:
    identifier = identifier.strip()
    try:
        uid = int(identifier)
        user = db.get_user(uid)
        if user and user["is_active"]:
            return dict(user)
    except ValueError:
        pass
    matches = db.find_users_by_name(identifier, active_only=True)
    if len(matches) == 0:
        await update.message.reply_text(f"❌ No active user found matching `{esc(identifier)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return None
    if len(matches) == 1:
        return dict(matches[0])
    lines = [f"⚠️ Multiple active users match `{esc(identifier)}`\\. Please be more specific:\n"]
    for m in matches:
        lines.append(f"• *{esc(user_label(m))}* — `{m['user_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
    return None


async def resolve_multiple_users(raw: str, update: Update) -> list | None:
    raw = raw.strip()
    if raw.lower() == "all":
        users = db.get_active_users()
        if not users:
            await update.message.reply_text("📭 No active users\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return None
        return [dict(u) for u in users]
    identifiers = [s.strip() for s in raw.split(",") if s.strip()]
    if not identifiers:
        await update.message.reply_text("❌ No users specified\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return None
    results = []
    for ident in identifiers:
        user = await resolve_active_user(ident, update)
        if user is None:
            return None
        results.append(user)
    return results


# ──────────────────── Bot menu setup ────────────────────

async def setup_commands(app):
    user_commands = [
        BotCommand("start", "About this bot & command guide"),
        BotCommand("report", "Submit today's report"),
        BotCommand("yesterday", "Submit yesterday's report"),
        BotCommand("update", "Update or delete a report"),
        BotCommand("status", "See who submitted today"),
        BotCommand("myreport", "View report (today/yesterday)"),
        BotCommand("vacation", "Set your vacation days"),
        BotCommand("myschedule", "View your schedule"),
    ]

    admin_commands = user_commands + [
        BotCommand("adduser", "Add user(s)"),
        BotCommand("removeuser", "Remove user(s)"),
        BotCommand("rename", "Rename a user"),
        BotCommand("listusers", "List all active users"),
        BotCommand("remind", "Manually trigger reminders"),
        BotCommand("summary", "Report summary (today/yesterday/date)"),
        BotCommand("settz", "Set timezone (batch)"),
        BotCommand("setreminders", "Set reminder times (batch)"),
        BotCommand("adminvacation", "Set vacation/duty for anyone"),
        BotCommand("schedule", "View all schedule overrides"),
        BotCommand("setsummary", "Set summary time & threshold"),
        BotCommand("settings", "View current settings"),
    ]

    from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeChat
    await app.bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
    for admin_id in config.ADMIN_IDS:
        try:
            await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            print(f"[Menu] Could not set admin commands for {admin_id}: {e}")
    print("[Menu] Bot commands registered.")


# ──────────────────── /start ────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the Daily Report Bot\\!*\n\n"
        "I'll remind you to write your daily report every day "
        "and sync all reports to the onboarding channel\\.\n\n"
        "📝 *Writing Reports*\n"
        "/report — Submit today's daily report\n"
        "/yesterday — Submit yesterday's report \\(catch\\-up\\)\n"
        "/update — Update or delete an existing report\n\n"
        "📊 *Viewing*\n"
        "/myreport — View today's report\n"
        "/myreport yesterday — View yesterday's report\n"
        "/status — See who has submitted today\n\n"
        "🏖️ *Time Off*\n"
        "/vacation — Set your vacation days\n"
        "/myschedule — View your schedule\n\n"
        "Type `/` to see the command menu anytime\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ──────────────────── /debugtopic ────────────────────

async def cmd_debugtopic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.reply_text(
        f"📍 *Debug Info*\n\n"
        f"chat\\_id: `{msg.chat.id}`\n"
        f"message\\_thread\\_id: `{msg.message_thread_id}`\n"
        f"is\\_topic\\_message: `{msg.is_topic_message}`\n\n"
        f"⚙️ *Current Config*\n"
        f"CHANNEL\\_ID: `{config.CHANNEL_ID}`\n"
        f"TOPIC\\_ID: `{config.TOPIC_ID}`\n"
        f"get\\_topic\\_id\\(\\): `{config.get_topic_id()}`",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ──────────────────── /report ────────────────────

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_active_user(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    date = today_for_user(update.effective_user.id)
    existing = db.get_report(update.effective_user.id, date)
    if existing:
        return await update.message.reply_text(
            f"📋 You already submitted today's report\\.\n\n"
            f"_{esc(existing['content'])}_\n\n"
            f"Use /update to modify or delete it\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    ctx.user_data["state"] = "awaiting_report"
    ctx.user_data["report_date"] = date
    ctx.user_data["is_yesterday"] = False
    await update.message.reply_text(
        f"📝 *Daily Report — {esc(format_date(date))}*\n\n"
        f"Please type your report below\\.\n\n"
        f"Suggested format:\n"
        f"*1\\. What did I do yesterday?*\n"
        f"\\- \\.\\.\\.\n\n"
        f"*2\\. What will I do today?*\n"
        f"\\- \\.\\.\\.\n\n"
        f"*3\\. What obstacles am I facing?*\n"
        f"\\- \\.\\.\\.\n\n"
        f"Send your message when ready 👇",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ──────────────────── /yesterday ────────────────────

async def cmd_yesterday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_active_user(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    date = yesterday_for_user(update.effective_user.id)
    existing = db.get_report(update.effective_user.id, date)
    if existing:
        return await update.message.reply_text(
            f"📋 You already submitted a report for {esc(format_date(date))}\\.\n\n"
            f"_{esc(existing['content'])}_\n\n"
            f"Use /update to modify or delete it\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    ctx.user_data["state"] = "awaiting_report"
    ctx.user_data["report_date"] = date
    ctx.user_data["is_yesterday"] = True
    await update.message.reply_text(
        f"📝 *Yesterday's Report — {esc(format_date(date))}*\n\n"
        f"Please type your report for yesterday below 👇",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ──────────────────── /update ────────────────────

async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_active_user(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    uid = update.effective_user.id
    today = today_for_user(uid)
    yesterday = yesterday_for_user(uid)

    today_report = db.get_report(uid, today)
    yesterday_report = db.get_report(uid, yesterday)

    if not today_report and not yesterday_report:
        return await update.message.reply_text(
            "📭 No reports to update\\. Use /report or /yesterday first\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if today_report and not yesterday_report:
        ctx.user_data["state"] = "awaiting_update"
        ctx.user_data["report_date"] = today
        return await update.message.reply_text(
            f"✏️ *Update Report — {esc(format_date(today))}*\n\n"
            f"Current:\n_{esc(today_report['content'])}_\n\n"
            f"Send updated report below, or type `delete` to remove it 👇",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if yesterday_report and not today_report:
        ctx.user_data["state"] = "awaiting_update"
        ctx.user_data["report_date"] = yesterday
        return await update.message.reply_text(
            f"✏️ *Update Report — {esc(format_date(yesterday))}*\n\n"
            f"Current:\n_{esc(yesterday_report['content'])}_\n\n"
            f"Send updated report below, or type `delete` to remove it 👇",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Today ({format_date(today)})", callback_data=f"update_{today}"),
            InlineKeyboardButton(f"Yesterday ({format_date(yesterday)})", callback_data=f"update_{yesterday}"),
        ]
    ])
    await update.message.reply_text(
        "Which report do you want to update?",
        reply_markup=keyboard
    )


# ──────────────────── /myreport ────────────────────

async def cmd_myreport(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_active_user(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    uid = update.effective_user.id

    if ctx.args and ctx.args[0].lower() in ("yesterday", "y"):
        date = yesterday_for_user(uid)
        label = "yesterday"
    else:
        date = today_for_user(uid)
        label = "today"

    report = db.get_report(uid, date)
    if report:
        catch_up = " \\(catch\\-up\\)" if report["is_yesterday"] else ""
        await update.message.reply_text(
            f"📋 *Your report for {esc(format_date(date))}:*{catch_up}\n\n{esc(report['content'])}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    else:
        if label == "today":
            await update.message.reply_text(
                f"📭 No report submitted for {label} \\({esc(format_date(date))}\\)\\.\n"
                f"Use /report to submit\\.\n\n"
                f"_Tip: use `/myreport yesterday` to check yesterday's\\._",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await update.message.reply_text(
                f"📭 No report for {label} \\({esc(format_date(date))}\\)\\.\n"
                f"Use /yesterday to submit a catch\\-up\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )


# ──────────────────── /status ────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_active_user(update.effective_user.id):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    date = today_for_user(update.effective_user.id)
    expected = db.get_active_expected_users(date)
    reports = db.get_reports_for_date(date)
    submitted_ids = {r["user_id"] for r in reports}

    done, pending = [], []
    for u in expected:
        name = user_label(u)
        (done if u["user_id"] in submitted_ids else pending).append(name)

    lines = [f"📊 *Report Status — {esc(format_date(date))}*\n"]
    lines.append(f"*Submitted \\({len(done)}\\):*")
    lines.extend([f"  ✅ {esc(n)}" for n in done] or ["  \\(none\\)"])
    lines.append(f"\n*Pending \\({len(pending)}\\):*")
    lines.extend([f"  ⏳ {esc(n)}" for n in pending] or ["  \\(none\\)"])
    lines.append(f"\n📈 Completion: {len(done)}/{len(expected)}")

    all_active = db.get_active_users()
    off_users = [u for u in all_active if not db.should_remind_user(u["user_id"], date)]
    if off_users:
        lines.append(f"\n🏖️ *Off today \\({len(off_users)}\\):*")
        for u in off_users:
            lines.append(f"  • {esc(user_label(u))}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ──────────────────── /vacation (user) ────────────────────

async def cmd_vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_active_user(uid):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    if not ctx.args:
        return await update.message.reply_text(
            "🏖️ *Set your vacation days*\n\n"
            "Set vacation:\n"
            "`/vacation 2025\\-01\\-20`\n"
            "`/vacation 2025\\-01\\-20 2025\\-01\\-24` \\(range\\)\n\n"
            "Remove vacation:\n"
            "`/vacation remove 2025\\-01\\-20`\n"
            "`/vacation remove 2025\\-01\\-20 2025\\-01\\-24` \\(range\\)\n\n"
            "View your schedule:\n"
            "`/myschedule`",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    args = list(ctx.args)
    scope = str(uid)

    if args[0].lower() == "remove":
        if len(args) < 2:
            return await update.message.reply_text("Usage: `/vacation remove <date> [end_date]`", parse_mode=ParseMode.MARKDOWN_V2)
        start = args[1]
        end = args[2] if len(args) > 2 else start
        if not _is_date_str(start) or not _is_date_str(end):
            return await update.message.reply_text("❌ Invalid date\\. Use `YYYY\\-MM\\-DD`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        dates = _date_range(start, end)
        for d in dates:
            db.remove_override(scope, d, "vacation")
        return await update.message.reply_text(
            f"✅ Removed your vacation: `{esc(format_date(dates[0]))}` → `{esc(format_date(dates[-1]))}` \\({len(dates)} day\\(s\\)\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    start = args[0]
    end = args[1] if len(args) > 1 else start
    if not _is_date_str(start) or not _is_date_str(end):
        return await update.message.reply_text("❌ Invalid date\\. Use `YYYY\\-MM\\-DD`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    dates = _date_range(start, end)
    for d in dates:
        db.add_override(scope, d, "vacation", note="self-service vacation")
    await update.message.reply_text(
        f"🏖️ Vacation set: `{esc(format_date(dates[0]))}` → `{esc(format_date(dates[-1]))}` \\({len(dates)} day\\(s\\)\\)\\.\n\n"
        f"Use `/myschedule` to view your schedule\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ──────────────────── /myschedule ────────────────────

async def cmd_myschedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_active_user(uid):
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    now = datetime.now(pytz.timezone(config.DEFAULT_TIMEZONE))
    year, month = now.year, now.month
    if ctx.args:
        try:
            parts = ctx.args[0].split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return await update.message.reply_text("Usage: `/myschedule [YYYY\\-MM]`", parse_mode=ParseMode.MARKDOWN_V2)

    scope = str(uid)
    user_overrides = db.get_overrides_for_month(year, month, scope=scope)
    global_overrides = db.get_overrides_for_month(year, month, scope="all")

    db_user = db.get_user(uid)
    name = user_label(db_user) if db_user else str(uid)

    lines = [f"📅 *Your Schedule — {year:04d}\\-{month:02d}*"]
    lines.append(f"👤 {esc(name)}\n")

    has_any = False
    if global_overrides:
        has_any = True
        lines.append("*Team\\-wide:*")
        for o in global_overrides:
            icon = "🏖️" if o["type"] == "vacation" else "💼"
            lines.append(f"  {icon} {esc(format_date(o['date']))} \\({esc(o['type'])}\\)")

    if user_overrides:
        has_any = True
        lines.append("\n*Your overrides:*" if global_overrides else "*Your overrides:*")
        for o in user_overrides:
            icon = "🏖️" if o["type"] == "vacation" else "💼"
            lines.append(f"  {icon} {esc(format_date(o['date']))} \\({esc(o['type'])}\\)")

    if not has_any:
        lines.append("No overrides this month\\.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ──────────────────── Admin commands ────────────────────

async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not ctx.args:
        return await update.message.reply_text(
            "*Add one or more users:*\n\n"
            "Single:\n`/adduser 123456 Alice`\n\n"
            "Batch \\(comma\\-separated\\):\n"
            "`/adduser 123456 Alice, 789012 Bob, 345678 Charlie`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    raw = " ".join(ctx.args)
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    added = []
    for entry in entries:
        parts = entry.split(None, 1)
        try:
            uid = int(parts[0])
        except ValueError:
            await update.message.reply_text(f"❌ Skipped `{esc(entry)}` — first part must be a numeric ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
            continue
        name = parts[1] if len(parts) > 1 else str(uid)
        db.add_user(uid, display_name=name)
        added.append(f"• *{esc(name)}* \\(`{uid}`\\)")
    if added:
        await update.message.reply_text(f"✅ Added {len(added)} user\\(s\\):\n" + "\n".join(added), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("❌ No users added\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not ctx.args:
        return await update.message.reply_text(
            "*Remove one or more users:*\n\n"
            "`/removeuser Alice`\n"
            "`/removeuser Alice, Bob, Charlie`\n"
            "`/removeuser all` — remove everyone",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    raw = " ".join(ctx.args)
    if raw.strip().lower() == "all":
        users = db.get_active_users()
        for u in users:
            db.remove_user(u["user_id"])
        return await update.message.reply_text(f"✅ Removed all {len(users)} active users\\.", parse_mode=ParseMode.MARKDOWN_V2)
    users = await resolve_multiple_users(raw, update)
    if not users:
        return
    removed = []
    for u in users:
        db.remove_user(u["user_id"])
        removed.append(f"• *{esc(user_label(u))}* \\(`{u['user_id']}`\\)")
    await update.message.reply_text(
        f"✅ Removed {len(removed)} user\\(s\\):\n" + "\n".join(removed) + "\n\nTheir reports are now hidden\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "Usage: `/rename <current name or ID> :: <new name>`\n\n"
            "Example:\n`/rename Alice :: Alice Wang`\n`/rename 123456 :: Bob Chen`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    raw = " ".join(ctx.args)
    if "::" not in raw:
        return await update.message.reply_text("❌ Use `::` to separate old and new name\\.", parse_mode=ParseMode.MARKDOWN_V2)
    parts = raw.split("::", 1)
    identifier = parts[0].strip()
    new_name = parts[1].strip()
    if not new_name:
        return await update.message.reply_text("❌ New name cannot be empty\\.", parse_mode=ParseMode.MARKDOWN_V2)
    user = await resolve_user(identifier, update)
    if not user:
        return
    old_name = user_label(user)
    db.rename_user(user["user_id"], new_name)
    await update.message.reply_text(
        f"✅ Renamed *{esc(old_name)}* → *{esc(new_name)}* \\(`{user['user_id']}`\\)",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_listusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    users = db.get_active_users()
    if not users:
        return await update.message.reply_text("📭 No active users\\.", parse_mode=ParseMode.MARKDOWN_V2)
    lines = ["👥 *Active Users*\n"]
    for u in users:
        tz_str = u["timezone"] or config.DEFAULT_TIMEZONE
        lines.append(
            f"• *{esc(user_label(u))}*  \\(`{u['user_id']}`\\)\n"
            f"  🕐 {esc(tz_str)}  ⏰ {esc(u['first_reminder'])} / {esc(u['second_reminder'])}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    count = await send_reminders(ctx, round_num=0)
    await update.message.reply_text(f"📤 Sent reminders to {count} user\\(s\\)\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)

    uid = update.effective_user.id

    if ctx.args:
        arg = ctx.args[0].lower()
        if arg in ("yesterday", "y"):
            date = yesterday_for_user(uid)
        elif _is_date_str(ctx.args[0]):
            date = ctx.args[0]
        else:
            return await update.message.reply_text(
                "Usage:\n"
                "`/summary` — today\n"
                "`/summary yesterday` — yesterday\n"
                "`/summary 2025\\-03\\-20` — specific date",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    else:
        date = today_for_user(uid)

    reports = db.get_reports_for_date(date)
    if not reports:
        return await update.message.reply_text(f"📭 No reports for {esc(format_date(date))}\\.", parse_mode=ParseMode.MARKDOWN_V2)

    expected = db.get_active_expected_users(date)
    submitted_ids = {r["user_id"] for r in reports}
    missing = [u for u in expected if u["user_id"] not in submitted_ids]

    lines = [f"📋 *Report Summary — {esc(format_date(date))}*\n"]
    for r in reports:
        name = r["display_name"] or r["username"] or str(r["user_id"])
        catch_up = " \\(catch\\-up\\)" if r["is_yesterday"] else ""
        lines.append(f"*{esc(name)}*{catch_up}:\n{esc(r['content'])}\n")

    if missing:
        lines.append(f"❌ *Missing \\({len(missing)}\\):*")
        for u in missing:
            lines.append(f"  • {esc(user_label(u))}")
        lines.append("")

    lines.append(f"📈 *Completion: {len(reports)}/{len(expected)}*")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_settz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "*Set timezone for one or more users:*\n\n"
            "`/settz Alice America/New_York`\n"
            "`/settz Alice, Bob Asia/Tokyo`\n"
            "`/settz all Asia/Shanghai`\n\n"
            "Common timezones:\n"
            "• `Asia/Shanghai` \\(UTC\\+8\\)\n"
            "• `Asia/Tokyo` \\(UTC\\+9\\)\n"
            "• `America/New_York` \\(UTC\\-5\\)\n"
            "• `Europe/London` \\(UTC\\+0\\)\n"
            "• `America/Los_Angeles` \\(UTC\\-8\\)",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    tz_str = ctx.args[-1]
    try:
        pytz.timezone(tz_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return await update.message.reply_text(f"❌ Unknown timezone: `{esc(tz_str)}`", parse_mode=ParseMode.MARKDOWN_V2)
    names_raw = " ".join(ctx.args[:-1])
    users = await resolve_multiple_users(names_raw, update)
    if not users:
        return
    for u in users:
        db.update_user_timezone(u["user_id"], tz_str)
    names = ", ".join(f"*{esc(user_label(u))}*" for u in users)
    await update.message.reply_text(
        f"✅ Timezone set to `{esc(tz_str)}` for {len(users)} user\\(s\\): {names}",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_setreminders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if len(ctx.args) < 3:
        return await update.message.reply_text(
            "*Set reminder times for one or more users:*\n\n"
            "`/setreminders Alice 09:00 10:30`\n"
            "`/setreminders Alice, Bob 09:00 10:30`\n"
            "`/setreminders all 09:00 10:30`\n\n"
            "Times are in each user's local timezone\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    t2_str = ctx.args[-1]
    t1_str = ctx.args[-2]
    t1 = parse_time_str(t1_str)
    t2 = parse_time_str(t2_str)
    if not t1 or not t2:
        return await update.message.reply_text("❌ Invalid time format\\. Use `HH:MM`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    names_raw = " ".join(ctx.args[:-2])
    users = await resolve_multiple_users(names_raw, update)
    if not users:
        return
    for u in users:
        db.update_user_reminders(u["user_id"], first_reminder=t1_str, second_reminder=t2_str)
    names = ", ".join(f"*{esc(user_label(u))}*" for u in users)
    await update.message.reply_text(
        f"✅ Reminders set to `{esc(t1_str)}` / `{esc(t2_str)}` for {len(users)} user\\(s\\): {names}",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_adminvacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "*Admin Vacation & Duty management*\n\n"
            "Global vacation \\(everyone off\\):\n"
            "`/adminvacation all 2025\\-01\\-20`\n"
            "`/adminvacation all 2025\\-01\\-20 2025\\-01\\-24`\n\n"
            "User vacation:\n"
            "`/adminvacation Alice 2025\\-01\\-20`\n"
            "`/adminvacation Alice, Bob 2025\\-01\\-20 2025\\-01\\-24`\n\n"
            "Duty \\(overrides holidays\\):\n"
            "`/adminvacation duty Alice 2025\\-01\\-25`\n\n"
            "Remove override:\n"
            "`/adminvacation remove all 2025\\-01\\-20`\n"
            "`/adminvacation remove Alice 2025\\-01\\-20 2025\\-01\\-24`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    args = list(ctx.args)

    if args[0].lower() == "remove":
        if len(args) < 3:
            return await update.message.reply_text("Usage: `/adminvacation remove <name\\(s\\)/all> <date> [end]`", parse_mode=ParseMode.MARKDOWN_V2)
        dates_args, name_args = _split_dates_from_end(args[1:])
        if not dates_args or not name_args:
            return await update.message.reply_text("❌ Could not parse\\. Put dates at the end\\.", parse_mode=ParseMode.MARKDOWN_V2)
        scope_raw = " ".join(name_args)
        scopes = await _resolve_scopes(scope_raw, update)
        if scopes is None:
            return
        start = dates_args[0]
        end = dates_args[-1] if len(dates_args) > 1 else start
        dates = _date_range(start, end)
        for scope in scopes:
            for d in dates:
                db.remove_override(scope, d, "vacation")
                db.remove_override(scope, d, "duty")
        return await update.message.reply_text(
            f"✅ Removed overrides `{esc(format_date(dates[0]))}` → `{esc(format_date(dates[-1]))}` for {len(scopes)} scope\\(s\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    if args[0].lower() == "duty":
        if len(args) < 3:
            return await update.message.reply_text("Usage: `/adminvacation duty <name\\(s\\)> <date> [end]`", parse_mode=ParseMode.MARKDOWN_V2)
        dates_args, name_args = _split_dates_from_end(args[1:])
        if not dates_args or not name_args:
            return await update.message.reply_text("❌ Could not parse\\.", parse_mode=ParseMode.MARKDOWN_V2)
        scope_raw = " ".join(name_args)
        scopes, labels = await _resolve_scopes_with_labels(scope_raw, update)
        if scopes is None:
            return
        start = dates_args[0]
        end = dates_args[1] if len(dates_args) > 1 else start
        dates = _date_range(start, end)
        for scope in scopes:
            for d in dates:
                db.add_override(scope, d, "duty", note="admin set duty")
        return await update.message.reply_text(
            f"💼 Duty set for {labels}: `{esc(format_date(dates[0]))}` → `{esc(format_date(dates[-1]))}` \\({len(dates)} day\\(s\\)\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    dates_args, name_args = _split_dates_from_end(args)
    if not dates_args or not name_args:
        return await update.message.reply_text("❌ Could not parse\\.", parse_mode=ParseMode.MARKDOWN_V2)
    scope_raw = " ".join(name_args)
    scopes, labels = await _resolve_scopes_with_labels(scope_raw, update)
    if scopes is None:
        return
    start = dates_args[0]
    end = dates_args[1] if len(dates_args) > 1 else start
    dates = _date_range(start, end)
    for scope in scopes:
        for d in dates:
            db.add_override(scope, d, "vacation", note="admin set vacation")
    await update.message.reply_text(
        f"🏖️ Vacation set for {labels}: `{esc(format_date(dates[0]))}` → `{esc(format_date(dates[-1]))}` \\({len(dates)} day\\(s\\)\\)\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    now = datetime.now(pytz.timezone(config.DEFAULT_TIMEZONE))
    year, month = now.year, now.month
    if ctx.args:
        try:
            parts = ctx.args[0].split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return await update.message.reply_text("Usage: `/schedule [YYYY\\-MM]`", parse_mode=ParseMode.MARKDOWN_V2)
    overrides = db.get_overrides_for_month(year, month)
    lines = [f"📅 *Schedule — {year:04d}\\-{month:02d}*\n"]
    if overrides:
        lines.append("*Overrides:*")
        for o in overrides:
            icon = "🏖️" if o["type"] == "vacation" else "💼"
            if o["scope"] == "all":
                scope_label = "Everyone"
            else:
                try:
                    u = db.get_user(int(o["scope"]))
                    scope_label = user_label(u) if u else o["scope"]
                except (ValueError, TypeError):
                    scope_label = o["scope"]
            lines.append(f"  {icon} {esc(format_date(o['date']))} — {esc(scope_label)} \\({esc(o['type'])}\\)")
    else:
        lines.append("No overrides this month\\.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_setsummary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    if not ctx.args:
        current_time = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
        current_tz = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
        current_min = db.get_setting("summary_min_reports", "2")
        return await update.message.reply_text(
            f"*Current summary settings:*\n\n"
            f"🕐 Time: `{esc(current_time)}` \\({esc(current_tz)}\\)\n"
            f"📊 Min reports to post: `{esc(current_min)}`\n\n"
            f"Set time: `/setsummary 12:00 [timezone]`\n"
            f"Set threshold: `/setsummary min 3`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    if ctx.args[0].lower() == "min":
        if len(ctx.args) < 2:
            return await update.message.reply_text("Usage: `/setsummary min <number>`", parse_mode=ParseMode.MARKDOWN_V2)
        try:
            n = int(ctx.args[1])
            if n < 0:
                raise ValueError
        except ValueError:
            return await update.message.reply_text("❌ Must be a non\\-negative number\\.", parse_mode=ParseMode.MARKDOWN_V2)
        db.set_setting("summary_min_reports", str(n))
        return await update.message.reply_text(f"✅ Summary will only post when ≥ `{n}` report\\(s\\) submitted\\.", parse_mode=ParseMode.MARKDOWN_V2)
    t = parse_time_str(ctx.args[0])
    if not t:
        return await update.message.reply_text("❌ Invalid time\\. Use `HH:MM`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    db.set_setting("summary_time", ctx.args[0])
    if len(ctx.args) > 1:
        tz_str = ctx.args[1]
        try:
            pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            return await update.message.reply_text(f"❌ Unknown timezone: `{esc(tz_str)}`", parse_mode=ParseMode.MARKDOWN_V2)
        db.set_setting("summary_timezone", tz_str)
    await update.message.reply_text(
        f"✅ Summary time set to `{esc(ctx.args[0])}` \\({esc(db.get_setting('summary_timezone'))}\\)\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only\\.", parse_mode=ParseMode.MARKDOWN_V2)
    summary_t = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
    summary_tz = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
    summary_min = db.get_setting("summary_min_reports", "2")
    lines = [
        "⚙️ *Current Settings*\n",
        f"📊 Summary time: *{esc(summary_t)}* \\({esc(summary_tz)}\\)",
        f"📊 Summary min reports: *{esc(summary_min)}*",
        f"🌏 Default TZ: *{esc(config.DEFAULT_TIMEZONE)}*",
        f"⏰ Default reminders: *{esc(config.DEFAULT_FIRST_REMINDER)}* / *{esc(config.DEFAULT_SECOND_REMINDER)}*",
        f"📡 Channel: `{config.CHANNEL_ID}`",
        f"💬 Topic ID: `{config.get_topic_id()}`",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ──────────────────── Shared helpers ────────────────────

def _is_date_str(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _split_dates_from_end(args: list) -> tuple:
    dates = []
    i = len(args) - 1
    while i >= 0 and _is_date_str(args[i]):
        dates.insert(0, args[i])
        i -= 1
    return (dates, args[:i + 1])


async def _resolve_scopes(scope_raw: str, update: Update) -> list | None:
    if scope_raw.lower() == "all":
        return ["all"]
    users = await resolve_multiple_users(scope_raw, update)
    if not users:
        return None
    return [str(u["user_id"]) for u in users]


async def _resolve_scopes_with_labels(scope_raw: str, update: Update) -> tuple:
    if scope_raw.lower() == "all":
        return (["all"], "everyone")
    users = await resolve_multiple_users(scope_raw, update)
    if not users:
        return (None, None)
    scopes = [str(u["user_id"]) for u in users]
    labels = ", ".join(f"*{esc(user_label(u))}*" for u in users)
    return (scopes, labels)


def _date_range(start: str, end: str) -> list:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    while s <= e:
        dates.append(s.strftime("%Y-%m-%d"))
        s += timedelta(days=1)
    return dates


# ──────────────── Channel post helper ────────────────

async def post_report_to_channel(ctx, user_id: int, report_date: str, content: str,
                                  is_yesterday: bool, report_id: int = None):
    db_user = db.get_user(user_id)
    name = db_user["display_name"] if db_user and db_user["display_name"] else str(user_id)
    tz_label = user_tz_abbrev(db_user)
    time_str = now_for_user(user_id)

    yesterday_tag = " \\(catch\\-up\\)" if is_yesterday else ""

    channel_text = (
        f"👤  *{esc(name)}*\n\n"
        f"📋 *Daily Report — {esc(format_date(report_date))}*{yesterday_tag}\n"
        f"{'─' * 30}\n\n"
        f"{esc(content)}\n\n"
        f"{'─' * 30}\n"
        f"🕐 {esc(time_str)} \\({esc(tz_label)}\\)"
    )

    try:
        send_kwargs = {
            "chat_id": config.CHANNEL_ID,
            "text": channel_text,
            "parse_mode": ParseMode.MARKDOWN_V2,
        }
        topic_id = config.get_topic_id()
        if topic_id:
            send_kwargs["message_thread_id"] = topic_id

        channel_msg = await ctx.bot.send_message(**send_kwargs)

        if report_id:
            db.update_channel_message_id(report_id, channel_msg.message_id)
        else:
            db.set_channel_message_id_by_user_date(user_id, report_date, channel_msg.message_id)
        return True
    except Exception as e:
        print(f"[Channel] Failed to post for {user_id}: {e}")
        return False


# ──────────────────── Text message handler ────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state not in ("awaiting_report", "awaiting_update"):
        return

    user = update.effective_user
    db_user = db.get_user(user.id)
    if not db_user or not db_user["is_active"]:
        ctx.user_data["state"] = None
        return await update.message.reply_text("⛔ You are not on the report list\\. Please contact an admin\\.", parse_mode=ParseMode.MARKDOWN_V2)

    content = update.message.text
    report_date = ctx.user_data.get("report_date", today_for_user(user.id))
    is_yesterday = ctx.user_data.get("is_yesterday", False)

    # ── DELETE flow ──
    if state == "awaiting_update" and content.strip().lower() == "delete":
        ctx.user_data["state"] = None
        channel_msg_id = db.delete_report(user.id, report_date)
        if channel_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=config.CHANNEL_ID, message_id=channel_msg_id)
            except Exception:
                pass
        await update.message.reply_text(
            f"🗑️ Report for {esc(format_date(report_date))} deleted\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # ── NEW REPORT ──
    if state == "awaiting_report":
        report_id = db.save_report(user.id, report_date, content, update.message.message_id,
                                    is_yesterday=1 if is_yesterday else 0)
        if report_id is None:
            ctx.user_data["state"] = None
            return await update.message.reply_text(
                f"⚠️ Already submitted for {esc(format_date(report_date))}\\. Use /update to modify\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        ctx.user_data["state"] = None
        synced = await post_report_to_channel(ctx, user.id, report_date, content, is_yesterday, report_id)
        tag = " and synced to channel" if synced else " \\(channel sync failed\\)"
        await update.message.reply_text(
            f"✅ Report submitted{esc(tag)}\\!\n\nUse /update anytime to modify or delete\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # ── UPDATE REPORT ──
    old_channel_msg_id = db.update_report(user.id, report_date, content)
    if old_channel_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=config.CHANNEL_ID, message_id=old_channel_msg_id)
        except Exception:
            pass

    ctx.user_data["state"] = None

    existing = db.get_report(user.id, report_date)
    was_yesterday = existing["is_yesterday"] if existing else False

    synced = await post_report_to_channel(ctx, user.id, report_date, content, was_yesterday)
    tag = " and synced to channel" if synced else " \\(channel sync failed\\)"
    await update.message.reply_text(
        f"✅ Report updated{esc(tag)}\\!\n\nUse /update anytime to modify or delete\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ──────────────────── Inline callback ────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "write_report":
        db_user = db.get_user(query.from_user.id)
        if not db_user or not db_user["is_active"]:
            return await query.message.reply_text("⛔ You are not on the report list\\.", parse_mode=ParseMode.MARKDOWN_V2)
        date = today_for_user(query.from_user.id)
        existing = db.get_report(query.from_user.id, date)
        if existing:
            return await query.message.reply_text("📋 Already submitted today\\. Use /update to modify\\.", parse_mode=ParseMode.MARKDOWN_V2)
        ctx.user_data["state"] = "awaiting_report"
        ctx.user_data["report_date"] = date
        ctx.user_data["is_yesterday"] = False
        await query.message.reply_text(
            f"📝 *Daily Report — {esc(format_date(date))}*\n\nPlease type your report below 👇",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    if query.data.startswith("update_"):
        date = query.data.replace("update_", "")
        db_user = db.get_user(query.from_user.id)
        if not db_user or not db_user["is_active"]:
            return await query.message.reply_text("⛔ Not on the report list\\.", parse_mode=ParseMode.MARKDOWN_V2)
        existing = db.get_report(query.from_user.id, date)
        if not existing:
            return await query.message.reply_text(f"📭 No report found for {esc(format_date(date))}\\.", parse_mode=ParseMode.MARKDOWN_V2)
        ctx.user_data["state"] = "awaiting_update"
        ctx.user_data["report_date"] = date
        await query.message.reply_text(
            f"✏️ *Update Report — {esc(format_date(date))}*\n\n"
            f"Current:\n_{esc(existing['content'])}_\n\n"
            f"Send updated report below, or type `delete` to remove it 👇",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return


# ──────────────────── Reminder engine ────────────────────

async def send_reminders(ctx: ContextTypes.DEFAULT_TYPE, round_num: int = 1) -> int:
    users = db.get_active_users()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Write Report", callback_data="write_report")]
    ])
    messages = {
        0: "📢 *Reminder:* Please submit your daily report\\.\nTap below or send /report\\.",
        1: "⏰ *Good morning\\!*\n\nTime to write your daily report for today\\.\nTap the button below or send /report to get started\\.",
        2: "⏰ *Second reminder\\!*\n\nYou haven't submitted today's daily report yet\\.\nPlease submit ASAP 🙏",
    }
    text = messages.get(round_num, messages[0])
    count = 0
    for user in users:
        user_timezone = pytz.timezone(user["timezone"] or config.DEFAULT_TIMEZONE)
        user_now = datetime.now(user_timezone)
        user_date = user_now.strftime("%Y-%m-%d")
        if not db.should_remind_user(user["user_id"], user_date):
            continue
        if db.get_report(user["user_id"], user_date):
            continue
        try:
            await ctx.bot.send_message(
                chat_id=user["user_id"], text=text,
                parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard
            )
            db.record_reminder(user["user_id"], user_date, round_num)
            count += 1
        except Exception as e:
            print(f"[Reminder] Failed for {user['user_id']}: {e}")
    return count
