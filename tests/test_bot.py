import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import bot


class _FakeJobQueue:
    def __init__(self):
        self.calls = []

    def run_repeating(self, callback, interval, first, name, job_kwargs):
        self.calls.append(
            {
                "callback": callback,
                "interval": interval,
                "first": first,
                "name": name,
                "job_kwargs": job_kwargs,
            }
        )


class _FakeApplication:
    def __init__(self):
        self.job_queue = _FakeJobQueue()


class BotScheduleTests(unittest.TestCase):
    def test_fast_scan_jobs_include_roofz_when_enabled(self):
        with patch.object(bot.config, "ROOFZ_ENABLED", True):
            names = [name for _, _, name in bot._fast_scan_jobs()]

        self.assertEqual(
            names,
            ["pararius-fast-scan", "general-fast-scan", "roofz-fast-scan"],
        )

    def test_fast_scan_jobs_skip_roofz_when_disabled(self):
        with patch.object(bot.config, "ROOFZ_ENABLED", False):
            names = [name for _, _, name in bot._fast_scan_jobs()]

        self.assertEqual(names, ["pararius-fast-scan", "general-fast-scan"])

    def test_schedule_fast_scan_uses_fast_interval(self):
        app = _FakeApplication()

        with patch.object(bot.config, "FAST_POLL_INTERVAL_SECONDS", 12):
            bot._schedule_fast_scan(
                app,
                bot.scheduled_roofz_scan,
                first=15,
                name="roofz-fast-scan",
            )

        self.assertEqual(len(app.job_queue.calls), 1)
        call = app.job_queue.calls[0]
        self.assertIs(call["callback"], bot.scheduled_roofz_scan)
        self.assertEqual(call["interval"], 12)
        self.assertEqual(call["first"], 15)
        self.assertEqual(call["name"], "roofz-fast-scan")
        self.assertEqual(
            call["job_kwargs"],
            {"coalesce": True, "max_instances": 1, "misfire_grace_time": 12},
        )


class BotScheduledScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_scan_limits_concurrent_users(self):
        active = 0
        max_active = 0
        scanned_chat_ids = []
        users = [
            {"chat_id": 1},
            {"chat_id": 2},
            {"chat_id": 3},
            {"chat_id": 4},
        ]

        async def run_scan_for_user(_bot, user, sources):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            scanned_chat_ids.append(user["chat_id"])
            await asyncio.sleep(0.01)
            active -= 1

        with (
            patch("bot.db.get_all_active_users", AsyncMock(return_value=users)),
            patch("bot.run_scan_for_user", AsyncMock(side_effect=run_scan_for_user)),
            patch.object(bot.config, "MAX_CONCURRENT_USERS_PER_JOB", 2),
            patch.object(bot.config, "TELEGRAM_ALLOWED_CHAT_IDS", set()),
        ):
            await bot._scheduled_scan_for_sources(
                SimpleNamespace(bot=object()),
                "Test",
                ("funda",),
            )

        self.assertEqual(set(scanned_chat_ids), {1, 2, 3, 4})
        self.assertEqual(max_active, 2)


if __name__ == "__main__":
    unittest.main()
