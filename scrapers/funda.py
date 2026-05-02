import asyncio
import logging
import random
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class FundaScraper(BaseScraper):
    SOURCE = "funda"
    BASE_URL = "https://www.funda.nl"

    def _build_url(self) -> str:
        area = quote('["amsterdam"]')
        url = f"{self.BASE_URL}/zoeken/huur?selected_area={area}"
        if self.max_price:
            url += f"&price=0-{self.max_price}"
        if self.min_rooms:
            url += f"&rooms={self.min_rooms}-"
        return url

    async def scrape(self) -> list[Listing]:
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.error("Funda: camoufox non installato. Esegui: pip install camoufox && python -m camoufox fetch")
            return []

        listings: list[Listing] = []
        await asyncio.sleep(random.uniform(1.0, 3.0))
        try:
            async with AsyncCamoufox(headless=True, locale=("nl-NL",)) as browser:
                page = await browser.new_page()
                await page.goto(self._build_url(), wait_until="networkidle", timeout=30000)
                html = await page.content()

            soup = BeautifulSoup(html, "lxml")
            addr_tags = soup.find_all(attrs={"data-testid": "listingDetailsAddress"})
            logger.info("Funda: %d listing trovati", len(addr_tags))

            for addr_tag in addr_tags:
                listing = self._parse_card(addr_tag)
                if listing:
                    listings.append(listing)
        except Exception as exc:
            logger.error("Funda scrape error: %s", exc)

        return listings

    def _parse_card(self, addr_tag) -> Listing | None:
        try:
            href = addr_tag.get("href", "")
            if not href:
                return None
            listing_id = href.strip("/").split("/")[-1]
            full_url = f"{self.BASE_URL}{href}"
            address = addr_tag.get_text(" ", strip=True)

            # Container immediato: h2.parent contiene prezzo e features
            card = addr_tag.parent.parent  # div con price+features

            price = ""
            for el in card.select("div.font-semibold, b"):
                txt = el.get_text(strip=True)
                if "maand" in txt or "€" in txt or "�" in txt:
                    price = txt
                    break

            if self.max_price and price:
                nums = re.findall(r"[\d.]+", price.replace(".", "").replace(",", "."))
                if nums:
                    try:
                        if float(nums[0]) > self.max_price:
                            return None
                    except ValueError:
                        pass

            items = [li.get_text(strip=True) for li in card.select("ul li")]
            rooms, size_m2 = None, None
            for item in items:
                item_clean = item.replace("\xa0", " ").strip()
                if re.search(r"\d+\s*m", item_clean):
                    size_m2 = item_clean
                elif re.match(r"^\d+$", item_clean):
                    if not rooms:
                        rooms = f"{item_clean} kamers"

            if rooms and self.min_rooms:
                try:
                    if int(rooms.split()[0]) < self.min_rooms:
                        return None
                except (ValueError, IndexError):
                    pass

            # Immagine: risali un livello in più
            card_root = addr_tag.parent.parent.parent
            img = card_root.select_one("img[src*='funda']") or card_root.select_one("img")
            image_url = img.get("src") if img else None

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=address,
                price=price,
                address=address,
                url=full_url,
                image_url=image_url,
                rooms=rooms,
                size_m2=size_m2,
            )
        except Exception as exc:
            logger.warning("Funda card parse error: %s", exc)
            return None
