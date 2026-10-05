"""
Alert system — detects key investment signals and delivers notifications.

Delivery channels (configure via environment variables):
  File:    always written to reports/alerts_YYYY-MM-DD.txt
  Email:   ALERT_EMAIL_TO + ALERT_EMAIL_FROM + ALERT_SMTP_PASSWORD
  Webhook: ALERT_WEBHOOK_URL  (Slack / Discord / any JSON POST endpoint)

Safeguards: price-based alerts are held back when the price failed its
cross-check, the ticker failed the data gate, or the broker export disagrees
with portfolio_data.py. BUY/ADD signals wait during the earnings blackout, skip
names your broker can't trade, and turn into WATCH when an ADD would break a
concentration cap. Thesis and Shariah alerts fire only when the status changes.
Every alert names the stock's Shariah status and the text carries a disclaimer.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smtplib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests as _requests
import config
from src.models import Opportunity, MacroContext
from src.events import earnings_blackout
from src.theses import is_exit_candidate
from src.portfolio import breaches_after_add
from src.output_gate import scrub

DISCLAIMER = "⚠️ Not financial advice. Check prices on your broker before acting."
_LEVEL_ICON = {"DANGER": "🚨", "BUY": "🟢", "DIP": "🔵", "WARN": "🟡", "INFO": "ℹ️"}


def _shariah(opp: Opportunity) -> str:
    return f"Shariah: {opp.shariah.compliant}" if opp.shariah else "Shariah: Unknown"


def _add(alerts, level, ticker, message):
    alerts.append({"level": level, "ticker": ticker, "message": message})


def check_conditions(opportunities: list[Opportunity], health=None, exposure: dict = None,
                     previous: dict = None, broker_diffs: list = None, macro: MacroContext = None) -> list[dict]:
    alerts = []
    prev = {r["ticker"]: r for r in (previous or {}).get("tickers", [])}
    broker_bad = {d["ticker"] for d in (broker_diffs or [])}
    exposure = exposure or {}

    if health is not None and health.degraded:
        _add(alerts, "DANGER", "RUN", "Data is DEGRADED — " + "; ".join(health.degraded_reasons)
             + ". BUY and DIP alerts suppressed this run.")
    for b in exposure.get("breaches", []):
        _add(alerts, "WARN", "PORTFOLIO", f"Concentration: {b}")
    for g in (macro.geo_themes if macro else []):
        pct = f" — {g['portfolio_exposed_pct']:.0f}% of your portfolio exposed" if g.get("portfolio_exposed_pct") else ""
        _add(alerts, "INFO", "GEO", f"{g['theme']}: {g['latest']['title'][:90]} ({g['latest']['date']}){pct}")
    allow_new_signals = not (health is not None and health.degraded)

    for opp in opportunities:
        if opp.price <= 0:
            if opp.portfolio is not None:
                _add(alerts, "WARN", opp.ticker, "Holding has no price this run — check the data source")
            continue
        p_prev = prev.get(opp.ticker, {})
        price_ok = opp.price_check != "Mismatch" and opp.data_ok
        if opp.price_check == "Mismatch":
            _add(alerts, "WARN", opp.ticker,
                 f"Price mismatch: Yahoo {opp.price:.2f} vs Finnhub {opp.price_alt:.2f} "
                 f"({opp.price_diff_pct:+.1f}%) — price-based alerts held back; check your broker")
        elif not opp.data_ok and opp.portfolio:
            _add(alerts, "WARN", opp.ticker, "Data gaps (" + ", ".join(opp.data_flags) + ") — price-based alerts held back")
        if opp.ticker in broker_bad:
            _add(alerts, "WARN", opp.ticker, "Broker export disagrees with portfolio_data.py — P&L alerts held back")

        # ── Holdings: P&L, thesis, Shariah status changes ──
        if opp.portfolio:
            pl = opp.portfolio.pl_pct
            if price_ok and opp.ticker not in broker_bad and pl is not None:
                if pl <= config.ALERT_PORTFOLIO_LOSS:
                    _add(alerts, "DANGER", opp.ticker, f"Position {pl:+.1f}% vs breakeven ({opp.portfolio.bep_currency}) — review EXIT. {config.BROKER_COST_NOTE}")
                elif pl >= config.ALERT_PORTFOLIO_GAIN:
                    _add(alerts, "INFO", opp.ticker, f"Position {pl:+.1f}% vs breakeven ({opp.portfolio.bep_currency}) — consider TRIMMING")
            before = p_prev.get("thesis_status")
            if before and opp.thesis_status != before:
                level = "DANGER" if opp.thesis_status == "Broken" else "INFO"
                _add(alerts, level, opp.ticker, f"Thesis {before} → {opp.thesis_status}: " + "; ".join(opp.thesis_notes[-3:]))
            s_before = opp.shariah.previous if opp.shariah else ""
            if opp.shariah and s_before and s_before != opp.shariah.compliant:
                level = "DANGER" if s_before == "Yes" and opp.shariah.compliant == "No" else "WARN"
                _add(alerts, level, opp.ticker, f"Shariah status changed {s_before} → {opp.shariah.compliant}: "
                     + "; ".join(opp.shariah.reasons[:2]))

            sr = opp.sell_review or {}
            if sr.get("strength") == "Strong" and sr.get("category") in ("Stop the loss", "Protect gains"):
                _add(alerts, "DANGER", opp.ticker, f"Sell review: {sr['category']} — {sr['action']}. {config.BROKER_COST_NOTE}")
            elif sr.get("strength") == "Strong":
                _add(alerts, "INFO", opp.ticker, f"Sell review: {sr['category']} — {sr['action']}")

        # ── New-money signals ──
        can_signal = allow_new_signals and price_ok and opp.tradable != "Watch only" and not is_exit_candidate(opp)
        upside = opp.adj_upside
        if can_signal and upside is not None and upside >= config.ALERT_UPSIDE_MIN:
            if earnings_blackout(opp):
                _add(alerts, "INFO", opp.ticker, f"Quality-adjusted upside +{upside:.0f}% but {opp.next_event} "
                     f"in {opp.days_to_event} trading days — wait for results. {_shariah(opp)}")
            else:
                breaches = breaches_after_add(opp, exposure) if opp.portfolio else []
                if breaches:
                    _add(alerts, "WARN", opp.ticker, f"WATCH (upside +{upside:.0f}%) — an ADD would break caps: "
                         + "; ".join(breaches) + f". {_shariah(opp)}")
                else:
                    _add(alerts, "BUY", opp.ticker, f"Quality-adjusted analyst upside +{upside:.0f}% "
                         f"(target {opp.target:.2f}, {opp.analyst_count or '?'} analysts, {opp.consensus_quality}). {_shariah(opp)}")

        if can_signal and opp.trend != "Downtrend":
            if opp.w52_low and opp.price < opp.w52_low * 1.05:
                _add(alerts, "DIP", opp.ticker, f"Within 5% of 52-week low, trend {opp.trend}. {_shariah(opp)}")
            if opp.risk and opp.risk.rsi_14 is not None and opp.risk.rsi_14 < 30:
                _add(alerts, "DIP", opp.ticker, f"RSI {opp.risk.rsi_14:.0f} — oversold, trend {opp.trend}. {_shariah(opp)}")
        if price_ok and opp.risk and opp.risk.rsi_14 is not None and opp.risk.rsi_14 > 75:
            _add(alerts, "WARN", opp.ticker, f"RSI {opp.risk.rsi_14:.0f} — overbought")

        # ── Insider, filings, earnings ──
        if opp.insider_signal == "Bullish":
            _add(alerts, "INFO" if not can_signal else "BUY", opp.ticker,
                 f"Insider BUYING — net +{opp.insider_net_shares:,} shares (30d). {_shariah(opp)}")
        elif opp.insider_signal == "Bearish":
            _add(alerts, "WARN", opp.ticker, f"Insider SELLING — net {opp.insider_net_shares:,} shares (30d)")
        for f in opp.filings:
            if f["red_flag"]:
                _add(alerts, "DANGER", opp.ticker, f"SEC {f['form']} {f['date']}: {', '.join(f['labels'])} — {f['url']}")
            elif opp.portfolio and f["form"] in ("S-3", "F-3", "424B4", "144"):
                _add(alerts, "WARN", opp.ticker, f"SEC {f['form']} {f['date']}: {', '.join(f['labels'])} — {f['url']}")
        if opp.eps_surprise is not None:
            if opp.eps_surprise >= config.ALERT_EPS_BEAT_MIN:
                _add(alerts, "INFO", opp.ticker, f"EPS beat +{opp.eps_surprise:.1f}% last quarter")
            elif opp.eps_surprise <= -10:
                _add(alerts, "WARN", opp.ticker, f"EPS miss {opp.eps_surprise:.1f}% last quarter")
        if opp.days_to_event is not None and opp.days_to_event <= 5 and (opp.portfolio or can_signal):
            _add(alerts, "INFO", opp.ticker, f"{opp.next_event} in {opp.days_to_event} trading days — expect volatility")
    return alerts


# kept for the old name used in tests and elsewhere
def _check_conditions(opportunities: list[Opportunity]) -> list[dict]:
    return check_conditions(opportunities)


def format_text(alerts: list[dict], run_date: str) -> str:
    if not alerts:
        return f"[{run_date}] No alerts triggered.\n{DISCLAIMER}\n"
    lines = [f"Stock Analysis Alerts — {run_date}", "=" * 52, ""]
    for level in ("DANGER", "BUY", "DIP", "WARN", "INFO"):
        group = [a for a in alerts if a["level"] == level]
        if not group:
            continue
        lines.append(f"{_LEVEL_ICON[level]} {level} ({len(group)})")
        lines += [f"   {a['ticker']:10s}  {a['message']}" for a in group]
        lines.append("")
    lines += [f"Total: {len(alerts)} alert(s)", "", DISCLAIMER]
    return "\n".join(lines)


def _send_email(subject: str, body: str) -> bool:
    if not (config.ALERT_EMAIL_TO and config.ALERT_EMAIL_FROM and config.ALERT_SMTP_PASSWORD):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, config.ALERT_EMAIL_FROM, config.ALERT_EMAIL_TO
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(config.ALERT_EMAIL_FROM, config.ALERT_SMTP_PASSWORD)
            srv.sendmail(config.ALERT_EMAIL_FROM, config.ALERT_EMAIL_TO, msg.as_string())
        return True
    except (smtplib.SMTPException, OSError) as e:
        print(f"  [alerts] email failed: {type(e).__name__}")
        return False


def _send_webhook(text: str) -> bool:
    if not config.ALERT_WEBHOOK_URL:
        return False
    try:
        resp = _requests.post(config.ALERT_WEBHOOK_URL, json={"text": text, "content": text[:1900]}, timeout=10)
        return resp.status_code < 300
    except _requests.RequestException as e:
        print(f"  [alerts] webhook failed: {type(e).__name__}")  # URL may contain a secret token
        return False


def dispatch_alerts(opportunities: list[Opportunity], macro: MacroContext, health=None, exposure: dict = None,
                    previous: dict = None, broker_diffs: list = None) -> tuple[list[dict], int]:
    """Evaluate, write and deliver alerts. Returns (alerts, lines removed by the avoid-list gate)."""
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    alerts = check_conditions(opportunities, health, exposure, previous, broker_diffs, macro)
    text, removed = scrub(format_text(alerts, run_date))

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    date_str = date.today().isoformat()
    alert_path = os.path.join(config.REPORT_DIR, f"alerts_{date_str}.txt")
    with open(alert_path, "w", encoding="utf-8") as f:
        f.write(text)

    counts = {lvl: sum(1 for a in alerts if a["level"] == lvl) for lvl in _LEVEL_ICON}
    print(f"  [alerts] {len(alerts)} alerts — {counts['DANGER']} danger · {counts['BUY']} buy · "
          f"{counts['DIP']} dip · {counts['WARN']} warn · saved {alert_path}")

    degraded = health is not None and health.degraded
    if (alerts or degraded) and config.ALERT_EMAIL_TO:
        subject = (f"[Stock Alert]{' DEGRADED' if degraded else ''} {len(alerts)} signals, "
                   f"{counts['DANGER'] + counts['BUY']} action items — {date_str}")
        if _send_email(subject, text):
            print(f"  [alerts] Email sent to {config.ALERT_EMAIL_TO}")
    if (alerts or degraded) and config.ALERT_WEBHOOK_URL and _send_webhook(text):
        print("  [alerts] Webhook delivered")
    return alerts, removed


def send_test() -> bool:
    """Send a test message to every configured channel. Returns True if all configured channels worked."""
    text = f"Test message from the stock-analysis pipeline ({datetime.now():%Y-%m-%d %H:%M}).\n" \
           f"Alerts will arrive like this after each scheduled run that finds signals.\n\n{DISCLAIMER}"
    results = []
    if config.ALERT_EMAIL_TO:
        ok = _send_email("[Stock Alert] Test message", text)
        print(f"Email to {config.ALERT_EMAIL_TO}: {'sent' if ok else 'FAILED (check ALERT_* settings in .env)'}")
        results.append(ok)
    if config.ALERT_WEBHOOK_URL:
        ok = _send_webhook(text)
        print(f"Webhook: {'delivered' if ok else 'FAILED'}")
        results.append(ok)
    if not results:
        print("No alert channel configured (set ALERT_EMAIL_TO/FROM/SMTP_PASSWORD or ALERT_WEBHOOK_URL in .env).")
    return bool(results) and all(results)


def notify_failure(log_path: str, exit_code: int) -> bool:
    """Tell the configured channels that a scheduled run crashed, with the end of its log."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-30:])
    except OSError:
        tail = "(log not readable)"
    tail, _ = scrub(tail)
    text = f"The scheduled run failed with exit code {exit_code}. No report or alerts were produced.\n" \
           f"Log: {log_path}\n\n--- last lines ---\n{tail}\n{DISCLAIMER}"
    sent = _send_email(f"[Stock Alert] Run FAILED — {date.today().isoformat()}", text) if config.ALERT_EMAIL_TO else False
    if config.ALERT_WEBHOOK_URL:
        sent = _send_webhook(text) or sent
    return sent


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Alert channel tools")
    p.add_argument("--test", action="store_true", help="send a test message to the configured channels")
    p.add_argument("--notify-failure", nargs=2, metavar=("LOG", "EXIT_CODE"), help="report a crashed run")
    a = p.parse_args()
    if a.test:
        sys.exit(0 if send_test() else 1)
    if a.notify_failure:
        notify_failure(a.notify_failure[0], int(a.notify_failure[1]))
    else:
        p.print_help()
