import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

import config
from scrapers.base import Listing

logger = logging.getLogger(__name__)

_BROWSER_LOCK = asyncio.Lock()
_playwright_manager: Any = None
_playwright: Any = None
_browser: Any = None
_context: Any = None
_page: Any = None


@dataclass(frozen=True)
class FundaAutoReplyContact:
    email: str
    first_name: str
    last_name: str
    phone: str

    def is_complete(self) -> bool:
        return all(
            value.strip()
            for value in (self.email, self.first_name, self.last_name, self.phone)
        )


@dataclass(frozen=True)
class FundaAutoReplyResult:
    listing_id: str
    status: str
    detail: str = ""
    sent: bool = False


async def send_funda_autoreply(
    listing: Listing,
    message: str,
    contact: FundaAutoReplyContact,
) -> FundaAutoReplyResult:
    if config.FUNDA_AUTOREPLY_DRY_RUN:
        logger.info("Funda auto-reply dry run for listing %s", listing.id)
        return FundaAutoReplyResult(listing.id, "dry_run", "Dry run enabled", sent=False)

    message = message.strip()
    if not message:
        return FundaAutoReplyResult(listing.id, "empty_message", "Reply template is empty")
    if not contact.is_complete():
        return FundaAutoReplyResult(
            listing.id,
            "contact_missing",
            "Funda contact details are incomplete",
        )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return FundaAutoReplyResult(
            listing.id,
            "playwright_missing",
            "Playwright is not installed or Chromium is missing",
        )

    async with _BROWSER_LOCK:
        try:
            page = await _page_for_reply(async_playwright)
            return await _send_with_page(page, listing, message, contact)
        except Exception as exc:
            logger.error("Funda auto-reply error for %s: %s", listing.id, exc)
            await _reset_browser(stop_playwright=True)
            return FundaAutoReplyResult(listing.id, "error", str(exc)[:500])


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
        _browser = await _playwright.chromium.launch(headless=config.FUNDA_AUTOREPLY_HEADLESS)

    if _context is None:
        _context = await _browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="nl-NL",
        )

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


async def _send_with_page(
    page,
    listing: Listing,
    message: str,
    contact: FundaAutoReplyContact,
) -> FundaAutoReplyResult:
    timeout_ms = max(5, config.FUNDA_AUTOREPLY_TIMEOUT_SECONDS) * 1000
    await page.goto(listing.url, wait_until="domcontentloaded", timeout=timeout_ms)
    await _settle_page(page)

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return FundaAutoReplyResult(listing.id, "captcha", "Funda asked for human verification")

    contact_form = await _find_contact_form(page)
    if contact_form is None:
        return FundaAutoReplyResult(
            listing.id,
            "form_not_found",
            "Could not find the Funda contact form",
        )

    editor = await _find_message_editor(contact_form)
    email_input = await _find_email_input(contact_form)
    first_name_input = await _find_labelled_input(contact_form, r"voornaam|first name")
    last_name_input = await _find_labelled_input(contact_form, r"achternaam|last name")
    phone_input = await _find_phone_input(contact_form)

    missing = []
    if editor is None:
        missing.append("message")
    if email_input is None:
        missing.append("email")
    if first_name_input is None:
        missing.append("first_name")
    if last_name_input is None:
        missing.append("last_name")
    if phone_input is None:
        missing.append("phone")
    if missing:
        return FundaAutoReplyResult(
            listing.id,
            "form_not_found",
            "Missing form fields: " + ", ".join(missing),
        )

    await editor.fill(message, timeout=6000)
    await email_input.fill(contact.email, timeout=6000)
    await first_name_input.fill(contact.first_name, timeout=6000)
    await last_name_input.fill(contact.last_name, timeout=6000)
    await phone_input.fill(contact.phone, timeout=6000)

    send_button = await _find_send_button(contact_form)
    if send_button is None:
        return FundaAutoReplyResult(
            listing.id,
            "send_button_not_found",
            "Could not find the Funda send button",
        )

    await send_button.click(timeout=6000)
    try:
        await page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass

    page_text = await _body_text(page)
    if _contains_captcha(page_text):
        return FundaAutoReplyResult(listing.id, "captcha", "Funda asked for human verification")
    if _send_failed(page_text):
        return FundaAutoReplyResult(listing.id, "submit_failed", "Funda did not accept the form")
    if _send_confirmed(page_text):
        return FundaAutoReplyResult(listing.id, "sent", "Contact form submitted", sent=True)

    return FundaAutoReplyResult(
        listing.id,
        "submit_unknown",
        "Funda did not show a confirmation after submitting the contact form",
    )


