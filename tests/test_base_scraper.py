import unittest

from scrapers.base import BaseScraper, Listing, parse_euro_amount


class _ConcreteScraper(BaseScraper):
    async def scrape(self) -> list[Listing]:
        return []


class BaseScraperTests(unittest.TestCase):
    def test_max_price_rejects_listings_without_parseable_price(self):
        scraper = _ConcreteScraper(max_price=1750)
        listing = Listing(
            id="missing-price",
            source="test",
            title="Missing price",
            price="",
            address="Amsterdam",
            url="https://example.test/missing-price",
            price_eur=None,
        )

        self.assertFalse(scraper._matches_filters(listing))

    def test_parse_euro_amount_handles_real_euro_symbol(self):
        self.assertEqual(parse_euro_amount("\u20ac 2.350,- /mnd"), 2350)


if __name__ == "__main__":
    unittest.main()
