import asyncio
from contextlib import asynccontextmanager
import json
from collections.abc import Iterable

import aiosqlite

import config
from config import DB_PATH
from scrapers.kamernet import serialize_kamernet_property_types

_DB: aiosqlite.Connection | None = None
_DB_CONNECT_LOCK = asyncio.Lock()
_DB_OPERATION_LOCK = asyncio.Lock()

async def _get_db() -> aiosqlite.Connection:
    global _DB
    if _DB is not None:
        return _DB

    async with _DB_CONNECT_LOCK:
        if _DB is None:
            _DB = await aiosqlite.connect(DB_PATH, timeout=_sqlite_timeout_seconds())
            _DB.row_factory = aiosqlite.Row
            await _configure_connection(_DB)
        return _DB


async def _configure_connection(db: aiosqlite.Connection) -> None:
    await db.execute(f"PRAGMA busy_timeout = {max(1, config.SQLITE_BUSY_TIMEOUT_MS)}")
    async with db.execute("PRAGMA journal_mode=WAL") as cur:
        await cur.fetchone()


def _sqlite_timeout_seconds() -> float:
    return max(0.001, config.SQLITE_BUSY_TIMEOUT_MS / 1000)


@asynccontextmanager
async def _db_operation():
    db = await _get_db()
    async with _DB_OPERATION_LOCK:
        yield db


async def close_db() -> None:
    global _DB
    async with _DB_CONNECT_LOCK:
        if _DB is None:
            return
        async with _DB_OPERATION_LOCK:
            await _DB.close()
            _DB = None


