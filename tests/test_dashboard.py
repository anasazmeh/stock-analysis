import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from dashboard.app import create_app  # noqa: E402
from src import dashboard_data, portfolio  # noqa: E402
from src.data_quality import RunHealth  # noqa: E402
from src.fx import parse_ecb_xml  # noqa: E402
from src.models import (Opportunity, PortfolioHolding, ShariahStatus, RiskProfile, AnalysisResult,  # noqa: E402
                        MacroContext)

FX = parse_ecb_xml("<Cube time='2026-10-02'><Cube currency='USD' rate='1.15'/></Cube>")


def sample_payload():
    """Example data for tests and screenshots — not real market data."""
    def opp(t, name, region, price, adj, status, trend, held=None, **kw):
        return Opportunity(
            ticker=t, name=name, region=region, country="US", sector="Technology", industry="Semiconductors",
            price=price, currency="USD", price_type="last close", price_time="2026-10-02 20:00 UTC",
            price_source="Yahoo Finance", price_check="Verified", price_alt=price, target=price * 1.3,
            upside=30.0, adj_upside=adj, analyst_count=25, consensus_quality="Good", rank_score=50 + adj / 2,
            data_ok=True, tradable="Yes", trend=trend, rel_strength={"SPY": 8.0}, ma50=price * 0.95, ma200=price * 0.85,
            hist_prices=[price * (0.8 + i / 600) for i in range(130)],
            shariah=ShariahStatus(compliant=status, methodology="AAOIFI", debt_ratio=0.05, cash_ratio=0.12,
                                  income_ratio=0.01, activity_screen="Pass", reasons=[],
                                  second_opinion={"Musaffa": "https://musaffa.com/stock/" + t}),
            risk=RiskProfile(composite_score=4.2, volatility_30d=38.0, rsi_14=55, geo_exposure="High", coverage=1.0),
            analysis=AnalysisResult(thesis=f"{name} example thesis.", bull_case="b", bear_case="r", sentiment_score=5,
                                    holder_action="HOLD" if held else "N/A", new_buyer_action="WATCH",
                                    confidence="medium", evidence_used=["price", "trend"]),
            portfolio=held, news=[{"title": f"{name} example headline", "source": "Reuters", "date": "2026-10-01",
                                   "url": "https://example.com"}],
            filings=[{"form": "8-K", "date": "2026-09-30", "items": ["2.02"], "labels": ["Results"],
                      "red_flag": False, "url": "https://www.sec.gov/"}], **kw)
    held = lambda shares, bep, pl, val, w, themes: PortfolioHolding(
        shares=shares, bep=bep, bep_currency="USD", pl_pct=pl, value_eur=val, cost_eur=val / (1 + pl / 100),
        pl_value_eur=val - val / (1 + pl / 100), weight_pct=w, themes=themes, status="🟢 HOLD")
    opps = [
        opp("NVDA", "NVIDIA", "🇺🇸 US", 180.0, 25.0, "Yes", "Uptrend", held(30, 99, 81.8, 4700, 41.0, ["AI / Semiconductors"]),
            thesis_status="On track", next_event="Earnings 2026-11-19", days_to_event=34),
        opp("SAP", "SAP SE", "🇪🇺 Europe", 168.0, 12.0, "Review", "Mixed", held(20, 147, -0.7, 2900, 25.3, ["Software"]),
            thesis_status="Review", thesis_notes=["trend is Mixed"]),
        opp("MU", "Micron", "🇺🇸 US", 120.0, 40.0, "Yes", "Uptrend"),
        opp("2222.SR", "Saudi Aramco", "🌙 Middle East", 27.0, 8.0, "Unknown", "Downtrend"),
    ]
    opps[3].tradable = "Watch only"
    opps[3].data_ok = False
    opps[3].data_flags = ["stale quote"]
    exp = portfolio.exposure(opps)
    top10 = [o for o in opps if o.data_ok]
    macro = MacroContext(regime="neutral", themes=["AI capex", "Rates on hold"], vix=17.2, eurusd=1.15,
                         events=[{"date": "2026-10-28", "name": "FOMC decision"}],
                         geo_themes=[{"theme": "US chip export controls", "documents": 1, "portfolio_exposed_pct": 41.0,
                                      "latest": {"title": "Export controls update", "date": "2026-09-25", "url": "https://example.com"}}])
    health = RunHealth()
    health.record("Yahoo Finance", "ok", "4/4 priced")
    health.record("Finnhub price check", "skipped", "no key")
    alerts = [{"level": "DANGER", "ticker": "RUN", "message": "example danger"},
              {"level": "BUY", "ticker": "MU", "message": "Quality-adjusted analyst upside +40%. Shariah: Yes"},
              {"level": "WARN", "ticker": "SAP", "message": "example warning"}]
    unpriced = [PortfolioHolding(name="iShares Nasdaq-100 UCITS ETF", shares=28, bep=148.97, bep_currency="EUR",
                                 note="No Yahoo ticker set in portfolio_data.py", shariah_note="Not Shariah-screened.")]
    return dashboard_data.build_payload(
        opps, macro, health=health, fx=FX, exposure=exp, unpriced=unpriced, top10=top10, alerts=alerts,
        changes=["New in Top 10: MU"], purification_rows=[("NVDA", {"dividends": 1.2, "currency": "USD", "ratio": 0.01,
                                                                    "amount": 0.01, "amount_eur": 0.01})],
        broker_diffs=None, scorecard={"since": "2026-09-01", "portfolio_pct": 4.0, "benchmark_pct": 2.5,
                                      "benchmark": "ISWD.L", "difference_pts": 1.5},
        now=datetime(2026, 10, 3, 7, 0))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.reports = tempfile.mkdtemp()
        self.runs = tempfile.mkdtemp()
        dashboard_data.write_latest(sample_payload(), os.path.join(self.reports, "latest.json"))
        for i, (v, b) in enumerate([(9000, 50), (9500, 51), (10100, 52)]):
            with open(os.path.join(self.runs, f"2026-09-0{i + 1}_070000.json"), "w") as f:
                json.dump({"run_at": f"2026-09-0{i + 1}T07:00:00", "portfolio_value_eur": v, "benchmark_close": b,
                           "degraded": i == 1, "top10": ["NVDA", "MU"]}, f)
        self.app = create_app(self.reports, self.runs, run_cmd=[sys.executable, "-c", "pass"])
        self.client = self.app.test_client()

    def test_pages_render(self):
        for path, needle in [("/", "Top 10 opportunities"), ("/portfolio", "iShares Nasdaq-100"),
                             ("/opportunities", "Regional heatmap"), ("/stock/NVDA", "NVIDIA example thesis"),
                             ("/history", "Portfolio vs MSCI World Islamic")]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(needle, r.get_data(as_text=True), path)

    def test_alert_badge_and_disclaimer(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="badge"', html)
        self.assertIn("Not financial advice", html)

    def test_unknown_stock_404(self):
        self.assertEqual(self.client.get("/stock/ZZZZ").status_code, 404)

    def test_api(self):
        data = self.client.get("/api/latest").get_json()
        self.assertEqual({o["ticker"] for o in data["opportunities"]}, {"NVDA", "SAP", "MU", "2222.SR"})

    def test_empty_state(self):
        app = create_app(tempfile.mkdtemp(), tempfile.mkdtemp())
        r = app.test_client().get("/")
        self.assertIn("No analysis yet", r.get_data(as_text=True))

    def test_refresh_requires_same_origin(self):
        self.assertEqual(self.client.post("/refresh").status_code, 403)
        self.assertEqual(self.client.post("/refresh", headers={"Origin": "https://evil.example"}).status_code, 403)
        r = self.client.post("/refresh", headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 202)
        for _ in range(50):
            s = self.client.get("/refresh/status").get_json()
            if not s["running"]:
                break
            time.sleep(0.1)
        self.assertEqual(s["exit_code"], 0)

    def test_avoid_list_rows_dropped(self):
        payload = sample_payload()
        payload["opportunities"].append({"ticker": "PLTR", "name": "Palantir"})
        path = os.path.join(tempfile.mkdtemp(), "latest.json")
        _, found = dashboard_data.write_latest(payload, path)
        self.assertGreater(found, 0)
        with open(path) as f:
            self.assertNotIn("PLTR", f.read())


if __name__ == "__main__":
    unittest.main()
