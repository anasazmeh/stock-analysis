# TODO / Roadmap

> Track outstanding tasks and next steps for the stock analysis pipeline.

---

## 🔴 Immediate — Do These First

### ✅ Your checklist (status as of 2026-10-05)
Setup on the Mac
- [x] `bash scripts/setup.sh` — packages in `.venv`, SEC contact, keys in `.env`
- [x] Claude Code installed and logged in
- [x] Dashboard runs at http://127.0.0.1:8050
- [x] Daily run scheduled (weekdays 12:00)
- [ ] Test email arrives (Hotmail inbox or Junk) — if not, `bash scripts/setup_schedule.sh`, answer `y`, fresh Gmail app password
- [ ] First full run `python3 main.py`, then every source ✅ in **Data Health**
- [ ] Add `FRED_API_KEY` once received (re-run `bash scripts/setup.sh`; it only asks for missing keys)

Portfolio data
- [ ] Yahoo tickers for the Nasdaq-100 ETF, gold ETC and silver ETC in `portfolio_data.py` (unpriced until set)
- [ ] Keep `shares` / `bep` current after each trade — or put DEGIRO / Revolut CSV exports in `data/broker/`
- [ ] Copy `data/theses.example.json` → `data/theses.json`; write a thesis and sell rules per holding
- [ ] Set `TAX_RESIDENCE` in `config.py`

After the first real run
- [ ] Abu Dhabi (`.AD`) and Dubai (`.AE`) tickers not flagged "wrong listing"
- [ ] Add broker-tradable "Watch only" names to `TRADABILITY_OVERRIDES`

Optional
- [ ] healthchecks.io ping URL (warns when the Mac slept through 12:00)
- [ ] FinBERT sentiment: `.venv/bin/python -m pip install -r requirements-ml.txt` (~1-2 GB)
- [ ] Monthly SPUS / HLAL / ISWD holdings CSVs in `data/universe/`
- [ ] Slack / Discord alerts: `ALERT_WEBHOOK_URL` in `.env`

The sections below explain each step.

### Quick setup
Run `bash scripts/setup.sh` — it installs the packages, checks Claude Code, and asks for your name/email
(SEC contact) and the free keys below, saving them to `.env` (private, git-ignored, read automatically).

