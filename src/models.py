from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AnalysisResult:
    thesis: str = ""
    bull_case: str = ""
    bear_case: str = ""
    sentiment_score: int = 0  # -10 to +10
    catalysts: list = field(default_factory=list)
    risk_flags: list = field(default_factory=list)

@dataclass
class RiskProfile:
    beta: float = 0.0
    volatility_30d: float = 0.0
    max_drawdown_6mo: float = 0.0
    debt_to_equity: float = 0.0
    rsi_14: float = 50.0
    geo_exposure: str = "Unknown"  # Low/Medium/High
    composite_score: float = 5.0  # 1-10

@dataclass
class ShariahStatus:
    compliant: str = "Unknown"  # Yes/No/Partial
    debt_ratio: float = 0.0
    cash_ratio: float = 0.0
    receivables_ratio: float = 0.0
    activity_screen: str = "Unknown"  # Pass/Fail/Ambiguous
    reasons: list = field(default_factory=list)

@dataclass
class MacroContext:
    regime: str = "Unknown"
    themes: list = field(default_factory=list)
    fed_rate: Optional[float] = None
    vix: Optional[float] = None
    yield_spread: Optional[float] = None
    geopolitical_summary: str = ""
    macro_news: list = field(default_factory=list)

@dataclass
class Opportunity:
    ticker: str = ""
    name: str = ""
    sector: str = "N/A"
    industry: str = "N/A"
    country: str = "N/A"
    # Price data
    price: float = 0.0
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
    # Pipeline outputs
    analysis: Optional[AnalysisResult] = None
    risk: Optional[RiskProfile] = None
    shariah: Optional[ShariahStatus] = None
    # Composite ranking score
    rank_score: float = 0.0
