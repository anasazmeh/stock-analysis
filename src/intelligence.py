"""
Stage 4 — AI Analysis
Uses Claude API to synthesize fundamentals + news into investment insights.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import anthropic
import config
import src.cache as cache
from src.models import Opportunity, AnalysisResult, MacroContext


def _ticker_summary(opp: Opportunity) -> dict:
    """Build a compact summary dict for sending to Claude."""
    news_titles = [n.get("title", "") for n in (opp.news or [])[:5]]
    return {
        "ticker": opp.ticker,
        "name": opp.name,
        "sector": opp.sector,
        "country": opp.country,
        "price": opp.price,
        "analyst_target": opp.target,
        "analyst_upside_pct": opp.upside,
        "forward_pe": opp.fpe,
        "revenue_growth_pct": opp.rev_growth,
        "eps_growth_pct": opp.eps_growth,
        "beta": opp.beta,
        "debt_to_equity": opp.de,
        "gross_margin_pct": opp.gross_margin,
        "recommendation": opp.rec,
        "recent_news": news_titles,
    }


def _parse_analysis(raw: dict) -> AnalysisResult:
    """Parse Claude's JSON response into AnalysisResult."""
    return AnalysisResult(
        thesis=raw.get("thesis", ""),
        bull_case=raw.get("bull_case", ""),
        bear_case=raw.get("bear_case", ""),
        sentiment_score=max(-10, min(10, int(raw.get("sentiment_score", 0)))),
        catalysts=raw.get("catalysts", []),
        risk_flags=raw.get("risk_flags", []),
    )


def analyze_tickers(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Phase A: Analyze each ticker with Claude in batches.
    Attaches AnalysisResult to each Opportunity.
    """
    if not config.ANTHROPIC_API_KEY:
        print("  [intelligence] No ANTHROPIC_API_KEY — skipping AI analysis")
        return opportunities

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    batch_size = config.BATCH_SIZE

    for i in range(0, len(opportunities), batch_size):
        batch = opportunities[i:i + batch_size]
        print(f"  [intelligence] Analyzing batch {i//batch_size + 1}: {[o.ticker for o in batch]}")

        # Check cache for whole batch
        batch_key = f"ai:batch:{'_'.join(o.ticker for o in batch)}"
        cached_batch = cache.get(batch_key, config.TTL_AI)
        if cached_batch:
            for opp in batch:
                if opp.ticker in cached_batch:
                    opp.analysis = _parse_analysis(cached_batch[opp.ticker])
            continue

        summaries = [_ticker_summary(o) for o in batch]

        prompt = f"""You are a senior equity research analyst focused on identifying stocks with potential for exponential growth in the next 6-12 months.

Analyze each of the following {len(batch)} stocks and return a JSON object with a key for each ticker symbol.

For each ticker, provide:
- "thesis": Investment thesis in 2-3 sentences explaining why this stock could grow exponentially in 6-12 months
- "bull_case": One sentence describing the best-case scenario
- "bear_case": One sentence describing the main risk
- "sentiment_score": Integer from -10 (very bearish) to +10 (very bullish) based on fundamentals and news
- "catalysts": List of 2-4 specific catalysts that could drive growth in 6-12 months
- "risk_flags": List of 1-3 key risks specific to this stock

Stock data:
{json.dumps(summaries, indent=2)}

Respond ONLY with valid JSON. Example format:
{{
  "AAPL": {{
    "thesis": "...",
    "bull_case": "...",
    "bear_case": "...",
    "sentiment_score": 7,
    "catalysts": ["...", "..."],
    "risk_flags": ["..."]
  }}
}}"""

        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            result = json.loads(raw_text)

            # Cache and attach
            cache.set(batch_key, result)
            for opp in batch:
                if opp.ticker in result:
                    opp.analysis = _parse_analysis(result[opp.ticker])
        except Exception as e:
            print(f"  [intelligence] Batch analysis failed: {e}")

    return opportunities


def build_macro_analysis(macro: MacroContext, opportunities: list[Opportunity]) -> MacroContext:
    """
    Phase B: Single Claude call to synthesize macro context.
    Fills in regime, themes, geopolitical_summary on the MacroContext object.
    """
    if not config.ANTHROPIC_API_KEY:
        return macro

    cache_key = "ai:macro"
    cached = cache.get(cache_key, config.TTL_AI)
    if cached:
        macro.regime = cached.get("regime", "Unknown")
        macro.themes = cached.get("themes", [])
        macro.geopolitical_summary = cached.get("geopolitical_summary", "")
        return macro

    sector_breakdown = {}
    for opp in opportunities:
        sector_breakdown.setdefault(opp.sector, []).append(opp.ticker)

    macro_news_titles = [n.get("title", "") for n in (macro.macro_news or [])[:15]]

    prompt = f"""You are a macro research analyst. Based on the following market data, provide a market regime assessment.

Macro indicators:
- Fed Funds Rate: {macro.fed_rate}%
- VIX: {macro.vix}
- 10Y-2Y Yield Spread: {macro.yield_spread}%

Recent macro news headlines:
{json.dumps(macro_news_titles, indent=2)}

Sectors being analyzed: {json.dumps(sector_breakdown, indent=2)}

Respond ONLY with valid JSON:
{{
  "regime": "risk-on" or "risk-off" or "neutral",
  "themes": ["theme 1", "theme 2", "theme 3"],
  "geopolitical_summary": "2-3 sentence summary of key geopolitical risks affecting markets"
}}"""

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        result = json.loads(raw_text)

        cache.set(cache_key, result)
        macro.regime = result.get("regime", "Unknown")
        macro.themes = result.get("themes", [])
        macro.geopolitical_summary = result.get("geopolitical_summary", "")
    except Exception as e:
        print(f"  [intelligence] Macro analysis failed: {e}")

    return macro
