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

    async def test_run_scan_for_user_autoreplies_to_new_kamernet_listings_when_enabled(self):
        listing = Listing(
            id="kamernet-1",
            source="kamernet",
            title="Kamernet listing",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/kamernet-1",
        )
        user_filters = {
            **_filters(),
            "kamernet_autoreply_enabled": True,
            "kamernet_autoreply_template": "Hi, I am interested in {title} in {city}.",
        }

        class FakeScraper:
            SOURCE = "kamernet"

            async def scrape(self):
                return [listing]

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", return_value=FakeScraper()),
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(return_value={"kamernet-1"}),
            ),
            patch("scanner.db.mark_sent_many", AsyncMock()),
            patch("scanner._send_notification", AsyncMock(return_value=True)),
            patch("scanner.db.get_filters", AsyncMock(return_value=user_filters)),
            patch("scanner.db.reserve_kamernet_auto_reply", AsyncMock(return_value=True)) as reserve,
            patch("scanner.db.update_kamernet_auto_reply", AsyncMock()) as update_reply,
            patch(
                "scanner.send_kamernet_autoreply",
                AsyncMock(
                    return_value=scanner.KamernetAutoReplyResult(
                        "kamernet-1",
                        "sent",
                        "Reply submitted",
                        sent=True,
                    )
                ),
            ) as send_autoreply,
        ):
            count = await scanner.run_scan_for_user(
                bot=object(),
                user_filters=user_filters,
                sources=("kamernet",),
            )

        self.assertEqual(count, 1)
        reserve.assert_awaited_once_with(
            123,
            "kamernet-1",
            "https://example.test/kamernet-1",
            "Kamernet listing",
        )
        send_autoreply.assert_awaited_once()
        sent_listing, sent_message = send_autoreply.await_args.args
        self.assertIs(sent_listing, listing)
        self.assertEqual(sent_message, "Hi, I am interested in Kamernet listing in Amsterdam.")
        update_reply.assert_awaited_once_with(123, "kamernet-1", "sent", "Reply submitted")

    async def test_run_scan_for_user_does_not_autoreply_when_notification_fails(self):
        listing = Listing(
            id="kamernet-1",
            source="kamernet",
            title="Kamernet listing",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/kamernet-1",
        )
        user_filters = {
            **_filters(),
            "kamernet_autoreply_enabled": True,
            "kamernet_autoreply_template": "Hi",
        }

        class FakeScraper:
            SOURCE = "kamernet"

            async def scrape(self):
                return [listing]

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", return_value=FakeScraper()),
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(return_value={"kamernet-1"}),
            ),
            patch("scanner.db.mark_sent_many", AsyncMock()),
            patch("scanner._send_notification", AsyncMock(return_value=False)),
            patch("scanner.db.reserve_kamernet_auto_reply", AsyncMock()) as reserve,
            patch("scanner.send_kamernet_autoreply", AsyncMock()) as send_autoreply,
        ):
            count = await scanner.run_scan_for_user(
                bot=object(),
                user_filters=user_filters,
                sources=("kamernet",),
            )

        self.assertEqual(count, 0)
        reserve.assert_not_awaited()
        send_autoreply.assert_not_awaited()

    async def test_run_scan_for_user_autoreplies_to_new_funda_listings_when_enabled(self):
        listing = Listing(
            id="funda-1",
            source="funda",
            title="Funda listing",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/funda-1",
        )
        user_filters = {
            **_filters(),
            "funda_autoreply_enabled": True,
            "funda_autoreply_template": "Hi, I am interested in {title} in {city}.",
            "funda_autoreply_email": "person@example.test",
            "funda_autoreply_first_name": "First",
            "funda_autoreply_last_name": "Last",
            "funda_autoreply_phone": "+31612345678",
        }

        class FakeScraper:
            SOURCE = "funda"

            async def scrape(self):
                return [listing]

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", return_value=FakeScraper()),
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(return_value={"funda-1"}),
            ),
            patch("scanner.db.mark_sent_many", AsyncMock()),
            patch("scanner._send_notification", AsyncMock(return_value=True)),
            patch("scanner.db.get_filters", AsyncMock(return_value=user_filters)),
            patch("scanner.db.reserve_funda_auto_reply", AsyncMock(return_value=True)) as reserve,
            patch("scanner.db.update_funda_auto_reply", AsyncMock()) as update_reply,
            patch("scanner.db.get_retryable_funda_auto_replies", AsyncMock(return_value=[])),
            patch(
                "scanner.send_funda_autoreply",
                AsyncMock(
                    return_value=scanner.FundaAutoReplyResult(
                        "funda-1",
                        "sent",
                        "Contact form submitted",
                        sent=True,
                    )
                ),
            ) as send_autoreply,
        ):
            count = await scanner.run_scan_for_user(
                bot=object(),
                user_filters=user_filters,
                sources=("funda",),
            )

        self.assertEqual(count, 1)
        reserve.assert_awaited_once_with(
            123,
            "funda-1",
            "https://example.test/funda-1",
            "Funda listing",
            "EUR 1500",
            "Amsterdam",
        )
        send_autoreply.assert_awaited_once()
        sent_listing, sent_message, sent_contact = send_autoreply.await_args.args
        self.assertIs(sent_listing, listing)
        self.assertEqual(sent_message, "Hi, I am interested in Funda listing in Amsterdam.")
        self.assertEqual(sent_contact.email, "person@example.test")
        self.assertEqual(sent_contact.first_name, "First")
        self.assertEqual(sent_contact.last_name, "Last")
        self.assertEqual(sent_contact.phone, "+31612345678")
        update_reply.assert_awaited_once_with(123, "funda-1", "sent", "Contact form submitted")

    async def test_run_scan_for_user_sends_funda_manual_review_when_enabled(self):
        listing = Listing(
            id="funda-manual",
            source="funda",
            title="Funda manual",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/funda-manual",
        )
        user_filters = {
            **_filters(),
            "funda_autoreply_enabled": True,
            "funda_autoreply_manual_approval": True,
            "funda_autoreply_template": "Hi about {title}.",
            "funda_autoreply_email": "person@example.test",
            "funda_autoreply_first_name": "First",
            "funda_autoreply_last_name": "Last",
            "funda_autoreply_phone": "+31612345678",
        }

        class FakeScraper:
            SOURCE = "funda"

            async def scrape(self):
                return [listing]

        fake_bot = type("FakeBot", (), {"send_message": AsyncMock()})()

        with (
            patch("scanner._scan_is_current", AsyncMock(return_value=True)),
            patch("scanner._build_scraper", return_value=FakeScraper()),
            patch(
                "scanner.db.get_unsent_listing_ids_and_mark_seen",
                AsyncMock(return_value={"funda-manual"}),
            ),
            patch("scanner.db.mark_sent_many", AsyncMock()),
            patch("scanner._send_notification", AsyncMock(return_value=True)),
            patch("scanner.db.get_filters", AsyncMock(return_value=user_filters)),
            patch("scanner.db.reserve_funda_auto_reply", AsyncMock(return_value=True)),
            patch("scanner.db.update_funda_auto_reply", AsyncMock()) as update_reply,
            patch("scanner.db.get_retryable_funda_auto_replies", AsyncMock(return_value=[])),
            patch("scanner.send_funda_autoreply", AsyncMock()) as send_autoreply,
        ):
            count = await scanner.run_scan_for_user(
                bot=fake_bot,
                user_filters=user_filters,
                sources=("funda",),
            )

        self.assertEqual(count, 1)
        send_autoreply.assert_not_awaited()
        update_reply.assert_awaited_once_with(
            123,
            "funda-manual",
            "manual_review",
            "Manual approval mode; contact form was not submitted",
        )
        fake_bot.send_message.assert_awaited_once()

    async def test_run_funda_autoreplies_retries_previous_failure(self):
        user_filters = {
            **_filters(),
            "funda_autoreply_enabled": True,
            "funda_autoreply_template": "Hi, I am interested in {title}.",
            "funda_autoreply_email": "person@example.test",
            "funda_autoreply_first_name": "First",
            "funda_autoreply_last_name": "Last",
            "funda_autoreply_phone": "+31612345678",
        }
        retry_row = {
            "listing_id": "funda-retry",
            "url": "https://example.test/funda-retry",
            "title": "Funda retry",
            "price": "EUR 1400",
            "address": "Amsterdam",
            "status": "submit_unknown",
            "error": "No confirmation",
            "attempt_count": 1,
        }

        with (
            patch("scanner.db.get_filters", AsyncMock(return_value=user_filters)),
            patch("scanner.db.get_retryable_funda_auto_replies", AsyncMock(return_value=[retry_row])) as retry_rows,
            patch("scanner.db.reserve_funda_auto_reply", AsyncMock(return_value=True)) as reserve,
            patch("scanner.db.update_funda_auto_reply", AsyncMock()) as update_reply,
            patch(
                "scanner.send_funda_autoreply",
                AsyncMock(
                    return_value=scanner.FundaAutoReplyResult(
                        "funda-retry",
                        "sent",
                        "Contact form submitted",
                        sent=True,
                    )
                ),
            ) as send_autoreply,
        ):
            await scanner._run_funda_autoreplies(
                bot=object(),
                chat_id=123,
                user_filters=user_filters,
                source="funda",
                new_listings=[],
            )

        retry_rows.assert_awaited_once_with(123, 2)
        reserve.assert_awaited_once_with(
            123,
            "funda-retry",
            "https://example.test/funda-retry",
            "Funda retry",
            "EUR 1400",
            "Amsterdam",
        )
        send_autoreply.assert_awaited_once()
        update_reply.assert_awaited_once_with(123, "funda-retry", "sent", "Contact form submitted")

    async def test_funda_dry_run_status_does_not_send_failure_notification(self):
        listing = Listing(
            id="funda-dry",
            source="funda",
            title="Funda dry run",
            price="EUR 1500",
            address="Amsterdam",
            url="https://example.test/funda-dry",
        )
        fake_bot = type("FakeBot", (), {"send_message": AsyncMock()})()

        await scanner._send_funda_autoreply_status(
            fake_bot,
            123,
            listing,
            scanner.FundaAutoReplyResult("funda-dry", "dry_run", "Dry run enabled"),
        )

        fake_bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
