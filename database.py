"""
Async SQLite helpers.
All tables are created here; the bot imports `Database` and calls `await db.setup()`.
"""

import aiosqlite
import json
import os
import time
import glob
from config import PRE_GRANTED_GUILD

DB_PATH          = os.path.join(os.path.dirname(__file__), "bot_data.db")
PENDING_AUTH_DIR = os.path.join(os.path.dirname(__file__), "pending_auth")


async def init_db() -> None:
    os.makedirs(PENDING_AUTH_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id        TEXT PRIMARY KEY,
                username       TEXT,
                access_token   TEXT,
                refresh_token  TEXT,
                token_expires  INTEGER,
                authorized_at  INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS user_access (
                user_id    TEXT PRIMARY KEY,
                granted_by TEXT,
                granted_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS server_access (
                server_id  TEXT PRIMARY KEY,
                granted_by TEXT,
                granted_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS farm_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_id        TEXT,
                target_server_id TEXT,
                members_added    INTEGER,
                tier             TEXT,
                farmed_at        INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS bot_config (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Pre-grant the owner's server
        await db.execute(
            "INSERT OR IGNORE INTO server_access (server_id, granted_by) VALUES (?, 'SYSTEM')",
            (str(PRE_GRANTED_GUILD),)
        )
        # Default tutorial  — build the string first, then pass as a proper 1-element tuple
        _tutorial = (
            "**📖 How to Get Members — Tutorial**\n\n"
            "**Step 1 — Get Authorized**\n"
            "Use `!lauth` and click **auth-bot**. Complete the Discord login.\n\n"
            "**Step 2 — Get a Role**\n"
            "Ask an admin to give you one of the roles below:\n"
            "• `member` — 2 members per `!farm`\n"
            "• `silver` — 10 members per `!farm`\n"
            "• `gold` — 15 members per `!farm`\n"
            "• `diamond` — 25 members per `!farm`\n"
            "• `premium` — 35 members per `!farm`\n\n"
            "**Step 3 — Whitelist Your Server**\n"
            "Ask the bot owner to run `!grantserver <your_server_id>`.\n\n"
            "**Step 4 — Farm**\n"
            "Run `!farm <server_id>` in any channel.\n\n"
            "> \u270f\ufe0f *Owner can edit this with* `!settutorial <text>`"
        )
        await db.execute(
            "INSERT OR IGNORE INTO bot_config (key, value) VALUES ('tutorial', ?)",
            (_tutorial,),
        )
        await db.commit()


# ─── Authorized users ──────────────────────────────────────────────────────

async def save_authorized_user(user_id: str, username: str,
                                access_token: str, refresh_token: str,
                                expires_in: int) -> None:
    expires_ts = int(time.time()) + expires_in
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO authorized_users (user_id, username, access_token, refresh_token, token_expires)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username,
                   access_token=excluded.access_token,
                   refresh_token=excluded.refresh_token,
                   token_expires=excluded.token_expires,
                   authorized_at=strftime('%s','now')""",
            (user_id, username, access_token, refresh_token, expires_ts)
        )
        await db.commit()


async def get_authorized_user(user_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM authorized_users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_authorized(limit: int = 100, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM authorized_users ORDER BY authorized_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def count_authorized() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM authorized_users") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def delete_authorized_user(user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM authorized_users WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


# ─── User access ───────────────────────────────────────────────────────────

async def grant_user_access(user_id: str, granted_by: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_access (user_id, granted_by) VALUES (?, ?)",
            (user_id, granted_by)
        )
        await db.commit()


async def revoke_user_access(user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM user_access WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def has_user_access(user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM user_access WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def list_user_access() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_access ORDER BY granted_at DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Server access ─────────────────────────────────────────────────────────

async def grant_server_access(server_id: str, granted_by: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO server_access (server_id, granted_by) VALUES (?, ?)",
            (server_id, granted_by)
        )
        await db.commit()


async def revoke_server_access(server_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM server_access WHERE server_id = ?", (server_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def has_server_access(server_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM server_access WHERE server_id = ?", (server_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def list_server_access() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM server_access ORDER BY granted_at DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Farm logs ─────────────────────────────────────────────────────────────

async def log_farm(farmer_id: str, target_server_id: str,
                   members_added: int, tier: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO farm_logs (farmer_id, target_server_id, members_added, tier)
               VALUES (?, ?, ?, ?)""",
            (farmer_id, target_server_id, members_added, tier)
        )
        await db.commit()


async def get_farm_stats(farmer_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*) as times, COALESCE(SUM(members_added), 0) as total
               FROM farm_logs WHERE farmer_id = ?""",
            (farmer_id,)
        ) as cur:
            row = await cur.fetchone()
            return {"times": row[0], "total": row[1]}


async def reset_farm_stats(farmer_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM farm_logs WHERE farmer_id = ?", (farmer_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def global_farm_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) as runs, COALESCE(SUM(members_added), 0) as total FROM farm_logs"
        ) as cur:
            row = await cur.fetchone()
            return {"runs": row[0], "total": row[1]}


# ─── Bot config ────────────────────────────────────────────────────────────

async def get_config(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM bot_config WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_config(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


# ─── Custom embeds ─────────────────────────────────────────────────────────

async def _ensure_embeds_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_embeds (
                name        TEXT PRIMARY KEY,
                title       TEXT,
                description TEXT,
                color       INTEGER,
                color_hex   TEXT,
                footer      TEXT
            )
        """)
        await db.commit()


async def get_custom_embed(name: str) -> dict | None:
    await _ensure_embeds_table()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM custom_embeds WHERE name = ?", (name,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_custom_embed(name: str, data: dict) -> None:
    await _ensure_embeds_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO custom_embeds (name, title, description, color, color_hex, footer)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   title=excluded.title,
                   description=excluded.description,
                   color=excluded.color,
                   color_hex=excluded.color_hex,
                   footer=excluded.footer""",
            (
                name,
                data.get("title", ""),
                data.get("description", ""),
                data.get("color", 0x5865F2),
                data.get("color_hex", "#5865F2"),
                data.get("footer", "FarmBot"),
            )
        )
        await db.commit()


# ─── Pending auth file processor ───────────────────────────────────────────

async def process_pending_auth() -> int:
    """Read JSON files dropped by the Express OAuth callback and save them."""
    processed = 0
    pattern = os.path.join(PENDING_AUTH_DIR, "*.json")
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            await save_authorized_user(
                user_id      = data["user_id"],
                username     = data["username"],
                access_token = data["access_token"],
                refresh_token= data.get("refresh_token", ""),
                expires_in   = data.get("expires_in", 604800),
            )
            os.remove(path)
            processed += 1
        except Exception:
            pass
    return processed
