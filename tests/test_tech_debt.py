import logging
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import runlog, tech_debt
from src.data_quality import RunHealth


class ClassifyTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(runlog.classify("  ✗ FAB.AD     no price"), "ERROR")
        self.assertEqual(runlog.classify("  [alerts] email failed: SMTPAuthenticationError"), "ERROR")
        self.assertEqual(runlog.classify("HTTP Error 404: Quote not found"), "ERROR")
        self.assertEqual(runlog.classify("  [symbols] no Yahoo quote found for X.AD — skipped"), "WARNING")
        self.assertIsNone(runlog.classify("⚠️  Stage 6: Risk, trend, exposure, events..."))
        self.assertIsNone(runlog.classify("  ✓ NVDA       180.00 USD (last close)"))
        self.assertIsNone(runlog.classify('  File "main.py", line 3, in <module>'))


class BacklogTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.json, self.md = os.path.join(d, "td.json"), os.path.join(d, "TECH_DEBT.md")

    def run_once(self, lines, **kw):
        found = [{"level": runlog.classify(l) or "WARNING", "text": l, "source": "output"} for l in lines]
        return tech_debt.update(found, tickers={"NVDA", "SAP"}, path=self.json, md_path=self.md, **kw)

    def test_grouping_masks_tickers_and_numbers(self):
        s = self.run_once(["  ✗ FAB.AD     no price", "  ✗ EAND.AD    no price", "  ✗ NVDA no price"])
        self.assertEqual(s["errors"], 1)
        data = tech_debt._load(self.json)
        (it,) = data["issues"].values()
        self.assertEqual(it["tickers"], ["EAND.AD", "FAB.AD", "NVDA"])
        self.assertIn("<ticker> no price", it["title"])

    def test_resolves_after_quiet_runs_and_reopens(self):
        self.run_once(["[enrich] Historical download failed: Timeout"])
        for _ in range(tech_debt.RESOLVE_AFTER):
            s = self.run_once([])
        self.assertEqual(s["resolved"], 1)
        self.assertEqual(s["open"], 0)
        s = self.run_once(["[enrich] Historical download failed: Timeout"])
        self.assertEqual(s["open"], 1)
        with open(self.md) as f:
            self.assertIn("Historical download failed", f.read())

    def test_secrets_and_avoid_list_kept_out(self):
        bad = sorted(config.AVOID_LIST)[0]
        self.run_once([f"GET https://x.io/q?apikey=SECRET123 failed", f"  ✗ {bad}.US no price"])
        with open(self.md) as f:
            text = f.read()
        self.assertNotIn("SECRET123", text)
        self.assertNotIn(bad, text)


class CaptureTests(unittest.TestCase):
    def test_finish_collects_output_library_logs_warnings_and_health(self):
        d = tempfile.mkdtemp()
        health = RunHealth()
        health.record("GDELT", "failed", "connection refused")
        health.record("Yahoo Finance", "ok", "4/4")
        runlog.start(d, force=True)
        try:
            print("  [alerts] email failed: SMTPAuthenticationError")
            logging.getLogger("yfinance").error("HTTP Error 404: Quote not found for symbol: FAB.AD")
            warnings.warn("old API", FutureWarning)
            found = runlog.finish(health, {"NVDA"}, 0, backlog_path=os.path.join(d, "td.json"),
                                  md_path=os.path.join(d, "TD.md"))
        finally:
            runlog.stop()
        text = " | ".join(i["text"] for i in found)
        self.assertIn("email failed", text)
        self.assertIn("Quote not found", text)
        self.assertIn("old API", text)
        self.assertIn("Data Health: GDELT failed", text)
        self.assertNotIn("Yahoo Finance", text)
        with open(os.path.join(d, "TD.md")) as f:
            self.assertIn("GDELT", f.read())


if __name__ == "__main__":
    unittest.main()
