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
        logger.info("Database initialized.")

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
    app.add_handler(CommandHandler("svuota", cmd_svuota))

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
    logger.info("Scheduled scan: %d active users.", len(users))
    for user in users:
        try:
            await run_scan_for_user(context.bot, user)
        except Exception as exc:
            logger.error("Scan error for user %s: %s", user["chat_id"], exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not await db.get_filters(chat_id):
        await db.save_filters(chat_id, max_price=2000, min_rooms=1, neighborhoods=[])

    interval_sec = config.POLL_INTERVAL_SECONDS
    interval_str = f"{interval_sec // 60} minutes" if interval_sec >= 60 else f"{interval_sec} seconds"
    await update.message.reply_text(
        "🏠 *Amsterdam House Hunter*\n\n"
        "I'll notify you as soon as I find new rental listings in Amsterdam\\!\n\n"
        "*Commands:*\n"
        "/cerca — set your filters \\(price, rooms, neighbourhood\\)\n"
        "/filtri — show active filters\n"
        "/test — search now without waiting\n"
        "/pausa — pause notifications\n"
        "/riprendi — resume notifications\n\n"
        f"I scan for new listings every *{interval_str}* on Pararius and Funda\\.\n"
        "Use /cerca to customise your search\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_filtri(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    f = await db.get_filters(chat_id)
    if not f:
        await update.message.reply_text("No filters configured. Use /cerca.")
        return

    zones = ", ".join(f["neighborhoods"]) if f["neighborhoods"] else "All Amsterdam"
    stato = "✅ Active" if f["active"] else "⏸ Paused"
    price_str = f"€{f['max_price']}/month" if f["max_price"] else "No limit"

    await update.message.reply_text(
        f"*Active filters:*\n\n"
        f"📍 Areas: {zones}\n"
        f"💶 Max rent: {price_str}\n"
        f"🛏 Min rooms: {f['min_rooms']}\n"
        f"🔔 Status: {stato}\n\n"
        "Use /cerca to update them.",
        parse_mode="Markdown",
    )


async def cmd_cerca(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Let's set up your search\\!\n\n"
        "💶 *Maximum monthly rent \\(€\\)?*\n"
        "Example: `1800` or `0` for no limit\\.\n\n"
        "Use /annulla to cancel\\.",
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
        await update.message.reply_text("Please enter a valid integer, e.g. `1500`.", parse_mode="Markdown")
        return ASK_PRICE

    await update.message.reply_text(
        "🛏 *Minimum number of rooms?*\n"
        "Example: `1`, `2`, `3`.",
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
        await update.message.reply_text("Please enter a valid integer, e.g. `2`.", parse_mode="Markdown")
        return ASK_ROOMS

    await update.message.reply_text(
        "📍 *Amsterdam neighbourhoods?*\n"
        "Enter neighbourhoods separated by commas, e.g.:\n"
        "`Jordaan, De Pijp, Centrum, Oud-West`\n\n"
        "Or type `all` for all of Amsterdam.",
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

    zones_str = ", ".join(neighborhoods) if neighborhoods else "All Amsterdam"
    price_str = f"€{max_price}/month" if max_price else "No limit"
    interval_sec = config.POLL_INTERVAL_SECONDS
    interval_str = f"{interval_sec // 60} minutes" if interval_sec >= 60 else f"{interval_sec} seconds"

    await update.message.reply_text(
        f"✅ *Filters saved!*\n\n"
        f"📍 Areas: {zones_str}\n"
        f"💶 Max rent: {price_str}\n"
        f"🛏 Min rooms: {min_rooms}\n\n"
        f"I'll scan for new listings every {interval_str}.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cmd_annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def cmd_pausa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.set_active(update.effective_chat.id, False)
    await update.message.reply_text("⏸ Notifications paused. Use /riprendi to resume.")


async def cmd_riprendi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.set_active(update.effective_chat.id, True)
    await update.message.reply_text("✅ Notifications resumed!")


async def cmd_svuota(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.clear_seen()
    await update.message.reply_text(
        "🗑 Listings database cleared.\n"
        "The next /test will treat all listings as new."
    )


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    f = await db.get_filters(chat_id)
    if not f:
        await update.message.reply_text("Set your filters first with /cerca.")
        return

    await update.message.reply_text("🔍 Searching for listings now...")
    count = await run_scan_for_user(context.bot, f)
    if count == 0:
        await update.message.reply_text("No new listings found at the moment.")
    else:
        await update.message.reply_text(f"✅ Found and sent {count} new listings!")
