import os
import tempfile
import unittest
from unittest.mock import patch

import db


class DbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path_patch = patch.object(db, "DB_PATH", os.path.join(self._tmpdir.name, "test.db"))
        self._busy_timeout_patch = patch.object(db.config, "SQLITE_BUSY_TIMEOUT_MS", 1234)
        await db.close_db()
        self._db_path_patch.start()
        self._busy_timeout_patch.start()

    async def asyncTearDown(self):
        await db.close_db()
        self._busy_timeout_patch.stop()
        self._db_path_patch.stop()
        self._tmpdir.cleanup()

    async def test_connection_uses_wal_busy_timeout_and_combined_unsent_seen_write(self):
        await db.init_db()

        async with db._db_operation() as conn:
            async with conn.execute("PRAGMA journal_mode") as cur:
                journal_mode = (await cur.fetchone())[0]
            async with conn.execute("PRAGMA busy_timeout") as cur:
                busy_timeout = (await cur.fetchone())[0]

        self.assertEqual(journal_mode.lower(), "wal")
        self.assertEqual(busy_timeout, 1234)

        rows = [
            ("funda", "1", "https://example.test/1", "One", "EUR 1000"),
            ("funda", "2", "https://example.test/2", "Two", "EUR 1200"),
            ("funda", "2", "https://example.test/2", "Two duplicate", "EUR 1200"),
        ]
        unsent_ids = await db.get_unsent_listing_ids_and_mark_seen(10, "funda", rows)

        self.assertEqual(unsent_ids, {"1", "2"})
        await db.mark_sent_many(10, "funda", ["1", "2"])

        unsent_ids = await db.get_unsent_listing_ids_and_mark_seen(
            10,
            "funda",
            rows + [("funda", "3", "https://example.test/3", "Three", "EUR 1300")],
        )

        self.assertEqual(unsent_ids, {"3"})

    async def test_kamernet_autoreply_settings_and_attempts_are_persisted(self):
        await db.init_db()
        await db.save_filters(
            chat_id=10,
            max_price=1800,
            min_bedrooms=1,
            min_size_m2=20,
            kamernet_property_type="room",
        )

        filters = await db.get_filters(10)
        self.assertFalse(filters["kamernet_autoreply_enabled"])
        self.assertEqual(filters["kamernet_autoreply_template"], "")

        await db.set_kamernet_autoreply_enabled(10, True)
        await db.set_kamernet_autoreply_template(10, "Hello from {city}")

        filters = await db.get_filters(10)
        self.assertTrue(filters["kamernet_autoreply_enabled"])
        self.assertEqual(filters["kamernet_autoreply_template"], "Hello from {city}")

        self.assertTrue(
            await db.reserve_kamernet_auto_reply(
                10,
                "kamernet-1",
                "https://example.test/kamernet-1",
                "Kamernet listing",
            )
        )
        self.assertFalse(
            await db.reserve_kamernet_auto_reply(
                10,
                "kamernet-1",
                "https://example.test/kamernet-1",
                "Kamernet listing",
            )
        )

        self.assertEqual(await db.get_kamernet_autoreply_stats(10), {"pending": 1})
        await db.update_kamernet_auto_reply(10, "kamernet-1", "sent", "")
        self.assertEqual(await db.get_kamernet_autoreply_stats(10), {"sent": 1})

if __name__ == "__main__":
    unittest.main()
