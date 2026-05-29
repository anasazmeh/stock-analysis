"""
User portfolio holdings.
BEP = breakeven price in the currency the position was opened in.
Update this file after each trade.
"""

HOLDINGS = [
    {"ticker": "NIO",   "shares": 26,  "bep": 42.78,  "bep_currency": "USD", "status": "🔴 Consider EXIT"},
    {"ticker": "TSM",   "shares": 20,  "bep": 150.25, "bep_currency": "USD", "status": "🟢 HOLD/ADD"},
    {"ticker": "AMZN",  "shares": 20,  "bep": 167.12, "bep_currency": "USD", "status": "🟢 HOLD"},
    {"ticker": "ASML",  "shares": 2,   "bep": 701.00, "bep_currency": "EUR", "status": "🟡 TRIM"},
    {"ticker": "AUR",   "shares": 100, "bep": 6.15,   "bep_currency": "USD", "status": "🟢 HOLD/ADD"},
    {"ticker": "AVGO",  "shares": 4,   "bep": 290.00, "bep_currency": "USD", "status": "🟢 HOLD"},
    {"ticker": "BYDDY", "shares": 90,  "bep": 12.20,  "bep_currency": "EUR", "status": "🟡 HOLD"},
    {"ticker": "CRDO",  "shares": 13,  "bep": 90.00,  "bep_currency": "USD", "status": "🟢 HOLD"},
    {"ticker": "CRWD",  "shares": 2,   "bep": 310.00, "bep_currency": "USD", "status": "🟢 HOLD/ADD"},
    {"ticker": "LCID",  "shares": 1,   "bep": 161.20, "bep_currency": "USD", "status": "🔴 Consider EXIT"},
    {"ticker": "NVDA",  "shares": 30,  "bep": 99.00,  "bep_currency": "USD", "status": "🟢 HOLD"},
    {"ticker": "MSFT",  "shares": 12,  "bep": 381.20, "bep_currency": "USD", "status": "🟢 HOLD/ADD"},
    {"ticker": "MMYT",  "shares": 45,  "bep": 43.30,  "bep_currency": "USD", "status": "🟢 HOLD"},
    {"ticker": "SAP",   "shares": 20,  "bep": 147.00, "bep_currency": "EUR", "status": "🟢 HOLD/ADD"},
    {"ticker": "TEM",   "shares": 10,  "bep": 55.00,  "bep_currency": "EUR", "status": "🟡 WATCH"},
]
