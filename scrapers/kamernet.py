import asyncio
import json
import logging
import random
import re

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
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://kamernet.nl/",
}

# searchCategories: 1=house, 2=room, 4=apartment, 8=studio
_SEARCH_CATEGORIES = "1,4,8"


class KamernetScraper(BaseScraper):
    SOURCE = "kamernet"
    BASE_URL = "https://kamernet.nl"

    def _build_url(self) -> str:
        url = (
            f"{self.BASE_URL}/en/for-rent/properties-amsterdam"
            f"?searchCategories={_SEARCH_CATEGORIES}&pageNo=1"
        )
        if self.max_price:
            url += f"&maxRent={self.max_price}"
        return url

    async def scrape(self) -> list[Listing]:
        url = self._build_url()
        listings: list[Listing] = []
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                await asyncio.sleep(random.uniform(2.0, 4.0))
                resp = await client.get(url, headers=_HEADERS)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            script = soup.select_one("script#__NEXT_DATA__")
            if script and script.string:
                data = json.loads(script.string)
                listings = self._parse_next_data(data)
            if not listings:
                listings = self._parse_html_fallback(soup)
        except Exception as exc:
            logger.error("Kamernet scrape error: %s", exc)
        return listings

    def _parse_next_data(self, data: dict) -> list[Listing]:
        listings: list[Listing] = []
        try:
            page_props = data.get("props", {}).get("pageProps", {})
            results = (
                page_props.get("tiles")
                or page_props.get("listings")
                or page_props.get("searchResult", {}).get("results", [])
                or page_props.get("results")
                or []
            )
            for item in results:
                listing = self._parse_item(item)
                if listing:
                    listings.append(listing)
        except Exception as exc:
            logger.warning("Kamernet __NEXT_DATA__ parse error: %s", exc)
        return listings

    def _parse_item(self, item: dict) -> Listing | None:
        try:
            listing_id = str(item.get("id", ""))
            if not listing_id:
                return None

            url_path = (
                item.get("url")
                or item.get("urlKey")
                or item.get("detailUrl")
                or f"/en/for-rent/apartment-amsterdam/amsterdam/apartment-{listing_id}"
            )
            full_url = f"{self.BASE_URL}{url_path}" if url_path.startswith("/") else url_path

            raw_price = item.get("rentalPrice") or item.get("price") or item.get("rent") or 0
            price = f"€{int(raw_price):,}/mese" if raw_price else "Prezzo non disponibile"

            rooms = item.get("roomCount") or item.get("numberOfRooms") or item.get("rooms")
            if rooms and self.min_rooms and int(rooms) < self.min_rooms:
                return None

            area = item.get("surfaceArea") or item.get("area") or item.get("surface")
            street = item.get("street", "")
            city = item.get("city", "Amsterdam")
            title = item.get("title") or street or f"Appartamento {listing_id}"
            address = f"{street}, {city}" if street else city

            image_url = (
                item.get("imageUrl")
                or item.get("mainImageUrl")
                or item.get("image")
                or (item.get("images") or [None])[0]
            )

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=title,
                price=price,
                address=address,
                url=full_url,
                image_url=image_url,
                rooms=str(rooms) if rooms else None,
                size_m2=f"{area} m²" if area else None,
            )
        except Exception as exc:
            logger.warning("Kamernet item parse error: %s", exc)
            return None

    def _parse_html_fallback(self, soup: BeautifulSoup) -> list[Listing]:
        listings: list[Listing] = []
        seen_ids: set[str] = set()
        for link in soup.select("a[href*='/en/for-rent/']"):
            try:
                href: str = link.get("href", "")
                # Only match individual listing pages (end with type-id)
                m = re.search(r"-(apartment|studio|house|room)-(\d+)$|-(apartment|studio|house|room)(\d+)$", href)
                if not m:
                    m = re.search(r"-(\d{5,})$", href)
                if not m:
                    continue
                listing_id = m.group(0).lstrip("-")
                if listing_id in seen_ids:
                    continue
                seen_ids.add(listing_id)

                full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                text = link.get_text(" ", strip=True)
                price_match = re.search(r"€\s?[\d.,]+", text)
                price = price_match.group(0) if price_match else ""

                listings.append(Listing(
                    id=listing_id,
                    source=self.SOURCE,
                    title=text[:80] or listing_id,
                    price=price,
                    address="Amsterdam",
                    url=full_url,
                ))
            except Exception:
                continue
        return listings
