import unittest
from datetime import datetime
from unittest import mock

from automation.rate_limit import detector
from automation.ui import button_clicker as automation


class ClickVerificationTests(unittest.TestCase):
    def tearDown(self):
        automation._try_again_cooldown_until = datetime.min
        automation._reset_try_again_rate_limit_state()

    def _make_control(self):
        return mock.Mock()

    @mock.patch("automation.ui.button_clicker.control_no_longer_visible", autospec=True)
    @mock.patch("automation.ui.button_clicker.scroll_control_into_view", autospec=True)
    @mock.patch("automation.ui.button_clicker.time.sleep", autospec=True)
    @mock.patch("automation.ui.button_clicker.click_button_instantly", autospec=True)
    def test_click_succeeds_on_first_attempt(self, mock_click, mock_sleep, mock_scroll, mock_visible):
        ctrl = self._make_control()
        mock_visible.return_value = True

        result = automation.click_button_with_verification(ctrl, "Allow button")

        self.assertTrue(result)
        mock_click.assert_called_once_with(ctrl)
        mock_scroll.assert_not_called()

    @mock.patch("automation.ui.button_clicker.control_no_longer_visible", autospec=True)
    @mock.patch("automation.ui.button_clicker.scroll_control_into_view", autospec=True)
    @mock.patch("automation.ui.button_clicker.time.sleep", autospec=True)
    @mock.patch("automation.ui.button_clicker.click_button_instantly", autospec=True)
    def test_click_retries_then_succeeds(self, mock_click, mock_sleep, mock_scroll, mock_visible):
        ctrl = self._make_control()
        # First attempt: 3 checks return False (still visible)
        # Second attempt: first check returns True (gone)
        mock_visible.side_effect = [False, False, False, True]

        result = automation.click_button_with_verification(ctrl, "Allow button", max_attempts=3)

        self.assertTrue(result)
        self.assertEqual(mock_click.call_count, 2)
        mock_scroll.assert_called_once()

    @mock.patch("automation.ui.button_clicker.control_no_longer_visible", autospec=True)
    @mock.patch("automation.ui.button_clicker.scroll_control_into_view", autospec=True)
    @mock.patch("automation.ui.button_clicker.time.sleep", autospec=True)
    @mock.patch("automation.ui.button_clicker.click_button_instantly", autospec=True)
    def test_click_gives_up_after_max_attempts(self, mock_click, mock_sleep, mock_scroll, mock_visible):
        ctrl = self._make_control()
        # Always visible
        mock_visible.return_value = False

        result = automation.click_button_with_verification(ctrl, "Allow button", max_attempts=3)

        self.assertFalse(result)
        self.assertEqual(mock_click.call_count, 3)
        self.assertEqual(mock_scroll.call_count, 2)

    @mock.patch("automation.rate_limit.detector.find_rate_limit_text_panels", autospec=True)
    @mock.patch("automation.rate_limit.detector.find_try_again_buttons", autospec=True)
    def test_detect_rate_limit_counts(self, mock_try_again, mock_panels):
        mock_try_again.return_value = [object(), object()]
        mock_panels.return_value = [object()]

        counts = detector.detect_rate_limit_in_window(mock.Mock())

        self.assertEqual(counts["try_again"], 2)
        # The new implementation returns 0 for panels for speed
        self.assertEqual(counts["panels"], 0)

    @mock.patch("automation.rate_limit.detector.find_rate_limit_text_panels", autospec=True)
    @mock.patch("automation.rate_limit.detector.find_try_again_buttons", autospec=True)
    def test_detect_rate_limit_counts_zero(self, mock_try_again, mock_panels):
        mock_try_again.return_value = []
        mock_panels.return_value = []

        counts = detector.detect_rate_limit_in_window(mock.Mock())

        self.assertEqual(counts["try_again"], 0)
        self.assertEqual(counts["panels"], 0)

    def test_determine_try_again_cooldown_end_uses_hours_from_message(self):
        now = datetime(2026, 4, 27, 10, 15, 0)

        deadline, reason = automation._determine_try_again_cooldown_end(
            "You have exceeded your usage limit. Try again in 5 hours.",
            now,
        )

        self.assertEqual(deadline, datetime(2026, 4, 27, 15, 15, 0))
        self.assertEqual(reason, "5 hour rate limit")

    def test_determine_try_again_cooldown_end_supports_word_numbers(self):
        now = datetime(2026, 4, 27, 10, 15, 0)

        deadline, reason = automation._determine_try_again_cooldown_end(
            "Please wait one hour before trying again.",
            now,
        )

        self.assertEqual(deadline, datetime(2026, 4, 27, 11, 15, 0))
        self.assertEqual(reason, "1 hour rate limit")

    def test_determine_try_again_cooldown_end_weekly_limit_waits_until_local_1am(self):
        now = datetime(2026, 4, 27, 14, 30, 0)

        deadline, reason = automation._determine_try_again_cooldown_end(
            "Weekly usage limit reached. Please try again next week.",
            now,
        )

        self.assertEqual(deadline, datetime(2026, 4, 28, 1, 0, 0))
        self.assertEqual(reason, "weekly rate limit; next probe at local 1am")

    def test_determine_try_again_cooldown_end_weekly_followup_uses_four_hour_cadence(self):
        first_now = datetime(2026, 4, 27, 14, 30, 0)
        second_now = datetime(2026, 4, 28, 1, 5, 0)

        automation._determine_try_again_cooldown_end(
            "Weekly usage limit reached. Please try again next week.",
            first_now,
        )
        deadline, reason = automation._determine_try_again_cooldown_end(
            "Weekly usage limit reached. Please try again next week.",
            second_now,
        )

        self.assertEqual(deadline, datetime(2026, 4, 28, 5, 0, 0))
        self.assertEqual(reason, "weekly rate limit; probing every 4 hours")

    @mock.patch("automation.ui.button_clicker.datetime", autospec=True)
    @mock.patch("automation.core.audio.speak", autospec=True)
    @mock.patch("automation.rate_limit.cooldown.set_cooldown_end", autospec=True)
    @mock.patch("automation.rate_limit.cooldown.start_cooldown", autospec=True)
    def test_trigger_rate_limit_cooldown_uses_parsed_message(
        self,
        mock_start_cooldown,
        mock_set_cooldown_end,
        mock_speak,
        mock_datetime,
    ):
        now = datetime(2026, 4, 27, 10, 0, 0)
        mock_datetime.now.return_value = now
        mock_datetime.min = datetime.min

        automation.trigger_rate_limit_cooldown(
            "Trading - Visual Studio Code",
            "You have exceeded your usage limit. Try again in 5 hours.",
        )

        self.assertEqual(automation._try_again_cooldown_until, datetime(2026, 4, 27, 15, 0, 0))
        mock_start_cooldown.assert_called_once()
        mock_set_cooldown_end.assert_called_once_with(datetime(2026, 4, 27, 15, 0, 0))
        mock_speak.assert_called_once_with("Rate limited. 5 hour rate limit.")


if __name__ == "__main__":
    unittest.main()
