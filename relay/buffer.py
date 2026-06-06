"""SQLite-backed message buffer with 7-day TTL for offline clients."""

import json
import time
import aiosqlite

DB_PATH = "/root/.shellchat/relay_buffer.db"
TTL_SECONDS = 7 * 24 * 3600


async def init_db(path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         TEXT PRIMARY KEY,
                pubkey     TEXT NOT NULL,
                channel    TEXT,
                kind       INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                raw        TEXT NOT NULL,
                stored_at  INTEGER NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_channel ON events(channel, created_at)")
        await db.commit()


async def store_event(event: dict, channel: str | None, path: str = DB_PATH) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?)",
            (
                event["id"],
                event["pubkey"],
                channel,
                event["kind"],
                event["created_at"],
                json.dumps(event),
                int(time.time()),
            ),
        )
        await db.commit()


async def get_events_since(channel: str, since: int, path: str = DB_PATH) -> list[dict]:
    cutoff = int(time.time()) - TTL_SECONDS
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT raw FROM events WHERE channel=? AND created_at>=? AND stored_at>=? ORDER BY created_at ASC",
            (channel, since, cutoff),
        ) as cur:
            rows = await cur.fetchall()
    return [json.loads(r[0]) for r in rows]


async def purge_expired(path: str = DB_PATH) -> int:
    cutoff = int(time.time()) - TTL_SECONDS
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("DELETE FROM events WHERE stored_at < ?", (cutoff,))
        await db.commit()
        return cur.rowcount
