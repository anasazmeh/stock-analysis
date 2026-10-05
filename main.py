#!/usr/bin/env python3
"""
Investment Opportunity Finder

Usage:
    python3 main.py                  Full pipeline run
    python3 main.py --no-ai          Skip the Claude analysis
    python3 main.py --no-cache       Ignore cached data (still refreshes the cache)
    python3 main.py --require-keys   Stop if FINNHUB/FRED keys or the `claude` command are missing
    python3 main.py --ipo "SpaceX" --broker-price 162 [--ticker SPCX] [--amount 2000]

Exit codes: 0 ok · 2 degraded data · 1 avoid-list leak or missing required keys.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from datetime import datetime

import config
import src.cache as cache
from src.data_quality import HEALTH, apply_gate


def _status(n_ok: int, n_total: int) -> str:
    if n_total == 0:
        return "skipped"
    return "ok" if n_ok == n_total else ("partial" if n_ok else "failed")


def preflight(require_keys: bool) -> bool:
    from src.intelligence import ai_available, ai_unavailable_reason
    keys = {"FINNHUB_API_KEY": config.FINNHUB_API_KEY, "FRED_API_KEY": config.FRED_API_KEY,
            "ALPHA_VANTAGE_API_KEY": config.ALPHA_VANTAGE_API_KEY, "NEWSAPI_KEY": config.NEWSAPI_KEY}
    if config.AI_BACKEND == "api":
        keys["ANTHROPIC_API_KEY"] = config.ANTHROPIC_API_KEY
    HEALTH.record("AI backend", "ok" if ai_available() else "skipped",
                  config.AI_BACKEND + ("" if ai_available() else f" — {ai_unavailable_reason()}"))
    missing = [k for k, v in keys.items() if not v]
    HEALTH.record("API keys", "ok" if not missing else "partial",
                  "all set" if not missing else "missing: " + ", ".join(missing))
    if "contact@example.com" in config.SEC_USER_AGENT:
        HEALTH.record("SEC contact", "partial", "set SEC_USER_AGENT to your name and email (SEC requirement)")
    required = [k for k in ("FINNHUB_API_KEY", "FRED_API_KEY") if not keys[k]]
    if config.AI_BACKEND != "off" and not ai_available():
        required.append(ai_unavailable_reason())
    if require_keys and required:
        print(f"❌ Missing: {', '.join(required)}")
        return False
    return True


def run_ipo(args) -> int:
    from src.ipo import build_dossier
    from src.output_gate import scrub
    text, _ = scrub(build_dossier(args.ipo, args.broker_price, args.ticker or "", args.amount))
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    safe = "".join(c for c in args.ipo if c.isalnum()) or "ipo"
    path = os.path.join(config.REPORT_DIR, f"ipo_{safe}_{datetime.now():%Y-%m-%d}.md")
    with open(path, "w") as f:
        f.write(text)
    print(text + f"\n\nSaved: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Investment Opportunity Finder")
    parser.add_argument("--no-ai", action="store_true", help="Skip Claude analysis")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached data")
    parser.add_argument("--require-keys", action="store_true", help="Exit if FINNHUB/FRED keys or the claude CLI are missing")
    parser.add_argument("--ipo", help="Build an IPO dossier for this company name and exit")
    parser.add_argument("--broker-price", type=float, help="IPO: price shown at your broker")
    parser.add_argument("--ticker", help="IPO: listing ticker, if trading")
    parser.add_argument("--amount", type=float, help="IPO: amount you plan to subscribe")
    args = parser.parse_args()
    cache.DISABLED = args.no_cache
    HEALTH.started = datetime.now().isoformat(timespec="seconds")

    print(f"\n{'=' * 60}\n  Investment Opportunity Finder\n  {datetime.now():%B %d, %Y — %H:%M}\n{'=' * 60}\n")
    if not preflight(args.require_keys):
        return 1
    if args.ipo:
        return run_ipo(args)

    from src.discovery import discover_candidates
    from src.enrichment import enrich_tickers
    from src.fx import get_fx
    from src.price_check import cross_check_prices
    from src.portfolio import (attach_portfolio, get_portfolio_tickers, unpriced_holdings, exposure as calc_exposure,
                               purification, HOLDINGS)
    from src.broker_import import run_reconciliation
    from src.universe import attach_universe_tags
    from src.filings import fetch_recent_filings
    from src.xbrl import fill_from_sec
    from src.shariah import check_shariah
    from src.alphavantage import run_alpha_vantage
    from src.argaam import enrich_saudi_targets
    from src.insider import fetch_insider_trades
    from src.ranking import apply_consensus_quality, fetch_rating_changes, rank_score
    from src.news import attach_news, build_macro_context, normalize_news
    from src.gdelt import attach_gdelt_news, add_gdelt_macro
    from src.newsapi_client import attach_news_sentiment
    from src.article_reader import attach_fulltext_sentiment
    from src.risk import compute_risk
    from src.geo_watch import apply_geo_watch
    from src.theses import apply_theses
    from src.events import attach_events
    from src.intelligence import analyze_tickers, build_macro_analysis
    from src.report import generate_report, save_report
    from src.output_gate import scrub
    from src.journal import latest_snapshot, what_changed, write_snapshot, append_decisions, scorecard
    from src.alerts import dispatch_alerts
    from src.dashboard_data import build_payload, write_latest
    from src.sell_review import apply_exit_metrics, review_holdings
    from src.cash_plan import build_cash_plan

    # ── 0. Broker reconciliation ─────────────────────────────────────────
    broker_diffs = run_reconciliation(HOLDINGS)
    HEALTH.record("Broker CSV reconciliation", "skipped" if broker_diffs is None else ("ok" if not broker_diffs else "partial"),
                  "no files in data/broker/" if broker_diffs is None else f"{len(broker_diffs)} differences")

    # ── 1. Discovery ─────────────────────────────────────────────────────
    print("📡 Stage 1: Discovering candidates...")
    tickers = sorted((set(discover_candidates()) | set(get_portfolio_tickers())) - config.AVOID_LIST)
    from src.symbols import resolve_tickers, mark_failed, STATUS as SYMBOLS
    held = set(get_portfolio_tickers())
    tickers = sorted(set(resolve_tickers(tickers, keep=held)) - config.AVOID_LIST)
    from src import runlog
    runlog.add_tickers(tickers)
    print(f"   → {len(tickers)} tickers (incl. holdings)\n")

    # ── 2. Market data, FX, price check, data-quality gate ───────────────
    print("📊 Stage 2: Fetching market data...")
    opportunities, benchmarks = enrich_tickers(tickers)
    priced = [o for o in opportunities if o.price > 0]
    mark_failed([o.ticker for o in opportunities if o.price <= 0 and o.ticker not in held])
    HEALTH.record("Symbol lookup", "partial" if SYMBOLS["missing"] else "ok",
                  "; ".join([f"{a} → {b}" for a, b in SYMBOLS["resolved"].items()]
                            + ([f"not on Yahoo: {', '.join(SYMBOLS['missing'])}"] if SYMBOLS["missing"] else []))
                  or "all symbols found")
    HEALTH.record("Yahoo Finance", _status(len(priced), len(opportunities)), f"{len(priced)}/{len(opportunities)} priced")
    fx = get_fx()
    HEALTH.record("ECB FX rates", "ok" if fx.rates else "failed", f"{fx.source} {fx.date}" if fx.rates else "unavailable")
    opportunities = cross_check_prices(opportunities)
    checked = [o for o in opportunities if o.price_check in ("Verified", "Mismatch")]
    HEALTH.record("Finnhub price check", "skipped" if not config.FINNHUB_API_KEY else _status(len(checked), len([o for o in priced if '.' not in o.ticker])),
                  f"{sum(o.price_check == 'Mismatch' for o in opportunities)} mismatches" if checked else "no key")
    opportunities = attach_portfolio(opportunities, fx)
    opportunities = attach_universe_tags(opportunities)
    apply_gate(opportunities, get_portfolio_tickers())
    print(f"   → {sum(o.data_ok for o in opportunities)} usable, degraded={HEALTH.degraded}\n")

    # ── 3. SEC filings, Shariah label ────────────────────────────────────
    print("🗂️  Stage 3: SEC filings + Shariah screening...")
    opportunities = fetch_recent_filings(opportunities)
    from src.sec import STATUS as SEC_STATUS
    HEALTH.record("SEC filings", "failed" if SEC_STATUS["cik_map"] == "failed" else "ok",
                  f"{sum(len(o.filings) for o in opportunities)} recent filings")
    filled = fill_from_sec(opportunities)
    opportunities = check_shariah(opportunities, fx)
    labels = [o.shariah.compliant for o in opportunities if o.shariah]
    HEALTH.record("Shariah screen", "ok" if labels else "skipped", f"Yes {labels.count('Yes')} · No {labels.count('No')} · "
                  f"Review {labels.count('Review')} · Unknown {labels.count('Unknown')} (SEC XBRL filled {filled})")
    print(f"   → {labels.count('Yes')} compliant, {labels.count('Unknown')} unknown\n")

    # ── 4. Earnings data, insider trades, consensus quality ──────────────
    print("📈 Stage 4: Earnings, insider trades, analyst consensus...")
    av_stats = run_alpha_vantage(opportunities)
    HEALTH.record("Alpha Vantage", "skipped" if not config.ALPHA_VANTAGE_API_KEY else "ok",
                  f"{av_stats['earnings_dates']} dates · {av_stats['eps_surprises']} EPS · {av_stats['targets']} targets")
    opportunities = enrich_saudi_targets(opportunities)
    opportunities = fetch_insider_trades(opportunities)
    insider_ran = [o for o in opportunities if o.insider_signal in ("Bullish", "Bearish", "Neutral")]
    HEALTH.record("SEC Form 4", "ok" if insider_ran else ("failed" if SEC_STATUS["cik_map"] == "failed" else "skipped"),
                  f"{sum(o.insider_signal in ('Bullish', 'Bearish') for o in opportunities)} signals")
    fetch_rating_changes(opportunities)
    opportunities = apply_consensus_quality(opportunities)
    print()

    # ── 5. News, macro ───────────────────────────────────────────────────
    print("📰 Stage 5: News and macro...")
    opportunities = attach_news(opportunities)
    macro = build_macro_context()
    if config.GDELT_ENABLED:
        opportunities = attach_gdelt_news(opportunities)
        macro = add_gdelt_macro(macro)
    if config.NEWSAPI_KEY:
        opportunities = attach_news_sentiment(opportunities)
    opportunities = normalize_news(opportunities)
    with_news = sum(1 for o in priced if o.news)
    HEALTH.record("News", _status(with_news, len(priced)), f"{with_news}/{len(priced)} tickers with recent news")
    HEALTH.record("FRED macro", "skipped" if not config.FRED_API_KEY else ("ok" if macro.fed_rate is not None else "failed"), "")
    if config.FULLTEXT_ENABLED:
        opportunities = attach_fulltext_sentiment(opportunities)
        n = sum(o.finbert_score is not None for o in opportunities)
        HEALTH.record("FinBERT", "ok" if n else "skipped", f"{n} tickers scored" if n else "model not installed")
    print()

    # ── 6. Risk, trend, regulatory watch, exposure, theses, events ───────
    print("⚠️  Stage 6: Risk, trend, exposure, events...")
    opportunities = compute_risk(opportunities, benchmarks)
    opportunities = apply_exit_metrics(opportunities)   # trailing stop etc., before the Claude stage
    macro = apply_geo_watch(opportunities, macro)
    from src.geo_watch import STATUS as GEO_STATUS
    HEALTH.record("Federal Register watch", "failed" if GEO_STATUS["failed_queries"] else "ok",
                  f"{len(macro.geo_themes)} active themes")
    exposure = calc_exposure(opportunities)
    opportunities = apply_theses(opportunities)
    for o in opportunities:
        o.rank_score = rank_score(o)
    macro = attach_events(opportunities, macro)
    print()

    # ── 7. Claude: macro first, then per-ticker evidence packs ───────────
    prompt_digest = ""
    from src.intelligence import ai_available
    if not args.no_ai and ai_available():
        print("🤖 Stage 7: Claude analysis...")
        macro = build_macro_analysis(macro, opportunities)
        opportunities, prompt_digest = analyze_tickers(opportunities, macro)
        n = sum(o.analysis is not None for o in opportunities)
        HEALTH.record("Claude analysis", _status(n, sum(o.data_ok for o in priced)), f"{n} tickers")
    else:
        HEALTH.record("Claude analysis", "skipped", "--no-ai, AI_BACKEND=off, or `claude` not installed")
    for o in opportunities:
        o.rank_score = rank_score(o)
    print()

    # ── 8. Report, journal, alerts ───────────────────────────────────────
    print("📝 Stage 8: Report, journal and alerts...")
    previous = latest_snapshot()
    bench_series = benchmarks.get(config.SCORECARD_BENCHMARK) or []
    bench_close = bench_series[-1] if bench_series else None
    card = scorecard(exposure.get("total_value_eur"), bench_close)
    pur = [(o.ticker, r) for o in opportunities if o.portfolio and (r := purification(o, fx))]
    ranked_now = sorted([o for o in opportunities if o.price > 0 and o.data_ok], key=lambda o: -o.rank_score)
    changes = what_changed(opportunities, ranked_now[:10], previous)
    unpriced = unpriced_holdings(opportunities)
    sell_rows = review_holdings(opportunities, fx, broker_diffs)
    cash_plan = build_cash_plan(opportunities, sell_rows, macro, benchmarks, fx, exposure)
    report, top10 = generate_report(opportunities, macro, health=HEALTH, fx=fx, exposure=exposure,
                                    unpriced=unpriced, changes=changes,
                                    purification_rows=pur, broker_diffs=broker_diffs, scorecard=card,
                                    av_stats=av_stats, sell_rows=sell_rows, cash_plan=cash_plan)
    report, removed = scrub(report)
    path = save_report(report)
    write_snapshot(opportunities, top10, HEALTH, prompt_digest,
                   portfolio_value_eur=exposure.get("total_value_eur"), benchmark_close=bench_close)
    append_decisions(opportunities, top10)
    alerts, removed_alerts = dispatch_alerts(opportunities, macro, HEALTH, exposure, previous, broker_diffs)
    _, removed_dash = write_latest(build_payload(
        opportunities, macro, health=HEALTH, fx=fx, exposure=exposure, unpriced=unpriced, top10=top10,
        alerts=alerts, changes=changes, purification_rows=pur, broker_diffs=broker_diffs, scorecard=card,
        sell_rows=sell_rows, cash_plan=cash_plan))
    removed_alerts += removed_dash

    print(f"\n{'=' * 60}\n  ✅ Report: {path}\n{'=' * 60}\n")
    if removed or removed_alerts:
        print(f"❌ Avoid-list gate removed {removed + removed_alerts} line(s) mentioning {sorted(config.AVOID_LIST)} — "
              f"find where they entered the pipeline.")
        return 1
    return 2 if HEALTH.degraded else 0


def run() -> int:
    """main() plus the end-of-run issue capture, which also runs after a crash."""
    from src import runlog
    if not any(a in ("-h", "--help") for a in sys.argv[1:]):
        log_path = runlog.start()
        if log_path:
            print(f"Log: {log_path}")
    code = 1
    try:
        code = main()
    except SystemExit as e:          # argparse --help / errors
        code = e.code if isinstance(e.code, int) else 1
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    finally:
        tickers = set(config.CURATED_WATCHLIST)
        try:
            from src.portfolio import get_portfolio_tickers
            tickers |= set(get_portfolio_tickers())
        except Exception:
            pass
        if "streams" in runlog._state:
            runlog.finish(HEALTH, tickers, code)
            runlog.stop()
    return code


if __name__ == "__main__":
    sys.exit(run())
