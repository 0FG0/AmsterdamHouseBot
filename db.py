import json
import logging
import aiosqlite
from config import DB_PATH

logger = logging.getLogger(__name__)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                source      TEXT NOT NULL,
                listing_id  TEXT NOT NULL,
                url         TEXT,
                title       TEXT,
                price       TEXT,
                scraped_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, listing_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_filters (
                chat_id       INTEGER PRIMARY KEY,
                max_price     INTEGER DEFAULT 2000,
                min_rooms     INTEGER DEFAULT 1,
                neighborhoods TEXT    DEFAULT '[]',
                active        INTEGER DEFAULT 1,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def is_seen(source: str, listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_listings WHERE source=? AND listing_id=?",
            (source, listing_id),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_seen(source: str, listing_id: str, url: str = "", title: str = "", price: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_listings (source, listing_id, url, title, price) VALUES (?,?,?,?,?)",
            (source, listing_id, url, title, price),
        )
        await db.commit()


async def save_filters(chat_id: int, max_price: int, min_rooms: int, neighborhoods: list, active: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_filters (chat_id, max_price, min_rooms, neighborhoods, active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                max_price=excluded.max_price,
                min_rooms=excluded.min_rooms,
                neighborhoods=excluded.neighborhoods,
                active=excluded.active,
                updated_at=CURRENT_TIMESTAMP
        """, (chat_id, max_price, min_rooms, json.dumps(neighborhoods), int(active)))
        await db.commit()


async def get_filters(chat_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_filters WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "chat_id": row["chat_id"],
                "max_price": row["max_price"],
                "min_rooms": row["min_rooms"],
                "neighborhoods": json.loads(row["neighborhoods"]),
                "active": bool(row["active"]),
            }


async def set_active(chat_id: int, active: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_filters SET active=? WHERE chat_id=?",
            (int(active), chat_id),
        )
        await db.commit()


async def clear_seen(source: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if source:
            await db.execute("DELETE FROM seen_listings WHERE source=?", (source,))
        else:
            await db.execute("DELETE FROM seen_listings")
        await db.commit()


async def get_all_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_filters WHERE active=1") as cur:
            rows = await cur.fetchall()
            return [
                {
                    "chat_id": row["chat_id"],
                    "max_price": row["max_price"],
                    "min_rooms": row["min_rooms"],
                    "neighborhoods": json.loads(row["neighborhoods"]),
                    "active": bool(row["active"]),
                }
                for row in rows
            ]
