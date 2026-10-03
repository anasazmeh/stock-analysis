# Stock Analysis Pipeline

Finds and reviews stock opportunities for a Shariah-compliant, EU-based portfolio, checks every data source before it is used, and writes a daily report and alerts.

> ⚠️ Not financial advice.

## Run

```bash
bash scripts/setup.sh    # installs packages, checks Claude Code, asks for your SEC contact + free keys → .env
claude                   # once, if you have never logged in — the AI stage uses your Claude subscription
python3 main.py
```

| Command | What it does |
|---|---|
| `python3 main.py` | Full run → `reports/YYYY-MM-DD.md`, `reports/alerts_YYYY-MM-DD.txt` |
| `python3 main.py --no-ai` | Skip the Claude analysis |
| `python3 main.py --no-cache` | Ignore cached data |
| `python3 main.py --ipo "SpaceX" --broker-price 162 --amount 2000` | IPO dossier with labelled offer / market / broker prices |
| `scripts/run_daily.sh` | Scheduled run (reads `.env`, logs to `logs/`, optional health-check pings) |

Exit codes: `0` ok · `2` degraded data · `1` avoid-list leak or missing required keys.

## Pipeline

1. **Discovery** — watchlist + holdings, S&P 500 / Nasdaq-100 and Shariah ETF momentum picks, regional screens (Saudi, UAE, DE, NL, FR).
2. **Market data** — Yahoo prices with type and time, ECB FX rates, Finnhub price cross-check, data-quality gate.
3. **SEC filings + Shariah label** — AAOIFI 30/30/5 ratios from annual statements (SEC XBRL fallback), activity screen, status history. A label only — nothing is filtered out.
4. **Earnings, insider trades, analyst consensus quality** (Alpha Vantage budget, SEC Form 4, rating changes).
5. **News and macro** — Yahoo, Finnhub, Google News, GDELT, NewsAPI; deduplicated, full text scored by FinBERT; FRED indicators.
6. **Risk, trend, regulatory watch, exposure, thesis rules, event calendar.**
7. **Claude analysis** via your logged-in Claude Code (`claude -p`, no API key) on a dated evidence pack (cites the facts it used, says when data is insufficient).
8. **Report, run snapshot, decision journal, alerts.**

## Your files

| File | Purpose |
|---|---|
| `portfolio_data.py` | Holdings (set Yahoo tickers for your ETFs/ETCs) |
| `data/theses.json` | Thesis and sell-discipline rules per holding (copy `data/theses.example.json`) |
| `data/events.json` | Your own dates, e.g. IPO lock-up ends |
| `data/universe/*.csv` | Shariah ETF holdings downloaded from the issuer (e.g. `SPUS.csv`) |
| `data/broker/*.csv` | DEGIRO / Revolut exports for reconciliation (git-ignored) |
| `data/decisions.jsonl` | Decision journal — fill in `user_action` |
| `config.py` | Watchlist, caps, thresholds, Shariah methodology, rank weights |

## Tests

```bash
python3 -m unittest discover tests
```
