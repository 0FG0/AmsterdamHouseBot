import unittest
from unittest.mock import AsyncMock

from scrapers.vva import VVAScraper, _page_count_from_html


PAGE_ONE_HTML = """
<html>
  <body>
    <script>var totalPropertyCount = 34;</script>
    <article class="object">
      <div class="object__holder">
        <div class="object__image">
          <a class="swiper-slide" href="/woningaanbod/huur/amsterdam/van-speijkstraat/41-1?take=16">
            <img data-src="https://images.example/vva-1.jpg">
          </a>
        </div>
        <div class="object__data">
          <a class="object__address-container" href="/woningaanbod/huur/amsterdam/van-speijkstraat/41-1?take=16">
            <h3 class="object__address">
              <span class="street">Van Speijkstraat 41-1</span>
              <span class="address">
                <span class="zipcode">1057GK</span>
                <span class="locality">Amsterdam</span>
              </span>
              <span class="price">&euro; 1.950,- /mnd</span>
            </h3>
          </a>
          <span class="object__features">
            <span class="object__features-item object_type" data-bs-title="Objecttype">
              <span class="value">Appartement</span>
            </span>
            <span class="object__features-item object_rooms" data-bs-title="kamers">
              <span class="number">3</span>
            </span>
            <span class="object__features-item object_bed_rooms" data-bs-title="slaapkamers">
              <span class="number">2</span>
            </span>
            <span class="object__features-item object_sqfeet" data-bs-title="Gebruiksoppervlakte">
              <span class="number">60 m2</span>
            </span>
          </span>
        </div>
      </div>
    </article>
    <article class="object">
      <a class="object__address-container" href="/woningaanbod/huur/amsterdam/herengracht/193b">
        <h3 class="object__address">
          <span class="street">Herengracht 193B</span>
          <span class="address">
            <span class="zipcode">1016BE</span>
            <span class="locality">Amsterdam</span>
          </span>
          <span class="price">&euro; 4.000,- /mnd</span>
        </h3>
      </a>
      <span class="object__features">
        <span class="object__features-item object_rooms" data-bs-title="kamers">
          <span class="number">3</span>
        </span>
        <span class="object__features-item object_bed_rooms" data-bs-title="slaapkamers">
          <span class="number">2</span>
        </span>
        <span class="object__features-item object_sqfeet" data-bs-title="Gebruiksoppervlakte">
          <span class="number">100 m2</span>
        </span>
      </span>
    </article>
  </body>
</html>
"""


PAGE_TWO_HTML = """
<html>
  <body>
    <article class="object">
      <a class="object__address-container" href="/woningaanbod/huur/amsterdam/keizersgracht/138B">
        <h3 class="object__address">
          <span class="street">Keizersgracht 138B</span>
          <span class="address">
            <span class="zipcode">1015CW</span>
            <span class="locality">Amsterdam</span>
          </span>
          <span class="price">&euro; 1.800,- /mnd</span>
        </h3>
      </a>
      <span class="object__features">
        <span class="object__features-item object_rooms" data-bs-title="kamers">
          <span class="number">3</span>
        </span>
        <span class="object__features-item object_sqfeet" data-bs-title="Gebruiksoppervlakte">
          <span class="number">70 m2</span>
        </span>
      </span>
    </article>
  </body>
</html>
"""


class VVAScraperTests(unittest.IsolatedAsyncioTestCase):
    async def test_scrape_parses_vva_cards_and_applies_filters(self):
        scraper = VVAScraper(
            city="Amsterdam",
            max_price=2000,
            min_bedrooms=2,
            min_size_m2=50,
        )
        scraper._fetch_pages = AsyncMock(
            return_value=[
                ("page-1", PAGE_ONE_HTML),
                ("page-2", PAGE_TWO_HTML),
            ]
        )

        listings = await scraper.scrape()

        self.assertEqual(
            [listing.id for listing in listings],
            ["amsterdam/van-speijkstraat/41-1", "amsterdam/keizersgracht/138b"],
        )
        self.assertTrue(all(listing.source == "vva" for listing in listings))
        self.assertEqual(listings[0].title, "Van Speijkstraat 41-1")
        self.assertEqual(listings[0].address, "Van Speijkstraat 41-1, 1057GK Amsterdam")
        self.assertEqual(
            listings[0].url,
            "https://www.vva.amsterdam/woningaanbod/huur/amsterdam/van-speijkstraat/41-1",
        )
        self.assertEqual(listings[0].image_url, "https://images.example/vva-1.jpg")
        self.assertEqual(listings[0].price_eur, 1950)
        self.assertEqual(listings[0].rooms, "3 rooms, 2 bedrooms")
        self.assertEqual(listings[0].bedrooms, 2)
        self.assertEqual(listings[0].size_m2_value, 60)
        self.assertEqual(listings[1].rooms, "3 rooms")
        self.assertEqual(listings[1].bedrooms, 3)

    async def test_scrape_deduplicates_listing_ids(self):
        scraper = VVAScraper(
            city="Amsterdam",
            max_price=0,
            min_bedrooms=0,
            min_size_m2=0,
        )
        scraper._fetch_pages = AsyncMock(
            return_value=[
                ("page-1", PAGE_TWO_HTML),
                ("page-2", PAGE_TWO_HTML),
            ]
        )

        listings = await scraper.scrape()

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].id, "amsterdam/keizersgracht/138b")

    def test_page_count_uses_total_property_count_and_caps_pages(self):
        self.assertEqual(
            _page_count_from_html("<script>var totalPropertyCount = 34;</script>"),
            3,
        )
        self.assertEqual(
            _page_count_from_html("<script>var totalPropertyCount = 1000;</script>"),
            20,
        )


if __name__ == "__main__":
    unittest.main()
