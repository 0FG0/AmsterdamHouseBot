import asyncio
from dataclasses import dataclass
import logging
import os
import re
from typing import Any

import config
from scrapers.base import Listing

logger = logging.getLogger(__name__)

KAMERNET_BASE_URL = "https://kamernet.nl"
LOGIN_URL = f"{KAMERNET_BASE_URL}/en/login"

_BROWSER_LOCK = asyncio.Lock()
_playwright_manager: Any = None
_playwright: Any = None
_browser: Any = None
_context: Any = None
_page: Any = None


@dataclass(frozen=True)
class KamernetAutoReplyResult:
    listing_id: str
    status: str
    detail: str = ""
    sent: bool = False


async def send_kamernet_autoreply(listing: Listing, message: str) -> KamernetAutoReplyResult:
    if config.KAMERNET_AUTOREPLY_DRY_RUN:
        logger.info("Kamernet auto-reply dry run for listing %s", listing.id)
        return KamernetAutoReplyResult(listing.id, "dry_run", "Dry run enabled", sent=False)

    message = message.strip()
    if not message:
        return KamernetAutoReplyResult(listing.id, "empty_message", "Reply template is empty")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return KamernetAutoReplyResult(
            listing.id,
            "playwright_missing",
            "Playwright is not installed or Chromium is missing",
        )

    async with _BROWSER_LOCK:
        try:
            page = await _page_for_reply(async_playwright)
            return await _send_with_page(page, listing, message)
        except Exception as exc:
            logger.error("Kamernet auto-reply error for %s: %s", listing.id, exc)
            await _reset_browser(stop_playwright=True)
            return KamernetAutoReplyResult(listing.id, "error", str(exc)[:500])


async def close_browser() -> None:
    async with _BROWSER_LOCK:
        await _reset_browser(stop_playwright=True)


async def _page_for_reply(playwright_factory):
    global _playwright_manager, _playwright, _browser, _context, _page

    if _playwright is None:
        _playwright_manager = playwright_factory()
        _playwright = await _playwright_manager.start()

    if _browser is None or not _browser.is_connected():
        await _reset_browser(stop_playwright=False)
        _browser = await _playwright.chromium.launch(headless=config.KAMERNET_AUTOREPLY_HEADLESS)

    if _context is None:
        context_kwargs = {
            "viewport": {"width": 1440, "height": 1200},
            "locale": "en-US",
        }
        storage_state_path = _storage_state_path()
        if storage_state_path and os.path.exists(storage_state_path):
            context_kwargs["storage_state"] = storage_state_path
        _context = await _browser.new_context(**context_kwargs)

    if _page is None or _page.is_closed():
        _page = await _context.new_page()

    return _page


async def _reset_browser(stop_playwright: bool = False) -> None:
    global _playwright_manager, _playwright, _browser, _context, _page

    resources = (_page, _context, _browser)
    _page = None
    _context = None
    _browser = None

    for resource in resources:
        if resource is None:
            continue
        try:
            await resource.close()
        except Exception:
            pass

    if stop_playwright and _playwright_manager is not None:
        try:
            await _playwright_manager.stop()
        except Exception:
            pass
        _playwright_manager = None
        _playwright = None


