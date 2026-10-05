"""
Stage 4 — Claude analysis, grounded in a dated evidence pack.

Runs after data quality, Shariah, risk, portfolio exposure, events and macro, so
Claude sees all of them. Each ticker gets a fact sheet of {value, source, as_of};
Claude must use only those facts, cite the ones it used, and return
INSUFFICIENT_DATA instead of guessing. Output is schema-constrained JSON and is
validated before it is cached or used.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import json
import os
import shutil
import subprocess
from datetime import date

import config
import src.cache as cache
from src.models import Opportunity, AnalysisResult, MacroContext

HOLDER_ACTIONS = ["HOLD", "ADD", "TRIM", "REVIEW_EXIT", "N/A"]
BUYER_ACTIONS = ["BUY", "WATCH", "AVOID"]

SYSTEM = (
    "You are a careful equity research analyst writing for one retail investor based in Europe "
    "who only invests in Shariah-compliant companies (AAOIFI). Use ONLY the facts in the evidence "
    "pack. Do not use prices, dates, deal terms or events from memory. When you mention a price, "
    "say its type and time as given (e.g. 'last close 2026-10-01'). If the facts are not enough "
    "for a view, set status to INSUFFICIENT_DATA and leave the opinion fields empty. Give a balanced "
    "bull and bear case and concrete invalidation triggers. List in evidence_used the fact keys you "
    "relied on. A Shariah status other than 'Yes' must be mentioned in risk_flags. This is not "
    "financial advice."
)

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "status": {"type": "string", "enum": ["OK", "INSUFFICIENT_DATA"]},
                    "thesis": {"type": "string"},
                    "bull_case": {"type": "string"},
                    "bear_case": {"type": "string"},
                    "invalidation_triggers": {"type": "array", "items": {"type": "string"}},
                    "sentiment_score": {"type": "integer"},
                    "catalysts": {"type": "array", "items": {"type": "string"}},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                    "holder_action": {"type": "string", "enum": HOLDER_ACTIONS},
                    "new_buyer_action": {"type": "string", "enum": BUYER_ACTIONS},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "evidence_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ticker", "status", "thesis", "bull_case", "bear_case",
                             "invalidation_triggers", "sentiment_score", "catalysts", "risk_flags",
                             "holder_action", "new_buyer_action", "confidence", "evidence_used"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["analyses"],
    "additionalProperties": False,
}

_MACRO_SCHEMA = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["risk-on", "risk-off", "neutral"]},
        "themes": {"type": "array", "items": {"type": "string"}},
        "geopolitical_summary": {"type": "string"},
    },
    "required": ["regime", "themes", "geopolitical_summary"],
    "additionalProperties": False,
}


def _fact(value, source, as_of=""):
    return {"value": value, "source": source, "as_of": as_of}


def evidence_pack(opp: Opportunity) -> dict:
    """Facts for one ticker. Missing values are omitted, never filled in."""
    facts = {}

    def add(key, value, source, as_of=""):
        if value not in (None, "", [], {}):
            facts[key] = _fact(value, source, as_of)

    add("price", f"{opp.price} {opp.currency} ({opp.price_type})", opp.price_source, opp.price_time)
    add("price_check", opp.price_check, "Finnhub cross-check", opp.price_as_of)
    add("analyst_target_mean", opp.target or None, opp.target_source)
    add("analyst_count", opp.analyst_count, opp.target_source)
    if opp.target_high and opp.target_low:
        add("analyst_target_range", f"{opp.target_low}–{opp.target_high}", opp.target_source)
    add("upside_pct_quality_adjusted", opp.adj_upside, "computed")
    add("consensus_quality", opp.consensus_quality, "computed")
    add("rating_changes_90d", opp.rating_changes_90d, "Yahoo upgrades/downgrades")
    add("forward_pe", opp.fpe, "Yahoo")
    add("revenue_growth_pct", opp.rev_growth or None, "Yahoo")
    add("eps_growth_pct", opp.eps_growth or None, "Yahoo")
    add("gross_margin_pct", opp.gross_margin or None, "Yahoo")
    add("debt_to_equity", opp.de, "Yahoo")
    add("eps_surprise_last_q_pct", opp.eps_surprise, "Alpha Vantage")
    add("next_event", opp.next_event, "events calendar")
    add("trading_days_to_event", opp.days_to_event, "events calendar")
    add("trend", opp.trend, "computed from price history")
    add("relative_strength_6m_pts", opp.rel_strength, "computed vs benchmarks")
    if opp.risk:
        add("risk_score_1_10", opp.risk.composite_score, "computed")
        add("volatility_30d_pct", opp.risk.volatility_30d, "computed")
        add("max_drawdown_6m_pct", opp.risk.max_drawdown_6mo, "computed")
        add("geo_exposure", opp.risk.geo_exposure, "config + supply chain")
        add("geo_notes", opp.risk.geo_notes, "config + regulatory feed")
    if opp.shariah:
        add("shariah_status", f"{opp.shariah.compliant} ({opp.shariah.methodology})", "computed",
            opp.shariah.inputs_source)
        add("shariah_reasons", opp.shariah.reasons, "computed")
    add("insider_signal_30d", opp.insider_signal if opp.insider_signal not in ("Neutral", "") else None,
        "SEC Form 4")
    add("recent_sec_filings", [f"{f['date']} {f['form']}: {', '.join(f['labels'])}" for f in opp.filings[:5]],
        "SEC EDGAR")
    add("news_sentiment_finbert", opp.finbert_score, "FinBERT over recent articles")
    for i, n in enumerate((opp.news or [])[:6]):
        add(f"news_{i + 1}", n.get("title"), n.get("source") or n.get("provider", ""), n.get("date", ""))
        if n.get("text"):
            add(f"news_{i + 1}_excerpt", n["text"][:400], n.get("source", ""), n.get("date", ""))
    if opp.portfolio:
        p = opp.portfolio
        add("held_position", f"{p.shares:g} units, breakeven {p.bep} {p.bep_currency}", "portfolio_data.py")
        add("position_pl_pct", p.pl_pct, f"computed in {p.bep_currency} with ECB FX")
        add("position_weight_pct", p.weight_pct, "computed (EUR)")
        add("position_themes", p.themes, "portfolio_data.py")
        add("thesis_status", opp.thesis_status, "data/theses.json rules")
        add("thesis_notes", opp.thesis_notes, "data/theses.json rules")
        m = opp.exit_metrics or {}
        add("drawdown_from_6m_high_pct", m.get("drawdown_from_high_pct"), "computed from price history")
        if "trail_stop_price" in m:
            add("trailing_stop", f"{m['trail_stop_price']} ({m['trail_stop_pct']}% below the 6-month high"
                f"{', HIT' if m['trail_stop_hit'] else ''})", "computed: 2x one-month volatility, 12-30%")
        add("return_3m_pct", m.get("return_3m_pct"), "computed from price history")
    return {"ticker": opp.ticker, "name": opp.name, "sector": opp.sector, "country": opp.country,
            "held": bool(opp.portfolio), "facts": facts}


def validate(raw: dict, packs: dict) -> dict:
    """Return {ticker: AnalysisResult} for well-formed items that match the batch."""
    out = {}
    for item in (raw or {}).get("analyses", []):
        t = item.get("ticker")
        if t not in packs:
            continue
        pack = packs[t]
        known = set(pack["facts"])
        if item["status"] == "INSUFFICIENT_DATA":
            out[t] = AnalysisResult(status="INSUFFICIENT_DATA",
                                    risk_flags=item.get("risk_flags", []),
                                    holder_action="HOLD" if pack["held"] else "N/A",
                                    new_buyer_action="WATCH", confidence="low")
            continue
        holder = item["holder_action"] if pack["held"] else "N/A"
        if pack["held"] and holder == "N/A":
            holder = "HOLD"
        out[t] = AnalysisResult(
            status="OK",
            thesis=item["thesis"], bull_case=item["bull_case"], bear_case=item["bear_case"],
            sentiment_score=max(-10, min(10, int(item["sentiment_score"]))),
            catalysts=item["catalysts"][:4], risk_flags=item["risk_flags"][:4],
            invalidation_triggers=item["invalidation_triggers"][:4],
            holder_action=holder, new_buyer_action=item["new_buyer_action"],
            confidence=item["confidence"],
            evidence_used=[k for k in item["evidence_used"] if k in known],
        )
    return out


def ai_available() -> bool:
    """claude-cli: the `claude` command is installed · api: a key is set · off: never."""
    if config.AI_BACKEND == "claude-cli":
        return shutil.which(config.CLAUDE_CLI) is not None
    if config.AI_BACKEND == "api":
        return bool(config.ANTHROPIC_API_KEY)
    return False


def ai_unavailable_reason() -> str:
    if config.AI_BACKEND == "claude-cli":
        return f"`{config.CLAUDE_CLI}` command not found — install Claude Code and log in"
    if config.AI_BACKEND == "api":
        return "ANTHROPIC_API_KEY not set"
    return "AI_BACKEND is 'off'"


def _ai_errors() -> tuple:
    errors = (RuntimeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, OSError)
    if config.AI_BACKEND == "api":
        import anthropic
        errors += (anthropic.APIError,)
    return errors


def _client():
    if config.AI_BACKEND != "api":
        return None
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)


def _call(client, user_text: str, schema: dict) -> dict:
    if config.AI_BACKEND == "claude-cli":
        return _call_cli(user_text, schema)
    return _call_api(client, user_text, schema)


def _call_cli(user_text: str, schema: dict) -> dict:
    """
    Run `claude -p` (Claude Code) so the analysis uses your Claude subscription.
    ANTHROPIC_API_KEY is removed from the child environment so the CLI never
    bills an API key; tools and MCP servers are disabled — it only reads the prompt.
    """
    cmd = [config.CLAUDE_CLI, "-p", "--output-format", "json", "--model", config.CLAUDE_CLI_MODEL,
           "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--system-prompt", SYSTEM, "--json-schema", json.dumps(schema)]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    proc = subprocess.run(cmd, input=user_text, capture_output=True, text=True,
                          timeout=config.CLAUDE_CLI_TIMEOUT, env=env)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude error ({out.get('subtype')}): {str(out.get('result'))[:200]}")
    if isinstance(out.get("structured_output"), dict):
        return out["structured_output"]
    return json.loads(out.get("result") or "")


def _call_api(client, user_text: str, schema: dict) -> dict:
    """One schema-constrained API request with server-side refusal fallback (paid)."""
    response = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_text}],
        output_config={"effort": config.CLAUDE_EFFORT,
                       "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("response truncated (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)


def _model_id() -> str:
    return f"cli:{config.CLAUDE_CLI_MODEL}" if config.AI_BACKEND == "claude-cli" else config.CLAUDE_MODEL


def _ticker_prompt(packs: list, macro: MacroContext, today: str) -> str:
    return (
        f"Today is {today}.\n\nMarket context: regime={macro.regime or 'Unknown'}; "
        f"themes={json.dumps(macro.themes)}; upcoming events={json.dumps(macro.events[:6])}.\n\n"
        f"Evidence packs ({len(packs)} stocks):\n{json.dumps(packs, indent=1, default=str)}\n\n"
        "Return one analysis per ticker. holder_action applies only to held positions "
        "(use N/A otherwise); new_buyer_action is for someone without a position. "
        "sentiment_score is -10..+10 (use 0 with INSUFFICIENT_DATA)."
    )


def analyze_tickers(opportunities: list[Opportunity], macro: MacroContext) -> tuple[list[Opportunity], str]:
    """Analyse tickers that passed the data gate. Returns (opportunities, prompt hash)."""
    if not ai_available():
        print(f"  [intelligence] Skipping AI analysis: {ai_unavailable_reason()}")
        return opportunities, ""
    client = _client()
    errors = _ai_errors()
    today = date.today().isoformat()
    usable = [o for o in opportunities if o.price > 0 and o.data_ok]
    usable.sort(key=lambda o: (0 if o.portfolio else 1, -(o.rank_score or 0)))
    eligible = usable[:config.AI_MAX_TICKERS]
    skipped = len([o for o in opportunities if o.price > 0]) - len(usable)
    if skipped:
        print(f"  [intelligence] {skipped} tickers skipped (failed data-quality gate)")
    if len(usable) > len(eligible):
        print(f"  [intelligence] {len(usable) - len(eligible)} lower-ranked tickers not sent "
              f"(AI_MAX_TICKERS={config.AI_MAX_TICKERS})")
    hashes = []

    def run(batch):
        packs = {o.ticker: evidence_pack(o) for o in batch}
        prompt = _ticker_prompt(list(packs.values()), macro, today)
        digest = hashlib.sha256((_model_id() + SYSTEM + prompt).encode()).hexdigest()[:16]
        hashes.append(digest)
        key = f"ai:v2:{digest}"
        cached = cache.get(key, config.TTL_AI)
        try:
            raw = cached or _call(client, prompt, _ANALYSIS_SCHEMA)
            results = validate(raw, packs)
        except errors as e:
            print(f"  [intelligence] batch {list(packs)} failed: {type(e).__name__}: {str(e)[:120]}")
            return list(packs)
        if not cached and len(results) == len(packs):
            cache.set(key, raw)  # only cache complete, validated answers
        for o in batch:
            if o.ticker in results:
                o.analysis = results[o.ticker]
        return [t for t in packs if t not in results]

    for i in range(0, len(eligible), config.BATCH_SIZE):
        batch = eligible[i:i + config.BATCH_SIZE]
        print(f"  [intelligence] Analyzing {[o.ticker for o in batch]}")
        missing = run(batch)
        for t in missing:  # retry one by one
            single = [o for o in batch if o.ticker == t]
            if run(single):
                print(f"  [intelligence] {t}: no valid analysis")
    combined = hashlib.sha256("".join(hashes).encode()).hexdigest()[:12] if hashes else ""
    return opportunities, combined


def build_macro_analysis(macro: MacroContext, opportunities: list[Opportunity]) -> MacroContext:
    """One schema-constrained call: regime, themes, geopolitical summary."""
    if not ai_available():
        return macro
    headlines = [f"[{n.get('region', '')} · {n.get('date') or 'undated'} · {n.get('source', '')}] {n.get('title', '')}"
                 for n in (macro.macro_news or [])[:20]]
    indicators = {"fed_funds_pct": macro.fed_rate, "cpi_yoy_pct": macro.cpi_yoy,
                  "unemployment_pct": macro.unemployment, "us_10y_2y_spread_pct": macro.yield_spread,
                  "vix": macro.vix, "eurusd": macro.eurusd}
    sectors = sorted({o.sector for o in opportunities if o.price > 0})
    prompt = (f"Today is {date.today().isoformat()}. Assess the market regime from ONLY these inputs.\n"
              f"Indicators (FRED, latest): {json.dumps(indicators)}\n"
              f"Upcoming events: {json.dumps(macro.events[:8])}\n"
              f"Active regulatory/geopolitical themes: {json.dumps(macro.geo_themes)}\n"
              f"Headlines: {json.dumps(headlines, indent=1)}\n"
              f"Sectors covered: {json.dumps(sectors)}\n"
              "Give 3-5 themes and a 2-3 sentence geopolitical summary.")
    digest = hashlib.sha256((_model_id() + prompt).encode()).hexdigest()[:16]
    cached = cache.get(f"ai:macro:v2:{digest}", config.TTL_AI)
    try:
        result = cached or _call(_client(), prompt, _MACRO_SCHEMA)
    except _ai_errors() as e:
        print(f"  [intelligence] Macro analysis failed: {type(e).__name__}")
        return macro
    if not cached:
        cache.set(f"ai:macro:v2:{digest}", result)
    macro.regime = result.get("regime", "Unknown")
    macro.themes = result.get("themes", [])
    macro.geopolitical_summary = result.get("geopolitical_summary", "")
    return macro