async def init_db():
    async with _db_operation() as db:
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
            CREATE TABLE IF NOT EXISTS sent_listings (
                chat_id     INTEGER NOT NULL,
                source      TEXT NOT NULL,
                listing_id  TEXT NOT NULL,
                sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, source, listing_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_filters (
                chat_id       INTEGER PRIMARY KEY,
                city          TEXT    DEFAULT 'Amsterdam',
                max_price     INTEGER DEFAULT 2000,
                min_rooms     INTEGER DEFAULT 1,
                min_bedrooms  INTEGER DEFAULT 1,
                min_size_m2   INTEGER DEFAULT 0,
                kamernet_property_type TEXT DEFAULT 'any',
                kamernet_autoreply_enabled INTEGER DEFAULT 0,
                kamernet_autoreply_template TEXT DEFAULT '',
                neighborhoods TEXT    DEFAULT '[]',
                active        INTEGER DEFAULT 1,
                setup_in_progress INTEGER DEFAULT 0,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS kamernet_auto_replies (
                chat_id     INTEGER NOT NULL,
                listing_id  TEXT NOT NULL,
                url         TEXT,
                title       TEXT,
                price       TEXT DEFAULT '',
                address     TEXT DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'pending',
                error       TEXT DEFAULT '',
                attempt_count INTEGER DEFAULT 0,
                last_attempt_at TIMESTAMP,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, listing_id)
            )
        """)
        await _ensure_column(db, "user_filters", "city", "TEXT DEFAULT 'Amsterdam'")
        await _ensure_column(db, "user_filters", "min_bedrooms", "INTEGER DEFAULT 1")
        await _ensure_column(db, "user_filters", "min_size_m2", "INTEGER DEFAULT 0")
        await _ensure_column(db, "user_filters", "kamernet_property_type", "TEXT DEFAULT 'any'")
        await _ensure_column(db, "user_filters", "kamernet_autoreply_enabled", "INTEGER DEFAULT 0")
        await _ensure_column(db, "user_filters", "kamernet_autoreply_template", "TEXT DEFAULT ''")
        await _ensure_column(db, "user_filters", "setup_in_progress", "INTEGER DEFAULT 0")
        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    if column not in {row[1] for row in rows}:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def mark_seen(source: str, listing_id: str, url: str = "", title: str = "", price: str = ""):
    await mark_seen_many([(source, listing_id, url, title, price)])


async def mark_seen_many(rows: Iterable[tuple[str, str, str, str, str]]) -> None:
    values = list(rows)
    if not values:
        return

    async with _db_operation() as db:
        await db.executemany(
            "INSERT OR IGNORE INTO seen_listings (source, listing_id, url, title, price) VALUES (?,?,?,?,?)",
            values,
        )
        await db.commit()


def _unique_listing_rows(rows: Iterable[tuple[str, str, str, str, str]]) -> list[tuple[str, str, str, str, str]]:
    values: list[tuple[str, str, str, str, str]] = []
    seen_ids: set[tuple[str, str]] = set()
    for source, listing_id, url, title, price in rows:
        key = (source, listing_id)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        values.append((source, listing_id, url, title, price))
    return values


async def was_sent(chat_id: int, source: str, listing_id: str) -> bool:
    async with _db_operation() as db:
        async with db.execute(
            "SELECT 1 FROM sent_listings WHERE chat_id=? AND source=? AND listing_id=?",
            (chat_id, source, listing_id),
        ) as cur:
            return await cur.fetchone() is not None


async def get_sent_listing_ids(chat_id: int, source: str, listing_ids: Iterable[str]) -> set[str]:
    ids = list(dict.fromkeys(listing_ids))
    if not ids:
        return set()

    placeholders = ",".join("?" for _ in ids)
    query = (
        "SELECT listing_id FROM sent_listings "
        f"WHERE chat_id=? AND source=? AND listing_id IN ({placeholders})"
    )
    async with _db_operation() as db:
        async with db.execute(query, (chat_id, source, *ids)) as cur:
            rows = await cur.fetchall()
            return {row[0] for row in rows}


async def get_unsent_listing_ids_and_mark_seen(
    chat_id: int,
    source: str,
    rows: Iterable[tuple[str, str, str, str, str]],
) -> set[str]:
    values = _unique_listing_rows(rows)
    if not values:
        return set()

    ids = [listing_id for _, listing_id, *_ in values]
    placeholders = ",".join("?" for _ in ids)
    query = (
        "SELECT listing_id FROM sent_listings "
        f"WHERE chat_id=? AND source=? AND listing_id IN ({placeholders})"
    )

    async with _db_operation() as db:
        async with db.execute(query, (chat_id, source, *ids)) as cur:
            sent_ids = {row[0] for row in await cur.fetchall()}

        unsent_values = [
            value
            for value in values
            if value[1] not in sent_ids
        ]
        if unsent_values:
            await db.executemany(
                "INSERT OR IGNORE INTO seen_listings (source, listing_id, url, title, price) VALUES (?,?,?,?,?)",
                unsent_values,
            )
        await db.commit()

    return {listing_id for _, listing_id, *_ in unsent_values}


async def mark_sent(chat_id: int, source: str, listing_id: str) -> None:
    await mark_sent_many(chat_id, source, [listing_id])


async def mark_sent_many(chat_id: int, source: str, listing_ids: Iterable[str]) -> None:
    ids = list(dict.fromkeys(listing_ids))
    if not ids:
        return

    async with _db_operation() as db:
        await db.executemany(
            "INSERT OR IGNORE INTO sent_listings (chat_id, source, listing_id) VALUES (?, ?, ?)",
            [(chat_id, source, listing_id) for listing_id in ids],
        )
        await db.commit()


async def save_filters(
    chat_id: int,
    max_price: int,
    min_bedrooms: int,
    min_size_m2: int = 0,
    city: str = "Amsterdam",
    kamernet_property_type: str = "any",
    active: bool = True,
):
    kamernet_property_type = serialize_kamernet_property_types(kamernet_property_type)
    async with _db_operation() as db:
        await db.execute("""
            INSERT INTO user_filters (chat_id, city, max_price, min_rooms, min_bedrooms, min_size_m2, kamernet_property_type, neighborhoods, active, setup_in_progress)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(chat_id) DO UPDATE SET
                city=excluded.city,
                max_price=excluded.max_price,
                min_rooms=excluded.min_rooms,
                min_bedrooms=excluded.min_bedrooms,
                min_size_m2=excluded.min_size_m2,
                kamernet_property_type=excluded.kamernet_property_type,
                active=excluded.active,
                setup_in_progress=0,
                updated_at=CURRENT_TIMESTAMP
        """, (
            chat_id,
            city,
            max_price,
            min_bedrooms,
            min_bedrooms,
            min_size_m2,
            kamernet_property_type,
            json.dumps([]),
            int(active),
        ))
        await db.commit()


async def get_filters(chat_id: int) -> dict | None:
    async with _db_operation() as db:
        async with db.execute("SELECT * FROM user_filters WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            min_bedrooms = row["min_bedrooms"] if row["min_bedrooms"] is not None else row["min_rooms"]
            return {
                "chat_id": row["chat_id"],
                "city": row["city"] or "Amsterdam",
                "max_price": row["max_price"],
                "min_bedrooms": min_bedrooms,
                "min_size_m2": row["min_size_m2"] or 0,
                "kamernet_property_type": serialize_kamernet_property_types(row["kamernet_property_type"]),
                "kamernet_autoreply_enabled": bool(row["kamernet_autoreply_enabled"]),
                "kamernet_autoreply_template": row["kamernet_autoreply_template"] or "",
                "active": bool(row["active"]),
                "setup_in_progress": bool(row["setup_in_progress"]),
            }


async def set_active(chat_id: int, active: bool):
    async with _db_operation() as db:
        await db.execute("""
            INSERT INTO user_filters (chat_id, active)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                active=excluded.active,
                updated_at=CURRENT_TIMESTAMP
        """, (chat_id, int(active)))
        await db.commit()


async def set_setup_in_progress(chat_id: int, setup_in_progress: bool) -> None:
    async with _db_operation() as db:
        await db.execute(
            """
            UPDATE user_filters
            SET setup_in_progress=?, updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=?
            """,
            (int(setup_in_progress), chat_id),
        )
        await db.commit()


async def set_kamernet_autoreply_enabled(chat_id: int, enabled: bool) -> None:
    async with _db_operation() as db:
        await db.execute(
            """
            INSERT INTO user_filters (chat_id, kamernet_autoreply_enabled)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                kamernet_autoreply_enabled=excluded.kamernet_autoreply_enabled,
                updated_at=CURRENT_TIMESTAMP
            """,
            (chat_id, int(enabled)),
        )
        await db.commit()


async def set_kamernet_autoreply_template(chat_id: int, template: str) -> None:
    async with _db_operation() as db:
        await db.execute(
            """
            INSERT INTO user_filters (chat_id, kamernet_autoreply_template)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                kamernet_autoreply_template=excluded.kamernet_autoreply_template,
                updated_at=CURRENT_TIMESTAMP
            """,
            (chat_id, template.strip()),
        )
        await db.commit()


async def reserve_kamernet_auto_reply(
    chat_id: int,
    listing_id: str,
    url: str = "",
    title: str = "",
) -> bool:
    async with _db_operation() as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO kamernet_auto_replies (chat_id, listing_id, url, title)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, listing_id, url, title),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_kamernet_auto_reply(
    chat_id: int,
    listing_id: str,
    status: str,
    error: str = "",
) -> None:
    async with _db_operation() as db:
        await db.execute(
            """
            UPDATE kamernet_auto_replies
            SET status=?, error=?, updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=? AND listing_id=?
            """,
            (status, error[:1000], chat_id, listing_id),
        )
        await db.commit()


async def get_kamernet_autoreply_stats(chat_id: int) -> dict[str, int]:
    async with _db_operation() as db:
        async with db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM kamernet_auto_replies
            WHERE chat_id=?
            GROUP BY status
            """,
            (chat_id,),
        ) as cur:
            rows = await cur.fetchall()
            return {row["status"]: row["count"] for row in rows}


