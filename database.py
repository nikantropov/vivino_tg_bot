"""Database layer for the Vivino bot."""

import aiosqlite
import os
from datetime import datetime, timezone, timedelta

from config import DB_PATH


async def init_db():
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT NULL,
                email TEXT NOT NULL UNIQUE,
                registered_at TEXT NOT NULL,
                is_banned INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                rating TEXT DEFAULT NULL,
                wine_name TEXT DEFAULT NULL,
                submitted_at TEXT NOT NULL,
                week_key TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                screenshot_id INTEGER,
                week_key TEXT NOT NULL,
                won_at TEXT NOT NULL,
                notified INTEGER DEFAULT 0,
                FOREIGN KEY (screenshot_id) REFERENCES screenshots(id)
            );

            CREATE INDEX IF NOT EXISTS idx_screenshots_week ON screenshots(week_key);
            CREATE INDEX IF NOT EXISTS idx_screenshots_email ON screenshots(email);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_screenshots_unique ON screenshots(file_unique_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_winners_week ON winners(week_key);
        """)
        await db.commit()
    print("[DB] Database initialized successfully.")


def get_current_week_key() -> str:
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_previous_week_key() -> str:
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    prev_monday = now - timedelta(days=now.weekday() + 7)
    iso = prev_monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


async def register_user(user_id, username, email):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
            row = await cursor.fetchone()
            if row and row[0] != user_id:
                return False, "Этот email уже зарегистрирован другим сотрудником."

            cursor = await db.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
            existing = await cursor.fetchone()
            if existing:
                old_email = existing[0]
                if old_email == email:
                    return False, f"Вы уже зарегистрированы с этим email: {email}"
                await db.execute("UPDATE users SET email = ?, username = ? WHERE user_id = ?",
                    (email, username, user_id))
                await db.commit()
                return True, f"Email обновлён: {email}"

            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO users (user_id, username, email, registered_at) VALUES (?, ?, ?, ?)",
                (user_id, username, email, now))
            await db.commit()
            return True, f"Вы успешно зарегистрированы!\nEmail: {email}\nТеперь отправьте скриншот с оценкой Vivino."
    except aiosqlite.IntegrityError:
        return False, "Ошибка: такой email уже существует."
    except Exception as e:
        return False, f"Ошибка базы данных: {e}"


async def is_duplicate_screenshot(user_id, file_unique_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM screenshots WHERE user_id = ? AND file_unique_id = ?",
            (user_id, file_unique_id))
        return await cursor.fetchone() is not None


async def save_screenshot(user_id, email, file_id, file_unique_id, file_path, week_key):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO screenshots (user_id, email, file_id, file_unique_id, file_path, submitted_at, week_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, email, file_id, file_unique_id, file_path, now, week_key))
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return False
    except Exception as e:
        print(f"[DB] Error saving screenshot: {e}")
        return False


async def get_user_email(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def is_user_registered(user_id):
    email = await get_user_email(user_id)
    return email is not None


async def get_week_participants(week_key):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT email, user_id, COUNT(*) as screenshot_count, MIN(submitted_at) as first_submit "
            "FROM screenshots WHERE week_key = ? GROUP BY email, user_id", (week_key,))
        rows = await cursor.fetchall()
        return [{"email": r[0], "user_id": r[1], "screenshot_count": r[2], "first_submit": r[3]} for r in rows]


async def get_week_screenshots_count(week_key):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM screenshots WHERE week_key = ?", (week_key,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def save_winner(user_id, email, week_key, screenshot_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "INSERT INTO winners (user_id, email, screenshot_id, week_key, won_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, screenshot_id, week_key, now))
        await db.commit()
        return cursor.lastrowid


async def is_winner_already_chosen(week_key):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM winners WHERE week_key = ?", (week_key,))
        row = await cursor.fetchone()
        return row is not None


async def get_all_winners():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM winners ORDER BY won_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM screenshots")
        total_screenshots = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(DISTINCT week_key) FROM screenshots")
        total_weeks = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM winners")
        total_winners = (await cursor.fetchone())[0]
        week_key = get_current_week_key()
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT email) FROM screenshots WHERE week_key = ?", (week_key,))
        this_week_participants = (await cursor.fetchone())[0]
        return {
            "total_users": total_users, "total_screenshots": total_screenshots,
            "active_weeks": total_weeks, "total_winners": total_winners,
            "this_week_participants": this_week_participants, "current_week": week_key,
        }


async def get_week_leaderboard(week_key):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT email, user_id, COUNT(*) as screenshot_count, "
            "MIN(submitted_at) as first_submit, MAX(submitted_at) as last_submit "
            "FROM screenshots WHERE week_key = ? "
            "GROUP BY email, user_id ORDER BY screenshot_count DESC", (week_key,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_participants():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT u.email, u.username, u.registered_at, "
            "COALESCE(s.total_shots, 0) as total_screenshots, "
            "COALESCE(s.weeks_active, 0) as weeks_active, w.win_count "
            "FROM users u "
            "LEFT JOIN (SELECT email, COUNT(*) as total_shots, COUNT(DISTINCT week_key) as weeks_active FROM screenshots GROUP BY email) s ON u.email = s.email "
            "LEFT JOIN (SELECT email, COUNT(*) as win_count FROM winners GROUP BY email) w ON u.email = w.email "
            "ORDER BY s.total_shots DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_screenshots():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT s.email, s.user_id, s.file_id, s.file_path, s.submitted_at, s.week_key, u.username "
            "FROM screenshots s LEFT JOIN users u ON s.user_id = u.user_id ORDER BY s.submitted_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_user_stats(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        email = row["email"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM screenshots WHERE user_id = ?", (user_id,))
        total = (await cursor.fetchone())["cnt"]

        week_key = get_current_week_key()
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM screenshots WHERE user_id = ? AND week_key = ?", (user_id, week_key))
        this_week = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(DISTINCT week_key) as cnt FROM screenshots WHERE user_id = ?", (user_id,))
        weeks_active = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM winners WHERE user_id = ?", (user_id,))
        wins = (await cursor.fetchone())["cnt"]

        cursor = await db.execute(
            "SELECT email, COUNT(*) as screenshot_count FROM screenshots WHERE week_key = ? GROUP BY email ORDER BY screenshot_count DESC", (week_key,))
        rows = await cursor.fetchall()
        rank = None
        total_participants = len(rows)
        for i, r in enumerate(rows):
            if r["email"] == email:
                rank = i + 1
                break

        return {
            "email": email, "total_screenshots": total, "this_week": this_week,
            "weeks_active": weeks_active, "wins": wins,
            "week_rank": rank, "week_participants": total_participants, "week_key": week_key,
        }


async def get_registered_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def get_screenshots_by_week(week_key):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT s.email, s.user_id, s.file_id, s.file_path, s.submitted_at, s.week_key, u.username "
            "FROM screenshots s LEFT JOIN users u ON s.user_id = u.user_id "
            "WHERE s.week_key = ? ORDER BY s.submitted_at DESC", (week_key,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