async def _send_with_page(page, listing: Listing, message: str) -> KamernetAutoReplyResult:
    timeout_ms = max(5, config.KAMERNET_AUTOREPLY_TIMEOUT_SECONDS) * 1000
    await page.goto(listing.url, wait_until="domcontentloaded", timeout=timeout_ms)
    await _settle_page(page)

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return KamernetAutoReplyResult(listing.id, "captcha", "Kamernet asked for human verification")

    if _looks_logged_out(page_text):
        login_result = await _login(page)
        if login_result is not None:
            return KamernetAutoReplyResult(listing.id, login_result, "Kamernet login is required")

        await page.goto(listing.url, wait_until="domcontentloaded", timeout=timeout_ms)
        await _settle_page(page)
        page_text = await _body_text(page)

    if _contains_captcha(page_text):
        return KamernetAutoReplyResult(listing.id, "captcha", "Kamernet asked for human verification")
    if _already_replied(page_text):
        return KamernetAutoReplyResult(listing.id, "already_replied", "Listing already has a reply", sent=True)
    if _subscription_required(page_text):
        return KamernetAutoReplyResult(
            listing.id,
            "subscription_required",
            "Kamernet requires premium access before replying",
        )

    contact_button = await _find_contact_button(page)
    if contact_button is not None:
        await contact_button.click(timeout=6000)
        await _settle_page(page)

    page_text = await _body_text(page)
    if _subscription_required(page_text):
        return KamernetAutoReplyResult(
            listing.id,
            "subscription_required",
            "Kamernet requires premium access before replying",
        )

    editor = await _find_message_editor(page)
    if editor is None:
        return KamernetAutoReplyResult(
            listing.id,
            "form_not_found",
            "Could not find the Kamernet reply form",
        )

    await editor.fill(message, timeout=6000)

    send_button = await _find_send_button(page)
    if send_button is None:
        return KamernetAutoReplyResult(
            listing.id,
            "send_button_not_found",
            "Could not find the Kamernet send button",
        )

    await send_button.click(timeout=6000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return KamernetAutoReplyResult(listing.id, "captcha", "Kamernet asked for human verification")
    if _subscription_required(page_text):
        return KamernetAutoReplyResult(
            listing.id,
            "subscription_required",
            "Kamernet requires premium access before replying",
        )
    if _send_failed(page_text):
        return KamernetAutoReplyResult(listing.id, "submit_failed", "Kamernet did not accept the reply")
    if _already_replied(page_text):
        await _save_storage_state()
        return KamernetAutoReplyResult(listing.id, "sent", "Reply submitted", sent=True)

    await _save_storage_state()
    return KamernetAutoReplyResult(
        listing.id,
        "sent_unconfirmed",
        "Reply may have been submitted, but no confirmation text was detected",
        sent=True,
    )


async def _login(page) -> str | None:
    email = config.KAMERNET_AUTOREPLY_EMAIL.strip()
    password = config.KAMERNET_AUTOREPLY_PASSWORD.strip()
    if not email or not password:
        return "auth_required"

    timeout_ms = max(5, config.KAMERNET_AUTOREPLY_TIMEOUT_SECONDS) * 1000
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    await _settle_page(page)

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return "captcha"

    email_input = await _first_visible_css(
        page,
        (
            "input[type='email']",
            "input[name='email']",
            "input[id='email']",
            "input[autocomplete='email']",
        ),
    )
    password_input = await _first_visible_css(
        page,
        (
            "input[type='password']",
            "input[name='password']",
            "input[id='password']",
            "input[autocomplete='current-password']",
        ),
    )
    if email_input is None or password_input is None:
        return "login_form_not_found"

    await email_input.fill(email, timeout=6000)
    await password_input.fill(password, timeout=6000)

    login_button = await _first_visible_role(
        page,
        "button",
        re.compile(r"^(log in|login|sign in)$", re.I),
    )
    if login_button is None:
        login_button = await _first_visible_css(page, ("button[type='submit']",))
    if login_button is None:
        return "login_button_not_found"

    await login_button.click(timeout=6000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return "captcha"
    if _looks_logged_out(page_text):
        return "auth_required"

    await _save_storage_state()
    return None


async def _settle_page(page) -> None:
    for label in ("Accept", "Akkoord", "Allow all", "Alles accepteren"):
        try:
            await page.get_by_role("button", name=re.compile(label, re.I)).click(timeout=1200)
            break
        except Exception:
            pass
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


async def _find_contact_button(page):
    patterns = (
        r"contact landlord",
        r"ask .* viewing",
        r"respond",
        r"react",
        r"contact",
    )
    for pattern in patterns:
        button = await _first_visible_role(page, "button", re.compile(pattern, re.I))
        if button is not None:
            return button
        link = await _first_visible_role(page, "link", re.compile(pattern, re.I))
        if link is not None:
            return link
    return None


async def _find_message_editor(page):
    return await _first_visible_css(
        page,
        (
            "textarea",
            "[contenteditable='true']",
            "[role='textbox']",
            "div[contenteditable='true']",
        ),
    )


async def _find_send_button(page):
    for pattern in (r"send message", r"send", r"respond", r"react"):
        button = await _first_visible_role(page, "button", re.compile(pattern, re.I))
        if button is not None:
            return button
    return await _first_visible_css(page, ("button[type='submit']",))


async def _first_visible_css(page, selectors: tuple[str, ...]):
    for selector in selectors:
        candidate = await _first_visible_locator(page.locator(selector))
        if candidate is not None:
            return candidate
    return None


async def _first_visible_role(page, role: str, name):
    return await _first_visible_locator(page.get_by_role(role, name=name))


async def _first_visible_locator(locator, limit: int = 10):
    try:
        count = await locator.count()
    except Exception:
        return None
    for index in range(min(count, limit)):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def _body_text(page) -> str:
    try:
        return await page.inner_text("body", timeout=3000)
    except Exception:
        return ""


async def _save_storage_state() -> None:
    if _context is None:
        return
    storage_state_path = _storage_state_path()
    if not storage_state_path:
        return
    directory = os.path.dirname(storage_state_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    await _context.storage_state(path=storage_state_path)


def _storage_state_path() -> str:
    return config.KAMERNET_AUTOREPLY_STORAGE_STATE_PATH.strip()


def _looks_logged_out(text: str) -> bool:
    normalized = text.lower()
    return (
        "you need to be logged in" in normalized
        or ("create account" in normalized and "log in" in normalized)
    )


def _contains_captcha(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "captcha",
            "verify you are human",
            "checking your browser",
            "unusual traffic",
        )
    )


def _subscription_required(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "upgrade to premium",
            "premium subscription",
            "take out a subscription",
            "payment required",
            "respond to favourite rooms",
        )
    )


def _already_replied(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "already responded",
            "already replied",
            "you have responded",
            "you have replied",
            "message sent",
        )
    )


def _send_failed(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "message could not be sent",
            "something went wrong",
            "try again later",
            "failed to send",
        )
    )
