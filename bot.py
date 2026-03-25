import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

import config
import database as db
from handlers import (
    cmd_start,
    cmd_debugtopic,
    cmd_report, cmd_yesterday, cmd_update,
    cmd_status, cmd_myreport,
    cmd_vacation, cmd_myschedule,
    cmd_adduser, cmd_removeuser, cmd_rename,
    cmd_listusers, cmd_remind, cmd_summary,
    cmd_settz, cmd_setreminders,
    cmd_adminvacation, cmd_schedule,
    cmd_setsummary, cmd_settings,
    handle_text, handle_callback,
    setup_commands,
)
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)


async def post_init(app: Application):
    await setup_commands(app)


def main():
    db.init_db()

    # ── DEBUG: verify config on startup ──
    print(f"[Config] CHANNEL_ID = {repr(config.CHANNEL_ID)}")
    print(f"[Config] TOPIC_ID = {repr(config.TOPIC_ID)}")
    print(f"[Config] get_topic_id() = {repr(config.get_topic_id())}")
    print(f"[Config] ADMIN_IDS = {config.ADMIN_IDS}")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # User commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("myreport", cmd_myreport))
    app.add_handler(CommandHandler("vacation", cmd_vacation))
    app.add_handler(CommandHandler("myschedule", cmd_myschedule))

    # Admin / debug commands
    app.add_handler(CommandHandler("debugtopic", cmd_debugtopic))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("settz", cmd_settz))
    app.add_handler(CommandHandler("setreminders", cmd_setreminders))
    app.add_handler(CommandHandler("adminvacation", cmd_adminvacation))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("setsummary", cmd_setsummary))
    app.add_handler(CommandHandler("settings", cmd_settings))

    # Callbacks & text
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text,
    ))

    setup_scheduler(app)
    logging.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()