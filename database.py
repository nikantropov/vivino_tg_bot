"""Database layer for the Vivino bot — asyncpg / PostgreSQL."""

import os
import asyncpg
from datetime import datetime, timezone, timedelta, date

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool = None


async def get_pool():
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT DEFAULT NULL,
                email TEXT NOT NULL UNIQUE,
                registered_at TEXT NOT NULL,
                is_banned INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS screenshots (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                email TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                rating TEXT DEFAULT NULL,
                wine_name TEXT DEFAULT NULL,
                submitted_at TEXT NOT NULL,
                week_key TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS winners (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                email TEXT NOT NULL,
                screenshot_id INTEGER,
                week_key TEXT NOT NULL,
                won_at TEXT NOT NULL,
                notified INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_screenshots_week ON screenshots(week_key);
            CREATE INDEX IF NOT EXISTS idx_screenshots_email ON screenshots(email);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_screenshots_unique ON screenshots(file_unique_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_winners_week ON winners(week_key);
        """)
    print("[DB] Database initialized (PostgreSQL).")


def week_key_to_display(week_key: str) -> str:
    """Convert ISO week key like '2026-W27' to '07.07-13.07'."""
    try:
        year_str, week_str = week_key.split("-W")
        d = date.fromisocalendar(int(year_str), int(week_str), 1)
        sunday = d + timedelta(days=6)
        return f"{d.day:02d}.{d.month:02d}-{sunday.day:02d}.{sunday.month:02d}"
    except Exception:
        return week_key


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
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, username FROM users WHERE email = $1", email)
            if row and row["user_id"] != user_id:
                return False, "Этот email уже зарегистрирован другим сотрудником."

            existing = await conn.fetchrow(
                "SELECT email FROM users WHERE user_id = $1", user_id)
            if existing:
                if existing["email"] == email:
                    return False, f"Вы уже зарегистрированы с этим email: {email}"
                await conn.execute(
                    "UPDATE users SET email = $1, username = $2 WHERE user_id = $3",
                    email, username, user_id)
                return True, f"Email обновлён: {email}"

            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "INSERT INTO users (user_id, username, email, registered_at) VALUES ($1, $2, $3, $4)",
                user_id, username, email, now)
            return True, f"Вы успешно зарегистрированы!\nEmail: {email}\nТеперь отправьте скриншот с оценкой Vivino."
    except asyncpg.UniqueViolationError:
        return False, "Ошибка: такой email уже существует."
    except Exception as e:
        return False, f"Ошибка базы данных: {e}"


async def is_duplicate_screenshot(user_id, file_unique_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM screenshots WHERE user_id = $1 AND file_unique_id = $2",
            user_id, file_unique_id)
        return row is not None


async def save_screenshot(user_id, email, file_id, file_unique_id, file_path, week_key):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "INSERT INTO screenshots (user_id, email, file_id, file_unique_id, file_path, submitted_at, week_key) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                user_id, email, file_id, file_unique_id, file_path, now, week_key)
            return True
    except asyncpg.UniqueViolationError:
        return False
    except Exception as e:
        print(f"[DB] Error saving screenshot: {e}")
        return False


async def get_user_email(user_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT email FROM users WHERE user_id = $1", user_id)
        return row["email"] if row else None


async def is_user_registered(user_id):
    email = await get_user_email(user_id)
    return email is not None


async def get_week_participants(week_key):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT email, user_id, COUNT(*) as screenshot_count, MIN(submitted_at) as first_submit "
            "FROM screenshots WHERE week_key = $1 GROUP BY email, user_id", week_key)
        return [dict(r) for r in rows]


async def get_week_screenshots_count(week_key):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM screenshots WHERE week_key = $1", week_key)
        return row["cnt"] if row else 0


async def save_winner(user_id, email, week_key, screenshot_id=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        now = datetime.now(timezone.utc).isoformat()
        if screenshot_id:
            row = await conn.fetchrow(
                "INSERT INTO winners (user_id, email, screenshot_id, week_key, won_at) "
                "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                user_id, email, screenshot_id, week_key, now)
        else:
            row = await conn.fetchrow(
                "INSERT INTO winners (user_id, email, week_key, won_at) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                user_id, email, week_key, now)
        return row["id"] if row else None


async def is_winner_already_chosen(week_key):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM winners WHERE week_key = $1", week_key)
        return row is not None


async def get_all_winners():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM winners ORDER BY won_at DESC")
        return [dict(r) for r in rows]


async def get_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_users = (await conn.fetchval("SELECT COUNT(*) FROM users")) or 0
        total_screenshots = (await conn.fetchval("SELECT COUNT(*) FROM screenshots")) or 0
        total_weeks = (await conn.fetchval("SELECT COUNT(DISTINCT week_key) FROM screenshots")) or 0
        total_winners = (await conn.fetchval("SELECT COUNT(*) FROM winners")) or 0
        week_key = get_current_week_key()
        this_week = (await conn.fetchval(
            "SELECT COUNT(DISTINCT email) FROM screenshots WHERE week_key = $1", week_key)) or 0
        return {
            "total_users": total_users,
            "total_screenshots": total_screenshots,
            "active_weeks": total_weeks,
            "total_winners": total_winners,
            "this_week_participants": this_week,
            "current_week": week_key,
        }


async def get_week_leaderboard(week_key):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT email, user_id, COUNT(*) as screenshot_count, "
            "MIN(submitted_at) as first_submit, MAX(submitted_at) as last_submit "
            "FROM screenshots WHERE week_key = $1 "
            "GROUP BY email, user_id ORDER BY screenshot_count DESC", week_key)
        return [dict(r) for r in rows]


async def get_all_participants():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.email, u.username, u.registered_at,
                   COALESCE(s.total_shots, 0) as total_screenshots,
                   COALESCE(s.weeks_active, 0) as weeks_active,
                   COALESCE(w.win_count, 0) as win_count
            FROM users u
            LEFT JOIN (
                SELECT email, COUNT(*) as total_shots, COUNT(DISTINCT week_key) as weeks_active
                FROM screenshots GROUP BY email
            ) s ON u.email = s.email
            LEFT JOIN (
                SELECT email, COUNT(*) as win_count FROM winners GROUP BY email
            ) w ON u.email = w.email
            ORDER BY s.total_shots DESC
        """)
        return [dict(r) for r in rows]


async def get_all_screenshots():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.email, s.user_id, s.file_id, s.file_path, s.submitted_at, s.week_key,
                   u.username
            FROM screenshots s
            LEFT JOIN users u ON s.user_id = u.user_id
            ORDER BY s.submitted_at DESC
        """)
        return [dict(r) for r in rows]


async def get_user_stats(user_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT email FROM users WHERE user_id = $1", user_id)
        if not row:
            return None
        email = row["email"]

        total = (await conn.fetchval(
            "SELECT COUNT(*) FROM screenshots WHERE user_id = $1", user_id)) or 0

        week_key = get_current_week_key()
        this_week = (await conn.fetchval(
            "SELECT COUNT(*) FROM screenshots WHERE user_id = $1 AND week_key = $2",
            user_id, week_key)) or 0

        weeks_active = (await conn.fetchval(
            "SELECT COUNT(DISTINCT week_key) FROM screenshots WHERE user_id = $1", user_id)) or 0

        wins = (await conn.fetchval(
            "SELECT COUNT(*) FROM winners WHERE user_id = $1", user_id)) or 0

        rows = await conn.fetch(
            "SELECT email, COUNT(*) as screenshot_count "
            "FROM screenshots WHERE week_key = $1 GROUP BY email ORDER BY screenshot_count DESC",
            week_key)
        rank = None
        for i, r in enumerate(rows):
            if r["email"] == email:
                rank = i + 1
                break

        return {
            "email": email,
            "total_screenshots": total,
            "this_week": this_week,
            "weeks_active": weeks_active,
            "wins": wins,
            "week_rank": rank,
            "week_participants": len(rows),
            "week_key": week_key,
        }


async def get_registered_user_ids():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE is_banned = 0")
        return [r["user_id"] for r in rows]


async def get_screenshots_by_email(email):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.email, s.user_id, s.file_id, s.file_path, s.submitted_at, s.week_key,
                   u.username
            FROM screenshots s
            LEFT JOIN users u ON s.user_id = u.user_id
            WHERE s.email = $1
            ORDER BY s.submitted_at DESC
        """, email)
        return [dict(r) for r in rows]


async def get_all_emails():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT email FROM users ORDER BY email")
        return [r["email"] for r in rows]


async def get_screenshots_by_week(week_key):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.email, s.user_id, s.file_id, s.file_path, s.submitted_at, s.week_key,
                   u.username
            FROM screenshots s
            LEFT JOIN users u ON s.user_id = u.user_id
            WHERE s.week_key = $1
            ORDER BY s.submitted_at DESC
        """, week_key)
        return [dict(r) for r in rows]
