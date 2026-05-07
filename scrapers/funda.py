import asyncio
import logging
import random
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import BaseScraper, Listing, parse_euro_amount, parse_first_int

logger = logging.getLogger(__name__)


class FundaScraper(BaseScraper):
    SOURCE = "funda"
    BASE_URL = "https://www.funda.nl"

    def _build_url(self) -> str:
        city = self.city.lower().replace(" ", "-")
        selected_area = quote(f'["{city}"]')
        url = f"{self.BASE_URL}/zoeken/huur?selected_area={selected_area}"
        if self.max_price:
            url += f"&price=0-{self.max_price}"
        if self.min_bedrooms:
            url += f"&rooms={self.min_bedrooms}-"
        return url

    async def scrape(self) -> list[Listing]:
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.error("Funda: camoufox is not installed. Run: python -m camoufox fetch")
            return []

        try:
            await asyncio.sleep(random.uniform(1.0, 3.0))
            async with AsyncCamoufox(headless=True, locale=("nl-NL",)) as browser:
                page = await browser.new_page()
                await page.goto(self._build_url(), wait_until="networkidle", timeout=30000)
                html = await page.content()

            soup = BeautifulSoup(html, "lxml")
            listings = [
                listing
                for address_link in soup.find_all(attrs={"data-testid": "listingDetailsAddress"})
                if (listing := self._parse_card(address_link)) and self._matches_filters(listing)
            ]
            logger.info("Funda: found %d matching listings", len(listings))
            return listings
        except Exception as exc:
            logger.error("Funda scrape error: %s", exc)
            return []

    def _parse_card(self, address_link) -> Listing | None:
        try:
            href = address_link.get("href", "")
            if not href:
                return None

            full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
            listing_id = href.strip("/").split("/")[-1]
            address = address_link.get_text(" ", strip=True)
            card = address_link.find_parent("div")
            card_root = card.find_parent("div") if card else None
            search_root = card_root or card or address_link

            price = ""
            for element in search_root.select("div.font-semibold, b, span"):
                text = element.get_text(" ", strip=True)
                if "maand" in text.lower() or "eur" in text.lower() or "€" in text:
                    price = text
                    break

            rooms, bedrooms, size_label, size_value = None, None, None, None
            for item in search_root.select("ul li"):
                text = item.get_text(" ", strip=True).replace("\xa0", " ")
                lower = text.lower()
                if "m2" in lower or "m²" in lower:
                    size_label = text
                    size_value = parse_first_int(text)
                elif "kamer" in lower or "slaapkamer" in lower or text.strip().isdigit():
                    rooms = text if not text.strip().isdigit() else f"{text} kamers"
                    bedrooms = parse_first_int(text)

            image = search_root.select_one("img[src*='funda']") or search_root.select_one("img")
            image_url = image.get("src") if image else None

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=address,
                price=price,
                address=address,
                url=full_url,
                image_url=image_url,
                rooms=rooms,
                size_m2=size_label,
                price_eur=parse_euro_amount(price),
                bedrooms=bedrooms,
                size_m2_value=size_value,
            )
        except Exception as exc:
            logger.warning("Funda card parse error: %s", exc)
            return None
