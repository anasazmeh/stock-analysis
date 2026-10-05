"""
User portfolio holdings. Update after each trade (or import broker CSVs, see src/broker_import.py).

Fields:
  ticker        Yahoo symbol used to price the position ("" = not priced yet)
  shares, bep   position size and breakeven price, in bep_currency
  bep_currency  currency the position was bought in (EUR for Frankfurt/Xetra lines)
  status        your own label (HOLD / TRIM / EXIT ...); thesis rules live in theses.yaml
  asset_type    Stock / ETF / ETC
  themes        exposure groups used for concentration checks (config.THEME_CAPS)
  units_per_listing  held units per priced listing unit (1 unless the held line differs,
                e.g. a local share vs an ADR representing 2 shares → 0.5)
"""

HOLDINGS = [
    {"ticker": "NIO",   "name": "NIO Inc (ADR)",        "shares": 26,  "bep": 42.78,  "bep_currency": "USD", "status": "🔴 Consider EXIT", "asset_type": "Stock", "themes": ["EV / China"]},
    {"ticker": "TSM",   "name": "Taiwan Semiconductor", "shares": 20,  "bep": 150.25, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "AMZN",  "name": "Amazon.com",           "shares": 20,  "bep": 167.12, "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["Cloud / Hyperscalers"]},
    {"ticker": "ASML",  "name": "ASML Holding",         "shares": 2,   "bep": 701.00, "bep_currency": "EUR", "status": "🟡 TRIM",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "AUR",   "name": "Aurora Innovation",    "shares": 100, "bep": 6.15,   "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Autonomy"]},
    {"ticker": "AVGO",  "name": "Broadcom",             "shares": 4,   "bep": 290.00, "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "BYDDY", "name": "BYD Co (ADR)",         "shares": 90,  "bep": 12.20,  "bep_currency": "EUR", "status": "🟡 HOLD",     "asset_type": "Stock", "themes": ["EV / China"]},
    {"ticker": "CRDO",  "name": "Credo Technology",     "shares": 13,  "bep": 90.00,  "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "CRWD",  "name": "CrowdStrike",          "shares": 2,   "bep": 310.00, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Software"]},
    {"ticker": "LCID",  "name": "Lucid Group",          "shares": 1,   "bep": 161.20, "bep_currency": "USD", "status": "🔴 Consider EXIT", "asset_type": "Stock", "themes": ["EV / China"]},
    {"ticker": "NVDA",  "name": "NVIDIA",               "shares": 30,  "bep": 99.00,  "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "MSFT",  "name": "Microsoft",            "shares": 12,  "bep": 381.20, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Cloud / Hyperscalers"]},
    {"ticker": "MMYT",  "name": "MakeMyTrip",           "shares": 45,  "bep": 43.30,  "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["India consumer"]},
    {"ticker": "SAP",   "name": "SAP SE",               "shares": 20,  "bep": 147.00, "bep_currency": "EUR", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Software"]},
    {"ticker": "TEM",   "name": "Tempus AI",            "shares": 10,  "bep": 55.00,  "bep_currency": "EUR", "status": "🟡 WATCH",    "asset_type": "Stock", "themes": ["Health AI"]},

    # Funds: set "ticker" to the Yahoo symbol of the exact line you hold (see the DEGIRO product page)
    {"ticker": "", "name": "iShares Nasdaq-100 UCITS ETF",   "shares": 28, "bep": 148.97, "bep_currency": "EUR", "status": "🟢 HOLD", "asset_type": "ETF", "themes": ["Broad US tech"], "shariah_note": "Conventional index fund — not Shariah-screened. Shariah alternatives: ISUS (iShares MSCI USA Islamic), ISWD (iShares MSCI World Islamic)."},
    {"ticker": "", "name": "WisdomTree Physical Gold ETC",   "shares": 5,  "bep": 479.00, "bep_currency": "USD", "status": "🟢 HOLD", "asset_type": "ETC", "themes": ["Precious metals"], "shariah_note": "Gold ETC — permissible only if it meets AAOIFI Shariah Standard 57 (allocated, physically backed, no interest). Check the issuer's prospectus."},
    {"ticker": "", "name": "WisdomTree Physical Silver ETC", "shares": 26, "bep": 61.59,  "bep_currency": "EUR", "status": "🟢 HOLD", "asset_type": "ETC", "themes": ["Precious metals"], "shariah_note": "Silver ETC — same AAOIFI SS-57 conditions as gold. Check the issuer's prospectus."},
]

# Cash you hold at each broker, in EUR (update when it changes). Used by the Cash plan tab:
# the reserve it recommends counts this cash first, before any sale proceeds.
CASH_EUR = {"DEGIRO": 0.0, "Revolut": 0.0}

# Money you will need from the portfolio within 12 months (tuition, a car, ...). Always kept as cash.
# Your emergency fund should sit outside the portfolio and is not counted here.
PLANNED_WITHDRAWALS_EUR = 0.0
