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
| `python3 dashboard/app.py` | Web dashboard at http://127.0.0.1:8050 (portfolio, opportunities, sell review, cash plan, stock pages, history, "Refresh data" button) |
| `bash scripts/setup_schedule.sh` | Email alerts + weekday cron job (asks, sends a test email, installs; `--remove` to stop) |
| `scripts/run_daily.sh` | Scheduled run (reads `.env`, logs to `logs/`, emails you if a run crashes, optional health-check pings) |
| `python3 -m src.alerts --test` | Send a test alert to the configured email / webhook |

### From your phone (at home or outside)
```bash
bash scripts/setup_remote.sh            # password + auto-start + Tailscale (your devices only)
bash scripts/setup_remote.sh --public   # optional: public https link, no app needed on the device
```
The dashboard keeps running on your Mac (where Claude Code is logged in) behind a password: every page, the
JSON API and **Refresh data** need login; 5 wrong tries lock that address for 15 minutes; login lasts 30 days
per device. [Tailscale](https://tailscale.com) (free) gives your devices an encrypted https address; the dashboard
itself only listens on 127.0.0.1. The Mac must be on and awake (the script keeps it awake while plugged in).
**Refresh data** shows the elapsed time and current stage, has a Cancel button and a log page (`/refresh/log`); a run is stopped after `REFRESH_TIMEOUT_MIN` (60). A full run takes several minutes — Claude reviews up to `AI_MAX_TICKERS` stocks, `AI_PARALLEL` calls at a time.
`--private` removes the public link, `--stop` turns remote access off. On the phone, *Add to Home Screen* opens it like an app.

Logs: every run started from a terminal is saved to `logs/run_YYYY-MM-DD_HHMMSS.log` (newest 30 kept); scheduled runs write `logs/run_YYYY-MM-DD.log`, and the dashboard's Refresh button writes `logs/dashboard_run.log`.

Technical debt: each run merges its warnings and errors into [`TECH_DEBT.md`](TECH_DEBT.md), grouped by cause with a suggested fix (`python3 -m src.tech_debt --scan logs/` imports older logs).

Tests: `python3 -m unittest discover tests` — GitHub runs them automatically on every push and pull request (`.github/workflows/tests.yml`).

Exit codes: `0` ok · `2` degraded data · `1` avoid-list leak or missing required keys.

## Your investor profile
`INVESTOR_PROFILE` in `config.py` (now: **+100% in 12 months, single-stock drops up to 50% accepted, at most 20% per stock**):
- Ranking switches to `RANK_WEIGHTS_GROWTH` — upside 30%, revenue/earnings growth 25%, trend 20%, sentiment 15%, steadiness 10%.
- Claude is told the goal and rates buy / watch / avoid against it, with one sentence on how each stock could (not) contribute.
- A **Goal fit** column (Strong / Possible / Unlikely) on Opportunities and each stock page: analyst upside vs the goal, revenue growth, and a warning when a stock fell more than your accepted drop.
- Sell rules widen: stop-loss at −35% (0.7 × the accepted drop), take profit at the goal (+100%), trailing stop up to 40%.
- The Cash plan uses the 20% position limit and asks 30% upside when Claude is off.
Set `"enabled": False` to go back to the balanced defaults.

## Pipeline

1. **Discovery** — watchlist + holdings, S&P 500 / Nasdaq-100 and Shariah ETF momentum picks, regional screens (Saudi, UAE, DE, NL, FR).
2. **Market data** — Yahoo prices with type and time, ECB FX rates, Finnhub price cross-check, data-quality gate.
3. **SEC filings + Shariah label** — AAOIFI 30/30/5 ratios from annual statements (SEC XBRL fallback), activity screen, status history. A label only — nothing is filtered out.
4. **Earnings, insider trades, analyst consensus quality** (Alpha Vantage budget, SEC Form 4, rating changes).
5. **News and macro** — Yahoo, Finnhub, Google News, GDELT, NewsAPI; deduplicated, full text scored by FinBERT; FRED indicators.
6. **Risk, trend, regulatory watch, exposure, thesis rules, event calendar.**
7. **Claude analysis** via your logged-in Claude Code (`claude -p`, no API key) on a dated evidence pack (cites the facts it used, says when data is insufficient).
8. **Sell review** — per holding: stop the loss / protect gains / take profit / trim to cap, from the loss vs breakeven, a volatility-based trailing stop off the 6-month high, trend, thesis, analyst target and revisions, insiders, SEC red flags and Claude's holder view; suggests how many shares and the euro proceeds. Holdings with bad data get no suggestion; Shariah is listed, never scored. Thresholds: `SELL_*` / `TRAIL_STOP_*` in `config.py`.
9. **Cash plan** — what to do with the money sales free up. Market risk level (Calm / Normal / Elevated / Stressed) from VIX, the US high-yield credit spread, the S&P 500 vs its 200-day average and 52-week high, the yield curve and Claude's read → cash reserve of 5–15% of the portfolio, plus tax on realised gains and planned withdrawals. The rest goes down the **Top 10 from the Opportunities tab, in the same order and weighted by the same rank score**, skipping names that fail a buy check (not tradable, Claude not a buy, downtrend, being sold, at the position cap) — every Top 10 name shows its outcome on both tabs. Money the Top 10 can't take (few qualify, 40% per-idea limit, position cap) gets its own decision: **keep ready** for Top 10 names that miss only on timing (Claude "watch", downtrend) but have upside; **hold as cash** in Elevated/Stressed markets; in Calm/Normal markets **next-in-line stocks** (ranks 11–20 that pass every check), then a **broad Shariah ETF** (`PARKING_ETF`, default ISWD — MSCI World Islamic) up to `PARKING_MAX_PCT`. `LEFTOVER_POLICY` = auto / cash / etf. Duplicate listings of one company (e.g. Apple as APC.F and APC.DE) are collapsed to one. Tranches in nervous markets, before big macro events and around earnings. Two scenarios (Strong sells / + Consider). Inputs: `CASH_EUR` and `PLANNED_WITHDRAWALS_EUR` in `portfolio_data.py`, `CASH_TARGET_PCT`, `REINVEST_*`, fees and tax in `config.py`.
10. **Report, run snapshot, decision journal, alerts.**

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
