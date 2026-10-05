"""
Dashboard snapshot: everything the web dashboard shows, written as
reports/latest.json at the end of each run (plus the run history in runs/).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses
import json
from datetime import datetime

import config
from src.models import Opportunity, MacroContext
from src.output_gate import find_violations
from src.sell_review import tax_note

_SPARK_DAYS = 126  # ~6 months of closes for the detail-page chart


def _asdict(obj):
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def opportunity_row(opp: Opportunity, top10: set) -> dict:
    return {
        "ticker": opp.ticker, "name": opp.name, "region": opp.region, "country": opp.country,
        "sector": opp.sector, "industry": opp.industry,
        "price": opp.price, "currency": opp.currency, "price_type": opp.price_type,
        "price_time": opp.price_time, "price_source": opp.price_source,
        "price_check": opp.price_check, "price_alt": opp.price_alt, "price_diff_pct": opp.price_diff_pct,
        "target": opp.target or None, "upside": opp.upside, "adj_upside": opp.adj_upside,
        "analyst_count": opp.analyst_count, "consensus_quality": opp.consensus_quality,
        "target_high": opp.target_high, "target_low": opp.target_low, "target_source": opp.target_source,
        "rating_changes_90d": opp.rating_changes_90d, "rec": opp.rec, "mcap": opp.mcap, "fpe": opp.fpe,
        "rank_score": opp.rank_score, "top10": opp.ticker in top10,
        "data_ok": opp.data_ok, "data_flags": opp.data_flags, "tradable": opp.tradable,
        "shariah": _asdict(opp.shariah), "risk": _asdict(opp.risk), "analysis": _asdict(opp.analysis),
        "portfolio": _asdict(opp.portfolio),
        "trend": opp.trend, "ma50": opp.ma50, "ma200": opp.ma200, "rel_strength": opp.rel_strength,
        "next_event": opp.next_event, "days_to_event": opp.days_to_event,
        "insider_signal": opp.insider_signal, "insider_net_shares": opp.insider_net_shares,
        "eps_surprise": opp.eps_surprise, "finbert_score": opp.finbert_score,
        "short_pct_float": opp.short_pct_float, "universe_tags": opp.universe_tags,
        "thesis_status": opp.thesis_status, "thesis_notes": opp.thesis_notes,
        "exit_metrics": opp.exit_metrics, "sell_review": opp.sell_review,
        "filings": opp.filings[:10],
        "news": [{k: n.get(k, "") for k in ("title", "source", "date", "url", "provider")} for n in opp.news[:8]],
        "history": [round(p, 4) for p in opp.hist_prices[-_SPARK_DAYS:]],
    }


def build_payload(opportunities: list[Opportunity], macro: MacroContext, *, health, fx, exposure: dict,
                  unpriced: list, top10: list, alerts: list, changes: list, purification_rows: list,
                  broker_diffs, scorecard: dict, sell_rows: list = None, now: datetime = None) -> dict:
    now = now or datetime.now()
    top = {o.ticker for o in top10}
    rows = [opportunity_row(o, top) for o in opportunities
            if o.ticker not in config.AVOID_LIST and (o.price > 0 or o.portfolio)]
    payload = {
        "run_at": now.isoformat(timespec="seconds"),
        "degraded": bool(health and health.degraded),
        "degraded_reasons": list(health.degraded_reasons) if health else [],
        "sources": [{"name": k, "status": v[0], "detail": v[1]} for k, v in (health.sources.items() if health else [])],
        "fx": {"date": fx.date, "source": fx.source, "eurusd": fx.rates.get("USD")} if fx is not None and fx.rates else {},
        "shariah_methodology": config.SHARIAH_METHODOLOGY,
        "rank_weights": config.RANK_WEIGHTS,
        "macro": {
            "regime": macro.regime, "themes": macro.themes, "geopolitical_summary": macro.geopolitical_summary,
            "indicators": {"Fed funds %": macro.fed_rate, "US CPI YoY %": macro.cpi_yoy,
                           "US unemployment %": macro.unemployment, "10Y-2Y spread %": macro.yield_spread,
                           "VIX": macro.vix, "EUR/USD": macro.eurusd},
            "events": macro.events, "geo_themes": macro.geo_themes,
            "news": [{k: n.get(k, "") for k in ("title", "source", "date", "url", "region")} for n in macro.macro_news[:15]],
        },
        "portfolio": {
            **{k: exposure.get(k) for k in ("total_value_eur", "total_cost_eur", "total_pl_eur",
                                            "themes", "currencies", "breaches")},
            "unpriced": [_asdict(p) for p in unpriced],
            "purification": [{"ticker": t, **r} for t, r in purification_rows],
            "broker_diffs": broker_diffs,
            "scorecard": scorecard,
        },
        "opportunities": rows,
        "sell_review": [r for r in (sell_rows or []) if r["ticker"] not in config.AVOID_LIST],
        "tax_residence": config.TAX_RESIDENCE,
        "sell_notes": [config.BROKER_COST_NOTE, tax_note()],
        "sell_settings": {"stop_loss_pct": config.SELL_STOP_LOSS_PCT, "take_profit_pct": config.SELL_TAKE_PROFIT_PCT,
                          "strong_score": config.SELL_STRONG_SCORE, "position_cap_pct": config.POSITION_CAP_PCT},
        "alerts": alerts,
        "changes": changes,
        "disclaimer": "Not financial advice. Check prices on your broker before acting.",
    }
    return payload


def write_latest(payload: dict, path: str = None) -> tuple[str, int]:
    """Write the snapshot. Returns (path, avoid-list violations found — those rows are dropped)."""
    path = path or os.path.join(config.REPORT_DIR, "latest.json")
    text = json.dumps(payload, default=str)
    bad = find_violations(text.replace("},", "},\n"))
    if bad:
        payload["opportunities"] = [r for r in payload["opportunities"]
                                    if not find_violations(json.dumps(r, default=str))]
        payload["alerts"] = [a for a in payload["alerts"] if not find_violations(json.dumps(a))]
        payload["sell_review"] = [r for r in payload.get("sell_review", [])
                                  if not find_violations(json.dumps(r, default=str))]
        text = json.dumps(payload, default=str)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    return path, len(bad)
