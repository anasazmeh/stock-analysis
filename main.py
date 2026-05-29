#!/usr/bin/env python3
"""
Investment Opportunity Finder
Finds stocks with exponential growth potential in the next 6-12 months.

Usage:
    python3 main.py              # Full pipeline run
    python3 main.py --no-ai      # Skip Claude API (faster, offline test)
    python3 main.py --no-cache   # Force fresh data
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from datetime import datetime

import config
from src.discovery import discover_candidates
from src.enrichment import enrich_tickers
from src.portfolio import attach_portfolio, get_portfolio_tickers
from src.alphavantage import enrich_missing_targets, fetch_earnings_dates, fetch_earnings_surprises
from src.argaam import enrich_saudi_targets
from src.insider import fetch_insider_trades
from src.news import attach_news, build_macro_context
from src.newsapi_client import attach_news_sentiment
from src.intelligence import analyze_tickers, build_macro_analysis
from src.risk import compute_risk
from src.shariah import check_shariah
from src.report import generate_report, save_report
from src.alerts import dispatch_alerts


def main():
    parser = argparse.ArgumentParser(description="Investment Opportunity Finder")
    parser.add_argument("--no-ai",    action="store_true", help="Skip Claude API analysis")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached data")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Investment Opportunity Finder")
    print(f"  {datetime.now().strftime('%B %d, %Y — %H:%M')}")
    print(f"{'='*60}\n")

    # ── Stage 1: Discovery ───────────────────────────────────────────────
    print("📡 Stage 1: Discovering candidates...")
    tickers = discover_candidates()
    # Always include portfolio tickers so P&L is computed even if not in screener
    tickers = sorted(set(tickers) | set(get_portfolio_tickers()) - config.AVOID_LIST)
    print(f"   → {len(tickers)} tickers (incl. portfolio holdings)\n")

    # ── Stage 2: Enrichment ──────────────────────────────────────────────
    print("📊 Stage 2: Fetching fundamentals...")
    opportunities = enrich_tickers(tickers)
    valid = [o for o in opportunities if o.price > 0]
    print(f"   → {len(valid)} tickers with valid data\n")

    # ── Stage 2x: Portfolio — attach P&L to holdings ────────────────────
    print("💼 Stage 2x: Attaching portfolio P&L...")
    opportunities = attach_portfolio(opportunities)
    portfolio_count = sum(1 for o in opportunities if o.portfolio)
    print(f"   → {portfolio_count} portfolio holdings tracked\n")

    # ── Stage 2a: Alpha Vantage — fill missing targets + earnings data ───
    if config.ALPHA_VANTAGE_API_KEY:
        print("📈 Stage 2a: Alpha Vantage enrichment...")
        opportunities = enrich_missing_targets(opportunities)
        opportunities = fetch_earnings_dates(opportunities)
        opportunities = fetch_earnings_surprises(opportunities)
        av_count = sum(1 for o in opportunities if o.earnings_date)
        print(f"   → {av_count} earnings dates fetched\n")
    else:
        print("📈 Stage 2a: Alpha Vantage skipped (no API key)\n")

    # ── Stage 2b: Argaam — Saudi (.SR) analyst targets ───────────────────
    print("🌙 Stage 2b: Argaam Saudi enrichment...")
    opportunities = enrich_saudi_targets(opportunities)
    saudi_enriched = sum(
        1 for o in opportunities if o.ticker.endswith(".SR") and o.target > 0
    )
    print(f"   → {saudi_enriched} Saudi tickers with targets\n")

    # ── Stage 2c: SEC EDGAR — insider trading signals ────────────────────
    print("🏛️  Stage 2c: SEC EDGAR insider trades...")
    opportunities = fetch_insider_trades(opportunities)
    bullish = sum(1 for o in opportunities if o.insider_signal == "Bullish")
    bearish = sum(1 for o in opportunities if o.insider_signal == "Bearish")
    print(f"   → {bullish} bullish, {bearish} bearish insider signals\n")

    # ── Stage 3: News ────────────────────────────────────────────────────
    print("📰 Stage 3: Gathering news & macro data...")
    opportunities = attach_news(opportunities)
    macro = build_macro_context()
    print(f"   → {sum(len(o.news) for o in opportunities)} news articles\n")

    # ── Stage 3a: NewsAPI — richer articles + keyword sentiment ─────────
    if config.NEWSAPI_KEY:
        print("📰 Stage 3a: NewsAPI sentiment scoring...")
        opportunities = attach_news_sentiment(opportunities)
        scored = sum(1 for o in opportunities if o.news_sentiment_score != 0)
        print(f"   → {scored} tickers with sentiment scores\n")
    else:
        print("📰 Stage 3a: NewsAPI skipped (no API key)\n")

    # ── Stage 4: AI Analysis ─────────────────────────────────────────────
    if not args.no_ai and config.ANTHROPIC_API_KEY:
        print("🤖 Stage 4: Running AI analysis (Claude)...")
        opportunities = analyze_tickers(opportunities)
        macro = build_macro_analysis(macro, opportunities)
        ai_count = sum(1 for o in opportunities if o.analysis)
        print(f"   → {ai_count} tickers analyzed\n")
    else:
        print("🤖 Stage 4: AI analysis skipped\n")

    # ── Stage 5: Risk ────────────────────────────────────────────────────
    print("⚠️  Stage 5: Computing risk profiles...")
    opportunities = compute_risk(opportunities)
    print(f"   → Risk profiles computed\n")

    # ── Stage 6: Shariah ─────────────────────────────────────────────────
    print("🕌 Stage 6: Shariah compliance screening...")
    opportunities = check_shariah(opportunities)
    compliant = sum(1 for o in opportunities if o.shariah and o.shariah.compliant == "Yes")
    print(f"   → {compliant} fully compliant stocks\n")

    # ── Stage 7: Report ──────────────────────────────────────────────────
    print("📝 Stage 7: Generating report...")
    report = generate_report(opportunities, macro)
    path = save_report(report)
    print(f"   → Report saved: {path}\n")

    # Also save to legacy report.md for backwards compatibility
    legacy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.md")
    with open(legacy_path, "w") as f:
        f.write(report)

    # ── Stage 8: Alerts ──────────────────────────────────────────────────
    print("🔔 Stage 8: Dispatching alerts...")
    dispatch_alerts(opportunities, macro)

    print(f"{'='*60}")
    print(f"  ✅ Done! Report at: {path}")
    print(f"{'='*60}\n")

    print(report[:3000] + "\n...(truncated, see full report)\n" if len(report) > 3000 else report)


if __name__ == "__main__":
    main()
