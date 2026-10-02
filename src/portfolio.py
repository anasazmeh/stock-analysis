"""
Portfolio P&L, EUR totals, weights and concentration checks.
Holdings are defined in portfolio_data.py at the project root.

P&L is computed in each position's own breakeven currency: a USD-listed price is
converted with the day's ECB rate before comparing it with a EUR breakeven. If no
rate is available the P&L is left empty rather than mixing currencies.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.fx import FxTable
from src.models import Opportunity, PortfolioHolding

try:
    from portfolio_data import HOLDINGS
except ImportError:
    HOLDINGS = []


def _holding(h: dict) -> PortfolioHolding:
    return PortfolioHolding(
        ticker=h.get("ticker", ""),
        name=h.get("name", h.get("ticker", "")),
        shares=h["shares"],
        bep=h["bep"],
        bep_currency=h.get("bep_currency", "USD").upper(),
        status=h.get("status", ""),
        asset_type=h.get("asset_type", "Stock"),
        themes=list(h.get("themes", [])),
        shariah_note=h.get("shariah_note", ""),
    )


def value_holding(p: PortfolioHolding, price: float, currency: str, fx: FxTable,
                  units_per_listing: float = 1.0) -> PortfolioHolding:
    """Fill P&L, EUR value and cost for one holding priced at `price` in `currency`."""
    unit_price = price * units_per_listing
    p.current_price = unit_price
    p.cost_eur = fx.convert(p.bep * p.shares, p.bep_currency, "EUR")
    if unit_price <= 0 or p.bep <= 0:
        p.note = "No valid price"
        return p
    p.fx_rate = fx.rate(currency, p.bep_currency)
    if p.fx_rate is None:
        p.note = f"No {currency}->{p.bep_currency} FX rate — P&L not computed"
        return p
    p.price_in_bep = unit_price * p.fx_rate
    p.pl_pct = round((p.price_in_bep / p.bep - 1) * 100, 1)
    p.pl_value = round((p.price_in_bep - p.bep) * p.shares, 2)
    p.value_eur = fx.convert(unit_price * p.shares, currency, "EUR")
    if p.value_eur is not None and p.cost_eur is not None:
        p.pl_value_eur = round(p.value_eur - p.cost_eur, 2)
    return p


def attach_portfolio(opportunities: list[Opportunity], fx: FxTable) -> list[Opportunity]:
    """Attach P&L (in the breakeven currency) and EUR value to held opportunities."""
    by_ticker = {h["ticker"]: h for h in HOLDINGS if h.get("ticker")}
    for opp in opportunities:
        h = by_ticker.get(opp.ticker)
        if not h:
            continue
        opp.portfolio = value_holding(_holding(h), opp.price, opp.currency, fx,
                                      h.get("units_per_listing", 1.0))
    _set_weights([o.portfolio for o in opportunities if o.portfolio])
    return opportunities


def _set_weights(holdings: list[PortfolioHolding]):
    total = sum(p.value_eur for p in holdings if p.value_eur)
    for p in holdings:
        p.weight_pct = round(p.value_eur / total * 100, 1) if total and p.value_eur else None


def unpriced_holdings(opportunities: list[Opportunity]) -> list[PortfolioHolding]:
    """Holdings with no price this run (blank ticker, or the fetch failed)."""
    priced = {o.ticker for o in opportunities if o.portfolio and o.portfolio.value_eur}
    missing = []
    for h in HOLDINGS:
        if h.get("ticker") and h["ticker"] in priced:
            continue
        p = _holding(h)
        p.note = "No Yahoo ticker set in portfolio_data.py" if not h.get("ticker") else "Price unavailable this run"
        missing.append(p)
    return missing


def exposure(opportunities: list[Opportunity]) -> dict:
    """EUR totals, theme / currency weights and cap breaches across priced holdings."""
    held = [o for o in opportunities if o.portfolio and o.portfolio.value_eur]
    total = sum(o.portfolio.value_eur for o in held)
    cost = sum(o.portfolio.cost_eur or 0 for o in held)
    themes, currencies = {}, {}
    for o in held:
        for t in o.portfolio.themes or ["Other"]:
            themes[t] = themes.get(t, 0) + o.portfolio.value_eur
        currencies[o.currency] = currencies.get(o.currency, 0) + o.portfolio.value_eur
    pct = lambda d: {k: round(v / total * 100, 1) for k, v in sorted(d.items(), key=lambda kv: -kv[1])} if total else {}
    breaches = [f"{o.ticker} is {o.portfolio.weight_pct:.0f}% of the portfolio (cap {config.POSITION_CAP_PCT:g}%)"
                for o in held if (o.portfolio.weight_pct or 0) > config.POSITION_CAP_PCT]
    breaches += [f"Theme '{t}' is {w:.0f}% of the portfolio (cap {config.THEME_CAP_PCT:g}%)"
                 for t, w in pct(themes).items() if w > config.THEME_CAP_PCT]
    return {
        "total_value_eur": round(total, 2),
        "total_cost_eur": round(cost, 2),
        "total_pl_eur": round(total - cost, 2),
        "themes": pct(themes),
        "currencies": pct(currencies),
        "breaches": breaches,
    }


def post_trade_weight(opp: Opportunity, add_eur: float, exp: dict) -> dict:
    """Weights of the position and its themes after adding `add_eur` (EUR)."""
    total = exp["total_value_eur"]
    if not total:
        return {}
    current = opp.portfolio.value_eur if opp.portfolio and opp.portfolio.value_eur else 0.0
    new_total = total + add_eur
    themes = opp.portfolio.themes if opp.portfolio else []
    return {
        "position_pct": round((current + add_eur) / new_total * 100, 1),
        "themes": {t: round((exp["themes"].get(t, 0) / 100 * total + add_eur) / new_total * 100, 1)
                   for t in themes},
    }


def breaches_after_add(opp: Opportunity, exp: dict) -> list[str]:
    """Caps a standard-size ADD (config.TYPICAL_ADD_EUR) would break."""
    after = post_trade_weight(opp, config.TYPICAL_ADD_EUR, exp)
    if not after:
        return []
    out = []
    if after["position_pct"] > config.POSITION_CAP_PCT:
        out.append(f"position would be {after['position_pct']:.0f}% (cap {config.POSITION_CAP_PCT:g}%)")
    out += [f"theme '{t}' would be {w:.0f}% (cap {config.THEME_CAP_PCT:g}%)"
            for t, w in after["themes"].items() if w > config.THEME_CAP_PCT]
    return out


def purification(opp: Opportunity, fx: FxTable) -> dict:
    """
    Estimated annual dividend purification: dividends x non-permissible income share.
    Uses the Shariah income ratio (interest income / total income) as the
    non-permissible share — a common approximation; your scholar may prescribe another.
    """
    p = opp.portfolio
    if not p or not opp.dividend_rate or not opp.shariah or opp.shariah.income_ratio is None:
        return {}
    dividends = opp.dividend_rate * p.shares
    amount = dividends * opp.shariah.income_ratio
    return {"dividends": round(dividends, 2), "currency": opp.currency, "ratio": opp.shariah.income_ratio,
            "amount": round(amount, 2), "amount_eur": fx.convert(amount, opp.currency, "EUR")}


def get_portfolio_tickers() -> list[str]:
    """Yahoo symbols of all priced holdings."""
    return [h["ticker"] for h in HOLDINGS if h.get("ticker")]
