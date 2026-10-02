"""
Alert system — detects key investment signals and delivers notifications.

Delivery channels (configure via environment variables):
  File:    always written to reports/alerts_YYYY-MM-DD.txt
  Email:   ALERT_EMAIL_TO + ALERT_EMAIL_FROM + ALERT_SMTP_PASSWORD
  Webhook: ALERT_WEBHOOK_URL  (Slack / Discord / any JSON POST endpoint)

To automate daily alerts, add a cron job:
  0 7 * * 1-5  cd ~/stock-analysis && python3 main.py >> logs/cron.log 2>&1
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smtplib
import requests as _requests
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config
from src.models import Opportunity, MacroContext

_LEVEL_ICON = {
    "DANGER": "🚨",
    "BUY":    "🟢",
    "DIP":    "🔵",
    "WARN":   "🟡",
    "INFO":   "ℹ️",
}


def _check_conditions(opportunities: list[Opportunity]) -> list[dict]:
    """Evaluate all alert conditions. Returns list of alert dicts."""
    alerts = []

    for opp in opportunities:
        if opp.price <= 0:
            continue

        # ── Portfolio P&L ────────────────────────────────────────────────
        if opp.portfolio and opp.portfolio.pl_pct is not None:
            pnl = opp.portfolio.pl_pct
            if pnl <= config.ALERT_PORTFOLIO_LOSS:
                alerts.append({
                    "level":   "DANGER",
                    "ticker":  opp.ticker,
                    "message": f"Portfolio down {pnl:+.1f}% vs BEP — review EXIT",
                })
            elif pnl >= config.ALERT_PORTFOLIO_GAIN:
                alerts.append({
                    "level":   "INFO",
                    "ticker":  opp.ticker,
                    "message": f"Portfolio up {pnl:+.1f}% vs BEP — consider TRIMMING",
                })

        # ── High analyst upside ──────────────────────────────────────────
        if opp.upside is not None and opp.upside >= config.ALERT_UPSIDE_MIN:
            alerts.append({
                "level":   "BUY",
                "ticker":  opp.ticker,
                "message": f"Analyst upside +{opp.upside:.1f}% (target {opp.target:.2f})",
            })

        # ── Insider activity ─────────────────────────────────────────────
        if opp.insider_signal == "Bullish":
            alerts.append({
                "level":   "BUY",
                "ticker":  opp.ticker,
                "message": f"Insider BUYING — net +{opp.insider_net_shares:,} shares (30d)",
            })
        elif opp.insider_signal == "Bearish":
            alerts.append({
                "level":   "WARN",
                "ticker":  opp.ticker,
                "message": f"Insider SELLING — net {opp.insider_net_shares:,} shares (30d)",
            })

        # ── SEC filing red flags; share-sale filings only matter for holdings ─
        for f in opp.filings:
            if f["red_flag"]:
                alerts.append({
                    "level":   "DANGER",
                    "ticker":  opp.ticker,
                    "message": f"SEC {f['form']} {f['date']}: {', '.join(f['labels'])} — {f['url']}",
                })
            elif opp.portfolio and f["form"] in ("S-3", "F-3", "424B4", "144"):
                alerts.append({
                    "level":   "WARN",
                    "ticker":  opp.ticker,
                    "message": f"SEC {f['form']} {f['date']}: {', '.join(f['labels'])} — {f['url']}",
                })

        # ── EPS surprises ────────────────────────────────────────────────
        if opp.eps_surprise is not None:
            if opp.eps_surprise >= config.ALERT_EPS_BEAT_MIN:
                alerts.append({
                    "level":   "INFO",
                    "ticker":  opp.ticker,
                    "message": f"EPS beat +{opp.eps_surprise:.1f}% last quarter",
                })
            elif opp.eps_surprise <= -10:
                alerts.append({
                    "level":   "WARN",
                    "ticker":  opp.ticker,
                    "message": f"EPS miss {opp.eps_surprise:.1f}% last quarter",
                })

        # ── Upcoming earnings (within 7 days) ────────────────────────────
        if opp.earnings_date:
            try:
                days = (date.fromisoformat(opp.earnings_date) - date.today()).days
                if 0 <= days <= 7:
                    alerts.append({
                        "level":   "INFO",
                        "ticker":  opp.ticker,
                        "message": f"Earnings in {days}d ({opp.earnings_date}) — expect volatility",
                    })
            except ValueError:
                pass

        # ── Dip buy signals ──────────────────────────────────────────────
        if opp.w52_low and opp.price < opp.w52_low * 1.05:
            alerts.append({
                "level":   "DIP",
                "ticker":  opp.ticker,
                "message": f"Within 5% of 52w low — potential dip entry",
            })

        if opp.risk and opp.risk.rsi_14 < 30:
            alerts.append({
                "level":   "DIP",
                "ticker":  opp.ticker,
                "message": f"RSI {opp.risk.rsi_14:.0f} — oversold, possible reversal",
            })

        # ── Overbought caution ───────────────────────────────────────────
        if opp.risk and opp.risk.rsi_14 > 75:
            alerts.append({
                "level":   "WARN",
                "ticker":  opp.ticker,
                "message": f"RSI {opp.risk.rsi_14:.0f} — overbought, reduce risk",
            })

    return alerts


def _format_text(alerts: list[dict], run_date: str) -> str:
    """Format alerts as plain text."""
    if not alerts:
        return f"[{run_date}] No alerts triggered.\n"

    lines = [f"Stock Analysis Alerts — {run_date}", "=" * 52, ""]
    for level in ("DANGER", "BUY", "DIP", "WARN", "INFO"):
        group = [a for a in alerts if a["level"] == level]
        if not group:
            continue
        lines.append(f"{_LEVEL_ICON[level]} {level} ({len(group)})")
        for a in group:
            lines.append(f"   {a['ticker']:10s}  {a['message']}")
        lines.append("")

    lines.append(f"Total: {len(alerts)} alert(s)")
    return "\n".join(lines)


def _send_email(subject: str, body: str) -> bool:
    """Send via SMTP (Gmail app-password or any SMTP). Returns True on success."""
    if not (config.ALERT_EMAIL_TO and config.ALERT_EMAIL_FROM and config.ALERT_SMTP_PASSWORD):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.ALERT_EMAIL_FROM
        msg["To"]      = config.ALERT_EMAIL_TO
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(config.ALERT_EMAIL_FROM, config.ALERT_SMTP_PASSWORD)
            srv.sendmail(config.ALERT_EMAIL_FROM, config.ALERT_EMAIL_TO, msg.as_string())
        return True
    except Exception as e:
        print(f"  [alerts] email failed: {e}")
        return False


def _send_webhook(text: str) -> bool:
    """POST alert to Slack/Discord/generic webhook. Returns True on success."""
    if not config.ALERT_WEBHOOK_URL:
        return False
    try:
        payload = {"text": text}  # Slack-compatible; Discord uses {"content": text}
        resp = _requests.post(
            config.ALERT_WEBHOOK_URL, json=payload, timeout=10
        )
        return resp.status_code < 300
    except Exception as e:
        print(f"  [alerts] webhook failed: {e}")
        return False


def dispatch_alerts(
    opportunities: list[Opportunity],
    macro: MacroContext,
) -> list[dict]:
    """
    Evaluate all alert conditions, write an alert file, and optionally
    deliver via email and/or webhook. Returns the triggered alert list.
    """
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    alerts   = _check_conditions(opportunities)
    text     = _format_text(alerts, run_date)

    # Always write to file
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    date_str   = datetime.now().strftime("%Y-%m-%d")
    alert_path = os.path.join(config.REPORT_DIR, f"alerts_{date_str}.txt")
    with open(alert_path, "w", encoding="utf-8") as f:
        f.write(text)

    counts = {lvl: sum(1 for a in alerts if a["level"] == lvl)
              for lvl in _LEVEL_ICON}
    print(f"  [alerts] {len(alerts)} alerts — "
          f"{counts['DANGER']} danger · {counts['BUY']} buy · "
          f"{counts['DIP']} dip · {counts['WARN']} warn")
    print(f"  [alerts] Saved: {alert_path}")

    if alerts and config.ALERT_EMAIL_TO:
        n_action = counts["DANGER"] + counts["BUY"]
        subject  = (f"[Stock Alert] {len(alerts)} signals, "
                    f"{n_action} action items — {date_str}")
        if _send_email(subject, text):
            print(f"  [alerts] Email → {config.ALERT_EMAIL_TO}")

    if alerts and config.ALERT_WEBHOOK_URL:
        if _send_webhook(text):
            print(f"  [alerts] Webhook delivered")

    return alerts
