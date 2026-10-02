"""
Report generation — the daily markdown report.
Ranking happens in src/ranking.py before this runs; this module only renders.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import config
from src.models import Opportunity, MacroContext
from src.ranking import rank_score as _rank_score  # noqa: F401  (re-exported for callers/tests)

DISCLAIMER = "> ⚠️ For informational purposes only. Not financial advice. Always check prices on your broker and do your own research."


def _upside_emoji(u):
    if u is None: return "N/A"
    if u >= 60:   return f"🟢 **+{u:.1f}%**"
    if u >= 30:   return f"🟡 +{u:.1f}%"
    if u >= 0:    return f"🟠 +{u:.1f}%"
    return f"🔴 {u:.1f}%"


def _risk_badge(score) -> str:
    if score is None: return "N/A (not enough data)"
    if score <= 3:    return f"🟢 {score:.1f}/10 Low"
    if score <= 6:    return f"🟡 {score:.1f}/10 Moderate"
    if score <= 8:    return f"🟠 {score:.1f}/10 High"
    return f"🔴 {score:.1f}/10 Very High"


def _shariah_badge(compliant: str) -> str:
    return {"Yes": "✅ Yes", "No": "❌ No", "Review": "🔎 Review"}.get(compliant, "❓ Unknown")


def _currency_sym(currency: str) -> str:
    return config.CURRENCY_SYMBOLS.get((currency or "").upper(), (currency or "") + " ")


def _fmt_price(price, currency: str) -> str:
    if price is None:
        return "N/A"
    sym = _currency_sym(currency)
    if (currency or "").upper() in ("KRW", "JPY", "IDR"):
        return f"{sym}{price:,.0f}"
    return f"{sym}{price:,.2f}"


def _eur(v) -> str:
    return "N/A" if v is None else (f"+€{v:,.0f}" if v >= 0 else f"-€{abs(v):,.0f}")


def _mcap_str(v: float, currency: str = "USD") -> str:
    sym = _currency_sym(currency)
    if v >= 1e12: return f"{sym}{v/1e12:.2f}T"
    if v >= 1e9:  return f"{sym}{v/1e9:.1f}B"
    if v > 0:     return f"{sym}{v/1e6:.0f}M"
    return "N/A"


def _rec_fmt(r: str) -> str:
    return {"strong_buy": "⭐ Strong Buy", "buy": "Buy", "hold": "Hold", "sell": "Sell",
            "strong_sell": "Strong Sell"}.get(r, r)


def _price_check_str(opp: Opportunity) -> str:
    if opp.price_check == "Verified":
        return f"✅ Verified — Finnhub {opp.price_alt:.2f} ({opp.price_as_of})"
    if opp.price_check == "Mismatch":
        return (f"⚠️ MISMATCH — Finnhub {opp.price_alt:.2f} ({opp.price_diff_pct:+.1f}%, "
                f"{opp.price_as_of}). Verify on your broker before acting.")
    if opp.price_check == "Single source":
        return "Yahoo only (no second source for this listing)"
    return "Not checked (Finnhub call failed)"


def _provenance(opp: Opportunity) -> str:
    return f"{opp.price_type or 'unknown type'}, {opp.price_source or 'unknown source'}, {opp.price_time or 'time unknown'}"


def _pct(v, signed=True) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _section_header(lines, health, ranked, run_date, sources_line):
    lines += [
        "# 📊 Investment Opportunity Report",
        f"**Generated:** {run_date}  |  **Tickers analysed:** {len(ranked)}  |  **Sources:** {sources_line}",
        "",
        DISCLAIMER,
        "",
    ]
    if health is not None and health.degraded:
        lines += ["> 🚨 **DEGRADED RUN** — " + "; ".join(health.degraded_reasons)
                  + ". BUY/DIP alerts were suppressed. Treat this report as incomplete.", ""]
    lines += ["---", ""]


def _section_changes(lines, changes):
    lines += ["## 🔄 What Changed Since the Last Run", ""] + [f"- {c}" for c in changes] + ["", "---", ""]


def _section_market(lines, macro: MacroContext):
    lines += ["## 🌍 Market Overview", ""]
    regime_emoji = {"risk-on": "🟢", "risk-off": "🔴", "neutral": "🟡"}.get(macro.regime, "⚪")
    lines += [f"**Market Regime:** {regime_emoji} {macro.regime.title() if macro.regime else 'Unknown'}", ""]
    if macro.themes:
        lines += ["**Key Macro Themes:**"] + [f"- {t}" for t in macro.themes] + [""]
    if macro.geopolitical_summary:
        lines += [f"**Geopolitical Summary:** {macro.geopolitical_summary}", ""]
    rows = [("Fed Funds Rate", macro.fed_rate, "%"), ("US CPI (YoY)", macro.cpi_yoy, "%"),
            ("US Unemployment", macro.unemployment, "%"), ("10Y-2Y Spread", macro.yield_spread, "%"),
            ("VIX", macro.vix, ""), ("EUR/USD", macro.eurusd, "")]
    shown = [(a, b, c) for a, b, c in rows if b is not None]
    if shown:
        lines += ["**Macro Indicators (FRED):**", "", "| Indicator | Value |", "|-----------|-------|"]
        lines += [f"| {a} | {b}{c} |" for a, b, c in shown] + [""]
    if macro.events:
        lines += ["**Upcoming Events:**", ""] + [f"- {e['date']} — {e['name']}" for e in macro.events[:10]] + [""]
    if macro.geo_themes:
        lines += ["**Active Regulatory Themes (US Federal Register):**", ""]
        for g in macro.geo_themes:
            exp = f" — {g['portfolio_exposed_pct']:.0f}% of portfolio exposed" if g.get("portfolio_exposed_pct") is not None else ""
            lines.append(f"- **{g['theme']}**: [{g['latest']['title'][:100]}]({g['latest']['url']}) ({g['latest']['date']}){exp}")
        lines.append("")
    lines += ["---", ""]


def _section_portfolio(lines, ranked, unpriced, exposure, fx, purification_rows, broker_diffs, scorecard):
    holdings = [o for o in ranked if o.portfolio]
    if not holdings and not unpriced:
        return
    lines += ["## 💼 Portfolio", ""]
    if exposure.get("total_value_eur"):
        lines.append(f"**Value:** €{exposure['total_value_eur']:,.0f} · **Cost:** €{exposure['total_cost_eur']:,.0f} · "
                     f"**Unrealised P&L:** {_eur(exposure['total_pl_eur'])} (priced holdings, EUR)")
    if fx is not None and fx.date:
        lines.append(f"*FX: {fx.source} reference rates of {fx.date} (1 EUR = {fx.rates.get('USD', 0):.4f} USD). "
                     f"P&L % is in each position's own breakeven currency.*")
    lines += ["", "| Ticker | Shares | Breakeven | Price | P&L % | P&L € | Weight | Shariah | Thesis | Next event | Your status |",
              "|--------|-------:|----------:|------:|------:|------:|-------:|:-------:|--------|-----------|-------------|"]
    for opp in sorted(holdings, key=lambda o: -(o.portfolio.value_eur or 0)):
        p = opp.portfolio
        price = _fmt_price(opp.price, opp.currency) + (" ✅" if opp.price_check == "Verified" else
                                                      " ⚠️" if opp.price_check == "Mismatch" else "")
        pl = _pct(p.pl_pct) if p.pl_pct is not None else f"N/A ({p.note})"
        lines.append(
            f"| **{opp.ticker}** | {p.shares:g} | {_fmt_price(p.bep, p.bep_currency)} | {price} | {pl} | "
            f"{_eur(p.pl_value_eur)} | {_pct(p.weight_pct, False)} | "
            f"{_shariah_badge(opp.shariah.compliant) if opp.shariah else '❓'} | {opp.thesis_status or '-'} | "
            f"{opp.next_event or '-'} | {p.status} |")
    for p in unpriced:
        lines.append(f"| {p.ticker or p.name} | {p.shares:g} | {_fmt_price(p.bep, p.bep_currency)} | not priced ({p.note}) | – | – | – | "
                     f"{'🔎 see note' if p.shariah_note else '–'} | – | – | {p.status} |")
    lines.append("")
    notes = [p for p in unpriced if p.shariah_note] + [o.portfolio for o in holdings if o.portfolio.shariah_note]
    for p in notes:
        lines.append(f"- **{p.name}** — {p.shariah_note}")
    if any(p.note.startswith("No Yahoo ticker") for p in unpriced):
        lines.append("- Funds show as *not priced* until you set their Yahoo ticker in `portfolio_data.py`.")
    if notes or unpriced:
        lines.append("")

    if exposure.get("themes"):
        lines += ["**Exposure by theme:** " + " · ".join(f"{t} {w:.0f}%" for t, w in exposure["themes"].items()),
                  "", "**Exposure by currency:** " + " · ".join(f"{c} {w:.0f}%" for c, w in exposure["currencies"].items()), ""]
    for b in exposure.get("breaches", []):
        lines.append(f"- ⚠️ {b}")
    if exposure.get("breaches"):
        lines.append("")

    reviews = [o for o in holdings if o.thesis_status in ("Broken", "Review")]
    if reviews:
        lines += ["**Thesis checks:**", ""]
        for o in reviews:
            lines.append(f"- **{o.ticker}** — {o.thesis_status}: " + "; ".join(o.thesis_notes))
        tax = f" Tax residence set to {config.TAX_RESIDENCE}." if config.TAX_RESIDENCE else \
              " Set TAX_RESIDENCE in config.py — loss-harvesting rules differ by country."
        lines += [f"- *Before selling: {config.BROKER_COST_NOTE}{tax}*", ""]

    if purification_rows:
        lines += ["**Estimated annual dividend purification** (dividends × interest-income share — confirm the method with your scholar):", "",
                  "| Ticker | Annual dividends | Non-permissible share | To purify |", "|---|---:|---:|---:|"]
        for t, r in purification_rows:
            eur = f" (≈€{r['amount_eur']:,.2f})" if r.get("amount_eur") is not None else ""
            lines.append(f"| {t} | {_fmt_price(r['dividends'], r['currency'])} | {r['ratio']:.1%} | "
                         f"{_fmt_price(r['amount'], r['currency'])}{eur} |")
        lines.append("")

    if broker_diffs is not None:
        if broker_diffs:
            lines += ["**Broker reconciliation** — differences with your DEGIRO/Revolut exports:", ""]
            lines += [f"- {d['ticker']}: {d['issue']}" for d in broker_diffs] + [""]
        else:
            lines += ["**Broker reconciliation:** ✅ portfolio_data.py matches your broker exports.", ""]

    if scorecard:
        lines += [f"**Scorecard since {scorecard['since']}:** portfolio {scorecard['portfolio_pct']:+.1f}% vs "
                  f"{scorecard['benchmark']} {scorecard['benchmark_pct']:+.1f}% "
                  f"({scorecard['difference_pts']:+.1f} pts; approximate — trades in between distort it)", ""]
    lines += ["---", ""]


def _card(lines, i, opp: Opportunity):
    lines += [f"### {i}. {opp.ticker} — {opp.name}", "", "| Field | Value |", "|-------|-------|"]
    target = _fmt_price(opp.target, opp.currency) if opp.target else "N/A"
    lines.append(f"| **Region / Country** | {opp.region} — {opp.country} |")
    lines.append(f"| **Price** | {_fmt_price(opp.price, opp.currency)} ({_provenance(opp)}) |")
    lines.append(f"| **Price Check** | {_price_check_str(opp)} |")
    lines.append(f"| **Analyst target / upside** | {target} / {_upside_emoji(opp.upside)} — "
                 f"{opp.analyst_count or '?'} analysts, consensus {opp.consensus_quality or 'N/A'}, "
                 f"quality-adjusted {_pct(opp.adj_upside)} ({opp.target_source or 'n/a'}) |")
    rc = opp.rating_changes_90d
    if rc:
        lines.append(f"| **Rating changes (90d)** | ⬆️ {rc.get('up', 0)} · ⬇️ {rc.get('down', 0)} |")
    lines.append(f"| **Shariah** | {_shariah_badge(opp.shariah.compliant) if opp.shariah else '❓ Unknown'}"
                 + (f" — {opp.shariah.reasons[0]}" if opp.shariah and opp.shariah.reasons else "")
                 + (" · " + " · ".join(f"[{k}]({v})" for k, v in opp.shariah.second_opinion.items())
                    if opp.shariah and opp.shariah.second_opinion else "") + " |")
    lines.append(f"| **Trend** | {opp.trend or 'Unknown'}" + (
        " · 6m vs " + ", ".join(f"{config.BENCHMARKS.get(k, k)} {v:+.0f} pts" for k, v in opp.rel_strength.items())
        if opp.rel_strength else "") + " |")
    lines.append(f"| **Market Cap / Sector** | {_mcap_str(opp.mcap, opp.currency)} · {opp.sector} — {opp.industry} |")
    if opp.tradable == "Watch only":
        lines.append("| **Broker** | 👀 Watch only — not available at DEGIRO/Revolut by default |")
    if opp.next_event:
        lines.append(f"| **Next event** | {opp.next_event} ({opp.days_to_event} trading days) |")
    a = opp.analysis
    if a and a.status == "OK":
        lines.append(f"| **AI thesis** | {a.thesis} |")
        lines.append(f"| **Bull / Bear** | 🐂 {a.bull_case} · 🐻 {a.bear_case} |")
        if a.invalidation_triggers:
            lines.append(f"| **Invalidation triggers** | {' · '.join(a.invalidation_triggers)} |")
        held = f"holder: **{a.holder_action}** · " if opp.portfolio else ""
        lines.append(f"| **AI view** | {held}new buyer: **{a.new_buyer_action}** · sentiment {a.sentiment_score:+d}/10 · confidence {a.confidence} |")
        if a.catalysts:
            lines.append(f"| **Catalysts** | {' · '.join(a.catalysts)} |")
        if a.risk_flags:
            lines.append(f"| **Risk flags** | {' · '.join(a.risk_flags)} |")
        if a.evidence_used:
            lines.append(f"| **Evidence used** | {', '.join(a.evidence_used)} |")
    elif a:
        lines.append("| **AI view** | Insufficient data for a view |")
    if opp.finbert_score is not None:
        lines.append(f"| **FinBERT news sentiment** | {opp.finbert_score:+.1f}/10 |")
    elif opp.news_sentiment_score:
        lines.append(f"| **News keyword sentiment** | {opp.news_sentiment_score:+.1f}/10 |")
    if opp.portfolio and opp.portfolio.pl_pct is not None:
        p = opp.portfolio
        lines.append(f"| **Your position** | {p.shares:g} · breakeven {_fmt_price(p.bep, p.bep_currency)} · "
                     f"P&L {p.pl_pct:+.1f}% · weight {_pct(p.weight_pct, False)} |")
    if opp.risk:
        r = opp.risk
        vol = f"{r.volatility_30d:.0f}%" if r.volatility_30d is not None else "N/A"
        rsi = f"{r.rsi_14:.0f}" if r.rsi_14 is not None else "N/A"
        lines.append(f"| **Risk** | {_risk_badge(r.composite_score)} · vol {vol} · RSI {rsi} · geo {r.geo_exposure}"
                     + (f" ({'; '.join(r.geo_notes[:2])})" if r.geo_notes else "") + " |")
    if opp.short_pct_float:
        lines.append(f"| **Short interest** | {opp.short_pct_float:.1f}% of float"
                     + (" ⚠️ crowded" if opp.short_pct_float >= 15 else "") + " |")
    if opp.eps_surprise is not None:
        lines.append(f"| **EPS surprise (last Q)** | {opp.eps_surprise:+.1f}% |")
    if opp.insider_signal not in ("Neutral", "", "N/A", "Unavailable"):
        lines.append(f"| **Insider activity (30d)** | {opp.insider_signal} — net {opp.insider_net_shares:+,} shares |")
    if opp.filings:
        shown = sorted(opp.filings, key=lambda f: not f["red_flag"])[:3]
        lines.append("| **Recent SEC filings** | " + " · ".join(
            f"{'🚩 ' if f['red_flag'] else ''}[{f['form']} {f['date']}]({f['url']}) {', '.join(f['labels'])}"
            for f in shown) + " |")
    if opp.universe_tags:
        lines.append(f"| **Index / Shariah ETF** | {', '.join(opp.universe_tags)} |")
    if opp.data_flags:
        lines.append(f"| **Data notes** | {', '.join(opp.data_flags)} |")
    lines += [f"| **Rank score** | {opp.rank_score:.1f}/100 |", ""]


def _section_top10(lines, top10):
    w = config.RANK_WEIGHTS
    weights = ", ".join(f"{k} {v:.0%}" for k, v in w.items() if v)
    lines += ["## 🏆 Top 10 Opportunities (6-12 month horizon)", "",
              f"*Ranked by: {weights}. Missing data lowers a score instead of counting as favourable. "
              f"Only tickers that pass the data-quality check are ranked. Shariah status is shown as a label.*", ""]
    for i, opp in enumerate(top10, 1):
        _card(lines, i, opp)
    lines += ["---", ""]


def _section_shariah(lines, ranked):
    counts = {}
    for o in ranked:
        s = o.shariah.compliant if o.shariah else "Unknown"
        counts[s] = counts.get(s, 0) + 1
    lines += [f"## 🕌 Shariah Status ({config.SHARIAH_METHODOLOGY})", "",
              " · ".join(f"{_shariah_badge(k)}: {v}" for k, v in sorted(counts.items())), "",
              "| Ticker | Status | Debt / mcap | Cash+securities / mcap | Interest income / income | Inputs | Notes |",
              "|---|:---:|---:|---:|---:|---|---|"]
    fmt = lambda v: f"{v:.1%}" if v is not None else "N/A"
    for o in ranked:
        s = o.shariah
        if not s:
            continue
        lines.append(f"| {o.ticker} | {_shariah_badge(s.compliant)} | {fmt(s.debt_ratio)} | {fmt(s.cash_ratio)} | "
                     f"{fmt(s.income_ratio)} | {s.inputs_source or 'N/A'} | {(s.reasons[0] if s.reasons else '')[:90]} |")
    lines += ["", "---", ""]


def _section_universe(lines, ranked):
    lines += [f"## 📋 Full Screened Universe ({len(ranked)} stocks)", "",
              "| # | Ticker | Company | Price | Upside (adj.) | Risk | Trend | Shariah | Rec | Region |",
              "|---|--------|---------|------:|:------:|:----:|:-----:|:-------:|-----|--------|"]
    for i, o in enumerate(ranked, 1):
        risk = f"{o.risk.composite_score:.1f}" if o.risk and o.risk.composite_score is not None else "N/A"
        lines.append(f"| {i} | **{o.ticker}** | {o.name} | {_fmt_price(o.price, o.currency)} | {_pct(o.adj_upside)} | "
                     f"{risk} | {o.trend or '-'} | {_shariah_badge(o.shariah.compliant) if o.shariah else '❓'} | "
                     f"{_rec_fmt(o.rec)} | {o.region} |")
    lines += ["", "---", ""]


def _section_gaps(lines, opportunities):
    gaps = [o for o in opportunities if not o.data_ok or o.price <= 0]
    if not gaps:
        return
    lines += [f"## 🕳️ Data Gaps ({len(gaps)} tickers — not ranked, no AI analysis, no action alerts)", ""]
    lines += [f"- **{o.ticker}** — {', '.join(o.data_flags) or 'no data'}" for o in gaps] + ["", "---", ""]


def _section_health(lines, health, av_stats):
    if health is None:
        return
    icon = {"ok": "✅", "partial": "🟡", "failed": "❌", "skipped": "⏭️"}
    lines += ["## 🩺 Data Health", "", "| Source | Status | Detail |", "|---|:---:|---|"]
    for name, (status, detail) in health.sources.items():
        lines.append(f"| {name} | {icon.get(status, status)} | {detail} |")
    if av_stats:
        lines.append(f"| Alpha Vantage budget | ℹ️ | {av_stats.get('budget_left', 0)} calls left today"
                     + (f" — {av_stats['stopped']}" if av_stats.get("stopped") else "") + " |")
    lines += ["", "---", ""]


def _section_methodology(lines, run_date):
    lines += [
        "## 📖 Methodology", "",
        "- **Discovery**: curated watchlist + holdings (always kept) + 6-month-momentum names from the S&P 500 / Nasdaq-100 and Shariah ETF holdings in `data/universe/` + largest companies in Saudi, UAE, Germany, Netherlands, France + Yahoo growth screens",
        "- **Prices**: Yahoo Finance with type and time shown; US prices cross-checked with Finnhub. Minor-unit quotes (pence) converted.",
        "- **Data-quality gate**: stale quotes, short history, missing market cap or the wrong listing keep a ticker out of the ranking, AI and action alerts. The run is DEGRADED when a holding lacks data or >20% of tickers fail.",
        "- **Portfolio**: P&L in each position's breakeven currency using ECB reference rates (SAR/AED via their USD pegs); EUR totals, weights, theme caps and thesis rules (`data/theses.json`).",
        f"- **Shariah ({config.SHARIAH_METHODOLOGY})**: a label, never a filter. Activity screen (industry, Islamic-bank allow-list, overrides) + ratios: interest-bearing debt and cash+interest-bearing securities each < 30% of market cap, interest income < 5% of total income, from the latest annual statements (Yahoo, SEC XBRL fallback) converted to the market-cap currency. Missing inputs → Unknown. New-debt filings → Review.",
        "- **Analysts**: consensus target with analyst count and spread; upside halved under 5 analysts, cut for wide targets or net downgrades.",
        "- **Events**: earnings (Finnhub, Yahoo, Alpha Vantage), FOMC/ECB/CPI, TSMC monthly revenue, `data/events.json`. No new BUY signal within 5 trading days of earnings.",
        "- **News**: Yahoo, Finnhub, Google News, GDELT (65 languages), NewsAPI; deduplicated, ≤10 days old, ordered by source quality; full text via Trafilatura scored with FinBERT.",
        "- **SEC EDGAR**: Form 4 insider trades (US filers), recent 8-K/6-K/S-3/424B4/13D/13G/144 filings with red flags.",
        "- **Regulatory watch**: US Federal Register (BIS) documents on chip export controls and the Entity List, mapped to holdings.",
        f"- **AI analysis**: Claude (`{config.CLAUDE_MODEL}`) on a dated evidence pack; must cite facts used, gives separate holder and new-buyer views, says when data is insufficient.",
        "- **Risk**: beta, 30-day volatility, 6-month drawdown, D/E, RSI, geography incl. supply chain — computed only from available data.",
        "- **Trend**: price vs 50/200-day averages and 6-month return vs S&P 500, semiconductors and MSCI World Islamic.",
        "- **Journal**: every run is saved in `runs/`; holdings and Top 10 are logged in `data/decisions.jsonl`.",
        "", f"*Report generated {run_date}*", "", DISCLAIMER,
    ]


def generate_report(opportunities: list[Opportunity], macro: MacroContext, *, health=None, fx=None,
                    exposure: dict = None, unpriced: list = None, changes: list = None,
                    purification_rows: list = None, broker_diffs: list = None, scorecard: dict = None,
                    av_stats: dict = None) -> tuple[str, list[Opportunity]]:
    """Render the report. Returns (markdown, top10)."""
    run_date = datetime.now().strftime("%B %d, %Y — %H:%M")
    ranked = sorted([o for o in opportunities if o.price > 0 and o.data_ok],
                    key=lambda o: o.rank_score, reverse=True)
    top10 = ranked[:10]
    internal = {"API keys", "SEC contact", "Data-quality gate", "Shariah screen", "Broker CSV reconciliation"}
    ok_sources = [k for k, (s, _) in (health.sources.items() if health else [])
                  if s in ("ok", "partial") and k not in internal]
    lines = []
    _section_header(lines, health, ranked, run_date, ", ".join(ok_sources) or "see Data Health")
    if changes:
        _section_changes(lines, changes)
    _section_market(lines, macro)
    _section_portfolio(lines, sorted([o for o in opportunities if o.price > 0], key=lambda o: o.ticker),
                       unpriced or [], exposure or {}, fx, purification_rows or [], broker_diffs, scorecard)
    _section_top10(lines, top10)
    _section_shariah(lines, ranked)
    _section_universe(lines, ranked)
    _section_gaps(lines, opportunities)
    _section_health(lines, health, av_stats)
    _section_methodology(lines, run_date)
    return "\n".join(lines), top10


def save_report(report: str) -> str:
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.md")
    with open(path, "w") as f:
        f.write(report)
    return path
