from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AnalysisResult:
    status: str = "OK"            # OK / INSUFFICIENT_DATA
    thesis: str = ""
    bull_case: str = ""
    bear_case: str = ""
    sentiment_score: Optional[int] = None  # -10 to +10; None when data is insufficient
    catalysts: list = field(default_factory=list)
    risk_flags: list = field(default_factory=list)
    invalidation_triggers: list = field(default_factory=list)
    holder_action: str = "N/A"    # HOLD / ADD / TRIM / REVIEW_EXIT / N/A (not held)
    new_buyer_action: str = ""    # BUY / WATCH / AVOID
    confidence: str = ""          # low / medium / high
    evidence_used: list = field(default_factory=list)

@dataclass
class RiskProfile:
    # None = not enough data; never replaced by a favourable default
    beta: Optional[float] = None
    volatility_30d: Optional[float] = None
    max_drawdown_6mo: Optional[float] = None
    debt_to_equity: Optional[float] = None
    rsi_14: Optional[float] = None
    geo_exposure: str = "Unknown"  # Low/Medium/High
    geo_notes: list = field(default_factory=list)   # active regulatory/geopolitical themes
    composite_score: Optional[float] = None  # 1-10
    coverage: float = 0.0          # share of risk weights backed by real data

@dataclass
class ShariahStatus:
    compliant: str = "Unknown"  # Yes / No / Review / Unknown — a label, never a filter
    methodology: str = ""
    debt_ratio: Optional[float] = None
    cash_ratio: Optional[float] = None
    receivables_ratio: Optional[float] = None
    income_ratio: Optional[float] = None       # non-permissible (interest) income / total income
    activity_screen: str = "Unknown"  # Pass / Fail / Review
    reasons: list = field(default_factory=list)
    inputs_source: str = ""     # e.g. "yfinance statements FY2025" / "SEC XBRL"
    second_opinion: dict = field(default_factory=dict)   # {"Musaffa": url, "Zoya": url}
    previous: str = ""          # status at the previous run

@dataclass
class MacroContext:
    regime: str = "Unknown"
    themes: list = field(default_factory=list)
    fed_rate: Optional[float] = None
    vix: Optional[float] = None
    yield_spread: Optional[float] = None
    cpi_yoy: Optional[float] = None
    unemployment: Optional[float] = None
    eurusd: Optional[float] = None
    geopolitical_summary: str = ""
    macro_news: list = field(default_factory=list)
    events: list = field(default_factory=list)        # upcoming macro events {date, name}
    geo_themes: list = field(default_factory=list)    # active regulatory/geopolitical themes

@dataclass
class PortfolioHolding:
    ticker: str = ""
    name: str = ""
    shares: float = 0.0
    bep: float = 0.0              # breakeven price
    bep_currency: str = "USD"     # currency BEP was set in
    current_price: float = 0.0    # in the listing currency
    price_in_bep: Optional[float] = None   # current price converted to bep_currency
    fx_rate: Optional[float] = None        # bep_currency per listing-currency unit
    pl_pct: Optional[float] = None    # % gain/loss vs BEP, in bep_currency
    pl_value: Optional[float] = None  # (price - BEP) × shares, in bep_currency
    value_eur: Optional[float] = None
    cost_eur: Optional[float] = None
    pl_value_eur: Optional[float] = None
    weight_pct: Optional[float] = None    # share of priced portfolio value (EUR)
    status: str = ""              # HOLD / SELL / TRIM / etc.
    asset_type: str = "Stock"
    themes: list = field(default_factory=list)
    shariah_note: str = ""
    note: str = ""                # why P&L is missing, etc.

