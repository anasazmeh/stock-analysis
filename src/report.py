"""
Stage 7 — Report Generation
Generates the daily investment opportunity markdown report.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
import config
from src.models import Opportunity, MacroContext


def _upside_emoji(u):
    if u is None: return "N/A"
    if u >= 60:   return f"🟢 **+{u:.1f}%**"
    if u >= 30:   return f"🟡 +{u:.1f}%"
    if u >= 0:    return f"🟠 +{u:.1f}%"
    return f"🔴 {u:.1f}%"


def _risk_badge(score: float) -> str:
    if score <= 3:   return f"🟢 {score:.1f}/10 Low"
    if score <= 6:   return f"🟡 {score:.1f}/10 Moderate"
    if score <= 8:   return f"🟠 {score:.1f}/10 High"
    return f"🔴 {score:.1f}/10 Very High"


def _shariah_badge(compliant: str) -> str:
    return {"Yes": "✅ Yes", "No": "❌ No", "Partial": "⚠️ Partial"}.get(compliant, "❓ Unknown")


def _mcap_str(v: float) -> str:
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v > 0:     return f"${v/1e6:.0f}M"
    return "N/A"


def _rec_fmt(r: str) -> str:
    return {
        "strong_buy": "⭐ Strong Buy", "buy": "Buy",
        "hold": "Hold", "sell": "Sell", "strong_sell": "Strong Sell"
    }.get(r, r)


def _rank_score(opp: Opportunity) -> float:
    """
    Composite ranking score (higher = better opportunity).
    Weights: upside(30%) + sentiment(20%) + risk_adj(20%) + momentum(15%) + shariah(15%)
    """
    w = config.RANK_WEIGHTS
    score = 0.0

    # Upside: normalize 0-100% upside to 0-1
    if opp.upside is not None:
        score += w["upside"] * min(max(opp.upside, 0) / 100.0, 1.0)

    # Sentiment: -10 to +10, normalize to 0-1
    if opp.analysis:
        score += w["sentiment"] * (opp.analysis.sentiment_score + 10) / 20.0

    # Risk-adjusted: invert risk score (low risk = better rank)
    if opp.risk:
        risk_inv = (10 - opp.risk.composite_score) / 10.0
        score += w["risk_adj"] * risk_inv

    # Momentum (RSI): prefer 40-60 range (neutral momentum, not overbought)
    if opp.risk:
        rsi = opp.risk.rsi_14
        if 40 <= rsi <= 60:
            momentum = 0.8
        elif 30 <= rsi <= 70:
            momentum = 0.5
        else:
            momentum = 0.2
        score += w["momentum"] * momentum

    # Shariah bonus
    if opp.shariah:
        bonus = {"Yes": 1.0, "Partial": 0.5, "No": 0.0}.get(opp.shariah.compliant, 0.0)
        score += w["shariah"] * bonus

    return round(score * 100, 2)  # scale to 0-100


def generate_report(opportunities: list[Opportunity], macro: MacroContext) -> str:
    """Generate the full markdown investment report."""
    run_date = datetime.now().strftime("%B %d, %Y — %H:%M")

    # Compute rank scores and sort
    for opp in opportunities:
        opp.rank_score = _rank_score(opp)
    ranked = sorted(
        [o for o in opportunities if o.price > 0],
        key=lambda o: o.rank_score,
        reverse=True
    )
    top10 = ranked[:10]
    shariah_picks = [o for o in ranked if o.shariah and o.shariah.compliant == "Yes"]

    lines = []

    # ── Header ──────────────────────────────────────────────────────────
    lines += [
        f"# 📊 Investment Opportunity Report",
        f"**Generated:** {run_date}  |  **Tickers Analyzed:** {len(ranked)}  |  **Source:** Yahoo Finance + Claude AI",
        "",
        "> ⚠️ For informational purposes only. Not financial advice. Always do your own research.",
        "",
        "---",
        "",
    ]

    # ── Market Overview ──────────────────────────────────────────────────
    lines += ["## 🌍 Market Overview", ""]
    regime_emoji = {"risk-on": "🟢", "risk-off": "🔴", "neutral": "🟡"}.get(macro.regime, "⚪")
    lines.append(f"**Market Regime:** {regime_emoji} {macro.regime.title() if macro.regime else 'Unknown'}")
    lines.append("")

    if macro.themes:
        lines.append("**Key Macro Themes:**")
        for theme in macro.themes:
            lines.append(f"- {theme}")
        lines.append("")

    if macro.geopolitical_summary:
        lines.append(f"**Geopolitical Summary:** {macro.geopolitical_summary}")
        lines.append("")

    # FRED indicators table
    fred_rows = [
        ("Fed Funds Rate", f"{macro.fed_rate:.2f}%" if macro.fed_rate is not None else "N/A"),
        ("VIX",            f"{macro.vix:.2f}" if macro.vix is not None else "N/A"),
        ("10Y-2Y Spread",  f"{macro.yield_spread:.3f}%" if macro.yield_spread is not None else "N/A"),
    ]
    if any(v != "N/A" for _, v in fred_rows):
        lines += ["**Macro Indicators:**", "", "| Indicator | Value |", "|-----------|-------|"]
        for label, val in fred_rows:
            lines.append(f"| {label} | {val} |")
        lines.append("")

    lines += ["---", ""]

    # ── Top 10 Opportunities ─────────────────────────────────────────────
    lines += [f"## 🏆 Top 10 Investment Opportunities (6-12 Month Horizon)", ""]
    lines.append("*Ranked by composite score: analyst upside (30%) + AI sentiment (20%) + risk-adjusted (20%) + momentum (15%) + Shariah (15%)*")
    lines.append("")

    for i, opp in enumerate(top10, 1):
        lines.append(f"### {i}. {opp.ticker} — {opp.name}")
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| **Price / Target / Upside** | ${opp.price:,.2f} / ${opp.target:,.2f} / {_upside_emoji(opp.upside)} |")
        lines.append(f"| **Market Cap** | {_mcap_str(opp.mcap)} |")
        lines.append(f"| **Sector** | {opp.sector} — {opp.industry} |")
        lines.append(f"| **Analyst Recommendation** | {_rec_fmt(opp.rec)} |")

        if opp.analysis:
            lines.append(f"| **Investment Thesis** | {opp.analysis.thesis} |")
            lines.append(f"| **Bull Case** | {opp.analysis.bull_case} |")
            lines.append(f"| **Bear Case** | {opp.analysis.bear_case} |")
            lines.append(f"| **AI Sentiment** | {opp.analysis.sentiment_score:+d}/10 |")
            if opp.analysis.catalysts:
                lines.append(f"| **Key Catalysts** | {' · '.join(opp.analysis.catalysts[:3])} |")

        if opp.risk:
            lines.append(f"| **Risk Score** | {_risk_badge(opp.risk.composite_score)} |")
            lines.append(f"| **Beta / Volatility** | {opp.risk.beta:.2f}x / {opp.risk.volatility_30d:.1f}% ann. |")
            lines.append(f"| **RSI (14d)** | {opp.risk.rsi_14:.1f} |")
            lines.append(f"| **Geo Exposure** | {opp.risk.geo_exposure} ({opp.country}) |")
            if opp.analysis and opp.analysis.risk_flags:
                lines.append(f"| **Risk Flags** | {' · '.join(opp.analysis.risk_flags)} |")

        if opp.shariah:
            lines.append(f"| **Shariah Status** | {_shariah_badge(opp.shariah.compliant)} |")
            if opp.shariah.reasons:
                lines.append(f"| **Shariah Notes** | {opp.shariah.reasons[0] if opp.shariah.reasons else ''} |")

        lines.append(f"| **Rank Score** | {opp.rank_score:.1f}/100 |")
        lines.append("")

    lines += ["---", ""]

    # ── Shariah Picks ────────────────────────────────────────────────────
    lines += [f"## 🕌 Shariah-Compliant Picks ({len(shariah_picks)} stocks)", ""]
    if shariah_picks:
        lines += [
            "| # | Ticker | Company | Price | Upside | Risk | D/E | Fwd P/E | Notes |",
            "|---|--------|---------|------:|:------:|:----:|:---:|:-------:|-------|",
        ]
        for i, opp in enumerate(shariah_picks, 1):
            risk_score = opp.risk.composite_score if opp.risk else 5.0
            lines.append(
                f"| {i} | **{opp.ticker}** | {opp.name} | ${opp.price:,.2f} | "
                f"{_upside_emoji(opp.upside)} | {risk_score:.1f}/10 | "
                f"{opp.de or 'N/A'} | {opp.fpe or 'N/A'}x | "
                f"{opp.shariah.reasons[0][:60] if opp.shariah and opp.shariah.reasons else 'Compliant'} |"
            )
    else:
        lines.append("No fully compliant stocks found in current screened universe.")
    lines += ["", "---", ""]

    # ── Full Watchlist Table ──────────────────────────────────────────────
    lines += [f"## 📋 Full Screened Universe ({len(ranked)} stocks)", ""]
    lines += [
        "| # | Ticker | Company | Price | Target | Upside | Risk | Shariah | Rec | Sector |",
        "|---|--------|---------|------:|-------:|:------:|:----:|:-------:|-----|--------|",
    ]
    for i, opp in enumerate(ranked, 1):
        risk_score = opp.risk.composite_score if opp.risk else 5.0
        shariah_status = _shariah_badge(opp.shariah.compliant) if opp.shariah else "❓"
        lines.append(
            f"| {i} | **{opp.ticker}** | {opp.name} | ${opp.price:,.2f} | "
            f"${opp.target:,.2f} | {_upside_emoji(opp.upside)} | "
            f"{risk_score:.1f} | {shariah_status} | {_rec_fmt(opp.rec)} | {opp.sector} |"
        )
    lines += ["", "---", ""]

    # ── Alerts ───────────────────────────────────────────────────────────
    lines += ["## ⚡ Alerts", ""]
    alerts = []
    for opp in ranked:
        if opp.upside and opp.upside >= 60:
            alerts.append(f"- 🟢 **{opp.ticker}** — Analyst upside **+{opp.upside:.1f}%** — Strong opportunity")
        if opp.price and opp.w52_low and opp.price < opp.w52_low * 1.05:
            alerts.append(f"- 🔵 **{opp.ticker}** — Within 5% of 52-week low (${opp.w52_low:,.2f}) — potential bottom")
        if opp.beta and opp.beta > 3:
            alerts.append(f"- 🟡 **{opp.ticker}** — Very high beta ({opp.beta:.1f}x) — extreme volatility")
        if opp.upside is not None and opp.upside < 0:
            alerts.append(f"- 🔴 **{opp.ticker}** — Trading **above analyst target** ({opp.upside:.1f}%) — caution")
        if opp.risk and opp.risk.rsi_14 > 75:
            alerts.append(f"- 🟡 **{opp.ticker}** — RSI {opp.risk.rsi_14:.0f} — overbought territory")
    if alerts:
        lines += alerts
    else:
        lines.append("- No critical alerts at this time.")
    lines += ["", "---", ""]

    # ── Sector Heatmap ───────────────────────────────────────────────────
    sector_data = {}
    for opp in ranked:
        s = opp.sector or "Unknown"
        sector_data.setdefault(s, {"tickers": [], "upsides": [], "risks": []})
        sector_data[s]["tickers"].append(opp.ticker)
        if opp.upside is not None:
            sector_data[s]["upsides"].append(opp.upside)
        if opp.risk:
            sector_data[s]["risks"].append(opp.risk.composite_score)

    lines += ["## 🔥 Sector Heatmap", ""]
    lines += [
        "| Sector | Stocks | Avg Upside | Avg Risk | Tickers |",
        "|--------|:------:|:----------:|:--------:|---------|",
    ]
    for sector, d in sorted(sector_data.items(), key=lambda x: -len(x[1]["tickers"])):
        avg_up  = round(sum(d["upsides"]) / len(d["upsides"]), 1) if d["upsides"] else None
        avg_risk = round(sum(d["risks"]) / len(d["risks"]), 1) if d["risks"] else None
        up_str  = f"+{avg_up}%" if avg_up and avg_up >= 0 else (f"{avg_up}%" if avg_up else "N/A")
        lines.append(
            f"| {sector} | {len(d['tickers'])} | {up_str} | "
            f"{avg_risk or 'N/A'} | {', '.join(d['tickers'][:5])} |"
        )
    lines += ["", "---", ""]

    # ── Methodology ──────────────────────────────────────────────────────
    lines += [
        "## 📖 Methodology",
        "",
        "- **Discovery**: yfinance screeners (`undervalued_growth_stocks`, `growth_technology_stocks`, `aggressive_small_caps`, `most_actives`) + curated watchlist",
        "- **Fundamentals**: Yahoo Finance via yfinance (price, target, P/E, growth, beta, margins, D/E)",
        "- **News**: Yahoo Finance ticker news + Google News RSS (macro queries)",
        "- **AI Analysis**: Claude API (`claude-sonnet-4-6`) — investment thesis, sentiment, catalysts per ticker; macro regime synthesis",
        "- **Risk**: Beta, 30d annualized volatility, 6mo max drawdown, D/E, RSI(14), geopolitical exposure",
        "- **Shariah**: AAOIFI-standard screening — business activity deny-list + financial ratios (debt/cash/receivables < 33% of market cap, interest income < 5% of revenue)",
        "- **Ranking**: Composite score = analyst upside (30%) + AI sentiment (20%) + risk-adjusted (20%) + RSI momentum (15%) + Shariah bonus (15%)",
        "",
        f"*Report auto-generated · {run_date}*",
    ]

    return "\n".join(lines)


def save_report(report: str) -> str:
    """Save report to reports/ directory with date-stamped filename. Returns path."""
    import os
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(config.REPORT_DIR, f"{date_str}.md")
    with open(path, "w") as f:
        f.write(report)
    return path
