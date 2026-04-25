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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
            script = soup.select_one("script#__NEXT_DATA__")
            if script and script.string:
                data = json.loads(script.string)
                listings = self._parse_next_data(data)
            else:
                logger.warning("Funda: __NEXT_DATA__ non trovato nella pagina, uso fallback HTML")
                listings = self._parse_html_fallback(soup)

            logger.info("Funda: trovati %d annunci grezzi", len(listings))
        except Exception as exc:
            logger.error("Funda scrape error: %s", exc)
        return listings

    def _parse_next_data(self, data: dict) -> list[Listing]:
        listings: list[Listing] = []
        page_props = data.get("props", {}).get("pageProps", {})

        # Prova più percorsi noti (Funda aggiorna la struttura frequentemente)
        candidates = [
            page_props.get("searchResult", {}).get("results"),
            page_props.get("initialData", {}).get("searchResult", {}).get("results"),
            page_props.get("data", {}).get("searchResult", {}).get("results"),
            page_props.get("searchResultData", {}).get("results"),
            page_props.get("results"),
        ]

        results = next((r for r in candidates if r), None)

        if results is None:
            logger.warning(
                "Funda: nessun percorso noto trovato in __NEXT_DATA__. "
                "Chiavi di pageProps: %s",
                list(page_props.keys())[:20],
            )
            listings = self._try_dehydrated_state(data)
            if not listings:
                listings = self._parse_html_fallback(
                    BeautifulSoup("", "lxml")
                )
            return listings

        for item in results:
            listing = self._parse_result_item(item)
            if listing:
                listings.append(listing)
        return listings

    def _try_dehydrated_state(self, data: dict) -> list[Listing]:
        """Tenta di estrarre annunci da dehydratedState (React Query)."""
        listings: list[Listing] = []
        try:
            queries = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [])
            )
            for query in queries:
                pages = (
                    query.get("state", {})
                         .get("data", {})
                         .get("pages", [])
                )
                for page in pages:
                    for item in page.get("results", []) or page.get("listings", []):
                        listing = self._parse_result_item(item)
                        if listing:
                            listings.append(listing)
            if listings:
                logger.info("Funda: trovati %d annunci via dehydratedState", len(listings))
        except Exception as exc:
            logger.debug("Funda dehydratedState parse error: %s", exc)
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
