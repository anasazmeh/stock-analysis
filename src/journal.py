"""
Run snapshots and decision journal.

- runs/<timestamp>.json   inputs and outputs of each run (prices with source and
                          time, ranks, labels, weights, model, git commit) so any
                          recommendation can be traced back to its inputs.
- data/decisions.jsonl    one row per holding / Top 10 name per run. Fill in
                          "user_action" yourself to keep a record of what you did.
- what_changed()          differences vs the previous run for the report.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob
import hashlib
import json
import subprocess
from datetime import datetime

import config
from src.models import Opportunity

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(_ROOT, "runs")
DECISIONS = os.path.join(_ROOT, "data", "decisions.jsonl")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def system_action(opp: Opportunity) -> str:
    """The pipeline's own label for a name, recorded for later review."""
    if opp.portfolio:
        if opp.thesis_status == "Broken":
            return "REVIEW EXIT (thesis broken)"
        if opp.thesis_status == "Review":
            return "REVIEW"
        return "HOLD"
    return "CANDIDATE" if opp.data_ok else "DATA GAP"


def ticker_row(opp: Opportunity) -> dict:
    return {
        "ticker": opp.ticker,
        "price": opp.price, "currency": opp.currency, "price_source": opp.price_source,
        "price_time": opp.price_time, "price_type": opp.price_type, "price_check": opp.price_check,
        "rank_score": opp.rank_score, "adj_upside": opp.adj_upside,
        "shariah": opp.shariah.compliant if opp.shariah else None,
        "trend": opp.trend, "thesis_status": opp.thesis_status,
        "ai_sentiment": opp.analysis.sentiment_score if opp.analysis else None,
        "pl_pct": opp.portfolio.pl_pct if opp.portfolio else None,
        "weight_pct": opp.portfolio.weight_pct if opp.portfolio else None,
        "data_flags": opp.data_flags,
        "action": system_action(opp),
    }


def latest_snapshot(runs_dir: str = None) -> dict:
    runs_dir = runs_dir or RUNS_DIR
    files = sorted(glob.glob(os.path.join(runs_dir, "*.json")))
    if not files:
        return {}
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def what_changed(opportunities: list[Opportunity], top10: list[Opportunity], previous: dict) -> list[str]:
    if not previous:
        return ["First recorded run — nothing to compare yet."]
    prev = {r["ticker"]: r for r in previous.get("tickers", [])}
    prev_top = set(previous.get("top10", []))
    now_top = {o.ticker for o in top10}
    out = []
    if now_top - prev_top:
        out.append("New in Top 10: " + ", ".join(sorted(now_top - prev_top)))
    if prev_top - now_top:
        out.append("Dropped from Top 10: " + ", ".join(sorted(prev_top - now_top)))
    for opp in opportunities:
        p = prev.get(opp.ticker)
        if not p:
            continue
        if opp.shariah and p.get("shariah") and p["shariah"] != opp.shariah.compliant:
            out.append(f"{opp.ticker}: Shariah {p['shariah']} → {opp.shariah.compliant}")
        if opp.portfolio and p.get("thesis_status") and p["thesis_status"] != opp.thesis_status:
            out.append(f"{opp.ticker}: thesis {p['thesis_status']} → {opp.thesis_status}")
        if p.get("price") and opp.price and p.get("currency") == opp.currency:
            move = (opp.price / p["price"] - 1) * 100
            if abs(move) >= config.WHAT_CHANGED_MOVE_PCT:
                out.append(f"{opp.ticker}: price {move:+.0f}% since last run")
    return out or ["No material changes since the last run."]


def scorecard(current_value_eur: float, benchmark_close: float, runs_dir: str = None,
              now: datetime = None) -> dict:
    runs_dir = runs_dir or RUNS_DIR
    """Portfolio value change vs the halal benchmark since the snapshot ~30 days ago.
    Trades between the two dates distort the portfolio figure, so it is labelled approximate."""
    now = now or datetime.now()
    best = None
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        try:
            with open(path) as f:
                snap = json.load(f)
            age = (now - datetime.fromisoformat(snap["run_at"])).days
        except (OSError, ValueError, KeyError):
            continue
        if age >= config.SCORECARD_DAYS and snap.get("portfolio_value_eur") and snap.get("benchmark_close"):
            best = snap  # files are sorted oldest first; keep the most recent one old enough
    if not best or not current_value_eur or not benchmark_close:
        return {}
    port = (current_value_eur / best["portfolio_value_eur"] - 1) * 100
    bench = (benchmark_close / best["benchmark_close"] - 1) * 100
    return {"since": best["run_at"][:10], "portfolio_pct": round(port, 1), "benchmark_pct": round(bench, 1),
            "benchmark": config.SCORECARD_BENCHMARK, "difference_pts": round(port - bench, 1)}


def write_snapshot(opportunities: list[Opportunity], top10: list[Opportunity], health, prompt_hash: str = "",
                   runs_dir: str = None, now: datetime = None, portfolio_value_eur: float = None,
                   benchmark_close: float = None) -> str:
    runs_dir = runs_dir or RUNS_DIR
    now = now or datetime.now()
    os.makedirs(runs_dir, exist_ok=True)
    snap = {
        "portfolio_value_eur": portfolio_value_eur,
        "benchmark_close": benchmark_close,
        "run_at": now.isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "model": (f"claude-cli:{config.CLAUDE_CLI_MODEL}" if config.AI_BACKEND == "claude-cli" else config.CLAUDE_MODEL),
        "prompt_hash": prompt_hash,
        "rank_weights": __import__("src.ranking", fromlist=["active_weights"]).active_weights(),
        "shariah_methodology": config.SHARIAH_METHODOLOGY,
        "degraded": health.degraded,
        "degraded_reasons": health.degraded_reasons,
        "sources": {k: list(v) for k, v in health.sources.items()},
        "top10": [o.ticker for o in top10],
        "tickers": [ticker_row(o) for o in opportunities if o.price > 0],
    }
    path = os.path.join(runs_dir, now.strftime("%Y-%m-%d_%H%M%S") + ".json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=1)
    return path


def append_decisions(opportunities: list[Opportunity], top10: list[Opportunity],
                     path: str = None, now: datetime = None):
    path = path or DECISIONS
    now = now or datetime.now()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    names = {o.ticker: o for o in opportunities if o.portfolio}
    names.update({o.ticker: o for o in top10})
    with open(path, "a") as f:
        for opp in names.values():
            row = ticker_row(opp)
            row.update({"date": now.date().isoformat(), "user_action": "", "review_date": ""})
            f.write(json.dumps(row) + "\n")


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
