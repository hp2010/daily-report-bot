import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional, List
import pytz

import config


def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ── Create tables if not exist ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            is_active INTEGER DEFAULT 1,
            timezone TEXT DEFAULT 'Asia/Shanghai',
            first_reminder TEXT DEFAULT '10:00',
            second_reminder TEXT DEFAULT '11:00',
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scope, date, type)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ── Migrate: add missing columns to existing tables ──
    _migrate_add_column(c, "users", "timezone", "TEXT DEFAULT 'Asia/Shanghai'")
    _migrate_add_column(c, "users", "first_reminder", "TEXT DEFAULT '10:00'")
    _migrate_add_column(c, "users", "second_reminder", "TEXT DEFAULT '11:00'")
    _migrate_add_column(c, "reminders", "round", "INTEGER DEFAULT 1")

    # ── Default settings ──
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('weekends_off', '1')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('summary_time', ?)", (config.DEFAULT_SUMMARY_TIME,))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('summary_timezone', ?)", (config.SUMMARY_TIMEZONE,))

    conn.commit()
    conn.close()
    print("[DB] Initialized and migrated.")


def _migrate_add_column(cursor, table: str, column: str, col_type: str):
    """Safely add a column if it doesn't exist."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"[DB] Migrated: added {table}.{column}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # column already exists, fine
        else:
            raise


# ──────────────────── Settings ────────────────────

def get_setting(key: str, default: str = None) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ──────────────────── Users ────────────────────

def add_user(user_id: int, username: str = None, display_name: str = None,
             timezone: str = None, first_reminder: str = None, second_reminder: str = None):
    tz = timezone or config.DEFAULT_TIMEZONE
    fr = first_reminder or config.DEFAULT_FIRST_REMINDER
    sr = second_reminder or config.DEFAULT_SECOND_REMINDER
    conn = get_conn()
    conn.execute(
        """INSERT INTO users (user_id, username, display_name, is_active, timezone, first_reminder, second_reminder)
           VALUES (?, ?, ?, 1, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               username = COALESCE(excluded.username, users.username),
               display_name = COALESCE(excluded.display_name, users.display_name),
               is_active = 1,
               timezone = COALESCE(excluded.timezone, users.timezone),
               first_reminder = COALESCE(excluded.first_reminder, users.first_reminder),
               second_reminder = COALESCE(excluded.second_reminder, users.second_reminder)""",
        (user_id, username, display_name, tz, fr, sr)
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


def get_user(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def update_user_timezone(user_id: int, timezone: str):
    conn = get_conn()
    conn.execute("UPDATE users SET timezone = ? WHERE user_id = ?", (timezone, user_id))
    conn.commit()
    conn.close()


def update_user_reminders(user_id: int, first_reminder: str = None, second_reminder: str = None):
    conn = get_conn()
    if first_reminder:
        conn.execute("UPDATE users SET first_reminder = ? WHERE user_id = ?", (first_reminder, user_id))
    if second_reminder:
        conn.execute("UPDATE users SET second_reminder = ? WHERE user_id = ?", (second_reminder, user_id))
    conn.commit()
    conn.close()


# ──────────────────── Schedule overrides ────────────────────

def add_override(scope: str, date_str: str, override_type: str, note: str = None):
    """
    scope: "all" for global, or str(user_id) for per-user
    override_type: "vacation" or "duty"
    """
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO schedule_overrides (scope, date, type, note) VALUES (?, ?, ?, ?)",
        (scope, date_str, override_type, note)
    )
    conn.commit()
    conn.close()


def remove_override(scope: str, date_str: str, override_type: str):
    conn = get_conn()
    conn.execute(
        "DELETE FROM schedule_overrides WHERE scope = ? AND date = ? AND type = ?",
        (scope, date_str, override_type)
    )
    conn.commit()
    conn.close()


def get_overrides_for_date(date_str: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM schedule_overrides WHERE date = ?",
        (date_str,)
    ).fetchall()
    conn.close()
    return rows


def should_remind_user(user_id: int, date_str: str) -> bool:
    """
    Determine if a user should be reminded on a given date.

    Priority logic:
    1. Per-user "duty" override → MUST remind (even on weekends/holidays)
    2. Per-user "vacation" override → DO NOT remind
    3. Global "vacation" override (all) → DO NOT remind
    4. Weekend + weekends_off setting → DO NOT remind
    5. Otherwise → remind
    """
    overrides = get_overrides_for_date(date_str)

    user_scope = str(user_id)

    for o in overrides:
        if o["scope"] == user_scope and o["type"] == "duty":
            return True  # explicit duty, override everything

    for o in overrides:
        if o["scope"] == user_scope and o["type"] == "vacation":
            return False

    for o in overrides:
        if o["scope"] == "all" and o["type"] == "vacation":
            return False

    # Check weekend
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.weekday() in (5, 6):  # Saturday, Sunday
        weekends_off = get_setting("weekends_off", "1")
        if weekends_off == "1":
            # check if this user has a duty override (already handled above)
            return False

    return True


def get_overrides_for_month(year: int, month: int, scope: str = None) -> list:
    prefix = f"{year:04d}-{month:02d}"
    conn = get_conn()
    if scope:
        rows = conn.execute(
            "SELECT * FROM schedule_overrides WHERE date LIKE ? AND scope = ? ORDER BY date",
            (f"{prefix}%", scope)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM schedule_overrides WHERE date LIKE ? ORDER BY date",
            (f"{prefix}%",)
        ).fetchall()
    conn.close()
    return rows


# ──────────────────── Reports ────────────────────

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


def set_channel_message_id_by_user_date(user_id: int, report_date: str, channel_message_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE reports SET channel_message_id = ? WHERE user_id = ? AND report_date = ?",
        (channel_message_id, user_id, report_date)
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
    """Only active users who should be reminded and haven't submitted."""
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
    # further filter by schedule
    return [u for u in rows if should_remind_user(u["user_id"], report_date)]


def get_reports_for_date(report_date: str) -> list:
    """Only show reports from currently active users."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT r.*, u.display_name, u.username
           FROM reports r
           JOIN users u ON r.user_id = u.user_id
           WHERE r.report_date = ?
             AND u.is_active = 1
           ORDER BY r.submitted_at""",
        (report_date,)
    ).fetchall()
    conn.close()
    return rows


def get_active_expected_users(report_date: str) -> list:
    """Users who are active AND expected to report on this date (not on vacation)."""
    users = get_active_users()
    return [u for u in users if should_remind_user(u["user_id"], report_date)]