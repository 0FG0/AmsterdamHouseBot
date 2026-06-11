import unittest
from unittest.mock import AsyncMock, patch

from scrapers.huurwoningen import HuurwoningenScraper


class HuurwoningenScraperTests(unittest.IsolatedAsyncioTestCase):
    async def test_forbidden_response_resets_shared_transport(self):
        scraper = HuurwoningenScraper(
            city="Amsterdam",
            max_price=2000,
            min_bedrooms=1,
            min_size_m2=0,
        )

        class ForbiddenResponse:
            text = ""

            def raise_for_status(self):
                raise RuntimeError("HTTP Error 403:")

        class FakeSession:
            async def get(self, *args, **kwargs):
                return ForbiddenResponse()

        with (
            patch("scrapers.huurwoningen._USE_CURL", True),
            patch("scrapers.huurwoningen.get_shared_session", AsyncMock(return_value=FakeSession())),
            patch("scrapers.huurwoningen.close_shared_session", AsyncMock()) as close_shared_session,
        ):
            listings = await scraper.scrape()

        self.assertEqual(listings, [])
        close_shared_session.assert_awaited_once_with("huurwoningen")


if __name__ == "__main__":
    unittest.main()
