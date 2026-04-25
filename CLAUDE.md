# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `.env.example` to `.env` and set `TELEGRAM_TOKEN`. Optional env vars: `POLL_INTERVAL_SECONDS` (default 900) and `DB_PATH` (default `listings.db`).

```bash
pip install -r requirements.txt
python main.py
```

## Architecture

The bot monitors Amsterdam rental listings from four sites and notifies Telegram users when new listings match their filters.

**Data flow:**
1. `bot.py` sets up a `job_queue.run_repeating` task that fires every `POLL_INTERVAL_SECONDS`
2. `scheduled_scan` (in `bot.py`) fetches all active users from DB and calls `run_scan_for_user` for each
3. `scanner.py:run_scan_for_user` instantiates all four scrapers with the user's filters, collects listings, deduplicates against `seen_listings` in SQLite, and sends Telegram notifications for new ones
4. `db.py` uses `aiosqlite` for async SQLite access — two tables: `seen_listings` (dedup) and `user_filters` (per-user settings)

**Scraper pattern** (`scrapers/`):
- All scrapers extend `BaseScraper` and implement `scrape() -> list[Listing]`
- Primary strategy: parse `<script id="__NEXT_DATA__">` JSON (used by Next.js sites)
- Fallback strategy: CSS selector HTML parsing
- Each scraper adds a random delay (1–5s) before the HTTP request to avoid rate limiting
- Filters by `max_price` and `min_rooms` during parsing; neighborhood filtering is stored in DB but not yet applied to scraper URL construction

**Bot commands:**
- `/cerca` — multi-step `ConversationHandler` that collects price → rooms → neighborhoods, then saves to DB
- `/test` — triggers an immediate scan for the user without waiting for the scheduled job
- `/pausa` / `/riprendi` — toggle `active` flag in `user_filters`

**Adding a new scraper:**
1. Create `scrapers/yoursite.py` extending `BaseScraper` with `SOURCE` and `BASE_URL` class attributes
2. Implement `scrape()` — follow the `__NEXT_DATA__` + HTML fallback pattern
3. Add it to the `scrapers` list in `scanner.py:run_scan_for_user`
4. Add its emoji to `_SOURCE_EMOJI` in `scanner.py`
