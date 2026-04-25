import logging

from telegram import Bot
from telegram.constants import ParseMode

import db
from scrapers.funda import FundaScraper
from scrapers.pararius import ParariusScraper

logger = logging.getLogger(__name__)

_SOURCE_EMOJI = {"pararius": "🟠", "funda": "🔵"}


async def run_scan_for_user(bot: Bot, user_filters: dict) -> int:
    chat_id = user_filters["chat_id"]
    scrapers = [
        ParariusScraper(
            max_price=user_filters["max_price"],
            min_rooms=user_filters["min_rooms"],
            neighborhoods=user_filters.get("neighborhoods", []),
        ),
        FundaScraper(
            max_price=user_filters["max_price"],
            min_rooms=user_filters["min_rooms"],
            neighborhoods=user_filters.get("neighborhoods", []),
        ),
    ]

    new_count = 0
    for scraper in scrapers:
        try:
            listings = await scraper.scrape()
            for listing in listings:
                if await db.is_seen(listing.source, listing.id):
                    continue
                await db.mark_seen(listing.source, listing.id, listing.url, listing.title, listing.price)
                await _send_notification(bot, chat_id, listing)
                new_count += 1
        except Exception as exc:
            logger.error("Scraper %s failed for user %s: %s", scraper.SOURCE, chat_id, exc)

    return new_count


async def _send_notification(bot: Bot, chat_id: int, listing) -> None:
    emoji = _SOURCE_EMOJI.get(listing.source, "🏠")
    source = listing.source.capitalize()

    parts = [f"*{listing.title}*", f"📍 {listing.address}", f"💶 {listing.price}"]
    if listing.rooms:
        parts.append(f"🛏 {listing.rooms}")
    if listing.size_m2:
        parts.append(f"📐 {listing.size_m2}")
    parts.append(f"\n🔗 [Vedi annuncio]({listing.url})")

    text = f"{emoji} *Nuovo su {source}!*\n\n" + "\n".join(parts)

    try:
        if listing.image_url:
            await bot.send_photo(
                chat_id=chat_id,
                photo=listing.image_url,
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )
    except Exception as exc:
        logger.warning("Photo send failed (%s), retrying as text: %s", chat_id, exc)
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as exc2:
            logger.error("Notification failed for %s: %s", chat_id, exc2)
