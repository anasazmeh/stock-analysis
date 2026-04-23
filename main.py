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
from src.news import attach_news, build_macro_context
from src.intelligence import analyze_tickers, build_macro_analysis
from src.risk import compute_risk
from src.shariah import check_shariah
from src.report import generate_report, save_report


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
    print(f"   → {len(tickers)} tickers\n")

    # ── Stage 2: Enrichment ──────────────────────────────────────────────
    print("📊 Stage 2: Fetching fundamentals...")
    opportunities = enrich_tickers(tickers)
    valid = [o for o in opportunities if o.price > 0]
    print(f"   → {len(valid)} tickers with valid data\n")

    # ── Stage 3: News ────────────────────────────────────────────────────
    print("📰 Stage 3: Gathering news & macro data...")
    opportunities = attach_news(opportunities)
    macro = build_macro_context()
    print(f"   → {sum(len(o.news) for o in opportunities)} news articles\n")

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

    print(f"{'='*60}")
    print(f"  ✅ Done! Report at: {path}")
    print(f"{'='*60}\n")

    print(report[:3000] + "\n...(truncated, see full report)\n" if len(report) > 3000 else report)


if __name__ == "__main__":
    main()
