import os

# ── API Keys ──────────────────────────────────────────
ANTHROPIC_API_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")
FINNHUB_API_KEY       = os.environ.get("FINNHUB_API_KEY", "")
FRED_API_KEY          = os.environ.get("FRED_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")  # free at alphavantage.co
ARGAAM_API_KEY        = os.environ.get("ARGAAM_API_KEY", "")          # Argaam Saudi data
NEWSAPI_KEY           = os.environ.get("NEWSAPI_KEY", "")             # free at newsapi.org
# SEC fair-access policy requires a real contact in the User-Agent, e.g. "Jane Doe jane@example.com"
SEC_USER_AGENT        = os.environ.get("SEC_USER_AGENT", "stock-analysis research contact@example.com")

# ── Claude ────────────────────────────────────────────
CLAUDE_MODEL  = "claude-opus-5-5"
CLAUDE_EFFORT = "high"   # low / medium / high / xhigh / max
BATCH_SIZE    = 4        # tickers per Claude API call (failed batches retry one by one)

# ── Discovery ─────────────────────────────────────────
# Predefined Yahoo screens. "day_gainers" / "most_actives" were dropped: they surface hype, not quality.
SCREENERS = [
    "undervalued_growth_stocks",
    "growth_technology_stocks",
]
# Regional screens (largest companies by market cap) so EU and Gulf ideas aren't missed
REGIONAL_SCREENS = {"sa": 8, "ae": 6, "de": 6, "nl": 4, "fr": 6}
REGIONAL_MIN_MCAP = 2e9
# Curated watchlist is always kept; this caps how many extra names screeners + index universe add.
MAX_DISCOVERED = 30

# ── Index universe (free: Wikipedia constituent tables) ──
UNIVERSE_INDICES = {
    "S&P 500":    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "Nasdaq-100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}
# Holdings CSVs downloaded from Shariah ETF issuers (e.g. SPUS, HLAL, ISWD) — file name = ETF label.
SHARIAH_ETF_DIR   = "data/universe"
UNIVERSE_TOP_N    = 20    # index names added per run, picked by 6-month price momentum

# ── News normalisation ──
NEWS_MAX_AGE_DAYS = 10
NEWS_SOURCE_TIERS = {   # lower tier = shown first
    1: ["reuters", "bloomberg", "wsj.com", "ft.com", "sec.gov", "nikkei", "argaam", "zawya"],
    2: ["cnbc", "marketwatch", "barrons", "economist", "apnews", "theinformation", "digitimes",
        "seekingalpha", "investors.com", "fortune", "techcrunch"],
}

# ── GDELT news (free, no key; GDELT asks for ≤1 request per 5 s) ──
GDELT_ENABLED      = True
GDELT_MAX_TICKERS  = 40   # holdings first, then curated watchlist, then the rest
GDELT_ARTICLES     = 8
GDELT_TIMESPAN     = "7d"
GDELT_MACRO_QUERIES = [
    '"Federal Reserve" interest rates',
    '"European Central Bank" rates',
    'Taiwan semiconductor "export controls"',
    '"Saudi Arabia" stock market',
    '"UAE" economy stocks',
]

# ── SEC EDGAR filings watch (free, US-listed tickers incl. ADRs) ──
FILINGS_ENABLED   = True
FILINGS_DAYS      = 30
FILINGS_FORMS     = {"8-K", "6-K", "10-Q", "10-K", "20-F", "S-1", "F-1", "424B4",
                     "S-3", "F-3", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G",
                     "144", "DEF 14A", "NT 10-K", "NT 10-Q"}

# ── Price cross-check (Finnhub free key, US listings) ──
PRICE_CHECK_TOLERANCE_PCT = 2.0   # max Yahoo vs Finnhub gap before a price is flagged

# ── Full-article reading + FinBERT sentiment ──
FULLTEXT_ENABLED       = True
FULLTEXT_MAX_TICKERS   = 30   # holdings first
FULLTEXT_PER_TICKER    = 3
FINBERT_MODEL          = "ProsusAI/finbert"   # needs: pip install -r requirements-ml.txt

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

    # ── Middle East — UAE Abu Dhabi (ADX, .AD) ────────────────────────────
    "FAB.AD":      ("UAE", "First Abu Dhabi Bank — largest UAE bank"),
    "ADNOCDIST.AD":("UAE", "ADNOC Distribution — fuel retail + EV charging"),
    "IHC.AD":      ("UAE", "International Holding — diversified conglomerate"),
    "EAND.AD":     ("UAE", "e& (Etisalat) — telecom + digital services"),
    "ADPORTS.AD":  ("UAE", "AD Ports Group — logistics + maritime"),

    # ── Middle East — UAE Dubai (DFM, .AE) ────────────────────────────────
    "EMAAR.AE":    ("UAE", "Emaar Properties — real estate + hospitality"),
    "DIB.AE":      ("UAE", "Dubai Islamic Bank — largest Islamic bank in UAE"),
    "DEWA.AE":     ("UAE", "DEWA — Dubai utilities, green hydrogen pivot"),
}

