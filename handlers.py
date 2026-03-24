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


def today_for_tz(timezone_str: str) -> str:
    tz = pytz.timezone(timezone_str)
    return datetime.now(tz).strftime("%Y-%m-%d")


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
        await update.message.reply_text(f"❌ No user found matching `{identifier}`.", parse_mode=ParseMode.MARKDOWN)
        return None
    if len(matches) == 1:
        return dict(matches[0])

    lines = [f"⚠️ Multiple users match `{identifier}`. Please be more specific:\n"]
    for m in matches:
        status = "✅" if m["is_active"] else "❌ inactive"
        lines.append(f"• *{user_label(m)}* — `{m['user_id']}` ({status})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
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
        await update.message.reply_text(f"❌ No active user found matching `{identifier}`.", parse_mode=ParseMode.MARKDOWN)
        return None
    if len(matches) == 1:
        return dict(matches[0])

    lines = [f"⚠️ Multiple active users match `{identifier}`. Please be more specific:\n"]
    for m in matches:
        lines.append(f"• *{user_label(m)}* — `{m['user_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return None


async def resolve_multiple_users(raw: str, update: Update) -> list | None:
    """
    Parse a comma-separated list of names/IDs.
    Special keyword "all" returns all active users.
    Returns list of user dicts, or None on any failure.
    """
    raw = raw.strip()
    if raw.lower() == "all":
        users = db.get_active_users()
        if not users:
            await update.message.reply_text("📭 No active users.")
            return None
        return [dict(u) for u in users]

    identifiers = [s.strip() for s in raw.split(",") if s.strip()]
    if not identifiers:
        await update.message.reply_text("❌ No users specified.")
        return None

    results = []
    for ident in identifiers:
        user = await resolve_active_user(ident, update)
        if user is None:
            return None  # stop on first failure, error already sent
        results.append(user)
    return results


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
        BotCommand("adduser", "Add user(s)"),
        BotCommand("removeuser", "Remove user(s)"),
        BotCommand("rename", "Rename a user"),
        BotCommand("listusers", "List all active users"),
        BotCommand("remind", "Manually trigger reminders"),
        BotCommand("summary", "Today's full summary"),
        BotCommand("settz", "Set timezone (batch)"),
        BotCommand("setreminders", "Set reminder times (batch)"),
        BotCommand("vacation", "Set vacation/duty (batch)"),
        BotCommand("schedule", "View schedule overrides"),
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
        f"✅ *Registered!*\n\nName: {name}\nID: `{u.id}`\n"
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
            f"_{existing['content']}_\n\nUse /update to modify it.",
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
        return await update.message.reply_text("📭 No report yet. Use /report first.")
    ctx.user_data["state"] = "awaiting_update"
    await update.message.reply_text(
        f"✏️ *Update Report — {date}*\n\n"
        f"Current:\n_{existing['content']}_\n\nSend updated report below 👇",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_myreport(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    report = db.get_today_report(update.effective_user.id, date)
    if report:
        await update.message.reply_text(f"📋 *Your report for {date}:*\n\n{report['content']}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("📭 No report submitted today. Use /report to submit.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_for_user(update.effective_user.id)
    expected = db.get_active_expected_users(date)
    reports = db.get_reports_for_date(date)
    submitted_ids = {r["user_id"] for r in reports}

    done, pending = [], []
    for u in expected:
        name = user_label(u)
        (done if u["user_id"] in submitted_ids else pending).append(name)

    lines = [f"📊 *Report Status — {date}*\n"]
    lines.append(f"*Submitted ({len(done)}):*")
    lines.extend([f"  ✅ {n}" for n in done] or ["  (none)"])
    lines.append(f"\n*Pending ({len(pending)}):*")
    lines.extend([f"  ⏳ {n}" for n in pending] or ["  (none)"])
    lines.append(f"\n📈 Completion: {len(done)}/{len(expected)}")

    all_active = db.get_active_users()
    off_users = [u for u in all_active if not db.should_remind_user(u["user_id"], date)]
    if off_users:
        lines.append(f"\n🏖️ *Off today ({len(off_users)}):*")
        for u in off_users:
            lines.append(f"  • {user_label(u)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────── Admin commands ────────────────────

async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /adduser 123456 Alice
    /adduser 123456 Alice, 789012 Bob, 345678 Charlie
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if not ctx.args:
        return await update.message.reply_text(
            "*Add one or more users:*\n\n"
            "Single:\n`/adduser 123456 Alice`\n\n"
            "Batch (comma-separated):\n"
            "`/adduser 123456 Alice, 789012 Bob, 345678 Charlie`",
            parse_mode=ParseMode.MARKDOWN
        )

    raw = " ".join(ctx.args)
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    added = []

    for entry in entries:
        parts = entry.split(None, 1)
        try:
            uid = int(parts[0])
        except ValueError:
            await update.message.reply_text(f"❌ Skipped `{entry}` — first part must be a numeric ID.", parse_mode=ParseMode.MARKDOWN)
            continue
        name = parts[1] if len(parts) > 1 else str(uid)
        db.add_user(uid, display_name=name)
        added.append(f"• *{name}* (`{uid}`)")

    if added:
        await update.message.reply_text(f"✅ Added {len(added)} user(s):\n" + "\n".join(added), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ No users added.")


async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /removeuser Alice
    /removeuser Alice, Bob, Charlie
    /removeuser all
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if not ctx.args:
        return await update.message.reply_text(
            "*Remove one or more users:*\n\n"
            "`/removeuser Alice`\n"
            "`/removeuser Alice, Bob, Charlie`\n"
            "`/removeuser all` — remove everyone",
            parse_mode=ParseMode.MARKDOWN
        )

    raw = " ".join(ctx.args)

    if raw.strip().lower() == "all":
        users = db.get_active_users()
        for u in users:
            db.remove_user(u["user_id"])
        return await update.message.reply_text(f"✅ Removed all {len(users)} active users.")

    users = await resolve_multiple_users(raw, update)
    if not users:
        return

    removed = []
    for u in users:
        db.remove_user(u["user_id"])
        removed.append(f"• *{user_label(u)}* (`{u['user_id']}`)")

    await update.message.reply_text(
        f"✅ Removed {len(removed)} user(s):\n" + "\n".join(removed) + "\n\nTheir reports are now hidden.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "Usage: `/rename <current name or ID> :: <new name>`\n\n"
            "Example:\n`/rename Alice :: Alice Wang`\n`/rename 123456 :: Bob Chen`",
            parse_mode=ParseMode.MARKDOWN
        )

    raw = " ".join(ctx.args)
    if "::" not in raw:
        return await update.message.reply_text(
            "❌ Use `::` to separate old and new name.\nExample: `/rename Alice :: Alice Wang`",
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


# ──── /settz — batch support ────

async def cmd_settz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /settz Alice America/New_York
    /settz Alice, Bob, Charlie Asia/Tokyo
    /settz all Asia/Shanghai
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "*Set timezone for one or more users:*\n\n"
            "`/settz Alice America/New_York`\n"
            "`/settz Alice, Bob Asia/Tokyo`\n"
            "`/settz all Asia/Shanghai`\n\n"
            "Common timezones:\n"
            "• `Asia/Shanghai` (UTC+8)\n"
            "• `Asia/Tokyo` (UTC+9)\n"
            "• `America/New_York` (UTC-5)\n"
            "• `Europe/London` (UTC+0)\n"
            "• `America/Los_Angeles` (UTC-8)",
            parse_mode=ParseMode.MARKDOWN
        )

    # Last arg is the timezone
    tz_str = ctx.args[-1]
    try:
        pytz.timezone(tz_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return await update.message.reply_text(f"❌ Unknown timezone: `{tz_str}`", parse_mode=ParseMode.MARKDOWN)

    names_raw = " ".join(ctx.args[:-1])
    users = await resolve_multiple_users(names_raw, update)
    if not users:
        return

    for u in users:
        db.update_user_timezone(u["user_id"], tz_str)

    names = ", ".join(f"*{user_label(u)}*" for u in users)
    await update.message.reply_text(
        f"✅ Timezone set to `{tz_str}` for {len(users)} user(s): {names}",
        parse_mode=ParseMode.MARKDOWN
    )


# ──── /setreminders — batch support ────

async def cmd_setreminders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /setreminders Alice 09:00 10:30
    /setreminders Alice, Bob 09:00 10:30
    /setreminders all 09:00 10:30
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if len(ctx.args) < 3:
        return await update.message.reply_text(
            "*Set reminder times for one or more users:*\n\n"
            "`/setreminders Alice 09:00 10:30`\n"
            "`/setreminders Alice, Bob 09:00 10:30`\n"
            "`/setreminders all 09:00 10:30`\n\n"
            "Times are in each user's local timezone.",
            parse_mode=ParseMode.MARKDOWN
        )

    t2_str = ctx.args[-1]
    t1_str = ctx.args[-2]
    t1 = parse_time_str(t1_str)
    t2 = parse_time_str(t2_str)
    if not t1 or not t2:
        return await update.message.reply_text("❌ Invalid time format. Use `HH:MM`.", parse_mode=ParseMode.MARKDOWN)

    names_raw = " ".join(ctx.args[:-2])
    users = await resolve_multiple_users(names_raw, update)
    if not users:
        return

    for u in users:
        db.update_user_reminders(u["user_id"], first_reminder=t1_str, second_reminder=t2_str)

    names = ", ".join(f"*{user_label(u)}*" for u in users)
    await update.message.reply_text(
        f"✅ Reminders set to `{t1_str}` / `{t2_str}` for {len(users)} user(s): {names}",
        parse_mode=ParseMode.MARKDOWN
    )


# ──── /vacation — batch support ────

async def cmd_vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /vacation all 2025-01-20
    /vacation all 2025-01-20 2025-01-24
    /vacation Alice 2025-01-20
    /vacation Alice, Bob 2025-01-20 2025-01-24
    /vacation duty Alice 2025-01-25
    /vacation duty Alice, Bob 2025-01-25 2025-01-26
    /vacation remove all 2025-01-20
    /vacation remove Alice 2025-01-20
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "*Vacation & Duty management*\n\n"
            "Global vacation (everyone off):\n"
            "`/vacation all 2025-01-20`\n"
            "`/vacation all 2025-01-20 2025-01-24`\n\n"
            "User vacation:\n"
            "`/vacation Alice 2025-01-20`\n"
            "`/vacation Alice, Bob 2025-01-20 2025-01-24`\n\n"
            "Duty (overrides weekend/holiday):\n"
            "`/vacation duty Alice 2025-01-25`\n"
            "`/vacation duty Alice, Bob 2025-01-25 2025-01-26`\n\n"
            "Remove override:\n"
            "`/vacation remove all 2025-01-20`\n"
            "`/vacation remove Alice 2025-01-20`",
            parse_mode=ParseMode.MARKDOWN
        )

    args = list(ctx.args)

    # ── remove ──
    if args[0].lower() == "remove":
        if len(args) < 3:
            return await update.message.reply_text("Usage: `/vacation remove <name(s)/all> <date>`", parse_mode=ParseMode.MARKDOWN)
        date_str = args[-1]
        scope_raw = " ".join(args[1:-1])
        scopes = await _resolve_scopes(scope_raw, update)
        if scopes is None:
            return
        for scope in scopes:
            db.remove_override(scope, date_str, "vacation")
            db.remove_override(scope, date_str, "duty")
        return await update.message.reply_text(
            f"✅ Removed overrides on `{date_str}` for {len(scopes)} scope(s).",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── duty ──
    if args[0].lower() == "duty":
        if len(args) < 3:
            return await update.message.reply_text("Usage: `/vacation duty <name(s)> <date> [end_date]`", parse_mode=ParseMode.MARKDOWN)
        dates_args, name_args = _split_dates_from_end(args[1:])
        if not dates_args or not name_args:
            return await update.message.reply_text("❌ Could not parse. Put dates at the end in `YYYY-MM-DD`.", parse_mode=ParseMode.MARKDOWN)
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
            f"💼 Duty set for {labels}: `{dates[0]}` → `{dates[-1]}` ({len(dates)} day(s)).",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── vacation ──
    dates_args, name_args = _split_dates_from_end(args)
    if not dates_args or not name_args:
        return await update.message.reply_text("❌ Could not parse. Put dates at the end in `YYYY-MM-DD`.", parse_mode=ParseMode.MARKDOWN)

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
        f"🏖️ Vacation set for {labels}: `{dates[0]}` → `{dates[-1]}` ({len(dates)} day(s)).",
        parse_mode=ParseMode.MARKDOWN
    )


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
    name_args = args[:i + 1]
    return (dates, name_args)


async def _resolve_scopes(scope_raw: str, update: Update) -> list | None:
    """Resolve to list of scope strings ('all' or user_id strings)."""
    if scope_raw.lower() == "all":
        return ["all"]
    users = await resolve_multiple_users(scope_raw, update)
    if not users:
        return None
    return [str(u["user_id"]) for u in users]


async def _resolve_scopes_with_labels(scope_raw: str, update: Update) -> tuple:
    """Returns (scopes_list, display_label_string) or (None, None)."""
    if scope_raw.lower() == "all":
        return (["all"], "everyone")
    users = await resolve_multiple_users(scope_raw, update)
    if not users:
        return (None, None)
    scopes = [str(u["user_id"]) for u in users]
    labels = ", ".join(f"*{user_label(u)}*" for u in users)
    return (scopes, labels)


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
    year, month = now.year, now.month
    if ctx.args:
        try:
            parts = ctx.args[0].split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return await update.message.reply_text("Usage: `/schedule [YYYY-MM]`", parse_mode=ParseMode.MARKDOWN)

    overrides = db.get_overrides_for_month(year, month)
    weekends_off = db.get_setting("weekends_off", "1") == "1"

    lines = [f"📅 *Schedule — {year:04d}-{month:02d}*\n"]
    lines.append(f"⚙️ Weekends off: *{'ON' if weekends_off else 'OFF'}*\n")

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
            lines.append(f"  {icon} {o['date']} — {scope_label} ({o['type']})")
    else:
        lines.append("No overrides this month.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──── /setsummary — now also sets threshold ────

async def cmd_setsummary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /setsummary                          → show current
    /setsummary 12:00                    → set time
    /setsummary 12:00 Asia/Shanghai      → set time + tz
    /setsummary min 3                    → set minimum reports threshold
    """
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        current_time = db.get_setting("summary_time", config.DEFAULT_SUMMARY_TIME)
        current_tz = db.get_setting("summary_timezone", config.SUMMARY_TIMEZONE)
        current_min = db.get_setting("summary_min_reports", "2")
        return await update.message.reply_text(
            f"*Current summary settings:*\n\n"
            f"🕐 Time: `{current_time}` ({current_tz})\n"
            f"📊 Min reports to post: `{current_min}`\n\n"
            f"Set time: `/setsummary 12:00 [timezone]`\n"
            f"Set threshold: `/setsummary min 3`",
            parse_mode=ParseMode.MARKDOWN
        )

    if ctx.args[0].lower() == "min":
        if len(ctx.args) < 2:
            return await update.message.reply_text("Usage: `/setsummary min <number>`", parse_mode=ParseMode.MARKDOWN)
        try:
            n = int(ctx.args[1])
            if n < 0:
                raise ValueError
        except ValueError:
            return await update.message.reply_text("❌ Must be a non-negative number.", parse_mode=ParseMode.MARKDOWN)
        db.set_setting("summary_min_reports", str(n))
        return await update.message.reply_text(
            f"✅ Summary will only post when ≥ `{n}` report(s) submitted.",
            parse_mode=ParseMode.MARKDOWN
        )

    t = parse_time_str(ctx.args[0])
    if not t:
        return await update.message.reply_text("❌ Invalid time. Use `HH:MM`.", parse_mode=ParseMode.MARKDOWN)

    db.set_setting("summary_time", ctx.args[0])
    if len(ctx.args) > 1:
        tz_str = ctx.args[1]
        try:
            pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            return await update.message.reply_text(f"❌ Unknown timezone: `{tz_str}`", parse_mode=ParseMode.MARKDOWN)
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
    summary_min = db.get_setting("summary_min_reports", "2")

    lines = [
        "⚙️ *Current Settings*\n",
        f"📅 Weekends off: *{weekends}*",
        f"📊 Summary time: *{summary_t}* ({summary_tz})",
        f"📊 Summary min reports: *{summary_min}*",
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

    db_user = db.get_user(user.id)
    name = (db_user["display_name"] if db_user and db_user["display_name"] else get_display_name(user))

    if state == "awaiting_report":
        report_id = db.save_report(user.id, date, content, update.message.message_id)
        if report_id is None:
            ctx.user_data["state"] = None
            return await update.message.reply_text("⚠️ Already submitted today. Use /update to modify.")
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
            chat_id=config.CHANNEL_ID, text=channel_text, parse_mode=ParseMode.MARKDOWN
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
            return await query.message.reply_text("📋 Already submitted today. Use /update to modify.")
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
        1: "⏰ *Good morning!*\n\nTime to write your daily report for today.\nTap the button below or send /report to get started.",
        2: "⏰ *Second reminder!*\n\nYou haven't submitted today's daily report yet.\nPlease submit ASAP 🙏",
    }
    text = messages.get(round_num, messages[0])
    count = 0

    for user in users:
        user_timezone = pytz.timezone(user["timezone"] or config.DEFAULT_TIMEZONE)
        user_now = datetime.now(user_timezone)
        user_date = user_now.strftime("%Y-%m-%d")
        if not db.should_remind_user(user["user_id"], user_date):
            continue
        if db.get_today_report(user["user_id"], user_date):
            continue
        try:
            await ctx.bot.send_message(
                chat_id=user["user_id"], text=text,
                parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
            )
            db.record_reminder(user["user_id"], user_date, round_num)
            count += 1
        except Exception as e:
            print(f"[Reminder] Failed for {user['user_id']}: {e}")
    return count