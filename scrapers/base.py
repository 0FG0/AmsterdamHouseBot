from abc import ABC, abstractmethod
from dataclasses import dataclass
import re


@dataclass
class Listing:
    id: str
    source: str
    title: str
    price: str
    address: str
    url: str
    image_url: str | None = None
    rooms: str | None = None
    size_m2: str | None = None
    price_eur: int | None = None
    bedrooms: int | None = None
    size_m2_value: int | None = None


class BaseScraper(ABC):
    SOURCE = ""
    BASE_URL = ""

    def __init__(
        self,
        city: str = "Amsterdam",
        max_price: int = 2000,
        min_bedrooms: int = 1,
        min_size_m2: int = 0,
    ):
        self.city = city.strip() or "Amsterdam"
        self.max_price = max_price
        self.min_bedrooms = min_bedrooms
        self.min_size_m2 = min_size_m2

    @abstractmethod
    async def scrape(self) -> list[Listing]:
        pass

    def _matches_filters(self, listing: Listing) -> bool:
        if self.max_price and listing.price_eur and listing.price_eur > self.max_price:
            return False
        if self.min_bedrooms and listing.bedrooms is not None and listing.bedrooms < self.min_bedrooms:
            return False
        if self.min_size_m2 and listing.size_m2_value and listing.size_m2_value < self.min_size_m2:
            return False
        return True


def parse_euro_amount(text: str | None) -> int | None:
    if not text:
        return None

    normalized = text.replace("\xa0", " ")
    patterns = (
        r"(?:€|EUR)\s*(\d[\d.,]*)",
        r"rent\s*price:?\s*(?:€|EUR)?\s*(\d[\d.,]*)",
        r"(\d[\d.,]*)\s*(?:p/m|per\s+maand|per\s+month|/month)",
    )

    match = None
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            break
    if not match:
        match = re.search(r"\d[\d.,]*", normalized)
    if not match:
        return None

    value = match.group(1) if match.lastindex else match.group(0)
    if "," in value:
        value = value.split(",", 1)[0]
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def parse_first_int(text: str | None) -> int | None:
    if not text:
        return None

    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None