async def _settle_page(page) -> None:
    for label in (
        "Accepteren",
        "Alles accepteren",
        "Accept",
        "Accept all",
        "Akkoord",
        "Allow all",
    ):
        try:
            await page.get_by_role("button", name=re.compile(label, re.I)).click(timeout=1200)
            break
        except Exception:
            pass
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


async def _find_contact_form(page):
    for selector in ("form", "[role='dialog']", "section", "article", "aside"):
        containers = page.locator(selector)
        try:
            count = await containers.count()
        except Exception:
            continue

        for index in range(min(count, 40)):
            container = containers.nth(index)
            try:
                if not await container.is_visible():
                    continue
            except Exception:
                continue
            if selector != "form" and not await _has_contact_hint(container):
                continue
            if await _looks_like_contact_form(container):
                return container
    return None


async def _looks_like_contact_form(scope) -> bool:
    editor = await _find_message_editor(scope)
    if editor is None:
        return False

    email_input = await _find_email_input(scope)
    send_button = await _find_send_button(scope)
    return email_input is not None and send_button is not None


async def _has_contact_hint(scope) -> bool:
    try:
        text = await scope.inner_text(timeout=1000)
    except Exception:
        return False
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "contact",
            "bezichtiging",
            "bericht",
            "aanvraag",
            "interesse",
            "makelaar",
            "verhuurder",
            "verstuur",
        )
    )


async def _find_message_editor(scope):
    return await _first_visible_css(
        scope,
        (
            "textarea[placeholder*='bericht']",
            "textarea",
            "[role='textbox']",
        ),
    )


async def _find_email_input(scope):
    labelled = await _find_labelled_input(scope, r"e-?mail|email")
    if labelled is not None:
        return labelled
    return await _first_visible_css(
        scope,
        (
            "input[type='email']",
            "input[name*='email' i]",
            "input[autocomplete='email']",
        ),
    )


async def _find_phone_input(scope):
    labelled = await _find_labelled_input(scope, r"telefoon|phone")
    if labelled is not None:
        return labelled
    return await _first_visible_css(
        scope,
        (
            "input[type='tel']",
            "input[name*='phone' i]",
            "input[name*='telefoon' i]",
            "input[autocomplete='tel']",
        ),
    )


async def _find_labelled_input(scope, pattern: str):
    candidate = await _first_visible_locator(scope.get_by_label(re.compile(pattern, re.I)))
    if candidate is not None:
        return candidate
    return await _find_input_after_label_text(scope, pattern)


async def _find_input_after_label_text(scope, pattern: str):
    labels = scope.locator("label")
    try:
        count = await labels.count()
    except Exception:
        return None
    matcher = re.compile(pattern, re.I)
    for index in range(min(count, 30)):
        label = labels.nth(index)
        try:
            if not await label.is_visible():
                continue
            text = await label.inner_text(timeout=1000)
        except Exception:
            continue
        if not matcher.search(text):
            continue

        candidate = await _first_visible_locator(label.locator("xpath=following::input[1]"), limit=1)
        if candidate is not None:
            return candidate
    return None


async def _find_send_button(scope):
    for pattern in (r"^verstuur$", r"verzenden", r"send", r"submit"):
        button = await _first_visible_locator(scope.get_by_role("button", name=re.compile(pattern, re.I)))
        if button is not None:
            return button
    return await _first_visible_css(scope, ("button[type='submit']",))


async def _first_visible_css(scope, selectors: tuple[str, ...]):
    for selector in selectors:
        candidate = await _first_visible_locator(scope.locator(selector))
        if candidate is not None:
            return candidate
    return None


async def _first_visible_locator(locator, limit: int = 12):
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


def _contains_captcha(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "captcha",
            "verify you are human",
            "checking your browser",
            "unusual traffic",
            "controleer of je een mens bent",
        )
    )


def _send_failed(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "kon niet worden verstuurd",
            "niet verzonden",
            "verplicht",
            "ongeldig",
            "controleer de verplichte",
            "controleer je invoer",
            "controleer uw invoer",
            "required",
            "invalid",
            "please check",
            "probeer het later opnieuw",
            "something went wrong",
            "try again later",
            "failed to send",
        )
    )


def _send_confirmed(text: str) -> bool:
    normalized = text.lower()
    return any(
        phrase in normalized
        for phrase in (
            "bericht is verzonden",
            "formulier is verzonden",
            "aanvraag is verzonden",
            "bedankt",
            "thank you",
            "message sent",
            "request sent",
        )
    )
