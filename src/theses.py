"""
Thesis and sell-discipline rules for holdings.

data/theses.json (optional, see data/theses.example.json) holds per-ticker:
  {"NVDA": {"thesis": "...", "review_date": "2027-01-31", "target_weight": 10,
            "invalidation": [{"type": "trend", "value": "Downtrend"},
                             {"type": "price_below", "value": 120}]}}
Holdings without an entry get config.DEFAULT_THESIS_RULES.

Status: Broken (an invalidation rule fired) / Review (soft rule or review date
passed) / On track.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date

import config
from src.models import Opportunity

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "theses.json")


def load_theses(path: str = None) -> dict:
    path = path or _PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"  [theses] {path} unreadable: {e}")
        return {}


def check_rule(opp: Opportunity, rule: dict):
    """Return a message if the rule fires, else None."""
    t, v = rule.get("type"), rule.get("value")
    p = opp.portfolio
    if t == "price_below" and opp.price and opp.price < v:
        return f"price {opp.price:.2f} below {v}"
    if t == "trend" and opp.trend == v:
        return f"trend is {v}"
    if t == "pl_below" and p and p.pl_pct is not None and p.pl_pct < v:
        return f"P&L {p.pl_pct:+.0f}% below {v}%"
    if t == "weight_above" and p and p.weight_pct is not None and p.weight_pct > v:
        return f"weight {p.weight_pct:.0f}% above {v}%"
    if t == "shariah_not" and opp.shariah and opp.shariah.compliant != v:
        return f"Shariah status is {opp.shariah.compliant}"
    if t == "shariah_is" and opp.shariah and opp.shariah.compliant == v:
        return f"Shariah status is {v}"
    if t == "rel_strength_below" and opp.rel_strength.get("SPY") is not None and opp.rel_strength["SPY"] < v:
        return f"6-month return {opp.rel_strength['SPY']:+.0f} pts vs S&P 500 (limit {v})"
    if t == "insider" and opp.insider_signal == v:
        return f"insider signal {v}"
    return None


def evaluate(opp: Opportunity, entry: dict, today: date) -> tuple[str, list[str]]:
    hard = [m for r in entry.get("invalidation", []) if (m := check_rule(opp, r))]
    soft = [m for r in entry.get("review", []) if (m := check_rule(opp, r))]
    review_date = entry.get("review_date")
    if review_date and review_date <= today.isoformat():
        soft.append(f"review date {review_date} reached")
    if hard:
        return "Broken", hard + soft
    if soft:
        return "Review", soft
    return "On track", []


def apply_theses(opportunities: list[Opportunity], today: date = None, path: str = None):
    today = today or date.today()
    theses = load_theses(path)
    for opp in opportunities:
        if not opp.portfolio:
            continue
        entry = theses.get(opp.ticker, config.DEFAULT_THESIS_RULES)
        opp.thesis_status, opp.thesis_notes = evaluate(opp, entry, today)
        if theses.get(opp.ticker, {}).get("thesis"):
            opp.thesis_notes.insert(0, f"Thesis: {theses[opp.ticker]['thesis']}")
    return opportunities


def is_exit_candidate(opp: Opportunity) -> bool:
    status = (opp.portfolio.status if opp.portfolio else "").upper()
    return "EXIT" in status or "SELL" in status or opp.thesis_status == "Broken"
