import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from dashboard.app import create_app

ORIGIN = {"Origin": "http://localhost"}
SLOW = [sys.executable, "-c",
        "import time,sys; print('📡 Stage 1: Discovering candidates...', flush=True); time.sleep(0.3); "
        "print('🤖 Stage 7: Claude analysis...', flush=True); time.sleep(30)"]
BAD = sorted(config.AVOID_LIST)[0]


def wait(client, cond, limit=15):
    end = time.time() + limit
    while time.time() < end:
        s = client.get("/refresh/status").get_json()
        if cond(s):
            return s
        time.sleep(0.2)
    raise AssertionError(f"timed out, last status {s}")


class RefreshTests(unittest.TestCase):
    def app(self, cmd, timeout_min=1):
        app = create_app(tempfile.mkdtemp(), tempfile.mkdtemp(), run_cmd=cmd)
        app.config["REFRESH_TIMEOUT_MIN"] = timeout_min
        return app.test_client()

    def test_progress_shows_stage_and_elapsed(self):
        c = self.app(SLOW)
        self.assertEqual(c.post("/refresh", headers=ORIGIN).status_code, 202)
        s = wait(c, lambda s: "Stage 7" in s.get("stage", ""))
        self.assertTrue(s["running"])
        self.assertGreaterEqual(s["elapsed_s"], 0)
        self.assertEqual(c.post("/refresh", headers=ORIGIN).status_code, 409)   # one run at a time
        c.post("/refresh/cancel", headers=ORIGIN)
        s = wait(c, lambda s: not s["running"])
        self.assertEqual(s["exit_code"], "cancelled")

    def test_timeout_stops_a_stuck_run(self):
        c = self.app(SLOW, timeout_min=0.02)   # 1.2 seconds
        c.post("/refresh", headers=ORIGIN)
        s = wait(c, lambda s: not s["running"])
        self.assertEqual(s["exit_code"], "timeout")

    def test_cancel_needs_same_origin(self):
        c = self.app(SLOW)
        c.post("/refresh", headers=ORIGIN)
        self.assertEqual(c.post("/refresh/cancel").status_code, 403)
        c.post("/refresh/cancel", headers=ORIGIN)
        wait(c, lambda s: not s["running"])

    def test_finished_run_and_log_page_scrubbed(self):
        c = self.app([sys.executable, "-c", f"print('Stage 9 done'); print('{BAD} should never show')"])
        c.post("/refresh", headers=ORIGIN)
        s = wait(c, lambda s: not s["running"] and s["finished"])
        self.assertEqual(s["exit_code"], 0)
        html = c.get("/refresh/log").get_data(as_text=True)
        self.assertIn("Stage 9 done", html)
        self.assertNotIn(BAD, html)


if __name__ == "__main__":
    unittest.main()
