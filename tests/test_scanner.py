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
    async def test_vva_is_registered_as_general_source(self):
        self.assertIn(scanner.VVA_SOURCE, scanner.GENERAL_SOURCES)
        self.assertIn(scanner.VVA_SOURCE, scanner.FAST_SOURCES)

        scraper = scanner._build_scraper("vva", _filters())

        self.assertEqual(scraper.SOURCE, "vva")

    def test_fast_sources_include_every_platform(self):
        self.assertEqual(
            scanner.FAST_SOURCES,
            (
                scanner.PARARIUS_SOURCE,
                scanner.FUNDA_SOURCE,
                scanner.KAMERNET_SOURCE,
                scanner.HUURWONINGEN_SOURCE,
                scanner.VVA_SOURCE,
                scanner.ROOFZ_SOURCE,
            ),
        )

    def test_enabled_all_sources_respects_roofz_flag(self):
        with patch.object(scanner.config, "ROOFZ_ENABLED", True):
            self.assertEqual(scanner.enabled_all_sources(), scanner.FAST_SOURCES)

        with patch.object(scanner.config, "ROOFZ_ENABLED", False):
            self.assertEqual(
                scanner.enabled_all_sources(),
                (
                    scanner.PARARIUS_SOURCE,
                    scanner.FUNDA_SOURCE,
                    scanner.KAMERNET_SOURCE,
                    scanner.HUURWONINGEN_SOURCE,
                    scanner.VVA_SOURCE,
                ),
            )

    async def test_run_scan_for_user_scans_sources_concurrently_and_batches_db(self):
        started: set[str] = set()
        release = asyncio.Event()
        seen_rows = []
        sent_rows = []

        async def get_unsent_listing_ids_and_mark_seen(chat_id, source, rows):
            seen_rows.extend(list(rows))
            return {listing_id for _, listing_id, *_ in seen_rows if source in listing_id}

        async def mark_sent_many(chat_id, source, listing_ids):
            sent_rows.append((chat_id, source, list(listing_ids)))

        def build_scraper(source, user_filters):
            return _FakeScraper(source, started, release)

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", side_effect=build_scraper),
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(side_effect=get_unsent_listing_ids_and_mark_seen),
            ),
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
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(return_value=set()),
            ) as get_unsent_listing_ids_and_mark_seen,
            patch("scanner.db.mark_sent_many", AsyncMock()) as mark_sent_many,
            patch("scanner._send_notification", AsyncMock()) as send_notification,
        ):
            count = await scanner.run_scan_for_user(
                bot=object(),
                user_filters=_filters(),
                sources=("funda",),
            )

        self.assertEqual(count, 0)
        get_unsent_listing_ids_and_mark_seen.assert_awaited_once()
        mark_sent_many.assert_awaited_once()
        send_notification.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
