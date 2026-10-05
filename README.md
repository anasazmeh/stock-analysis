# Stock Analysis Pipeline

Finds and reviews stock opportunities for a Shariah-compliant, EU-based portfolio, checks every data source before it is used, and writes a daily report and alerts.

> ⚠️ Not financial advice.

## Run

```bash
bash scripts/setup.sh    # installs packages into .venv, checks Claude Code, asks for your SEC contact + free keys → .env
source .venv/bin/activate   # in every new terminal, before the python3 commands
claude                   # once, if you have never logged in — the AI stage uses your Claude subscription
python3 main.py
```

| Command | What it does |
|---|---|
| `python3 main.py` | Full run → `reports/YYYY-MM-DD.md`, `reports/alerts_YYYY-MM-DD.txt` |
| `python3 main.py --no-ai` | Skip the Claude analysis |
| `python3 main.py --no-cache` | Ignore cached data |
| `python3 main.py --ipo "SpaceX" --broker-price 162 --amount 2000` | IPO dossier with labelled offer / market / broker prices |
| `python3 dashboard/app.py` | Web dashboard at http://127.0.0.1:8050 (portfolio, opportunities, sell review, stock pages, history, "Refresh data" button) |
| `bash scripts/setup_schedule.sh` | Email alerts + weekday cron job (asks, sends a test email, installs; `--remove` to stop) |
| `scripts/run_daily.sh` | Scheduled run (reads `.env`, logs to `logs/`, emails you if a run crashes, optional health-check pings) |
| `python3 -m src.alerts --test` | Send a test alert to the configured email / webhook |

Logs: every run started from a terminal is saved to `logs/run_YYYY-MM-DD_HHMMSS.log` (newest 30 kept); scheduled runs write `logs/run_YYYY-MM-DD.log`, and the dashboard's Refresh button writes `logs/dashboard_run.log`.

Technical debt: each run merges its warnings and errors into [`TECH_DEBT.md`](TECH_DEBT.md), grouped by cause with a suggested fix (`python3 -m src.tech_debt --scan logs/` imports older logs).

Exit codes: `0` ok · `2` degraded data · `1` avoid-list leak or missing required keys.

## Pipeline

1. **Discovery** — watchlist + holdings, S&P 500 / Nasdaq-100 and Shariah ETF momentum picks, regional screens (Saudi, UAE, DE, NL, FR).
2. **Market data** — Yahoo prices with type and time, ECB FX rates, Finnhub price cross-check, data-quality gate.
3. **SEC filings + Shariah label** — AAOIFI 30/30/5 ratios from annual statements (SEC XBRL fallback), activity screen, status history. A label only — nothing is filtered out.
4. **Earnings, insider trades, analyst consensus quality** (Alpha Vantage budget, SEC Form 4, rating changes).
5. **News and macro** — Yahoo, Finnhub, Google News, GDELT, NewsAPI; deduplicated, full text scored by FinBERT; FRED indicators.
6. **Risk, trend, regulatory watch, exposure, thesis rules, event calendar.**
7. **Claude analysis** via your logged-in Claude Code (`claude -p`, no API key) on a dated evidence pack (cites the facts it used, says when data is insufficient).
8. **Sell review** — per holding: stop the loss / protect gains / take profit / trim to cap, from the loss vs breakeven, a volatility-based trailing stop off the 6-month high, trend, thesis, analyst target and revisions, insiders, SEC red flags and Claude's holder view; suggests how many shares and the euro proceeds. Holdings with bad data get no suggestion; Shariah is listed, never scored. Thresholds: `SELL_*` / `TRAIL_STOP_*` in `config.py`.
9. **Report, run snapshot, decision journal, alerts.**

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
