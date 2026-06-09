import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _parse_chat_ids(raw_value: str) -> set[int]:
    chat_ids: set[int] = set()
    for item in raw_value.replace(",", " ").split():
        try:
            chat_ids.add(int(item))
        except ValueError:
            sys.exit(f"ERRORE: TELEGRAM_ALLOWED_CHAT_IDS contiene un chat ID non valido: {item}")
    return chat_ids


def _parse_bool(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
FAST_POLL_INTERVAL_SECONDS = int(
    os.getenv(
        "FAST_POLL_INTERVAL_SECONDS",
        os.getenv("PARARIUS_POLL_INTERVAL_SECONDS", str(min(POLL_INTERVAL_SECONDS, 60))),
    )
)
PARARIUS_POLL_INTERVAL_SECONDS = FAST_POLL_INTERVAL_SECONDS
ROOFZ_POLL_INTERVAL_SECONDS = FAST_POLL_INTERVAL_SECONDS
SCRAPER_TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "45"))
PARARIUS_SCRAPER_TIMEOUT_SECONDS = int(os.getenv("PARARIUS_SCRAPER_TIMEOUT_SECONDS", "20"))
FUNDA_SCRAPER_TIMEOUT_SECONDS = int(os.getenv("FUNDA_SCRAPER_TIMEOUT_SECONDS", "25"))
FUNDA_PYFUNDA_TIMEOUT_SECONDS = int(os.getenv("FUNDA_PYFUNDA_TIMEOUT_SECONDS", "12"))
FUNDA_PYFUNDA_MAX_RETRIES = int(os.getenv("FUNDA_PYFUNDA_MAX_RETRIES", "2"))
FUNDA_PYFUNDA_RETRY_BACKOFF_SECONDS = float(
    os.getenv("FUNDA_PYFUNDA_RETRY_BACKOFF_SECONDS", "0.1")
)
FUNDA_MAX_BACKGROUND_THREADS = int(os.getenv("FUNDA_MAX_BACKGROUND_THREADS", "1"))
ROOFZ_SCRAPER_TIMEOUT_SECONDS = int(os.getenv("ROOFZ_SCRAPER_TIMEOUT_SECONDS", "90"))
ROOFZ_ENABLED = _parse_bool(os.getenv("ROOFZ_ENABLED", "true"))
VVA_MAX_PAGES_PER_SCAN = int(os.getenv("VVA_MAX_PAGES_PER_SCAN", "1"))
MAX_CONCURRENT_USERS_PER_JOB = int(os.getenv("MAX_CONCURRENT_USERS_PER_JOB", "3"))
DB_PATH = os.getenv("DB_PATH", "listings.db")
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "5000"))
TELEGRAM_ALLOWED_CHAT_IDS = _parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))

if not TELEGRAM_TOKEN:
    sys.exit("ERRORE: TELEGRAM_TOKEN non trovato. Copia .env.example in .env e inserisci il token.")
