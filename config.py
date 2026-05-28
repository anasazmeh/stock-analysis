import os

# ── API Keys ──────────────────────────────────────────
ANTHROPIC_API_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")
FINNHUB_API_KEY       = os.environ.get("FINNHUB_API_KEY", "")
FRED_API_KEY          = os.environ.get("FRED_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")  # free at alphavantage.co
ARGAAM_API_KEY        = os.environ.get("ARGAAM_API_KEY", "")          # Argaam Saudi data

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

    # ── US ────────────────────────────────────────────────────────────────
    "NVDA":  ("US",          "AI infrastructure king"),
    "MSFT":  ("US",          "Azure AI + Copilot"),
    "AMZN":  ("US",          "AWS + AI cloud"),
    "AVGO":  ("US",          "Networking + AI chips"),
    "ISRG":  ("US",          "Surgical robotics monopoly"),
    "MU":    ("US",          "AI memory chips HBM3E"),
    "ARM":   ("US",          "CPU architecture licensor"),
    "META":  ("US",          "Social AI + ad platform"),
    "LLY":   ("US",          "GLP-1 obesity drugs leader"),
    "JPM":   ("US",          "Diversified banking — AI capital markets"),
    "CRWD":  ("US",          "AI-native cybersecurity platform"),

    # ── Europe (US ADR) ───────────────────────────────────────────────────
    "ASML":  ("Netherlands", "EUV lithography monopoly"),
    "SAP":   ("Germany",     "Enterprise AI software"),
    "AZN":   ("UK",          "Pharma — rich oncology pipeline"),
    "NVO":   ("Denmark",     "Ozempic/Wegovy GLP-1 leader"),
    "ARGX":  ("Belgium",     "Biotech — autoimmune disease"),

    # ── Europe (local exchanges) ──────────────────────────────────────────
    "MC.PA":  ("France",    "Luxury conglomerate — LVMH"),
    "RMS.PA": ("France",    "Ultra-luxury — Hermès"),
    "SU.PA":  ("France",    "Energy automation — Schneider Electric"),
    "ENR.DE": ("Germany",   "Clean energy transition — Siemens Energy"),

    # ── Asia (US ADR) ─────────────────────────────────────────────────────
    "TSM":   ("Taiwan",      "AI chip fab monopoly"),
    "BABA":  ("China",       "E-commerce + Alibaba Cloud AI"),
    "BIDU":  ("China",       "AI + autonomous vehicles"),
    "SE":    ("Singapore",   "SE Asia super-app"),
    "INFY":  ("India",       "IT services — AI transformation"),

    # ── Asia (local exchanges) ────────────────────────────────────────────
    "700.HK":      ("Hong Kong",  "Tencent — tech/gaming/fintech"),
    "005930.KS":   ("Korea",      "Samsung — memory/mobile/AI"),
    "066570.KS":   ("Korea",      "LG Electronics — EV parts/appliances"),
    "RELIANCE.NS": ("India",      "Conglomerate — Jio + Retail + Green H2"),
    "HDFCBANK.NS": ("India",      "India's largest private bank"),
    "6503.T":      ("Japan",      "Mitsubishi Electric — AI factory automation"),
    "9984.T":      ("Japan",      "SoftBank — AI/Vision Fund"),

    # ── Middle East — Saudi Tadawul (.SR) ─────────────────────────────────
    "7203.SR": ("Saudi Arabia", "Elm — digital gov IT monopoly"),
    "4013.SR": ("Saudi Arabia", "Dr. Sulaiman Al-Habib — healthcare"),
    "1120.SR": ("Saudi Arabia", "Al Rajhi Bank — Islamic banking"),
    "2222.SR": ("Saudi Arabia", "Saudi Aramco — energy + dividend"),
    "1211.SR": ("Saudi Arabia", "Ma'aden — mining + materials"),
    "2082.SR": ("Saudi Arabia", "ACWA Power — renewables"),
    "2010.SR": ("Saudi Arabia", "SABIC — petrochemicals"),
    "7010.SR": ("Saudi Arabia", "STC — telecom + STC Pay fintech"),
}

# ── Avoid List ────────────────────────────────────────
# Tickers added here are excluded from all analysis, reports, and discovery.
AVOID_LIST = {
    "PLTR",   # user preference
    "GRAB",   # user preference
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
TTL_SCREENER     = 12 * 3600
TTL_FUNDAMENTALS = 6  * 3600
TTL_NEWS         = 4  * 3600
TTL_FRED         = 24 * 3600
TTL_AI           = 12 * 3600
TTL_EARNINGS     = 24 * 3600
TTL_INSIDER      = 6  * 3600

# ── Enrichment ────────────────────────────────────────
ENRICH_WORKERS = 5    # ThreadPoolExecutor max_workers

# ── Geopolitical exposure by country ─────────────────
GEO_EXPOSURE = {
    # Low risk
    "US":           "Low",
    "Germany":      "Low",
    "Netherlands":  "Low",
    "France":       "Low",
    "UK":           "Low",
    "Denmark":      "Low",
    "Belgium":      "Low",
    "Switzerland":  "Low",
    "Sweden":       "Low",
    "Japan":        "Low",
    "Australia":    "Low",
    "UAE":          "Low",
    # Medium risk
    "Singapore":    "Medium",
    "India":        "Medium",
    "Korea":        "Medium",
    "Saudi Arabia": "Medium",
    "Brazil":       "Medium",
    "Mexico":       "Medium",
    # High risk
    "China":        "High",
    "Taiwan":       "High",
    "Hong Kong":    "High",
    "Russia":       "High",
    "Iran":         "High",
    "Israel":       "High",
}

# ── Region map — company home country → display region ───────────────
REGION_MAP = {
    # US
    "US":           "🇺🇸 US",
    # Europe
    "Germany":      "🇪🇺 Europe",
    "Netherlands":  "🇪🇺 Europe",
    "France":       "🇪🇺 Europe",
    "UK":           "🇪🇺 Europe",
    "Denmark":      "🇪🇺 Europe",
    "Belgium":      "🇪🇺 Europe",
    "Switzerland":  "🇪🇺 Europe",
    "Sweden":       "🇪🇺 Europe",
    # Asia
    "China":        "🌏 Asia",
    "Taiwan":       "🌏 Asia",
    "Hong Kong":    "🌏 Asia",
    "Japan":        "🌏 Asia",
    "Korea":        "🌏 Asia",
    "India":        "🌏 Asia",
    "Singapore":    "🌏 Asia",
    "Australia":    "🌏 Asia",
    # Middle East
    "Saudi Arabia": "🌙 Middle East",
    "UAE":          "🌙 Middle East",
    "Israel":       "🌙 Middle East",
}

# ── Currency symbols by ISO code ──────────────────────
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "HKD": "HK$",
    "KRW": "₩",
    "JPY": "¥",
    "INR": "₹",
    "SAR": "SAR ",
    "AED": "AED ",
    "CNY": "¥",
    "SGD": "S$",
    "TWD": "NT$",
}

# ── Sanity checks ─────────────────────────────────────
assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9, "RISK_WEIGHTS must sum to 1.0"
assert abs(sum(RANK_WEIGHTS.values()) - 1.0) < 1e-9, "RANK_WEIGHTS must sum to 1.0"
