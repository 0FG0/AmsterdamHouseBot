import asyncio
import logging
import random
import re

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class RoofzScraper(BaseScraper):
    SOURCE = "roofz"
    BASE_URL = "https://roofz.eu"

    def _build_url(self) -> str:
        return f"{self.BASE_URL}/huur/woningen?filter=location:amsterdam"

    async def scrape(self) -> list[Listing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Roofz: playwright non installato. Esegui: pip install playwright && playwright install chromium")
            return []

        listings: list[Listing] = []
        await asyncio.sleep(random.uniform(1.0, 3.0))
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(self._build_url(), wait_until="networkidle", timeout=30000)

                cards = page.locator("[class*='offer-card']:not([class*='__'])")
                count = await cards.count()
                logger.info("Roofz: %d card trovate", count)

                seen_slugs: set[str] = set()
                for i in range(count):
                    card = cards.nth(i)
                    listing = await self._parse_card(card)
                    if listing and listing.id not in seen_slugs:
                        seen_slugs.add(listing.id)
                        listings.append(listing)

                await browser.close()
        except Exception as exc:
            logger.error("Roofz scrape error: %s", exc)

        logger.info("Roofz: trovati %d annunci grezzi (Amsterdam)", len(listings))
        return listings

    async def _parse_card(self, card) -> Listing | None:
        try:
            link_el = card.locator("a.offer-card__content, a[href*='/huur/woningen/']").first
            href = await link_el.get_attribute("href") or ""
            if not href:
                return None
            slug = href.strip("/").split("/")[-1]
            full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href

            title_el = card.locator(".offer-card__title, .property__title").first
            title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else slug

            address_el = card.locator(".offer-card__text > div").first
            address = (await address_el.inner_text()).strip() if await address_el.count() > 0 else ""

            price_el = card.locator(".offer-card__text b").first
            raw_price_text = (await price_el.inner_text()).strip() if await price_el.count() > 0 else ""
            price = raw_price_text if raw_price_text else "Prezzo non disponibile"

            if self.max_price and raw_price_text:
                nums = re.findall(r"[\d.]+", raw_price_text.replace(".", "").replace(",", "."))
                if nums:
                    try:
                        if float(nums[0]) > self.max_price:
                            return None
                    except ValueError:
                        pass

            detail_items = await card.locator(".property__details--item").all_inner_texts()
            rooms, size_m2 = None, None
            for text in detail_items:
                text = text.strip()
                if re.search(r"m[²2]", text):
                    size_m2 = text
                elif re.match(r"^\d+$", text):
                    if not rooms:
                        rooms = f"{text} kamers"

            if rooms and self.min_rooms:
                try:
                    if int(rooms.split()[0]) < self.min_rooms:
                        return None
                except (ValueError, IndexError):
                    pass

            img_el = card.locator("img").first
            image_url = await img_el.get_attribute("src") if await img_el.count() > 0 else None

            return Listing(
                id=slug,
                source=self.SOURCE,
                title=title,
                price=price,
                address=address,
                url=full_url,
                image_url=image_url,
                rooms=rooms,
                size_m2=size_m2,
            )
        except Exception as exc:
            logger.warning("Roofz card parse error: %s", exc)
            return None
