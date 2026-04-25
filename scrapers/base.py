from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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


class BaseScraper(ABC):
    SOURCE = ""
    BASE_URL = ""

    def __init__(self, max_price: int = 2000, min_rooms: int = 1, neighborhoods: list | None = None):
        self.max_price = max_price
        self.min_rooms = min_rooms
        self.neighborhoods = neighborhoods or []

    @abstractmethod
    async def scrape(self) -> list[Listing]:
        pass
