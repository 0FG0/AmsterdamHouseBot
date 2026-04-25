import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import db
from scanner import run_scan_for_user

logger = logging.getLogger(__name__)

ASK_PRICE, ASK_ROOMS, ASK_NEIGHBORHOODS = range(3)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_application() -> Application:
    async def _post_init(app: Application) -> None:
        await db.init_db()
        logger.info("Database inizializzato.")

    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("filtri", cmd_filtri))
    app.add_handler(CommandHandler("pausa", cmd_pausa))
    app.add_handler(CommandHandler("riprendi", cmd_riprendi))
    app.add_handler(CommandHandler("test", cmd_test))

    cerca_conv = ConversationHandler(
        entry_points=[CommandHandler("cerca", cmd_cerca)],
        states={
            ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_price)],
            ASK_ROOMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_rooms)],
            ASK_NEIGHBORHOODS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_neighborhoods)],
        },
        fallbacks=[CommandHandler("annulla", cmd_annulla)],
    )
    app.add_handler(cerca_conv)

    app.job_queue.run_repeating(
        scheduled_scan,
        interval=config.POLL_INTERVAL_SECONDS,
        first=20,
    )

    return app


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    users = await db.get_all_active_users()
    logger.info("Scan programmato: %d utenti attivi.", len(users))
    for user in users:
        try:
            await run_scan_for_user(context.bot, user)
        except Exception as exc:
            logger.error("Errore scan utente %s: %s", user["chat_id"], exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not await db.get_filters(chat_id):
        await db.save_filters(chat_id, max_price=2000, min_rooms=1, neighborhoods=[])

    interval_min = config.POLL_INTERVAL_SECONDS // 60
    await update.message.reply_text(
        "🏠 *Casa Hunter Amsterdam*\n\n"
        "Ti avviso appena trovo nuovi annunci di affitto ad Amsterdam\\!\n\n"
        "*Comandi:*\n"
        "/cerca — imposta i filtri \\(prezzo, camere, zona\\)\n"
        "/filtri — mostra i filtri attivi\n"
        "/test — cerca subito senza aspettare\n"
        "/pausa — sospendi le notifiche\n"
        "/riprendi — riprendi le notifiche\n\n"
        f"Cerco nuovi annunci ogni *{interval_min} minuti* su Pararius e Funda\\.\n"
        "Usa /cerca per personalizzare la ricerca\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_filtri(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    f = await db.get_filters(chat_id)
    if not f:
        await update.message.reply_text("Nessun filtro configurato. Usa /cerca.")
        return

    zones = ", ".join(f["neighborhoods"]) if f["neighborhoods"] else "Tutta Amsterdam"
    stato = "✅ Attivo" if f["active"] else "⏸ In pausa"
    price_str = f"€{f['max_price']}/mese" if f["max_price"] else "Nessun limite"

    await update.message.reply_text(
        f"*Filtri attivi:*\n\n"
        f"📍 Zone: {zones}\n"
        f"💶 Max affitto: {price_str}\n"
        f"🛏 Camere min: {f['min_rooms']}\n"
        f"🔔 Stato: {stato}\n\n"
        "Usa /cerca per modificarli.",
        parse_mode="Markdown",
    )


async def cmd_cerca(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Configuriamo la ricerca\\!\n\n"
        "💶 *Affitto massimo al mese \\(€\\)?*\n"
        "Esempio: `1800` oppure `0` per nessun limite\\.\n\n"
        "Usa /annulla per uscire\\.",
        parse_mode="MarkdownV2",
    )
    return ASK_PRICE


async def recv_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text.strip())
        if price < 0:
            raise ValueError
        context.user_data["max_price"] = price
    except ValueError:
        await update.message.reply_text("Inserisci un numero intero valido, es. `1500`.", parse_mode="Markdown")
        return ASK_PRICE

    await update.message.reply_text(
        "🛏 *Numero minimo di camere?*\n"
        "Esempio: `1`, `2`, `3`.",
        parse_mode="Markdown",
    )
    return ASK_ROOMS


async def recv_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        rooms = int(update.message.text.strip())
        if rooms < 0:
            raise ValueError
        context.user_data["min_rooms"] = rooms
    except ValueError:
        await update.message.reply_text("Inserisci un numero intero valido, es. `2`.", parse_mode="Markdown")
        return ASK_ROOMS

    await update.message.reply_text(
        "📍 *Zone di Amsterdam?*\n"
        "Scrivi i quartieri separati da virgola, es:\n"
        "`Jordaan, De Pijp, Centrum, Oud-West`\n\n"
        "Oppure scrivi `tutte` per tutta Amsterdam.",
        parse_mode="Markdown",
    )
    return ASK_NEIGHBORHOODS


async def recv_neighborhoods(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if text.lower() in ("tutte", "tutti", "all", "0", ""):
        neighborhoods: list[str] = []
    else:
        neighborhoods = [n.strip() for n in text.split(",") if n.strip()]

    max_price: int = context.user_data.get("max_price", 2000)
    min_rooms: int = context.user_data.get("min_rooms", 1)
    await db.save_filters(chat_id, max_price, min_rooms, neighborhoods, active=True)

    zones_str = ", ".join(neighborhoods) if neighborhoods else "Tutta Amsterdam"
    price_str = f"€{max_price}/mese" if max_price else "Nessun limite"
    interval_min = config.POLL_INTERVAL_SECONDS // 60

    await update.message.reply_text(
        f"✅ *Filtri salvati!*\n\n"
        f"📍 Zone: {zones_str}\n"
        f"💶 Max affitto: {price_str}\n"
        f"🛏 Camere min: {min_rooms}\n\n"
        f"Cerco nuovi annunci ogni {interval_min} minuti.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cmd_annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Operazione annullata.")
    return ConversationHandler.END


async def cmd_pausa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.set_active(update.effective_chat.id, False)
    await update.message.reply_text("⏸ Notifiche sospese. Usa /riprendi per riattivarle.")


async def cmd_riprendi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.set_active(update.effective_chat.id, True)
    await update.message.reply_text("✅ Notifiche riattivate!")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    f = await db.get_filters(chat_id)
    if not f:
        await update.message.reply_text("Configura prima i filtri con /cerca.")
        return

    await update.message.reply_text("🔍 Cerco annunci adesso...")
    count = await run_scan_for_user(context.bot, f)
    if count == 0:
        await update.message.reply_text("Nessun annuncio nuovo trovato in questo momento.")
    else:
        await update.message.reply_text(f"✅ Trovati e inviati {count} nuovi annunci!")
