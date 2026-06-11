from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, call, patch

import funda_autoreply
from scrapers.base import Listing


def _listing() -> Listing:
    return Listing(
        id="funda-1",
        source="funda",
        title="Funda listing",
        price="EUR 1500",
        address="Amsterdam",
        url="https://example.test/funda-1",
    )


def _contact() -> funda_autoreply.FundaAutoReplyContact:
    return funda_autoreply.FundaAutoReplyContact(
        email="person@example.test",
        first_name="First",
        last_name="Last",
        phone="+31612345678",
    )


class _FakePage:
    def __init__(self, body_texts: list[str]):
        self.goto = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self._body_texts = body_texts

    async def inner_text(self, selector: str, timeout: int):
        return self._body_texts.pop(0)


class FundaAutoReplySenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_with_page_submits_scoped_contact_form_when_confirmed(self):
        page = _FakePage(["Contact form", "Bedankt, je aanvraag is verzonden"])
        form = object()
        editor = SimpleNamespace(fill=AsyncMock())
        email_input = SimpleNamespace(fill=AsyncMock())
        first_name_input = SimpleNamespace(fill=AsyncMock())
        last_name_input = SimpleNamespace(fill=AsyncMock())
        phone_input = SimpleNamespace(fill=AsyncMock())
        send_button = SimpleNamespace(click=AsyncMock())

        with (
            patch("funda_autoreply._settle_page", AsyncMock()),
            patch("funda_autoreply._find_contact_form", AsyncMock(return_value=form)) as find_form,
            patch("funda_autoreply._find_message_editor", AsyncMock(return_value=editor)) as find_editor,
            patch("funda_autoreply._find_email_input", AsyncMock(return_value=email_input)) as find_email,
            patch(
                "funda_autoreply._find_labelled_input",
                AsyncMock(side_effect=[first_name_input, last_name_input]),
            ) as find_labelled,
            patch("funda_autoreply._find_phone_input", AsyncMock(return_value=phone_input)) as find_phone,
            patch("funda_autoreply._find_send_button", AsyncMock(return_value=send_button)) as find_send,
        ):
            result = await funda_autoreply._send_with_page(page, _listing(), "Hello", _contact())

        self.assertTrue(result.sent)
        self.assertEqual(result.status, "sent")
        find_form.assert_awaited_once_with(page)
        find_editor.assert_awaited_once_with(form)
        find_email.assert_awaited_once_with(form)
        find_labelled.assert_has_awaits(
            [
                call(form, r"voornaam|first name"),
                call(form, r"achternaam|last name"),
            ]
        )
        find_phone.assert_awaited_once_with(form)
        find_send.assert_awaited_once_with(form)
        editor.fill.assert_awaited_once_with("Hello", timeout=6000)
        email_input.fill.assert_awaited_once_with("person@example.test", timeout=6000)
        first_name_input.fill.assert_awaited_once_with("First", timeout=6000)
        last_name_input.fill.assert_awaited_once_with("Last", timeout=6000)
        phone_input.fill.assert_awaited_once_with("+31612345678", timeout=6000)
        send_button.click.assert_awaited_once_with(timeout=6000)

    async def test_send_with_page_treats_unknown_submit_state_as_not_sent(self):
        page = _FakePage(["Contact form", "Contact form"])
        field = SimpleNamespace(fill=AsyncMock())
        send_button = SimpleNamespace(click=AsyncMock())

        with (
            patch("funda_autoreply._settle_page", AsyncMock()),
            patch("funda_autoreply._find_contact_form", AsyncMock(return_value=object())),
            patch("funda_autoreply._find_message_editor", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_email_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_labelled_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_phone_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_send_button", AsyncMock(return_value=send_button)),
        ):
            result = await funda_autoreply._send_with_page(page, _listing(), "Hello", _contact())

        self.assertFalse(result.sent)
        self.assertEqual(result.status, "submit_unknown")
        send_button.click.assert_awaited_once_with(timeout=6000)

    async def test_send_with_page_reports_validation_failure_as_not_sent(self):
        page = _FakePage(["Contact form", "Controleer de verplichte velden"])
        field = SimpleNamespace(fill=AsyncMock())
        send_button = SimpleNamespace(click=AsyncMock())

        with (
            patch("funda_autoreply._settle_page", AsyncMock()),
            patch("funda_autoreply._find_contact_form", AsyncMock(return_value=object())),
            patch("funda_autoreply._find_message_editor", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_email_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_labelled_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_phone_input", AsyncMock(return_value=field)),
            patch("funda_autoreply._find_send_button", AsyncMock(return_value=send_button)),
        ):
            result = await funda_autoreply._send_with_page(page, _listing(), "Hello", _contact())

        self.assertFalse(result.sent)
        self.assertEqual(result.status, "submit_failed")

    async def test_send_with_page_stops_when_contact_form_is_missing(self):
        page = _FakePage(["Listing body"])

        with (
            patch("funda_autoreply._settle_page", AsyncMock()),
            patch("funda_autoreply._find_contact_form", AsyncMock(return_value=None)),
            patch("funda_autoreply._find_message_editor", AsyncMock()) as find_editor,
        ):
            result = await funda_autoreply._send_with_page(page, _listing(), "Hello", _contact())

        self.assertFalse(result.sent)
        self.assertEqual(result.status, "form_not_found")
        find_editor.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