### 0. AI analysis — no API key needed
The Claude stage runs through your logged-in Claude Code (`claude -p`), so it uses your Claude
subscription instead of a paid API key. Install Claude Code, run `claude` once and log in — that's it.
Settings in `config.py`: `AI_BACKEND` ("claude-cli" / "api" / "off"), `CLAUDE_CLI_MODEL`
("opus" / "sonnet"), `AI_MAX_TICKERS` (holdings first; lower it to use less of your plan's limits).

### 1. Get Free API Keys
Four keys unlock features already coded in the pipeline:

| Key | Sign-up URL | Unlocks |
|-----|-------------|---------|
| `NEWSAPI_KEY` | https://newsapi.org → Get API Key (2 min) | Keyword sentiment scoring per ticker |
| `ALPHA_VANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key (2 min) | Missing analyst targets, earnings dates, EPS surprises |
| `FINNHUB_API_KEY` | https://finnhub.io/register (free) | Second price source — flags Yahoo prices that disagree; extra company news |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html (free) | Fed rate, CPI, yield curve, VIX in the macro section |

`bash scripts/setup.sh` asks for them and saves them to `.env`; you can also add `KEY="value"` lines to `.env` by hand.

### 1b. Set Up the Free No-Key Sources
These run automatically (GDELT, SEC filings, Wikipedia index lists, article text), but need:

- **SEC contact** — SEC requires a real name and email in requests:
  `export SEC_USER_AGENT="Your Name your@email.com"`
- **FinBERT sentiment** (optional, ~1-2 GB download): `pip install -r requirements-ml.txt`
- **Shariah ETF holdings** (optional): download the holdings CSV from the issuer's site
  (e.g. SPUS / HLAL / ISWD) into `data/universe/`, named after the ETF (`SPUS.csv`).
  Refresh monthly. Their tickers are added to discovery and shown as a label.
- GDELT asks for ≤1 request per 5 s, so Stage 3b takes ~4 min for 40 tickers
  (`GDELT_MAX_TICKERS` in `config.py`; cached for 4 h).

### 2. Set Up Daily Automated Alerts
```bash
bash scripts/setup_schedule.sh
```
It asks for the address to email alerts to and a Gmail app password, sends a test email, then installs a
weekday cron job (default 07:00, your computer's time). It is safe to re-run; `--remove` stops the daily run.
- Email goes out when a run finds signals, when a run is degraded, and when a run crashes (with the end of the log).
- Optional `HEALTHCHECK_URL` (a free healthchecks.io check) warns you when a run never starts — e.g. the computer was off.
- Slack/Discord instead of, or as well as, email: add `ALERT_WEBHOOK_URL="https://hooks.slack.com/..."` to `.env`.
- Test the channels any time: `python3 -m src.alerts --test`. Logs: `logs/run_YYYY-MM-DD.log`.
- macOS: cron skips runs while the Mac sleeps.

### 3. Keep Portfolio Data Current
- `portfolio_data.py`: update `bep` and `shares` after every trade.
- **Set the Yahoo tickers of your three funds** (Nasdaq-100 ETF, gold ETC, silver ETC) — they show as "not priced" until then.
- Export DEGIRO / Revolut CSVs into `data/broker/` — every run then checks `portfolio_data.py` against them.
- Copy `data/theses.example.json` to `data/theses.json` and write a thesis + invalidation rules per holding.
- Add your own dates (IPO lock-ups, AGMs) to `data/events.json`.
- Set `TAX_RESIDENCE` in `config.py`.

### 4. Verify On Your Machine (blocked in the cloud sandbox)
- First full run: check the **Data Health** section — every source should be ✅.
- Abu Dhabi tickers use `.AD`; confirm Yahoo resolves them (a wrong listing shows as "wrong listing" in Data gaps).
- Dubai tickers moved from `.DU` to `.AE`.
- Saudi / UAE / India / Korea names are marked "Watch only" (not on DEGIRO/Revolut) — override in `TRADABILITY_OVERRIDES` if your broker offers them.

---

## 🧰 Technical Debt

### From the logs (automatic)
Every run collects the warnings and errors it prints, plus library warnings (yfinance, pandas) and any
Data Health source that wasn't ✅, and merges them into **[TECH_DEBT.md](TECH_DEBT.md)**: grouped by cause
(network, missing setup, symbol, email, data quality, code bug), with the tickers affected, how many runs
it appeared in and a suggested fix. Items not seen for 5 runs move to *Resolved*.
- [ ] After a few real runs, work through TECH_DEBT.md top to bottom (errors first)
- [ ] Import the logs you already have: `python3 -m src.tech_debt --scan logs/`
- [ ] Commit TECH_DEBT.md now and then so the backlog is visible on GitHub

### Known design debt
- [ ] **No CI** — tests only run by hand; add a GitHub Actions workflow running `python3 -m unittest discover tests`
- [ ] **Live-data parsers are tested against documented formats only** (the build sandbox can't reach Yahoo, SEC,
      GDELT…) — save a few real responses as test fixtures after the first runs
- [ ] **Abu Dhabi suffix unconfirmed** (`.AD` vs `.AE` on Yahoo) — check the "Symbol lookup" line in Data Health, then fix `config.py`
- [ ] **`MACRO_EVENTS` in `config.py` ends on 2026-12-17** — add the 2027 Fed / ECB / CPI dates before then
- [ ] **Most modules report with `print()`** — issue capture relies on wording ("failed", "✗", "warning");
      move to `logging` with levels when touching a module
- [ ] **yfinance is an unofficial Yahoo API** — it breaks every few months; the Finnhub price cross-check is the
      safety net, keep the key set
- [ ] **Broker CSV import** column names are guessed from DEGIRO / Revolut docs — check against your real exports
- [ ] **Dashboard uses Flask's development server** — fine on 127.0.0.1, never expose it to a network
- [ ] **Shariah ratios use annual statements** — quarterly data would catch debt changes sooner

---

## 🖥️ Web Dashboard
`python3 dashboard/app.py` → http://127.0.0.1:8050 (local only). Pages: Overview (alerts, what changed,
events, Top 10, data health), Portfolio (sortable holdings, P&L and exposure charts, thesis checks,
purification), Opportunities (filters, sortable table, regional heatmap), Sell review (stop the loss /
protect gains / take profit / trim, with shares and euro estimates), a page per stock (price chart,
AI view, Shariah ratios, risk, filings, news) and History (portfolio vs MSCI World Islamic).
"Refresh data" runs the pipeline in the background. Data comes from `reports/latest.json`, written by every run.

---

## ✅ Completed

- [x] yfinance fundamentals pipeline (7 stages)
- [x] Multi-region watchlist: US, Europe, Asia, Middle East (Saudi + UAE)
- [x] Multi-currency price display (USD, EUR, GBP, SAR, AED, KRW, JPY, INR)
- [x] Shariah compliance screening (AAOIFI standard)
- [x] Risk scoring (beta, volatility, drawdown, D/E, RSI, geo exposure)
- [x] Alpha Vantage enrichment — missing targets, earnings dates, EPS surprises
- [x] Argaam Saudi analyst targets for `.SR` tickers
- [x] SEC EDGAR Form 4 insider trading signals (US tickers, no key needed)
- [x] NewsAPI keyword sentiment scoring (fallback when Claude unavailable)
- [x] Portfolio P&L integration — live price vs BEP, unrealised gain/loss
- [x] Alert system — file + email + webhook, 9 trigger conditions
- [x] UAE coverage: 5 Abu Dhabi (`.AD`) + 3 Dubai (`.DU`) tickers
- [x] AVOID_LIST — PLTR and GRAB permanently excluded
- [x] Regional breakdown section in report
- [x] GDELT news, SEC filings watch, Trafilatura + FinBERT, index / Shariah-ETF universe
- [x] Finnhub price cross-check; price source, type and time on every row
- [x] Roadmap "Now": EUR P&L via ECB FX · accurate Shariah label (AAOIFI 30/30/5, statement inputs, currency-consistent, label only) · data-quality gate + DEGRADED runs · fixed news and Form 4 parsers · grounded Claude evidence packs · single entry point + avoid-list output gate
- [x] Roadmap "Next": event calendar + earnings blackout · Alpha Vantage budget · consensus quality · exposure caps + funds in holdings · IPO dossier mode · regional discovery · filings-driven Shariah review · Shariah second-opinion links + status history · news normalisation · trend + sell discipline · decision journal + run snapshots · Gulf symbols + broker coverage · broker CSV reconciliation · Federal Register regulatory watch · Data Health, run script, tests
- [x] Web dashboard (Flask + Chart.js, works offline)
- [x] Sell review tab: trailing stop, drawdown from 6-month high, 3-month return; sell verdicts with share counts and EUR estimates
- [x] Roadmap "Later": crowding (short interest) · purification estimate · tax/broker cost notes · price-type labelling + liquidity flag · monthly scorecard vs MSCI World Islamic

## ⏳ Not Done (deliberately)
- TSMC monthly revenue / SIA chip sales as data (only the release dates are in the calendar — no stable free API).
- Saudi Exchange / ADX / DFM announcement scraping (GDELT's translated search covers Arabic news meanwhile).
- Alpha Vantage NEWS_SENTIMENT (the 25-call daily budget is better spent on earnings and targets; FinBERT covers sentiment).
- OpenFIGI ISIN mapping (tradability uses exchange rules + `TRADABILITY_OVERRIDES` instead).
- Zoya / Halal Terminal API second opinion (paid/limited; the report links to Musaffa and Zoya pages instead).
