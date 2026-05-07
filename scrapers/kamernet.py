import asyncio
import json
import logging
import random
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, Listing, parse_euro_amount, parse_first_int

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
_SEARCH_CATEGORIES = "1,2,4,8"


class KamernetScraper(BaseScraper):
    SOURCE = "kamernet"
    BASE_URL = "https://kamernet.nl"

    def _build_url(self) -> str:
        city_slug = self.city.lower().replace(" ", "-")
        url = (
            f"{self.BASE_URL}/en/for-rent/properties-{city_slug}"
            f"?searchCategories={_SEARCH_CATEGORIES}&pageNo=1"
        )
        if self.max_price:
            url += f"&maxRent={self.max_price}"
        if self.min_size_m2:
            url += f"&minSize={self.min_size_m2}"
        return url

    async def scrape(self) -> list[Listing]:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                await asyncio.sleep(random.uniform(2.0, 4.0))
                response = await client.get(self._build_url(), headers=_HEADERS)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            listings = []
            next_data = soup.select_one("script#__NEXT_DATA__")
            if next_data and next_data.string:
                listings = self._parse_next_data(json.loads(next_data.string))
            if not listings:
                listings = self._parse_html_fallback(soup)

            listings = [listing for listing in listings if self._matches_filters(listing)]
            logger.info("Kamernet: found %d matching listings", len(listings))
            return listings
        except Exception as exc:
            logger.error("Kamernet scrape error: %s", exc)
            return []

    def _parse_next_data(self, data: dict) -> list[Listing]:
        page_props = data.get("props", {}).get("pageProps", {})
        results = (
            page_props.get("tiles")
            or page_props.get("listings")
            or page_props.get("searchResult", {}).get("results", [])
            or page_props.get("results")
            or []
        )
        listings = [listing for item in results if (listing := self._parse_item(item))]
        return listings

    def _parse_item(self, item: dict) -> Listing | None:
        try:
            listing_id = str(item.get("id") or item.get("listingId") or "")
            if not listing_id:
                return None

            url_path = (
                item.get("url")
                or item.get("urlKey")
                or item.get("detailUrl")
                or f"/en/for-rent/apartment-{self.city.lower()}/{self.city.lower()}/apartment-{listing_id}"
            )
            full_url = f"{self.BASE_URL}{url_path}" if url_path.startswith("/") else url_path

            price_value = item.get("rentalPrice") or item.get("price") or item.get("rent")
            price_eur = int(price_value) if isinstance(price_value, (int, float)) else parse_euro_amount(str(price_value))
            price = f"EUR {price_eur}/month" if price_eur else "Price unavailable"

            bedrooms = _first_present_int(item, "roomCount", "numberOfRooms", "rooms")
            size_value = _first_present_int(item, "surfaceArea", "area", "surface")
            street = item.get("street") or item.get("address") or ""
            city = item.get("city") or self.city
            title = item.get("title") or street or f"Kamernet listing {listing_id}"
            address = f"{street}, {city}" if street else city
            image_url = _pick_image_url(item)

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=title,
                price=price,
                address=address,
                url=full_url,
                image_url=image_url,
                rooms=f"{bedrooms} rooms" if bedrooms else None,
                size_m2=f"{size_value} m2" if size_value else None,
                price_eur=price_eur,
                bedrooms=bedrooms,
                size_m2_value=size_value,
            )
        except Exception as exc:
            logger.warning("Kamernet item parse error: %s", exc)
            return None

    def _parse_html_fallback(self, soup: BeautifulSoup) -> list[Listing]:
        listings: list[Listing] = []
        seen_ids: set[str] = set()
        for link in soup.select("a[href*='/en/for-rent/']"):
            href = link.get("href", "")
            match = re.search(r"-(\d{5,})/?$", href)
            if not match:
                continue

            listing_id = match.group(1)
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            text = link.get_text(" ", strip=True)
            price_eur = parse_euro_amount(text)
            size_value = parse_first_int(text.split("m2", 1)[0]) if "m2" in text.lower() else None
            listings.append(
                Listing(
                    id=listing_id,
                    source=self.SOURCE,
                    title=text[:80] or f"Kamernet listing {listing_id}",
                    price=f"EUR {price_eur}/month" if price_eur else "",
                    address=self.city,
                    url=full_url,
                    price_eur=price_eur,
                    size_m2=f"{size_value} m2" if size_value else None,
                    size_m2_value=size_value,
                )
            )
        return listings


def _first_present_int(item: dict, *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                parsed = parse_first_int(str(value))
                if parsed is not None:
                    return parsed
    return None


def _pick_image_url(item: dict) -> str | None:
    image = item.get("imageUrl") or item.get("mainImageUrl") or item.get("image")
    if isinstance(image, dict):
        image = image.get("url") or image.get("src")
    if image:
        return str(image)

    images = item.get("images") or []
    if not images:
        return None
    first = images[0]
    if isinstance(first, dict):
        return first.get("url") or first.get("src")
    return str(first)
