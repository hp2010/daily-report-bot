from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
import database as db


# ──────────────────── Helpers ────────────────────

def user_tz(user_row):
    return pytz.timezone(user_row["timezone"] if user_row else config.DEFAULT_TIMEZONE)


def today_for_user(user_id: int) -> str:
    u = db.get_user(user_id)
    tz = user_tz(u)
    return datetime.now(tz).strftime("%Y-%m-%d")


def yesterday_for_tz(timezone_str: str) -> str:
    tz = pytz.timezone(timezone_str)
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")


def now_for_user(user_id: int) -> str:
    u = db.get_user(user_id)
    tz = user_tz(u)
    return datetime.now(tz).strftime("%H:%M:%S")


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


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


# ← NEW: Unified user resolution — accepts name or ID
async def resolve_user(identifier: str, update: Update) -> dict | None:
    """
    Resolve a user by numeric ID or display name.
    If ambiguous, prompt the admin to pick.
    Returns a user row dict or None.
    """
    identifier = identifier.strip()

    # Try numeric ID first
    try:
        uid = int(identifier)
        user = db.get_user(uid)
        if user and user["is_active"]:
            return dict(user)
        elif user:
            # exists but inactive
            return dict(user)
        else:
            # no such user by ID, fall through to name search
            pass
    except ValueError:
        pass

    # Name search
    matches = db.find_users_by_name(identifier, active_only=False)

    if len(matches) == 0:
        await update.message.reply_text(
            f"❌ No user found matching `{identifier}`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return None

    if len(matches) == 1:
        return dict(matches[0])

    # Multiple matches — ask admin to be more specific
    lines = [f"⚠️ Multiple users match `{identifier}`. Please be more specific:\n"]
    for m in matches:
        status = "✅" if m["is_active"] else "❌ inactive"
        lines.append(f"• {user_label(m)} — `{m['user_id']}` ({status})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return None


# ← NEW: resolve user but require active
async def resolve_active_user(identifier: str, update: Update) -> dict | None:
    """Same as resolve_user but only returns active users."""
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
        await update.message.reply_text(
            f"❌ No active user found matching `{identifier}`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return None

    if len(matches) == 1:
        return dict(matches[0])

    lines = [f"⚠️ Multiple active users match `{identifier}`. Please be more specific:\n"]
    for m in matches:
        lines.append(f"• {user_label(m)} — `{m['user_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return None


# ──────────────────── Bot menu setup ────────────────────

async def setup_commands(app):
    user_commands = [
        BotCommand("register", "Join the daily report list"),
        BotCommand("report", "Submit today's report"),
        BotCommand("update", "Update today's report"),
        BotCommand("status", "See who submitted today"),
        BotCommand("myreport", "View your today's report"),
    ]

    admin_commands = user_commands + [
        BotCommand("adduser", "Add a user"),
        BotCommand("removeuser", "Remove a user"),
        BotCommand("rename", "Rename a user"),                      # ← NEW
        BotCommand("listusers", "List all active users"),
        BotCommand("remind", "Manually trigger reminders"),
        BotCommand("summary", "Today's full summary"),
        BotCommand("settz", "Set user timezone"),
        BotCommand("setreminders", "Set user reminder times"),
        BotCommand("vacation", "Set vacation/duty day"),
        BotCommand("schedule", "View schedule overrides"),
        BotCommand("setsummary", "Set summary time"),
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
        "👋 *Welcome to the Daily Report Bot!*\n\n"
        "I'll remind you to write your daily report every day "
        "and sync all reports to the onboarding channel.\n\n"
        "Type `/` to see all available commands.",
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────── User commands ────────────────────

async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    name = get_display_name(u)
    db.add_user(u.id, username=u.username, display_name=name)
    await update.message.reply_text(
        f"✅ *Registered!*\n\n"
        f"Name: {name}\n"
        f"ID: `{u.id}`\n"
        f"Timezone: {config.DEFAULT_TIMEZONE}\n\n"
        f"You'll receive daily report reminders from now on.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    existing = db.get_today_report(update.effective_user.id, date)

    if existing:
        return await update.message.reply_text(
            f"📋 You already submitted today's report.\n\n"
            f"_{existing['content']}_\n\n"
            f"Use /update to modify it.",
            parse_mode=ParseMode.MARKDOWN
        )

    ctx.user_data["state"] = "awaiting_report"
    await update.message.reply_text(
        f"📝 *Daily Report — {date}*\n\n"
        f"Please type your report below.\n\n"
        f"Suggested format:\n"
        f"*Done today:*\n- ...\n\n"
        f"*Blockers:*\n- ...\n\n"
        f"*Plan for tomorrow:*\n- ...\n\n"
        f"Send your message when ready 👇",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    existing = db.get_today_report(update.effective_user.id, date)

    if not existing:
        return await update.message.reply_text(
            "📭 You haven't submitted today's report yet. Use /report first."
        )

    ctx.user_data["state"] = "awaiting_update"
    await update.message.reply_text(
        f"✏️ *Update Report — {date}*\n\n"
        f"Your current report:\n_{existing['content']}_\n\n"
        f"Send your updated report below 👇",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_myreport(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    report = db.get_today_report(update.effective_user.id, date)
    if report:
        await update.message.reply_text(
            f"📋 *Your report for {date}:*\n\n{report['content']}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("📭 No report submitted today. Use /report to submit.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    expected = db.get_active_expected_users(date)
    reports = db.get_reports_for_date(date)
    submitted_ids = {r["user_id"] for r in reports}

    done = []
    pending = []
    for u in expected:
        name = user_label(u)
        if u["user_id"] in submitted_ids:
            done.append(f"  ✅ {name}")
        else:
            pending.append(f"  ⏳ {name}")

    lines = [f"📊 *Report Status — {date}*\n"]
    lines.append(f"*Submitted ({len(done)}):*")
    lines.extend(done or ["  (none)"])
    lines.append(f"\n*Pending ({len(pending)}):*")
    lines.extend(pending or ["  (none)"])
    lines.append(f"\n📈 Completion: {len(done)}/{len(expected)}")

    all_active = db.get_active_users()
    off_users = [u for u in all_active if not db.should_remind_user(u["user_id"], date)]
    if off_users:
        lines.append(f"\n🏖️ *Off today ({len(off_users)}):*")
        for u in off_users:
            lines.append(f"  • {user_label(u)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────── Admin commands ────────────────────

# ← CHANGED: accepts name or ID
async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        return await update.message.reply_text(
            "Usage: `/adduser <user_id> [display name]`\n\n"
            "The user\\_id must be numeric (ask them to /start the bot first).",
            parse_mode=ParseMode.MARKDOWN
        )

    try:
        uid = int(ctx.args[0])
    except ValueError:
        return await update.message.reply_text("❌ user\\_id must be a number for adding new users.")

    name = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else str(uid)
    db.add_user(uid, display_name=name)
    await update.message.reply_text(
        f"✅ Added user: *{name}* (`{uid}`)",
        parse_mode=ParseMode.MARKDOWN
    )


# ← CHANGED: accepts name or ID
async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        return await update.message.reply_text(
            "Usage: `/removeuser <name or user_id>`",
            parse_mode=ParseMode.MARKDOWN
        )

    identifier = " ".join(ctx.args)
    user = await resolve_active_user(identifier, update)
    if not user:
        return

    db.remove_user(user["user_id"])
    await update.message.reply_text(
        f"✅ Removed *{user_label(user)}* (`{user['user_id']}`). "
        f"Their reports are now hidden from summaries.",
        parse_mode=ParseMode.MARKDOWN
    )


# ← NEW: /rename
async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "Usage: `/rename <current name or user_id> :: <new name>`\n\n"
            "Example:\n"
            "`/rename Alice :: Alice Wang`\n"
            "`/rename 123456 :: Bob Chen`",
            parse_mode=ParseMode.MARKDOWN
        )

    raw = " ".join(ctx.args)
    if "::" not in raw:
        return await update.message.reply_text(
            "❌ Please use `::` to separate current identity and new name.\n\n"
            "Example: `/rename Alice :: Alice Wang`",
            parse_mode=ParseMode.MARKDOWN
        )

    parts = raw.split("::", 1)
    identifier = parts[0].strip()
    new_name = parts[1].strip()

    if not new_name:
        return await update.message.reply_text("❌ New name cannot be empty.")

    user = await resolve_user(identifier, update)
    if not user:
        return

    old_name = user_label(user)
    db.rename_user(user["user_id"], new_name)

    await update.message.reply_text(
        f"✅ Renamed *{old_name}* → *{new_name}* (`{user['user_id']}`)",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_listusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    users = db.get_active_users()
    if not users:
        return await update.message.reply_text("📭 No active users.")

    lines = ["👥 *Active Users*\n"]
    for u in users:
        tz_str = u["timezone"] or config.DEFAULT_TIMEZONE
        lines.append(
            f"• *{user_label(u)}*  (`{u['user_id']}`)\n"
            f"  🕐 {tz_str}  ⏰ {u['first_reminder']} / {u['second_reminder']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    count = await send_reminders(ctx, round_num=0)
    await update.message.reply_text(f"📤 Sent reminders to {count} user(s).")


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    date = today_for_user(update.effective_user.id)
    reports = db.get_reports_for_date(date)

    if not reports:
        return await update.message.reply_text(f"📭 No reports for {date} yet.")

    lines = [f"📋 *Report Summary — {date}*\n"]
    for r in reports:
        name = r["display_name"] or r["username"] or str(r["user_id"])
        lines.append(f"*{name}:*\n{r['content']}\n")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ← CHANGED: accepts name or ID
async def cmd_settz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "Usage: `/settz <name or user_id> <timezone>`\n\n"
            "Example:\n"
            "`/settz Alice America/New_York`\n"
            "`/settz 123456 Asia/Tokyo`\n\n"
            "Common timezones:\n"
            "• `Asia/Shanghai` (UTC+8)\n"
            "• `Asia/Tokyo` (UTC+9)\n"
            "• `America/New_York` (UTC-5)\n"
            "• `Europe/London` (UTC+0)\n"
            "• `America/Los_Angeles` (UTC-8)",
            parse_mode=ParseMode.MARKDOWN
        )

    # Last arg is timezone, everything before is the identifier
    tz_str = ctx.args[-1]
    identifier = " ".join(ctx.args[:-1])

    try:
        pytz.timezone(tz_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return await update.message.reply_text(
            f"❌ Unknown timezone: `{tz_str}`",
            parse_mode=ParseMode.MARKDOWN
        )

    user = await resolve_active_user(identifier, update)
    if not user:
        return

    db.update_user_timezone(user["user_id"], tz_str)
    await update.message.reply_text(
        f"✅ Timezone for *{user_label(user)}* set to `{tz_str}`.",
        parse_mode=ParseMode.MARKDOWN
    )


# ← CHANGED: accepts name or ID
async def cmd_setreminders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if len(ctx.args) < 3:
        return await update.message.reply_text(
            "Usage: `/setreminders <name or user_id> <1st_time> <2nd_time>`\n\n"
            "Example:\n"
            "`/setreminders Alice 09:00 10:30`\n"
            "`/setreminders 123456 09:00 10:30`\n\n"
            "Times are in the user's local timezone.",
            parse_mode=ParseMode.MARKDOWN
        )

    # Last two args are times, everything before is the identifier
    t2_str = ctx.args[-1]
    t1_str = ctx.args[-2]
    identifier = " ".join(ctx.args[:-2])

    t1 = parse_time_str(t1_str)
    t2 = parse_time_str(t2_str)

    if not t1 or not t2:
        return await update.message.reply_text(
            "❌ Invalid time format. Use `HH:MM`.",
            parse_mode=ParseMode.MARKDOWN
        )

    user = await resolve_active_user(identifier, update)
    if not user:
        return

    db.update_user_reminders(user["user_id"], first_reminder=t1_str, second_reminder=t2_str)
    await update.message.reply_text(
        f"✅ Reminders for *{user_label(user)}* set to `{t1_str}` and `{t2_str}`.",
        parse_mode=ParseMode.MARKDOWN
    )


# ← CHANGED: /vacation also accepts names
async def cmd_vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "*Vacation & Duty management*\n\n"
            "Set global vacation (everyone off):\n"
            "`/vacation all 2025-01-20`\n"
            "`/vacation all 2025-01-20 2025-01-24` (range)\n\n"
            "Set one user on vacation:\n"
            "`/vacation Alice 2025-01-20`\n"
            "`/vacation Alice 2025-01-20 2025-01-24`\n\n"
            "Set one user on duty (overrides weekend/holiday):\n"
            "`/vacation duty Alice 2025-01-25`\n\n"
            "Remove an override:\n"
            "`/vacation remove all 2025-01-20`\n"
            "`/vacation remove Alice 2025-01-20`",
            parse_mode=ParseMode.MARKDOWN
        )

    args = list(ctx.args)

    # ── /vacation remove <scope> <date> ──
    if args[0].lower() == "remove":
        if len(args) < 3:
            return await update.message.reply_text(
                "Usage: `/vacation remove <name/all> <date>`",
                parse_mode=ParseMode.MARKDOWN
            )
        date_str = args[-1]
        scope_raw = " ".join(args[1:-1])
        scope = await _resolve_scope(scope_raw, update)
        if scope is None:
            return
        db.remove_override(scope, date_str, "vacation")
        db.remove_override(scope, date_str, "duty")
        scope_display = "everyone" if scope == "all" else f"*{scope_raw}*"
        return await update.message.reply_text(
            f"✅ Removed overrides for {scope_display} on `{date_str}`.",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── /vacation duty <scope> <date> [end_date] ──
    if args[0].lower() == "duty":
        if len(args) < 3:
            return await update.message.reply_text(
                "Usage: `/vacation duty <name> <date> [end_date]`",
                parse_mode=ParseMode.MARKDOWN
            )
        # Find where dates start (look from the end for date-like strings)
        dates_args, name_args = _split_dates_from_end(args[1:])
        if not dates_args or not name_args:
            return await update.message.reply_text(
                "❌ Could not parse. Usage: `/vacation duty Alice 2025-01-25`",
                parse_mode=ParseMode.MARKDOWN
            )
        scope_raw = " ".join(name_args)
        scope = await _resolve_scope(scope_raw, update)
        if scope is None:
            return
        start = dates_args[0]
        end = dates_args[1] if len(dates_args) > 1 else start
        dates = _date_range(start, end)
        for d in dates:
            db.add_override(scope, d, "duty", note="admin set duty")
        scope_display = f"*{scope_raw}*"
        return await update.message.reply_text(
            f"💼 Duty set for {scope_display}: `{dates[0]}` → `{dates[-1]}` ({len(dates)} day(s)).",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── /vacation <scope> <date> [end_date] ──
    dates_args, name_args = _split_dates_from_end(args)
    if not dates_args or not name_args:
        return await update.message.reply_text(
            "❌ Could not parse. Make sure dates are at the end in `YYYY-MM-DD` format.",
            parse_mode=ParseMode.MARKDOWN
        )

    scope_raw = " ".join(name_args)
    scope = await _resolve_scope(scope_raw, update)
    if scope is None:
        return

    start = dates_args[0]
    end = dates_args[1] if len(dates_args) > 1 else start
    dates = _date_range(start, end)
    for d in dates:
        db.add_override(scope, d, "vacation", note="admin set vacation")

    scope_display = "everyone" if scope == "all" else f"*{scope_raw}*"
    await update.message.reply_text(
        f"🏖️ Vacation set for {scope_display}: `{dates[0]}` → `{dates[-1]}` ({len(dates)} day(s)).",
        parse_mode=ParseMode.MARKDOWN
    )


def _is_date_str(s: str) -> bool:
    """Check if a string looks like YYYY-MM-DD."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _split_dates_from_end(args: list) -> tuple:
    """
    Split args into (date_args, name_args) by scanning from the end.
    Returns (dates_from_end_reversed, remaining_name_args).
    E.g. ["Alice", "Wang", "2025-01-20", "2025-01-24"]
         → (["2025-01-20", "2025-01-24"], ["Alice", "Wang"])
    """
    dates = []
    i = len(args) - 1
    while i >= 0 and _is_date_str(args[i]):
        dates.insert(0, args[i])
        i -= 1
    name_args = args[:i + 1]
    return (dates, name_args)


async def _resolve_scope(scope_raw: str, update: Update) -> str | None:
    """
    Resolve scope string to either "all" or a user_id string.
    Returns None if resolution fails.
    """
    if scope_raw.lower() == "all":
        return "all"

    # Try as user identifier
    user = await resolve_active_user(scope_raw, update)
    if user:
        return str(user["user_id"])
    return None


def _date_range(start: str, end: str) -> list:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    while s <= e:
        dates.append(s.strftime("%Y-%m-%d"))
        s += timedelta(days=1)
    return dates


# ──── /schedule ────

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    now = datetime.now(pytz.timezone(config.DEFAULT_TIMEZONE))
    year = now.year
    month = now.month

    if ctx.args:
        try:
            parts = ctx.args[0].split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return await update.message.reply_text(
                "Usage: `/schedule [YYYY-MM]`",
                parse_mode=ParseMode.MARKDOWN
            )

    overrides = db.get_overrides_for_month(year, month)
    weekends_off = db.get_setting("weekends_off", "1") == "1"

    lines = [f"📅 *Schedule — {year:04d}-{month:02d}*\n"]

    if weekends_off:
        lines.append("⚙️ Weekends off: *ON*\n")
    else:
        lines.append("⚙️ Weekends off: *OFF*\n")

    if overrides:
        lines.append("*Overrides:*")
        for o in overrides:
            icon = "🏖️" if o["type"] == "vacation" else "💼"
            if o["scope"] == "all":
                scope_label = "Everyone"
            else:
                # Try to show name instead of ID
                try:
                    u = db.get_user(int(o["scope"]))
                    scope_label = user_label(u) if u else o["scope"]
                except (ValueError, TypeError):
                    scope_label = o["scope"]
            lines.append(f"  {icon} {o['date']} — {scope_label} ({o['type']})")
    else:
        lines.append("No overrides this month.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──── /setsummary ────

async def cmd_setsummary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        current_time = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
        current_tz = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
        return await update.message.reply_text(
            f"Current summary: `{current_time}` ({current_tz})\n\n"
            f"Usage: `/setsummary <HH:MM> [timezone]`\n"
            f"Example: `/setsummary 12:00 Asia/Shanghai`",
            parse_mode=ParseMode.MARKDOWN
        )

    t = parse_time_str(ctx.args[0])
    if not t:
        return await update.message.reply_text(
            "❌ Invalid time. Use `HH:MM`.",
            parse_mode=ParseMode.MARKDOWN
        )

    db.set_setting("summary_time", ctx.args[0])

    if len(ctx.args) > 1:
        tz_str = ctx.args[1]
        try:
            pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            return await update.message.reply_text(
                f"❌ Unknown timezone: `{tz_str}`",
                parse_mode=ParseMode.MARKDOWN
            )
        db.set_setting("summary_timezone", tz_str)

    await update.message.reply_text(
        f"✅ Summary time set to `{ctx.args[0]}` ({db.get_setting('summary_timezone')}).",
        parse_mode=ParseMode.MARKDOWN
    )


# ──── /settings ────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    weekends = "ON" if db.get_setting("weekends_off", "1") == "1" else "OFF"
    summary_t = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
    summary_tz = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)

    lines = [
        "⚙️ *Current Settings*\n",
        f"📅 Weekends off: *{weekends}*",
        f"📊 Summary time: *{summary_t}* ({summary_tz})",
        f"🌏 Default TZ: *{config.DEFAULT_TIMEZONE}*",
        f"⏰ Default reminders: *{config.DEFAULT_FIRST_REMINDER}* / *{config.DEFAULT_SECOND_REMINDER}*",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────── Text message handler ────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state not in ("awaiting_report", "awaiting_update"):
        return

    user = update.effective_user
    date = today_for_user(user.id)
    content = update.message.text
    name = get_display_name(user)

    # Use DB display_name if available (may have been renamed by admin)
    db_user = db.get_user(user.id)
    if db_user and db_user["display_name"]:
        name = db_user["display_name"]

    if state == "awaiting_report":
        report_id = db.save_report(user.id, date, content, update.message.message_id)
        if report_id is None:
            ctx.user_data["state"] = None
            return await update.message.reply_text(
                "⚠️ You already submitted today. Use /update to modify."
            )
    else:
        old_channel_msg_id = db.update_report(user.id, date, content)
        report_id = None
        if old_channel_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=config.CHANNEL_ID, message_id=old_channel_msg_id)
            except Exception:
                pass

    ctx.user_data["state"] = None

    channel_text = (
        f"📋 *Daily Report — {date}*\n"
        f"👤 *{name}*\n"
        f"{'─' * 24}\n\n"
        f"{content}\n\n"
        f"{'─' * 24}\n"
        f"🕐 Submitted at {now_for_user(user.id)}"
    )

    tag = ""
    try:
        channel_msg = await ctx.bot.send_message(
            chat_id=config.CHANNEL_ID,
            text=channel_text,
            parse_mode=ParseMode.MARKDOWN
        )
        if report_id:
            db.update_channel_message_id(report_id, channel_msg.message_id)
        else:
            db.set_channel_message_id_by_user_date(user.id, date, channel_msg.message_id)
        tag = " and synced to channel"
    except Exception as e:
        tag = f" (channel sync failed: {e})"

    action = "updated" if state == "awaiting_update" else "submitted"
    await update.message.reply_text(f"✅ Report {action}{tag}!\n\nUse /update anytime to modify.")


# ──────────────────── Inline callback ────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "write_report":
        date = today_for_user(query.from_user.id)
        existing = db.get_today_report(query.from_user.id, date)
        if existing:
            return await query.message.reply_text(
                "📋 You already submitted today. Use /update to modify."
            )
        ctx.user_data["state"] = "awaiting_report"
        await query.message.reply_text(
            f"📝 *Daily Report — {date}*\n\nPlease type your report below 👇",
            parse_mode=ParseMode.MARKDOWN
        )


# ──────────────────── Reminder engine ────────────────────

async def send_reminders(ctx: ContextTypes.DEFAULT_TYPE, round_num: int = 1) -> int:
    users = db.get_active_users()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Write Report", callback_data="write_report")]
    ])

    messages = {
        0: "📢 *Reminder:* Please submit your daily report.\nTap below or send /report.",
        1: (
            "⏰ *Good morning!*\n\n"
            "Time to write your daily report for today.\n"
            "Tap the button below or send /report to get started."
        ),
        2: (
            "⏰ *Second reminder!*\n\n"
            "You haven't submitted today's daily report yet.\n"
            "Please submit ASAP 🙏"
        ),
    }
    text = messages.get(round_num, messages[0])
    count = 0

    for user in users:
        user_timezone = pytz.timezone(user["timezone"] or config.DEFAULT_TIMEZONE)
        user_now = datetime.now(user_timezone)
        user_date = user_now.strftime("%Y-%m-%d")

        if not db.should_remind_user(user["user_id"], user_date):
            continue

        existing = db.get_today_report(user["user_id"], user_date)
        if existing:
            continue

        try:
            await ctx.bot.send_message(
                chat_id=user["user_id"],
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            db.record_reminder(user["user_id"], user_date, round_num)
            count += 1
        except Exception as e:
            print(f"[Reminder] Failed for {user['user_id']}: {e}")

    return count