#!/usr/bin/env python3
"""
Global Stock Market Analyzer
Run: python3 analyze.py
Refreshes live data and generates a full Markdown report.
"""

import yfinance as yf
from datetime import datetime
import os

# ─────────────────────────────────────────────
# WATCHLIST — edit freely to add/remove tickers
# ─────────────────────────────────────────────
WATCHLIST = {
    # Ticker : (Region, Shariah, Notes)
    "NVDA":    ("🇺🇸 US",        "⚠️ Partial", "AI infrastructure king"),
    "MSFT":    ("🇺🇸 US",        "⚠️ Partial", "Azure AI + Copilot"),
    "AMZN":    ("🇺🇸 US",        "⚠️ Partial", "AWS + AI cloud"),
    "AVGO":    ("🇺🇸 US",        "❌ No",       "VMware debt too high"),
    "PLTR":    ("🇺🇸 US",        "✅ Yes",      "Zero debt, AI gov contracts"),
    "ISRG":    ("🇺🇸 US",        "✅ Yes",      "Surgical robotics monopoly"),
    "MU":      ("🇺🇸 US",        "✅ Yes",      "AI memory chips HBM3E"),
    "ARM":     ("🇺🇸 US",        "⚠️ Partial", "High beta 4.1x — volatile"),
    "BABA":    ("🇨🇳 China",     "❌ No",       "Cheapest mega-cap globally"),
    "BIDU":    ("🇨🇳 China",     "❌ No",       "AI + autonomous vehicles"),
    "TSM":     ("🇹🇼 Taiwan",    "✅ Yes",      "AI chip monopoly"),
    "ASML":    ("🇪🇺 EU",        "✅ Yes",      "EUV lithography monopoly"),
    "SAP":     ("🇪🇺 EU",        "✅ Yes",      "Enterprise AI software"),
    "SE":      ("🇸🇬 Singapore", "⚠️ Partial", "SE Asia super-app"),
    "GRAB":    ("🇸🇬 Singapore", "⚠️ Partial", "SE Asia fintech/ride-hail"),
}

# Baseline prices from March 18, 2026 (update after each refresh if desired)
BASELINE = {
    "NVDA": 181.93, "MSFT": 399.41, "AMZN": 215.20, "AVGO": 321.31,
    "PLTR": 155.08, "ISRG": 482.76, "MU": 461.69,   "ARM":  127.31,
    "BABA": 136.57, "BIDU": 120.69, "TSM": 345.98,  "ASML": 1389.16,
    "SAP":  190.12, "SE":   87.59,  "GRAB": 3.84,
}

SHARIAH_COMPLIANT_ONLY = False   # Set True to filter table to Shariah stocks only
OUTPUT_FILE = "report.md"        # Set None to print only, or a filename to save


def fetch(ticker):
    info = yf.Ticker(ticker).info
    price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    target = info.get("targetMeanPrice") or 0
    return {
        "name":       info.get("shortName", ticker)[:32],
        "sector":     info.get("sector", "N/A"),
        "price":      price,
        "target":     target,
        "upside":     round((target / price - 1) * 100, 1) if price and target else None,
        "fpe":        round(info.get("forwardPE") or 0, 1) or None,
        "rev_growth": round((info.get("revenueGrowth") or 0) * 100, 1),
        "eps_growth": round((info.get("earningsGrowth") or 0) * 100, 1),
        "beta":       round(info.get("beta") or 0, 2) or None,
        "de":         round(info.get("debtToEquity") or 0, 1) or None,
        "gross_m":    round((info.get("grossMargins") or 0) * 100, 1),
        "op_m":       round((info.get("operatingMargins") or 0) * 100, 1),
        "w52_low":    info.get("fiftyTwoWeekLow"),
        "w52_high":   info.get("fiftyTwoWeekHigh"),
        "rec":        info.get("recommendationKey", "N/A"),
        "mcap":       info.get("marketCap") or 0,
    }


def mcap_str(v):
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    return f"${v/1e6:.0f}M"


def upside_emoji(u):
    if u is None: return "N/A"
    if u >= 60:   return f"🟢 **+{u}%**"
    if u >= 30:   return f"🟡 +{u}%"
    if u >= 0:    return f"🟠 +{u}%"
    return f"🔴 {u}%"


def rec_fmt(r):
    mapping = {"strong_buy": "⭐ Strong Buy", "buy": "Buy",
               "hold": "Hold", "sell": "Sell", "strong_sell": "Strong Sell"}
    return mapping.get(r, r)


