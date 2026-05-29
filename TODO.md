# TODO / Roadmap

> Track outstanding tasks and next steps for the stock analysis pipeline.

---

## 🔴 Immediate — Do These First

### 1. Get Free API Keys
Three keys unlock features already coded in the pipeline:

| Key | Sign-up URL | Unlocks |
|-----|-------------|---------|
| `NEWSAPI_KEY` | https://newsapi.org → Get API Key (2 min) | Keyword sentiment scoring per ticker |
| `ALPHA_VANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key (2 min) | Missing analyst targets, earnings dates, EPS surprises |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com (5 min) | Full AI investment thesis per ticker |

Export them before running:
```bash
export NEWSAPI_KEY="your_key"
export ALPHA_VANTAGE_API_KEY="your_key"
export ANTHROPIC_API_KEY="your_key"
python3 main.py
```

### 2. Set Up Daily Automated Alerts
Add a cron job to run the pipeline every weekday at 7 AM:
```bash
crontab -e
# Add this line:
0 7 * * 1-5  cd ~/stock-analysis && python3 main.py >> ~/stock-analysis/logs/cron.log 2>&1
```

For email/webhook delivery of alerts, also set:
```bash
export ALERT_EMAIL_TO="your@email.com"
export ALERT_EMAIL_FROM="sender@gmail.com"
export ALERT_SMTP_PASSWORD="gmail_app_password"
# or for Slack/Discord:
export ALERT_WEBHOOK_URL="https://hooks.slack.com/..."
```

### 3. Keep Portfolio Data Current
- File: `portfolio_data.py`
- Update `bep` and `shares` after every trade
- The pipeline auto-includes your holdings in every run

---

## 🟡 Next Feature — Web Dashboard

Build a simple Flask web UI so the report is viewable in a browser with:
- Sortable tables (by upside, risk, P&L, region)
- Portfolio P&L bar chart
- Regional heatmap
- Alert badge / notification panel

Estimated effort: ~1 day of work.
All data is already produced by the pipeline — the dashboard just needs to render it.

Tech stack suggestion: Flask + Jinja2 templates + Chart.js (no heavy frontend build needed).

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
