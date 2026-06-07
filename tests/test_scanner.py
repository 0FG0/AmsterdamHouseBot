import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import scanner
from scrapers.base import Listing


def _filters() -> dict:
    return {
        "chat_id": 123,
        "city": "Amsterdam",
        "max_price": 2000,
        "min_bedrooms": 1,
        "min_size_m2": 0,
        "kamernet_property_type": "any",
        "active": True,
        "setup_in_progress": False,
    }


class _FakeScraper:
    def __init__(self, source: str, started: set[str], release: asyncio.Event):
        self.SOURCE = source
        self._started = started
        self._release = release

    async def scrape(self) -> list[Listing]:
        self._started.add(self.SOURCE)
        if len(self._started) == 2:
            self._release.set()
        await self._release.wait()
        return [
            Listing(
                id=f"{self.SOURCE}-1",
                source=self.SOURCE,
                title=f"{self.SOURCE} listing",
                price="EUR 1500",
                address="Amsterdam",
                url=f"https://example.test/{self.SOURCE}-1",
            )
        ]


class ScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_scan_for_user_scans_sources_concurrently_and_batches_db(self):
        started: set[str] = set()
        release = asyncio.Event()
        seen_rows = []
        sent_rows = []

        async def mark_seen_many(rows):
            seen_rows.extend(list(rows))

        async def mark_sent_many(chat_id, source, listing_ids):
            sent_rows.append((chat_id, source, list(listing_ids)))

        def build_scraper(source, user_filters):
            return _FakeScraper(source, started, release)

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", side_effect=build_scraper),
            patch("scanner.db.get_sent_listing_ids", AsyncMock(return_value=set())),
            patch("scanner.db.mark_seen_many", AsyncMock(side_effect=mark_seen_many)),
            patch("scanner.db.mark_sent_many", AsyncMock(side_effect=mark_sent_many)),
            patch("scanner._send_notification", AsyncMock(return_value=True)),
        ):
            count = await asyncio.wait_for(
                scanner.run_scan_for_user(
                    bot=object(),
                    user_filters=_filters(),
                    sources=("funda", "kamernet"),
                ),
                timeout=1,
            )

        self.assertEqual(count, 2)
        self.assertEqual(started, {"funda", "kamernet"})
        self.assertCountEqual(
            seen_rows,
            [
                ("funda", "funda-1", "https://example.test/funda-1", "funda listing", "EUR 1500"),
                (
                    "kamernet",
                    "kamernet-1",
                    "https://example.test/kamernet-1",
                    "kamernet listing",
                    "EUR 1500",
                ),
            ],
        )
        self.assertCountEqual(
            sent_rows,
            [
                (123, "funda", ["funda-1"]),
                (123, "kamernet", ["kamernet-1"]),
            ],
        )

    async def test_run_scan_for_user_skips_already_sent_listings(self):
        listing = Listing(
            id="funda-1",
            source="funda",
            title="Funda listing",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/funda-1",
        )

        class FakeScraper:
            SOURCE = "funda"

            async def scrape(self):
                return [listing]

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", return_value=FakeScraper()),
            patch("scanner.db.get_sent_listing_ids", AsyncMock(return_value={"funda-1"})),
            patch("scanner.db.mark_seen_many", AsyncMock()) as mark_seen_many,
            patch("scanner.db.mark_sent_many", AsyncMock()) as mark_sent_many,
            patch("scanner._send_notification", AsyncMock()) as send_notification,
        ):
            count = await scanner.run_scan_for_user(
                bot=object(),
                user_filters=_filters(),
                sources=("funda",),
            )

        self.assertEqual(count, 0)
        mark_seen_many.assert_awaited_once()
        mark_sent_many.assert_awaited_once()
        send_notification.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