def build_report(data: dict, run_date: str) -> str:
    rows = []
    for t, d in data.items():
        region, shariah, notes = WATCHLIST[t]
        if SHARIAH_COMPLIANT_ONLY and shariah != "✅ Yes":
            continue
        base   = BASELINE.get(t)
        chg    = f"▲ +{round((d['price']/base-1)*100,1)}%" if base and d['price'] > base else \
                 f"▼ {round((d['price']/base-1)*100,1)}%" if base else "—"
        rows.append((t, d, region, shariah, notes, chg))

    # Sort by upside descending
    rows.sort(key=lambda x: x[1]["upside"] or -999, reverse=True)

    lines = []
    lines.append(f"# 📊 Global Stock Analysis Report")
    lines.append(f"**Generated:** {run_date}  |  **Tickers:** {len(rows)}  |  **Source:** Yahoo Finance\n")
    lines.append("> ⚠️ For informational purposes only. Not financial advice.\n")

    # ── Main Table ──
    lines.append("## 🏆 Full Watchlist — Ranked by Analyst Upside\n")
    lines.append("| # | Ticker | Company | Geo | Shariah | Price | Target | **Upside** | Fwd P/E | Rev Growth | Beta | Gross Margin | Vs Baseline | Rec |")
    lines.append("|---|--------|---------|-----|:-------:|------:|-------:|:----------:|:-------:|:----------:|:----:|:------------:|:-----------:|-----|")

    for i, (t, d, region, shariah, notes, chg) in enumerate(rows, 1):
        lines.append(
            f"| {i} | **{t}** | {d['name']} | {region} | {shariah} | "
            f"${d['price']:,.2f} | ${d['target']:,.2f} | {upside_emoji(d['upside'])} | "
            f"{d['fpe'] or 'N/A'}x | {d['rev_growth']:+.1f}% | "
            f"{d['beta'] or 'N/A'} | {d['gross_m']:.1f}% | {chg} | {rec_fmt(d['rec'])} |"
        )

    # ── Shariah-only table ──
    lines.append("\n---\n")
    lines.append("## 🕌 Shariah-Compliant Picks Only\n")
    lines.append("| Ticker | Company | Price | Upside | D/E | Fwd P/E | Gross Margin | Notes |")
    lines.append("|--------|---------|------:|:------:|:---:|:-------:|:------------:|-------|")
    for t, d, region, shariah, notes, chg in rows:
        if shariah == "✅ Yes":
            lines.append(
                f"| **{t}** | {d['name']} | ${d['price']:,.2f} | {upside_emoji(d['upside'])} | "
                f"{d['de'] or 'N/A'} | {d['fpe'] or 'N/A'}x | {d['gross_m']:.1f}% | {notes} |"
            )

    # ── Alerts ──
    lines.append("\n---\n")
    lines.append("## ⚡ Alerts\n")
    alerts = []
    for t, d, region, shariah, notes, chg in rows:
        if d["upside"] and d["upside"] >= 60:
            alerts.append(f"- 🟢 **{t}** — Analyst upside **+{d['upside']}%** (Strong opportunity)")
        if d["price"] and d["w52_low"] and d["price"] < d["w52_low"] * 1.05:
            alerts.append(f"- 🔵 **{t}** — Trading within **5% of 52-week low** (potential bottom)")
        if d["beta"] and d["beta"] > 3:
            alerts.append(f"- 🟡 **{t}** — Very high beta ({d['beta']}x) — extreme volatility risk")
        if d["upside"] and d["upside"] < 0:
            alerts.append(f"- 🔴 **{t}** — Trading **above analyst target** ({d['upside']}%) — avoid near-term")
    for a in alerts:
        lines.append(a)
    if not alerts:
        lines.append("- No critical alerts at this time.")

    # ── Snapshot ──
    lines.append("\n---\n")
    lines.append("## 📈 Quick Snapshot\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    avg_upside = round(sum(d["upside"] for _, d, *_ in rows if d["upside"]) / len(rows), 1)
    top = rows[0]
    bottom = min(rows, key=lambda x: x[1]["upside"] or 999)
    strong_buys = sum(1 for _, d, *_ in rows if d["rec"] == "strong_buy")
    lines.append(f"| Avg Analyst Upside | {avg_upside}% |")
    lines.append(f"| Highest Upside | {top[0]} ({upside_emoji(top[1]['upside'])}) |")
    lines.append(f"| Lowest Upside | {bottom[0]} ({bottom[1]['upside']}%) |")
    lines.append(f"| Strong Buy Count | {strong_buys}/{len(rows)} |")
    lines.append(f"| Shariah Compliant | {sum(1 for _,_,_,s,*_ in rows if s=='✅ Yes')}/{len(rows)} |")

    lines.append(f"\n---\n*Report auto-generated by `analyze.py` on {run_date}*")
    return "\n".join(lines)


def main():
    run_date = datetime.now().strftime("%B %d, %Y — %H:%M")
    print(f"\n🔄  Fetching live data for {len(WATCHLIST)} tickers...\n")

    data = {}
    for t in WATCHLIST:
        try:
            data[t] = fetch(t)
            price = data[t]["price"]
            upside = data[t]["upside"]
            print(f"  ✓  {t:<6}  ${price:<10,.2f}  →  target ${data[t]['target']:,.2f}  ({upside:+.1f}%)")
        except Exception as e:
            print(f"  ✗  {t:<6}  ERROR: {e}")

    report = build_report(data, run_date)

    if OUTPUT_FILE:
        path = os.path.join(os.path.dirname(__file__), OUTPUT_FILE)
        with open(path, "w") as f:
            f.write(report)
        print(f"\n✅  Report saved → {path}\n")

    print(report)


if __name__ == "__main__":
    main()
