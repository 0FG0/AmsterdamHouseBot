import asyncio
import json
import logging
import random
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
    "Referer": "https://www.funda.nl/",
}


class FundaScraper(BaseScraper):
    SOURCE = "funda"
    BASE_URL = "https://www.funda.nl"

    def _build_url(self) -> str:
        area = quote('["amsterdam"]')
        url = f"{self.BASE_URL}/zoeken/huur?selected_area={area}"
        if self.max_price:
            url += f"&price={quote(f'0-{self.max_price}')}"
        if self.min_rooms:
            url += f"&rooms={quote(f'{self.min_rooms}-')}"
        return url

    async def scrape(self) -> list[Listing]:
        url = self._build_url()
        listings: list[Listing] = []
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                await asyncio.sleep(random.uniform(2.0, 5.0))
                resp = await client.get(url, headers=_HEADERS)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")

            # Funda uses Next.js — all data is in __NEXT_DATA__
            script = soup.select_one("script#__NEXT_DATA__")
            if script and script.string:
                data = json.loads(script.string)
                listings = self._parse_next_data(data)
            else:
                listings = self._parse_html_fallback(soup)
        except Exception as exc:
            logger.error("Funda scrape error: %s", exc)
        return listings

    # ------------------------------------------------------------------
    def _parse_next_data(self, data: dict) -> list[Listing]:
        listings: list[Listing] = []
        try:
            results = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResult", {})
                    .get("results", [])
            )
            for item in results:
                listing = self._parse_result_item(item)
                if listing:
                    listings.append(listing)
        except Exception as exc:
            logger.warning("Funda __NEXT_DATA__ parse error: %s", exc)
        return listings

    def _parse_result_item(self, item: dict) -> Listing | None:
        try:
            listing_id = str(item.get("id", ""))
            if not listing_id:
                return None

            url_key = item.get("urlKey") or item.get("url_key", "")
            full_url = f"{self.BASE_URL}/huur/{url_key}/" if url_key else self.BASE_URL

            raw_price = item.get("rentPrice") or item.get("price") or 0
            price = f"€{int(raw_price):,}/mese" if raw_price else "Prezzo non disponibile"

            rooms = item.get("numberOfRooms") or item.get("number_of_rooms")
            if rooms and self.min_rooms and int(rooms) < self.min_rooms:
                return None

            area = item.get("area") or item.get("livingArea")
            address = item.get("address", "Amsterdam")
            city = item.get("city", "Amsterdam")

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=address,
                price=price,
                address=f"{address}, {city}",
                url=full_url,
                image_url=item.get("mainPhotoUrl") or item.get("main_photo_url"),
                rooms=str(rooms) if rooms else None,
                size_m2=f"{area} m²" if area else None,
            )
        except Exception as exc:
            logger.warning("Funda item parse error: %s", exc)
            return None

    def _parse_html_fallback(self, soup: BeautifulSoup) -> list[Listing]:
        listings: list[Listing] = []
        for card in soup.select("[data-test-id='search-result-item']"):
            try:
                link = card.select_one("a[href*='/huur/']")
                if not link:
                    continue
                href: str = link.get("href", "")
                full_url = self.BASE_URL + href if href.startswith("/") else href
                listing_id = href.strip("/").split("/")[-1]
                price_el = card.select_one("[data-test-id='price-rent']")
                price = price_el.get_text(strip=True) if price_el else ""
                listings.append(Listing(
                    id=listing_id,
                    source=self.SOURCE,
                    title=link.get_text(strip=True),
                    price=price,
                    address="Amsterdam",
                    url=full_url,
                ))
            except Exception:
                continue
        return listings