async def clear_seen(source: str | None = None):
    async with _db_operation() as db:
        if source:
            await db.execute("DELETE FROM seen_listings WHERE source=?", (source,))
            await db.execute("DELETE FROM sent_listings WHERE source=?", (source,))
        else:
            await db.execute("DELETE FROM seen_listings")
            await db.execute("DELETE FROM sent_listings")
        await db.commit()


async def get_all_active_users() -> list[dict]:
    async with _db_operation() as db:
        async with db.execute(
            "SELECT * FROM user_filters WHERE active=1 AND setup_in_progress=0"
        ) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "chat_id": row["chat_id"],
                    "city": row["city"] or "Amsterdam",
                    "max_price": row["max_price"],
                    "min_bedrooms": row["min_bedrooms"] if row["min_bedrooms"] is not None else row["min_rooms"],
                    "min_size_m2": row["min_size_m2"] or 0,
                    "kamernet_property_type": serialize_kamernet_property_types(row["kamernet_property_type"]),
                    "kamernet_autoreply_enabled": bool(row["kamernet_autoreply_enabled"]),
                    "kamernet_autoreply_template": row["kamernet_autoreply_template"] or "",
                    "active": bool(row["active"]),
                    "setup_in_progress": bool(row["setup_in_progress"]),
                }
                for row in rows
            ]
