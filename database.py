import sqlite3
from typing import Optional
import config


def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            report_date TEXT,
            content TEXT,
            message_id INTEGER,
            channel_message_id INTEGER,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(user_id, report_date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            remind_date TEXT,
            round INTEGER DEFAULT 1,
            reminded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, remind_date, round)
        )
    """)

    conn.commit()
    conn.close()


def add_user(user_id: int, username: str = None, display_name: str = None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO users (user_id, username, display_name, is_active)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(user_id) DO UPDATE SET
               username = excluded.username,
               display_name = excluded.display_name,
               is_active = 1""",
        (user_id, username, display_name)
    )
    conn.commit()
    conn.close()


def remove_user(user_id: int):
    conn = get_conn()
    conn.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_active_users() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()
    conn.close()
    return rows


def save_report(user_id: int, report_date: str, content: str, message_id: int) -> Optional[int]:
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO reports (user_id, report_date, content, message_id) VALUES (?, ?, ?, ?)",
            (user_id, report_date, content, message_id)
        )
        report_id = c.lastrowid
        conn.commit()
        conn.close()
        return report_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def update_report(user_id: int, report_date: str, content: str) -> Optional[int]:
    conn = get_conn()
    c = conn.cursor()
    old = c.execute(
        "SELECT id, channel_message_id FROM reports WHERE user_id = ? AND report_date = ?",
        (user_id, report_date)
    ).fetchone()
    if not old:
        conn.close()
        return None

    c.execute(
        "UPDATE reports SET content = ?, submitted_at = CURRENT_TIMESTAMP WHERE id = ?",
        (content, old["id"])
    )
    conn.commit()
    conn.close()
    return old["channel_message_id"]


def update_channel_message_id(report_id: int, channel_message_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE reports SET channel_message_id = ? WHERE id = ?",
        (channel_message_id, report_id)
    )
    conn.commit()
    conn.close()


def get_today_report(user_id: int, report_date: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? AND report_date = ?",
        (user_id, report_date)
    ).fetchone()
    conn.close()
    return row


def record_reminder(user_id: int, remind_date: str, round_num: int):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO reminders (user_id, remind_date, round) VALUES (?, ?, ?)",
        (user_id, remind_date, round_num)
    )
    conn.commit()
    conn.close()


def get_unsubmitted_users(report_date: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        """SELECT u.* FROM users u
           WHERE u.is_active = 1
           AND u.user_id NOT IN (
               SELECT user_id FROM reports WHERE report_date = ?
           )""",
        (report_date,)
    ).fetchall()
    conn.close()
    return rows


def get_reports_for_date(report_date: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        """SELECT r.*, u.display_name, u.username
           FROM reports r JOIN users u ON r.user_id = u.user_id
           WHERE r.report_date = ?
           ORDER BY r.submitted_at""",
        (report_date,)
    ).fetchall()
    conn.close()
    return rows