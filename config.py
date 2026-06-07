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
PARARIUS_POLL_INTERVAL_SECONDS = int(
    os.getenv("PARARIUS_POLL_INTERVAL_SECONDS", str(min(POLL_INTERVAL_SECONDS, 60)))
)
ROOFZ_POLL_INTERVAL_SECONDS = int(
    os.getenv("ROOFZ_POLL_INTERVAL_SECONDS", str(max(POLL_INTERVAL_SECONDS * 5, 900)))
)
SCRAPER_TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "45"))
PARARIUS_SCRAPER_TIMEOUT_SECONDS = int(os.getenv("PARARIUS_SCRAPER_TIMEOUT_SECONDS", "20"))
ROOFZ_SCRAPER_TIMEOUT_SECONDS = int(os.getenv("ROOFZ_SCRAPER_TIMEOUT_SECONDS", "90"))
ROOFZ_ENABLED = _parse_bool(os.getenv("ROOFZ_ENABLED", "true"))
DB_PATH = os.getenv("DB_PATH", "listings.db")
TELEGRAM_ALLOWED_CHAT_IDS = _parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))

if not TELEGRAM_TOKEN:
    sys.exit("ERRORE: TELEGRAM_TOKEN non trovato. Copia .env.example in .env e inserisci il token.")
