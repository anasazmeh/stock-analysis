import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import alerts


class AlertChannelTests(unittest.TestCase):
    def test_send_test_without_channels(self):
        with mock.patch.object(config, "ALERT_EMAIL_TO", ""), mock.patch.object(config, "ALERT_WEBHOOK_URL", ""):
            self.assertFalse(alerts.send_test())

    def test_send_test_reports_email_result(self):
        with mock.patch.object(config, "ALERT_EMAIL_TO", "me@example.com"), \
             mock.patch.object(config, "ALERT_WEBHOOK_URL", ""), \
             mock.patch.object(alerts, "_send_email", return_value=True) as send:
            self.assertTrue(alerts.send_test())
            self.assertIn("Not financial advice", send.call_args[0][1])

    def test_notify_failure_scrubs_log_tail(self):
        log = os.path.join(tempfile.mkdtemp(), "run.log")
        with open(log, "w") as f:
            f.write("fetching PLTR\nTraceback: boom\n")
        with mock.patch.object(config, "ALERT_EMAIL_TO", "me@example.com"), \
             mock.patch.object(config, "ALERT_WEBHOOK_URL", ""), \
             mock.patch.object(alerts, "_send_email", return_value=True) as send:
            self.assertTrue(alerts.notify_failure(log, 1))
            subject, body = send.call_args[0]
            self.assertIn("FAILED", subject)
            self.assertIn("boom", body)
            self.assertNotIn("PLTR", body)


if __name__ == "__main__":
    unittest.main()
