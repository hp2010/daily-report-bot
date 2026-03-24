import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

import config
import database as db
from handlers import (
    cmd_start,                                          # ← no cmd_register
    cmd_adduser, cmd_removeuser, cmd_rename,
    cmd_listusers,
    cmd_report, cmd_update, cmd_status, cmd_myreport,
    cmd_summary, cmd_remind,
    cmd_settz, cmd_setreminders,
    cmd_vacation, cmd_schedule,
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
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    # ← /register removed
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("myreport", cmd_myreport))

    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("settz", cmd_settz))
    app.add_handler(CommandHandler("setreminders", cmd_setreminders))
    app.add_handler(CommandHandler("vacation", cmd_vacation))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("setsummary", cmd_setsummary))
    app.add_handler(CommandHandler("settings", cmd_settings))

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