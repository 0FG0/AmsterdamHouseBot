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
    "Referer": "https://roofz.eu/",
}


class RoofzScraper(BaseScraper):
    SOURCE = "roofz"
    BASE_URL = "https://roofz.eu"

    def _build_url(self) -> str:
        return f"{self.BASE_URL}/huur/woningen"

    async def scrape(self) -> list[Listing]:
        url = self._build_url()
        listings: list[Listing] = []
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                await asyncio.sleep(random.uniform(1.0, 3.0))
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
            logger.error("Roofz scrape error: %s", exc)
        return listings

    def _parse_next_data(self, data: dict) -> list[Listing]:
        listings: list[Listing] = []
        try:
            page_props = data.get("props", {}).get("pageProps", {})
            results = (
                page_props.get("properties")
                or page_props.get("listings")
                or page_props.get("woningen")
                or page_props.get("apartments")
                or page_props.get("results")
                or []
            )
            for item in results:
                listing = self._parse_item(item)
                if listing:
                    listings.append(listing)
        except Exception as exc:
            logger.warning("Roofz __NEXT_DATA__ parse error: %s", exc)
        return listings

    def _parse_item(self, item: dict) -> Listing | None:
        try:
            slug = str(item.get("slug") or item.get("id") or "")
            if not slug:
                return None

            city = str(item.get("city") or item.get("plaats") or "")
            address = str(item.get("address") or item.get("street") or item.get("name") or slug)
            # Only show Amsterdam listings since the agency covers all of NL
            if city and "amsterdam" not in city.lower() and "amsterdam" not in address.lower():
                return None

            url_path = item.get("url") or f"/huur/woningen/{slug}"
            full_url = f"{self.BASE_URL}{url_path}" if url_path.startswith("/") else url_path

            raw_price = item.get("price") or item.get("rentalPrice") or item.get("rent") or 0
            if self.max_price and raw_price and int(raw_price) > self.max_price:
                return None
            price = f"€{int(raw_price):,}/mese" if raw_price else "Prezzo non disponibile"

            rooms = item.get("rooms") or item.get("numberOfRooms") or item.get("bedrooms")
            if rooms and self.min_rooms and int(rooms) < self.min_rooms:
                return None

            area = item.get("area") or item.get("surfaceArea") or item.get("size")
            image_url = (
                item.get("image")
                or item.get("imageUrl")
                or item.get("mainImage")
                or (item.get("images") or [None])[0]
            )

            return Listing(
                id=slug,
                source=self.SOURCE,
                title=address,
                price=price,
                address=f"{address}, {city}" if city else address,
                url=full_url,
                image_url=image_url,
                rooms=str(rooms) if rooms else None,
                size_m2=f"{area} m²" if area else None,
            )
        except Exception as exc:
            logger.warning("Roofz item parse error: %s", exc)
            return None

    def _parse_html_fallback(self, soup: BeautifulSoup) -> list[Listing]:
        listings: list[Listing] = []
        seen_slugs: set[str] = set()
        for link in soup.select("a[href*='/huur/woningen/']"):
            try:
                href: str = link.get("href", "")
                slug = href.strip("/").split("/")[-1]
                if not slug or slug in ("woningen", "") or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                text = link.get_text(" ", strip=True)
                price_match = re.search(r"€\s?[\d.,]+", text)
                price = price_match.group(0) if price_match else ""

                listings.append(Listing(
                    id=slug,
                    source=self.SOURCE,
                    title=text[:80] or slug,
                    price=price,
                    address="Amsterdam",
                    url=full_url,
                ))
            except Exception:
                continue
        return listings
