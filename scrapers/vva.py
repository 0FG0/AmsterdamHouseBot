import asyncio
import logging
import math
import re
from urllib.parse import urlencode, urljoin, urlparse

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
}

_PAGE_SIZE = 16
_MAX_PAGES = 20


class VVAScraper(BaseScraper):
    SOURCE = "vva"
    BASE_URL = "https://www.vva.amsterdam"

    def _build_url(self, skip: int = 0) -> str:
        city_slug = re.sub(r"[^a-z0-9]+", "-", self.city.lower()).strip("-")
        path = f"/woningaanbod/huur/{city_slug}" if city_slug else "/woningaanbod/huur"
        params = {
            "moveunavailablelistingstothebottom": "true",
            "orderby": "9",
            "take": str(_PAGE_SIZE),
        }
        if skip:
            params["skip"] = str(skip)
        return f"{self.BASE_URL}{path}?{urlencode(params)}"

    async def scrape(self) -> list[Listing]:
        try:
            pages = await self._fetch_pages()
            listings = self._parse_pages(pages)
            logger.info(
                "VVA: found %d matching listings from %d public pages",
                len(listings),
                len(pages),
            )
            return listings
        except Exception as exc:
            logger.error("VVA scrape error: %s", exc)
            return []

    async def _fetch_pages(self) -> list[tuple[str, str]]:
        first_url = self._build_url()
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            first_html = await self._fetch_page(client, first_url)
            page_urls = self._page_urls_from_html(first_html)
            rest_urls = page_urls[1:]

            tasks = [
                asyncio.create_task(self._fetch_page(client, url))
                for url in rest_urls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        pages = [(first_url, first_html)]
        for url, result in zip(rest_urls, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("VVA page failed from %s: %s", url, result)
                continue
            pages.append((url, result))
        return pages

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url, headers=_HEADERS)
        response.raise_for_status()
        logger.info("VVA page fetched from %s", url)
        return response.text

    def _page_urls_from_html(self, html: str) -> list[str]:
        page_count = _page_count_from_html(html)
        return [
            self._build_url(skip=page_index * _PAGE_SIZE)
            for page_index in range(page_count)
        ]

    def _parse_pages(self, pages: list[tuple[str, str]]) -> list[Listing]:
        listings: list[Listing] = []
        seen_ids: set[str] = set()
        raw_counts: dict[str, int] = {}

        for url, html in pages:
            page_listings = self._parse_html(html)
            raw_counts[url] = len(page_listings)
            for listing in page_listings:
                if listing.id in seen_ids:
                    continue
                if not self._matches_city(listing):
                    continue
                if not self._matches_filters(listing):
                    continue
                seen_ids.add(listing.id)
                listings.append(listing)

        logger.info("VVA raw listings by page: %s", raw_counts)
        return listings

    def _parse_html(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        listings: list[Listing] = []
        seen_ids: set[str] = set()

        for article in _article_candidates(soup):
            listing = self._parse_article(article)
            if not listing or listing.id in seen_ids:
                continue
            seen_ids.add(listing.id)
            listings.append(listing)
        return listings

    def _parse_article(self, article) -> Listing | None:
        try:
            link_tag = _find_listing_link(article)
            if not link_tag:
                return None

            full_url = _canonical_listing_url(
                urljoin(self.BASE_URL, link_tag.get("href", ""))
            )
            listing_id = _listing_id_from_url(full_url)
            if not listing_id:
                return None

            street = _text(article.select_one(".object__address .street"))
            zipcode = _text(article.select_one(".object__address .zipcode"))
            locality = _text(article.select_one(".object__address .locality"))
            address_parts = [street, " ".join(part for part in (zipcode, locality) if part)]
            address = ", ".join(part for part in address_parts if part) or self.city

            price = _text(article.select_one(".object__address .price, .price"))
            object_type = _text(article.select_one(".object_type .value"))
            title = street or address or object_type or f"VVA listing {listing_id}"

            rooms_count = _feature_number(article, "object_rooms", "kamers")
            bedrooms_count = _feature_number(article, "object_bed_rooms", "slaapkamers")
            size_value = _feature_number(article, "object_sqfeet", "gebruiksoppervlakte")
            bedrooms = bedrooms_count or rooms_count

            return Listing(
                id=listing_id,
                source=self.SOURCE,
                title=title,
                price=price,
                address=address,
                url=full_url,
                image_url=_pick_image_url(article),
                rooms=_rooms_label(rooms_count, bedrooms_count),
                size_m2=f"{size_value} m2" if size_value else None,
                price_eur=parse_euro_amount(price),
                bedrooms=bedrooms,
                size_m2_value=size_value,
            )
        except Exception as exc:
            logger.warning("Failed to parse VVA article: %s", exc)
            return None

    def _matches_city(self, listing: Listing) -> bool:
        city = self.city.lower()
        searchable_text = " ".join((listing.title, listing.address, listing.url)).lower()
        return city in searchable_text


def _article_candidates(soup: BeautifulSoup) -> list:
    candidates = soup.select("article.object")
    if candidates:
        return candidates
    return [
        article
        for article in soup.select("article")
        if article.select_one("a[href*='/woningaanbod/huur/']")
    ]


def _find_listing_link(article):
    return (
        article.select_one("a.object__address-container[href]")
        or article.select_one("a[href*='/woningaanbod/huur/']")
    )


def _canonical_listing_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _listing_id_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/").lower()
    for prefix in ("woningaanbod/huur/", "en-gb/residential-listings/rent/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return path


def _feature_number(article, class_name: str, tooltip: str) -> int | None:
    for feature in article.select(".object__features-item"):
        classes = feature.get("class") or []
        feature_tooltip = _clean_text(feature.get("data-bs-title", "")).lower()
        if class_name not in classes and feature_tooltip != tooltip:
            continue

        number = _text(feature.select_one(".number")) or _text(feature)
        return parse_first_int(number)
    return None


def _rooms_label(rooms_count: int | None, bedrooms_count: int | None) -> str | None:
    if rooms_count and bedrooms_count and rooms_count != bedrooms_count:
        return f"{_count_label(rooms_count, 'room')}, {_count_label(bedrooms_count, 'bedroom')}"
    if bedrooms_count:
        return _count_label(bedrooms_count, "bedroom")
    if rooms_count:
        return _count_label(rooms_count, "room")
    return None


def _count_label(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _pick_image_url(article) -> str | None:
    image = article.select_one("img[data-src], img[src], img[data-srcset], img[srcset]")
    if not image:
        return None

    image_url = (
        image.get("data-src")
        or image.get("src")
        or _first_srcset_url(image.get("data-srcset"))
        or _first_srcset_url(image.get("srcset"))
    )
    if not image_url:
        return None
    if image_url.startswith("//"):
        return f"https:{image_url}"
    return urljoin(VVAScraper.BASE_URL, image_url)


def _first_srcset_url(srcset: str | None) -> str | None:
    if not srcset:
        return None
    first_candidate = srcset.split(",", 1)[0].strip()
    return first_candidate.split(" ", 1)[0] if first_candidate else None


def _page_count_from_html(html: str) -> int:
    total_count = _total_count_from_html(html)
    if total_count is not None:
        return max(1, min(_MAX_PAGES, math.ceil(total_count / _PAGE_SIZE)))

    soup = BeautifulSoup(html, "lxml")
    page_numbers = [
        page_number
        for link in soup.select(".sys_paging[pagenumber]")
        if (page_number := parse_first_int(link.get("pagenumber"))) is not None
    ]
    return max(1, min(_MAX_PAGES, max(page_numbers, default=1)))


def _total_count_from_html(html: str) -> int | None:
    match = re.search(r"totalPropertyCount\s*=\s*(\d+)", html)
    if match:
        return int(match.group(1))

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    match = re.search(r"(\d+)\s+objecten\s+gevonden", text, re.I)
    return int(match.group(1)) if match else None


def _text(tag) -> str:
    if not tag:
        return ""
    return _clean_text(tag.get_text(" ", strip=True))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
