from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
import database as db

tz = pytz.timezone(config.TIMEZONE)


def today_str():
    return datetime.now(tz).strftime("%Y-%m-%d")


def yesterday_str():
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")


def now_str():
    return datetime.now(tz).strftime("%H:%M:%S")


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def display_name(user) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def user_label(row) -> str:
    return row["display_name"] or (f"@{row['username']}" if row["username"] else str(row["user_id"]))


# ──────────────────────────── Commands ────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the Daily Report Bot!*\n\n"
        "I'll remind you to write your daily report every day, "
        "and sync all reports to the onboarding channel.\n\n"
        "📝 *Commands*\n"
        "/register — Join the daily report list\n"
        "/report — Submit today's report\n"
        "/update — Update today's report\n"
        "/status — See who submitted today\n"
        "/myreport — View your today's report\n\n"
        "🔒 *Admin*\n"
        "/adduser `<user_id>` `[name]` — Add a user\n"
        "/removeuser `<user_id>` — Remove a user\n"
        "/listusers — List all active users\n"
        "/remind — Manually trigger reminders\n"
        "/summary — Today's full summary",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    name = display_name(u)
    db.add_user(u.id, username=u.username, display_name=name)
    await update.message.reply_text(
        f"✅ *Registered!*\n\n"
        f"Name: {name}\n"
        f"ID: `{u.id}`\n\n"
        f"You'll receive daily report reminders from now on.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        return await update.message.reply_text("Usage: `/adduser <user_id> [display name]`", parse_mode=ParseMode.MARKDOWN)

    try:
        uid = int(ctx.args[0])
    except ValueError:
        return await update.message.reply_text("❌ user_id must be a number.")

    name = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else str(uid)
    db.add_user(uid, display_name=name)
    await update.message.reply_text(f"✅ Added user: {name} (`{uid}`)", parse_mode=ParseMode.MARKDOWN)


async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    if not ctx.args:
        return await update.message.reply_text("Usage: `/removeuser <user_id>`", parse_mode=ParseMode.MARKDOWN)

    uid = int(ctx.args[0])
    db.remove_user(uid)
    await update.message.reply_text(f"✅ Removed user `{uid}`.", parse_mode=ParseMode.MARKDOWN)


async def cmd_listusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    users = db.get_active_users()
    if not users:
        return await update.message.reply_text("📭 No active users.")

    lines = ["👥 *Active Users*\n"]
    for u in users:
        lines.append(f"• {user_label(u)}  (`{u['user_id']}`)")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_str()
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
    date = today_str()
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
    date = today_str()
    report = db.get_today_report(update.effective_user.id, date)
    if report:
        await update.message.reply_text(f"📋 *Your report for {date}:*\n\n{report['content']}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("📭 No report submitted today. Use /report to submit.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date = today_str()
    users = db.get_active_users()
    reports = db.get_reports_for_date(date)
    submitted_ids = {r["user_id"] for r in reports}

    done = []
    pending = []
    for u in users:
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
    lines.append(f"\n📈 Completion: {len(done)}/{len(users)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    date = today_str()
    reports = db.get_reports_for_date(date)

    if not reports:
        return await update.message.reply_text(f"📭 No reports for {date} yet.")

    lines = [f"📋 *Report Summary — {date}*\n"]
    for r in reports:
        name = r["display_name"] or r["username"] or str(r["user_id"])
        lines.append(f"*{name}:*\n{r['content']}\n")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Admin only.")

    count = await send_reminders(ctx, round_num=0)
    await update.message.reply_text(f"📤 Sent reminders to {count} user(s).")


# ──────────────────────── Message handler ────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state not in ("awaiting_report", "awaiting_update"):
        return  # ignore random messages

    user = update.effective_user
    date = today_str()
    content = update.message.text
    name = display_name(user)

    if state == "awaiting_report":
        report_id = db.save_report(user.id, date, content, update.message.message_id)
        if report_id is None:
            ctx.user_data["state"] = None
            return await update.message.reply_text(
                "⚠️ You already submitted today. Use /update to modify."
            )
    else:  # awaiting_update
        old_channel_msg_id = db.update_report(user.id, date, content)
        report_id = None
        # try to delete old channel message
        if old_channel_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=config.CHANNEL_ID, message_id=old_channel_msg_id)
            except Exception:
                pass

    ctx.user_data["state"] = None

    # ── Forward to channel ──
    channel_text = (
        f"📋 *Daily Report — {date}*\n"
        f"👤 *{name}*\n"
        f"{'─' * 24}\n\n"
        f"{content}\n\n"
        f"{'─' * 24}\n"
        f"🕐 Submitted at {now_str()}"
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
            # update case: store new channel message id
            conn = db.get_conn()
            conn.execute(
                "UPDATE reports SET channel_message_id = ? WHERE user_id = ? AND report_date = ?",
                (channel_msg.message_id, user.id, date)
            )
            conn.commit()
            conn.close()
        tag = " and synced to channel"
    except Exception as e:
        tag = f" (channel sync failed: {e})"

    action = "updated" if state == "awaiting_update" else "submitted"
    await update.message.reply_text(
        f"✅ Report {action}{tag}!\n\nUse /update anytime to modify.",
    )


# ──────────────────── Inline button callback ─────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "write_report":
        date = today_str()
        existing = db.get_today_report(query.from_user.id, date)
        if existing:
            return await query.message.reply_text(
                "📋 You already submitted today. Use /update to modify."
            )
        ctx.user_data["state"] = "awaiting_report"
        await query.message.reply_text(
            f"📝 *Daily Report — {date}*\n\n"
            f"Please type your report below 👇",
            parse_mode=ParseMode.MARKDOWN
        )


# ──────────────────── Reminder logic ─────────────────────────────

async def send_reminders(ctx: ContextTypes.DEFAULT_TYPE, round_num: int = 1) -> int:
    date = today_str()
    unsubmitted = db.get_unsubmitted_users(date)

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
            "Please submit before noon 🙏"
        ),
    }

    text = messages.get(round_num, messages[0])
    count = 0

    for user in unsubmitted:
        try:
            await ctx.bot.send_message(
                chat_id=user["user_id"],
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            db.record_reminder(user["user_id"], date, round_num)
            count += 1
        except Exception as e:
            print(f"[Reminder] Failed for {user['user_id']}: {e}")

    return count