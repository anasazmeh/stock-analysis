import os

# ── API Keys ──────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
FRED_API_KEY      = os.environ.get("FRED_API_KEY", "")

# ── Claude ────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"
BATCH_SIZE   = 6   # tickers per Claude API call

# ── Discovery ─────────────────────────────────────────
SCREENERS = [
    "undervalued_growth_stocks",
    "growth_technology_stocks",
    "aggressive_small_caps",
    "most_actives",
    "day_gainers",
]
MAX_TICKERS = 50

CURATED_WATCHLIST = {
    # Ticker : (Region, Notes)
    "NVDA":  ("US",        "AI infrastructure king"),
    "MSFT":  ("US",        "Azure AI + Copilot"),
    "AMZN":  ("US",        "AWS + AI cloud"),
    "AVGO":  ("US",        "Networking + AI chips"),
    "PLTR":  ("US",        "Zero debt, AI gov contracts"),
    "ISRG":  ("US",        "Surgical robotics monopoly"),
    "MU":    ("US",        "AI memory chips HBM3E"),
    "ARM":   ("US",        "CPU architecture licensor"),
    "BABA":  ("China",     "Cheapest mega-cap globally"),
    "BIDU":  ("China",     "AI + autonomous vehicles"),
    "TSM":   ("Taiwan",    "AI chip monopoly"),
    "ASML":  ("EU",        "EUV lithography monopoly"),
    "SAP":   ("EU",        "Enterprise AI software"),
    "SE":    ("Singapore", "SE Asia super-app"),
    "GRAB":  ("Singapore", "SE Asia fintech/ride-hail"),
}

# ── Risk Weights (must sum to 1.0) ───────────────────
RISK_WEIGHTS = {
    "beta":        0.20,
    "volatility":  0.20,
    "drawdown":    0.15,
    "debt":        0.15,
    "geo":         0.15,
    "rsi_extreme": 0.15,
}

# ── Ranking Weights (must sum to 1.0) ─────────────────
RANK_WEIGHTS = {
    "upside":       0.30,
    "sentiment":    0.20,
    "risk_adj":     0.20,
    "momentum":     0.15,
    "shariah":      0.15,
}

# ── Shariah (AAOIFI thresholds) ───────────────────────
SHARIAH_ENABLED           = True
SHARIAH_DEBT_THRESHOLD    = 0.33
SHARIAH_CASH_THRESHOLD    = 0.33
SHARIAH_RECV_THRESHOLD    = 0.33
SHARIAH_INTEREST_THRESHOLD = 0.05  # interest income / total revenue

# ── Paths ─────────────────────────────────────────────
import pathlib
_BASE      = pathlib.Path(__file__).parent
REPORT_DIR = str(_BASE / "reports")
CACHE_DIR  = str(_BASE / "data" / "cache")

# ── Cache TTLs (seconds) ──────────────────────────────
TTL_SCREENER   = 12 * 3600
TTL_FUNDAMENTALS = 6 * 3600
TTL_NEWS       = 4 * 3600
TTL_FRED       = 24 * 3600
TTL_AI         = 12 * 3600

# ── Enrichment ────────────────────────────────────────
ENRICH_WORKERS = 5    # ThreadPoolExecutor max_workers

# ── Geopolitical exposure by country ─────────────────
GEO_EXPOSURE = {
    "China":     "High",
    "Taiwan":    "High",
    "Russia":    "High",
    "Iran":      "High",
    "US":        "Low",
    "EU":        "Low",
    "Germany":   "Low",
    "Japan":     "Low",
    "Singapore": "Medium",
    "India":     "Medium",
    "Korea":     "Medium",
}

# ── Sanity checks ─────────────────────────────────────
assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9, "RISK_WEIGHTS must sum to 1.0"
assert abs(sum(RANK_WEIGHTS.values()) - 1.0) < 1e-9, "RANK_WEIGHTS must sum to 1.0"
