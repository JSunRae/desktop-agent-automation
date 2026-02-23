import unittest
from unittest import mock

from automation.ui import button_clicker as automation
from automation.rate_limit import detector


class ClickVerificationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
