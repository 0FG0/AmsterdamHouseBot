import json
import unittest
from unittest.mock import AsyncMock, patch

from scrapers.kamernet import KamernetScraper


def _next_data_html(items: list[dict]) -> str:
    data = {
        "props": {
            "pageProps": {
                "targetPageProps": {
                    "findListingsResponse": {
                        "listings": items,
                    }
                }
            }
        }
    }
    return (
        "<html><body>"
        f"<script id=\"__NEXT_DATA__\" type=\"application/json\">{json.dumps(data)}</script>"
        "</body></html>"
    )


def _listing_item(listing_id: str, street: str, price: int = 1650) -> dict:
    return {
        "id": listing_id,
        "street": street,
        "city": "Amsterdam",
        "listingType": 4,
        "totalRentalPrice": price,
        "surfaceArea": 32,
        "url": f"/en/for-rent/studio-amsterdam/{street.lower().replace(' ', '-')}/studio-{listing_id}",
    }


class KamernetScraperTests(unittest.IsolatedAsyncioTestCase):
    def test_build_url_supports_page_number(self):
        url = KamernetScraper(city="Amsterdam")._build_url(page_no=2)

        self.assertIn("pageNo=2", url)

    async def test_fetch_pages_uses_configured_page_cap(self):
        scraper = KamernetScraper(city="Amsterdam")
        scraper._fetch_page = AsyncMock(return_value="<html></html>")

        with (
            patch("scrapers.kamernet.config.KAMERNET_MAX_PAGES_PER_SCAN", 2),
            patch("scrapers.kamernet.get_httpx_client", AsyncMock(return_value=object())),
        ):
            pages = await scraper._fetch_pages()

        self.assertEqual(len(pages), 2)
        requested_urls = [call.args[1] for call in scraper._fetch_page.await_args_list]
        self.assertTrue(any("pageNo=1" in url for url in requested_urls))
        self.assertTrue(any("pageNo=2" in url for url in requested_urls))

    async def test_scrape_reads_multiple_pages_and_deduplicates_top_ads(self):
        pinned = _listing_item("2380000", "Pinned Studio", 1400)
        target = _listing_item("2385264", "De Wittenkade", 1650)
        page_one = _next_data_html([pinned, _listing_item("2380001", "Page One", 1300)])
        page_two = _next_data_html([pinned, target])

        scraper = KamernetScraper(
            city="Amsterdam",
            max_price=2000,
            min_bedrooms=0,
            min_size_m2=0,
            property_type="studio",
        )
        scraper._fetch_pages = AsyncMock(
            return_value=[
                ("https://kamernet.test/pageNo=1", page_one),
                ("https://kamernet.test/pageNo=2", page_two),
            ]
        )

        listings = await scraper.scrape()

        self.assertEqual(
            [listing.id for listing in listings],
            ["2380000", "2380001", "2385264"],
        )
        self.assertEqual(listings[-1].title, "De Wittenkade")
        self.assertEqual(listings[-1].price_eur, 1650)


if __name__ == "__main__":
    unittest.main()
