import asyncio
import logging
import random

from bs4 import BeautifulSoup

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    _USE_CURL = True
except ImportError:
    import httpx
    _USE_CURL = False
    logger.warning("curl_cffi non disponibile, Pararius potrebbe ricevere 403. Installa: pip install curl_cffi")

_HEADERS = {
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
}


class ParariusScraper(BaseScraper):
    SOURCE = "pararius"
    BASE_URL = "https://www.pararius.nl"

    def _build_url(self) -> str:
        price_seg = f"/0-{self.max_price}" if self.max_price else ""
        return f"{self.BASE_URL}/huurwoningen/amsterdam{price_seg}"

    async def scrape(self) -> list[Listing]:
        url = self._build_url()
        listings: list[Listing] = []
        try:
            await asyncio.sleep(random.uniform(1.0, 3.0))
            if _USE_CURL:
                async with CurlAsyncSession(impersonate="chrome124") as session:
                    resp = await session.get(url, headers=_HEADERS, timeout=30)
                    resp.raise_for_status()
                    html = resp.text
            else:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(url, headers=_HEADERS)
                    resp.raise_for_status()
                    html = resp.text

            soup = BeautifulSoup(html, "lxml")
            for article in soup.select("section.listing-search-item"):
                listing = self._parse_article(article)
                if listing:
                    listings.append(listing)

            logger.info("Pararius: trovati %d annunci grezzi", len(listings))
        except Exception as exc:
            logger.error("Pararius scrape error: %s", exc)
        return listings

    def _parse_article(self, article) -> Listing | None:
        try:
            link_tag = article.select_one("a.listing-search-item__link--title")
            if not link_tag:
                return None

            relative_url: str = link_tag.get("href", "")
            full_url = f"{self.BASE_URL}{relative_url}"
            listing_id = relative_url.strip("/").split("/")[-1]

            title_tag = article.select_one(".listing-search-item__title")
            title = (title_tag or link_tag).get_text(strip=True)

            subtitle_tag = article.select_one(".listing-search-item__sub-title")
            address = subtitle_tag.get_text(strip=True) if subtitle_tag else "Amsterdam"

            price_tag = article.select_one(".listing-search-item__price")
            price = price_tag.get_text(strip=True) if price_tag else ""

            rooms, size_m2 = None, None
            for feat in article.select(".listing-search-item__features li"):
                text = feat.get_text(strip=True)
                if "m²" in text or "m²" in text:
                    size_m2 = text
                elif "kamer" in text:
                    rooms = text

            if rooms and self.min_rooms:
                try:
                    if int(rooms.split()[0]) < self.min_rooms:
                        return None
                except (ValueError, IndexError):
                    pass

            img = article.select_one("img")
            image_url = img.get("src") if img else None

            return Listing(
                id=listing_id,
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
            logger.warning("Failed to parse Pararius article: %s", exc)
            return None