# ── Avoid List ────────────────────────────────────────
# Tickers added here are excluded from all analysis, reports, and discovery.
AVOID_LIST = {
    "PLTR",   # user preference
    "GRAB",   # user preference
}
# Company names checked by the final output gate (ticker -> name as it appears in text)
AVOID_NAMES = {
    "PLTR": "Palantir",
    "GRAB": "Grab Holdings",
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
# Shariah is a label only (weight 0). Set e.g. 0.15 and lower the others to rank by it.
RANK_WEIGHTS = {
    "upside":       0.35,   # consensus-quality-adjusted analyst upside
    "sentiment":    0.25,   # Claude, else FinBERT, else keyword score
    "risk_adj":     0.20,
    "trend":        0.20,   # price vs 50/200-day averages + relative strength
    "shariah":      0.00,
}

# ── Shariah screening (label only — never filters) ────
SHARIAH_ENABLED     = True
SHARIAH_METHODOLOGY = "AAOIFI"
# Ratios use market cap as the denominator; "income" is interest income / total income.
SHARIAH_METHODOLOGIES = {
    "AAOIFI": {"debt": 0.30, "cash": 0.30, "receivables": None, "income": 0.05},   # Shariah Standard No. 21
    "DJIM":   {"debt": 0.33, "cash": 0.33, "receivables": 0.33, "income": 0.05},
}
# Islamic banks / insurers that pass the activity screen despite their sector
ISLAMIC_FINANCIALS = {
    "1120.SR": "Al Rajhi Bank",
    "1150.SR": "Alinma Bank",
    "1140.SR": "Bank Albilad",
    "DIB.AE":  "Dubai Islamic Bank",
}
# Manual verdicts for cases the industry label can't capture: ticker -> (Yes/No/Review, why)
SHARIAH_OVERRIDES = {
    "MC.PA": ("No", "LVMH Wines & Spirits (Moët Hennessy) revenue is above the 5% limit"),
    "IHC.AD": ("Review", "Conglomerate with financial-services subsidiaries"),
}

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
TTL_UNIVERSE     = 7  * 24 * 3600
TTL_FILINGS      = 6  * 3600
TTL_FULLTEXT     = 7  * 24 * 3600
TTL_PRICE_CHECK  = 15 * 60
TTL_FX           = 12 * 3600

# ── Alert thresholds ──────────────────────────────────
ALERT_EMAIL_TO       = os.environ.get("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM     = os.environ.get("ALERT_EMAIL_FROM", "")
ALERT_SMTP_HOST      = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT      = int(os.environ.get("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_PASSWORD  = os.environ.get("ALERT_SMTP_PASSWORD", "")
ALERT_WEBHOOK_URL    = os.environ.get("ALERT_WEBHOOK_URL", "")  # Slack/Discord/generic
ALERT_UPSIDE_MIN     = 50.0   # % — trigger when analyst upside ≥ this
ALERT_PORTFOLIO_LOSS = -20.0  # % — trigger when P&L ≤ this
ALERT_PORTFOLIO_GAIN = 100.0  # % — trigger when P&L ≥ this
ALERT_EPS_BEAT_MIN   = 15.0   # % — trigger when EPS surprise ≥ this

WHAT_CHANGED_MOVE_PCT = 10.0   # price moves since the last run worth listing
SCORECARD_DAYS        = 28     # compare with the snapshot at least this old
SCORECARD_BENCHMARK   = "ISWD.L"   # iShares MSCI World Islamic (must also be in BENCHMARKS)

# ── Personal notes shown next to TRIM / EXIT reviews ──
TAX_RESIDENCE = ""     # e.g. "NL" — loss-harvesting rules differ by country
BROKER_COST_NOTE = "Check your broker's fee and FX-conversion cost — on small positions they can exceed the gain."

# ── Sell discipline (holdings without an entry in data/theses.json) ──
DEFAULT_THESIS_RULES = {
    "invalidation": [{"type": "shariah_is", "value": "No"}],
    "review": [{"type": "shariah_not", "value": "Yes"},
               {"type": "trend", "value": "Downtrend"},
               {"type": "rel_strength_below", "value": -25},
               {"type": "weight_above", "value": 12}],
}

# ── Event calendar ────────────────────────────────────
EARNINGS_LOOKUP_MAX     = 40   # Yahoo calendar lookups per run (holdings first)
EARNINGS_BLACKOUT_DAYS  = 5    # no new BUY/ADD signal within this many trading days of earnings
# Scheduled macro events — extend each year from the Fed, ECB and BLS calendars.
MACRO_EVENTS = [
    {"date": "2026-10-14", "name": "US CPI (September)", "themes": ["All"]},
    {"date": "2026-10-28", "name": "FOMC decision (27-28 Oct)", "themes": ["All"]},
    {"date": "2026-10-29", "name": "ECB rate decision", "themes": ["All"]},
    {"date": "2026-12-09", "name": "FOMC decision (8-9 Dec)", "themes": ["All"]},
    {"date": "2026-12-17", "name": "ECB rate decision", "themes": ["All"]},
]

# ── Argaam (undocumented endpoint — opt in only if your use is permitted) ──
ARGAAM_ENABLED              = False
ARGAAM_MAX_TARGET_AGE_DAYS  = 180

# ── Alpha Vantage quota ───────────────────────────────
AV_DAILY_BUDGET        = 22   # free tier is 25/day; keep a margin for manual use
AV_RESERVE_FOR_TARGETS = 6    # calls kept for missing targets after holdings' EPS

# ── Analyst consensus quality ─────────────────────────
MIN_ANALYSTS      = 5      # fewer → upside halved in the ranking
MAX_TARGET_SPREAD = 0.80   # (high - low) / mean above this → upside x0.6

# Expected quote currency by Yahoo suffix — a mismatch means the symbol resolved to the wrong listing
SUFFIX_CURRENCY = {".SR": "SAR", ".AE": "AED", ".AD": "AED", ".DE": "EUR", ".PA": "EUR", ".AS": "EUR",
                   ".MI": "EUR", ".MC": "EUR", ".L": "GBP", ".HK": "HKD", ".KS": "KRW", ".T": "JPY",
                   ".NS": "INR", ".SW": "CHF"}
# Markets reachable at DEGIRO / Revolut (US listings have no suffix). Others are "Watch only".
BROKER_MARKETS = {"", ".DE", ".PA", ".AS", ".MI", ".MC", ".BR", ".LS", ".VI", ".HE", ".CO", ".ST",
                  ".OL", ".SW", ".L", ".HK", ".T", ".TO"}
TRADABILITY_OVERRIDES = {}   # ticker -> "Yes" / "Watch only", after checking your broker
MIN_DAILY_VALUE_TRADED = 2_000_000   # avg volume x price (quote currency); below = "low liquidity"

# ── Data-quality gate ─────────────────────────────────
MAX_QUOTE_AGE_DAYS = 4.0     # older quotes are "stale" (covers weekends + a holiday)
MAX_FAILED_SHARE   = 0.20    # run is DEGRADED when more tickers than this fail

# ── Portfolio concentration ───────────────────────────
POSITION_CAP_PCT = 12.0     # max single position, % of priced portfolio (EUR)
THEME_CAP_PCT    = 40.0     # max per theme (see "themes" in portfolio_data.py)
TYPICAL_ADD_EUR  = 1000.0   # trade size used for "weight after an ADD" checks

# ── Enrichment ────────────────────────────────────────
ENRICH_WORKERS = 5    # ThreadPoolExecutor max_workers
HISTORY_PERIOD = "2y" # enough for a 200-day moving average
# Benchmarks for relative strength (6-month excess return)
BENCHMARKS = {
    "SPY":    "S&P 500",
    "SOXX":   "Semiconductors",
    "ISWD.L": "MSCI World Islamic",
}

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

# Supply-chain exposure that headquarters country misses: ticker -> (level, reason)
SUPPLY_CHAIN_GEO = {
    "NVDA": ("High", "Chips made by TSMC in Taiwan; China export controls"),
    "AVGO": ("High", "Chips made by TSMC in Taiwan"),
    "CRDO": ("High", "Chips made by TSMC in Taiwan"),
    "AMD":  ("High", "Chips made by TSMC in Taiwan; China export controls"),
    "ARM":  ("Medium", "Licensees concentrated in Taiwan/China"),
    "ASML": ("Medium", "China export licences (Dutch/US rules)"),
    "AAPL": ("Medium", "Assembly in China; chips from TSMC"),
}

# Regulatory themes watched in the US Federal Register (BIS = Bureau of Industry and Security)
GEO_LOOKBACK_DAYS = 21
GEO_THEMES = {
    "US chip export controls": {"term": "semiconductor",
                                "tickers": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "CRDO", "MU", "ARM"]},
    "BIS Entity List changes": {"term": "entity list",
                                "tickers": ["NVDA", "AMD", "TSM", "ASML", "NIO", "BYDDY", "BABA", "BIDU"]},
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
