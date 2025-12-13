import unittest
from unittest import mock

import LAGACY_auto_allow_copilot as automation


class ClickVerificationTests(unittest.TestCase):
    def _make_control(self, exists_side_effect):
        control = mock.Mock()
        control.Exists.side_effect = exists_side_effect
        return control

    @mock.patch("auto_allow_copilot._scroll_control_into_view", autospec=True)
    @mock.patch("auto_allow_copilot.time.sleep", autospec=True)
    @mock.patch("auto_allow_copilot.click_button_instantly", autospec=True)
    def test_click_succeeds_on_first_attempt(self, mock_click, mock_sleep, mock_scroll):
        ctrl = self._make_control([False])

        result = automation.click_button_with_verification(ctrl, "Allow button")

        self.assertTrue(result)
        mock_click.assert_called_once_with(ctrl)
        ctrl.Exists.assert_called_once()
        mock_scroll.assert_not_called()

    @mock.patch("auto_allow_copilot._scroll_control_into_view", autospec=True)
    @mock.patch("auto_allow_copilot.time.sleep", autospec=True)
    @mock.patch("auto_allow_copilot.click_button_instantly", autospec=True)
    def test_click_retries_then_succeeds(self, mock_click, mock_sleep, mock_scroll):
        ctrl = self._make_control([True, True, True, False])

        result = automation.click_button_with_verification(ctrl, "Allow button", max_attempts=3)

        self.assertTrue(result)
        self.assertEqual(mock_click.call_count, 2)
        mock_scroll.assert_called_once()

    @mock.patch("auto_allow_copilot._scroll_control_into_view", autospec=True)
    @mock.patch("auto_allow_copilot.time.sleep", autospec=True)
    @mock.patch("auto_allow_copilot.click_button_instantly", autospec=True)
    def test_click_gives_up_after_max_attempts(self, mock_click, mock_sleep, mock_scroll):
        ctrl = self._make_control([True] * 12)

        result = automation.click_button_with_verification(ctrl, "Allow button", max_attempts=3)

        self.assertFalse(result)
        self.assertEqual(mock_click.call_count, 3)
        self.assertEqual(mock_scroll.call_count, 2)

    @mock.patch("auto_allow_copilot.find_rate_limit_text_panels", autospec=True)
    @mock.patch("auto_allow_copilot.find_try_again_buttons", autospec=True)
    def test_detect_rate_limit_counts(self, mock_try_again, mock_panels):
        mock_try_again.return_value = [object(), object()]
        mock_panels.return_value = [object()]

        counts = automation.detect_rate_limit_in_window(mock.Mock())

        self.assertEqual(counts["try_again"], 2)
        self.assertEqual(counts["panels"], 1)

    @mock.patch("auto_allow_copilot.find_rate_limit_text_panels", autospec=True)
    @mock.patch("auto_allow_copilot.find_try_again_buttons", autospec=True)
    def test_detect_rate_limit_counts_zero(self, mock_try_again, mock_panels):
        mock_try_again.return_value = []
        mock_panels.return_value = []

        counts = automation.detect_rate_limit_in_window(mock.Mock())

        self.assertEqual(counts["try_again"], 0)
        self.assertEqual(counts["panels"], 0)


if __name__ == "__main__":
    unittest.main()
