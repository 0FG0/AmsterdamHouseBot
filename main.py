import logging

from bot import create_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    app = create_application()
    print("Bot avviato. Premi Ctrl+C per fermare.")
    app.run_polling(drop_pending_updates=True)
