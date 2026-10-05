import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import cache, symbols, runlog


class SymbolTests(unittest.TestCase):
    def setUp(self):
        self._dir = config.CACHE_DIR
        config.CACHE_DIR = tempfile.mkdtemp()

    def tearDown(self):
        config.CACHE_DIR = self._dir

    def test_hong_kong_codes_get_four_digits(self):
        self.assertEqual(symbols.normalize("700.HK"), "0700.HK")
        self.assertEqual(symbols.normalize("9988.HK"), "9988.HK")
        self.assertEqual(symbols.candidates("700.HK")[0], "0700.HK")

    def test_abu_dhabi_falls_back_to_ae(self):
        live = {"FAB.AE"}
        out = symbols.resolve_tickers(["FAB.AD", "SAP.DE"], probe=lambda s: s in live, search=lambda n, t: None)
        self.assertEqual(out, ["FAB.AE", "SAP.DE"])
        self.assertEqual(symbols.STATUS["resolved"], {"FAB.AD": "FAB.AE"})

    def test_search_by_name_and_alias_copies_config(self):
        config.SHARIAH_OVERRIDES["ZZZ.AD"] = ("Review", "test")
        config.CURATED_WATCHLIST["ZZZ.AD"] = ("UAE", "Zed Holding — test")
        try:
            out = symbols.resolve_tickers(["ZZZ.AD"], probe=lambda s: False,
                                          search=lambda name, t: "ZEDH.AE" if name == "Zed Holding" else None)
            self.assertEqual(out, ["ZEDH.AE"])
            self.assertEqual(config.SHARIAH_OVERRIDES["ZEDH.AE"], ("Review", "test"))
        finally:
            for k in ("ZZZ.AD", "ZEDH.AE"):
                config.SHARIAH_OVERRIDES.pop(k, None)
                config.CURATED_WATCHLIST.pop(k, None)

    def test_missing_symbol_dropped_and_cached(self):
        calls = []
        probe = lambda s: calls.append(s) or False
        self.assertEqual(symbols.resolve_tickers(["NOPE.AD"], probe=probe, search=lambda n, t: None), [])
        self.assertEqual(symbols.STATUS["missing"], ["NOPE.AD"])
        n = len(calls)
        symbols.resolve_tickers(["NOPE.AD"], probe=probe, search=lambda n, t: None)
        self.assertEqual(len(calls), n)   # the miss is cached, no new lookups

    def test_holdings_and_normal_symbols_not_probed(self):
        calls = []
        out = symbols.resolve_tickers(["NVDA", "HELD.AD"], keep={"HELD.AD"},
                                      probe=lambda s: calls.append(s) or True, search=lambda n, t: None)
        self.assertEqual(out, ["NVDA", "HELD.AD"])
        self.assertEqual(calls, [])

    def test_failed_ticker_is_rechecked_next_run(self):
        symbols.mark_failed(["OLD"])
        out = symbols.resolve_tickers(["OLD"], probe=lambda s: s == "OLD", search=lambda n, t: None)
        self.assertEqual(out, ["OLD"])


class RunLogTests(unittest.TestCase):
    def test_output_copied_to_log(self):
        d = tempfile.mkdtemp()
        path = runlog.start(d, force=True)
        try:
            print("hello log")
        finally:
            runlog.stop()
        with open(path) as f:
            self.assertIn("hello log", f.read())


if __name__ == "__main__":
    unittest.main()