@dataclass
class Opportunity:
    ticker: str = ""
    name: str = ""
    sector: str = "N/A"
    industry: str = "N/A"
    country: str = "N/A"
    currency: str = "USD"   # ISO currency code from yfinance
    region: str = "US"      # display region from REGION_MAP
    # Price data
    price: float = 0.0
    # Price provenance
    price_source: str = ""        # "Yahoo Finance"
    price_time: str = ""          # when the quote was set (UTC)
    price_type: str = ""          # "live (delayed)" / "last close"
    market_state: str = ""
    exchange: str = ""
    quote_type: str = ""          # EQUITY / ETF ...
    financial_currency: str = ""  # currency of the financial statements
    avg_volume: Optional[float] = None
    dividend_rate: Optional[float] = None       # annual dividend per share (quote currency)
    short_pct_float: Optional[float] = None     # % of float sold short
    # Analyst consensus quality
    analyst_count: Optional[int] = None
    target_high: Optional[float] = None
    target_low: Optional[float] = None
    target_median: Optional[float] = None
    target_source: str = ""
    consensus_quality: str = ""   # Good / Thin / Wide / None
    adj_upside: Optional[float] = None   # upside discounted for thin/wide consensus
    rating_changes_90d: dict = field(default_factory=dict)   # {"up": n, "down": n}
    # Statement inputs for the Shariah ratios: {field: value, "currency", "period", "source"}
    shariah_inputs: dict = field(default_factory=dict)
    # Data quality
    data_flags: list = field(default_factory=list)   # what is missing/stale
    data_ok: bool = True
    # Trend vs benchmarks
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    rel_strength: dict = field(default_factory=dict)  # {"SPY": +12.3, ...} 6-month excess return %
    trend: str = ""               # Uptrend / Downtrend / Mixed / Unknown
    # Events
    next_event: str = ""
    days_to_event: Optional[int] = None
    # Thesis / sell discipline
    thesis_status: str = ""       # On track / Review / Broken
    thesis_notes: list = field(default_factory=list)
    # Tradability
    tradable: str = ""            # Yes / Watch only / Unknown
    # Second-source check: Verified / Mismatch / Single source / Unchecked
    price_check: str = "Unchecked"
    price_alt: Optional[float] = None        # Finnhub price
    price_diff_pct: Optional[float] = None   # Yahoo vs Finnhub, %
    price_as_of: str = ""                    # Finnhub quote time
    target: float = 0.0
    upside: Optional[float] = None
    # Fundamentals
    fpe: Optional[float] = None
    rev_growth: float = 0.0
    eps_growth: float = 0.0
    beta: Optional[float] = None
    de: Optional[float] = None
    gross_margin: float = 0.0
    op_margin: float = 0.0
    w52_low: Optional[float] = None
    w52_high: Optional[float] = None
    rec: str = "N/A"
    mcap: float = 0.0
    # For Shariah/Risk
    total_debt: float = 0.0
    total_cash: float = 0.0
    total_revenue: float = 0.0
    interest_expense: float = 0.0
    total_assets: float = 0.0
    accounts_receivable: float = 0.0
    interest_income: float = 0.0
    short_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    # Historical prices (list of close prices, newest last)
    hist_prices: list = field(default_factory=list)
    # News
    news: list = field(default_factory=list)
    # NewsAPI keyword sentiment score (-10..+10, always available)
    news_sentiment_score: float = 0.0
    # Alpha Vantage enrichment
    earnings_date: Optional[str] = None     # next earnings date YYYY-MM-DD
    eps_surprise: Optional[float] = None    # last quarter EPS surprise %
    # Insider trading signal (SEC EDGAR Form 4)
    insider_signal: str = "Neutral"         # Bullish / Bearish / Neutral
    insider_net_shares: int = 0             # net shares bought (+) / sold (-)
    # FinBERT score over full article text (-10..+10), None if not run
    finbert_score: Optional[float] = None
    # Recent SEC filings: {form, date, items, labels, red_flag, url}
    filings: list = field(default_factory=list)
    # Index / Shariah ETF membership, e.g. ["S&P 500", "SPUS"]
    universe_tags: list = field(default_factory=list)
    # Portfolio holding (if this ticker is in user's portfolio)
    portfolio: Optional[PortfolioHolding] = None
    # Sell review (holdings only): price facts for exits and the verdict
    exit_metrics: dict = field(default_factory=dict)   # drawdown from 6m high, trailing stop, 3m return
    sell_review: dict = field(default_factory=dict)    # {category, strength, action}
    # Pipeline outputs
    analysis: Optional[AnalysisResult] = None
    risk: Optional[RiskProfile] = None
    shariah: Optional[ShariahStatus] = None
    # Composite ranking score
    rank_score: float = 0.0
