"""DEGIRO Transactions export: newest-first order, splits, ISIN changes, realised EUR P&L."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import broker_import  # noqa: E402

HEADER = ("Date,Time,Product,ISIN,Reference exchange,Venue,Quantity,Price,,Local value,,Value EUR,Exchange rate,"
          "AutoFX Fee,Transaction and/or third party fees EUR,Total EUR,Order ID\n")
# Newest first, like the real export (made-up products and amounts)
EXPORT = HEADER + (
    '27-10-2026,14:33,ALPHA INC,US0000000001,NDQ,XNAS,-8,"270,0000",USD,"2160,00",USD,"1938,10","1,1145","-4,85","-2,00","1931,26",o4\n'
    '02-07-2026,00:00,ALPHA INC,US0000000001,NDQ,,8,"193,1850",USD,"-1545,48",USD,"-1351,37","1,1436","0,00",,"-1351,37",\n'
    '02-07-2026,00:00,ALPHA INC,US0000000001,NDQ,,-2,"772,7400",USD,"1545,48",USD,"1351,37","1,1436","0,00",,"1351,37",\n'
    '19-07-2024,18:27,ALPHA INC,US0000000001,NDQ,ARCX,2,"310,0000",USD,"-620,00",USD,"-569,39","1,0889","-1,42","-2,00","-572,81",o3\n'
    '07-08-2025,14:25,BETA HOLDINGS,US0000000003,OTC,,4,"7,4997",USD,"-30,00",USD,"-25,77","1,1641","0,00",,"-25,77",\n'
    '07-08-2025,14:25,BETA INC,US0000000002,OTC,,-4,"7,4997",USD,"30,00",USD,"25,77","1,1641","0,00",,"25,77",\n'
    '29-04-2021,15:34,BETA INC,US0000000002,NDQ,XNAS,4,"15,1000",USD,"-60,40",USD,"-50,00","1,2121","-1,56","-0,91","-52,47",o2\n'
    '14-06-2022,08:55,GAMMA GROUP,US0000000004,NDQ,,-1,"0,0000",USD,"0,00",USD,"0,00","1,0434","0,00",,"0,00",\n'
    '27-01-2022,19:06,GAMMA GROUP,US0000000004,NDQ,XNAS,1,"38,5000",USD,"-38,50",USD,"-34,56","1,1141","-0,09","-0,50","-35,14",o1\n'
)


class DegiroHistoryTests(unittest.TestCase):
    def test_newest_first_export_replayed_in_order(self):
        held = broker_import.parse_degiro(EXPORT)
        self.assertEqual(sorted(held), ["US0000000003"])          # ALPHA sold, GAMMA delisted
        beta = held["US0000000003"]
        self.assertEqual(beta.shares, 4)
        self.assertAlmostEqual(beta.cost_eur, 52.47, places=2)     # cost carried through the ISIN change

    def test_split_keeps_cost_and_sale_realises_once(self):
        alpha = broker_import.parse_degiro(EXPORT, include_closed=True)["US0000000001"]
        self.assertAlmostEqual(alpha.realised_eur, 1931.26 - 572.81, places=2)
        self.assertEqual(alpha.last_sale, "2026-10-27 14:33")

    def test_delisting_written_off(self):
        gamma = broker_import.parse_degiro(EXPORT, include_closed=True)["US0000000004"]
        self.assertAlmostEqual(gamma.realised_eur, -35.14, places=2)

    def test_realised_summary(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "degiro_transactions.csv"), "w") as f:
            f.write(EXPORT)
        s = broker_import.realised_summary(d)
        self.assertAlmostEqual(s["total_eur"], 1358.45 - 35.14, places=2)
        self.assertEqual(s["positions"][0]["last_sale"], "2026-10-27")
        self.assertIsNone(broker_import.realised_summary(tempfile.mkdtemp()))

    def test_reconcile_matches_by_isin(self):
        held = list(broker_import.parse_degiro(EXPORT).values())
        holdings = [{"ticker": "BETA", "isin": "US0000000003", "name": "Beta", "shares": 4, "bep": 7.4997,
                     "bep_currency": "USD"}]
        self.assertEqual(broker_import.reconcile(holdings, held), [])
        holdings[0]["shares"] = 5
        self.assertIn("shares 5", broker_import.reconcile(holdings, held)[0]["issue"])


if __name__ == "__main__":
    unittest.main()
