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
    # From the DEGIRO account statement of 19 Oct 2026 (all trades since Jul 2020, splits included).
    # Sold on 19 Oct 2026: NIO, AUR, BYDDY, LCID, MMYT.
    {"ticker": "TSM",   "name": "Taiwan Semiconductor", "shares": 20,  "bep": 150.25, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "AMZN",  "name": "Amazon.com",           "shares": 20,  "bep": 167.12, "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["Cloud / Hyperscalers"]},
    {"ticker": "ASML",  "name": "ASML Holding",         "shares": 2,   "bep": 701.00, "bep_currency": "EUR", "status": "🟡 TRIM",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "AVGO",  "name": "Broadcom",             "shares": 4,   "bep": 290.00, "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "CRDO",  "name": "Credo Technology",     "shares": 13,  "bep": 90.00,  "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    # 4-for-1 split on 2 Jul 2026: 2 shares @ 772.74 became 8 @ 193.19
    {"ticker": "CRWD",  "name": "CrowdStrike",          "shares": 8,   "bep": 193.19, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Software"]},
    {"ticker": "NVDA",  "name": "NVIDIA",               "shares": 30,  "bep": 99.00,  "bep_currency": "USD", "status": "🟢 HOLD",     "asset_type": "Stock", "themes": ["AI / Semiconductors"]},
    {"ticker": "MSFT",  "name": "Microsoft",            "shares": 12,  "bep": 381.20, "bep_currency": "USD", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Cloud / Hyperscalers"]},
    {"ticker": "SAP",   "name": "SAP SE",               "shares": 20,  "bep": 147.00, "bep_currency": "EUR", "status": "🟢 HOLD/ADD", "asset_type": "Stock", "themes": ["Software"]},
    {"ticker": "TEM",   "name": "Tempus AI",            "shares": 10,  "bep": 55.00,  "bep_currency": "EUR", "status": "🟡 WATCH",    "asset_type": "Stock", "themes": ["Health AI"]},
    # Leftover from Wish/ContextLogic (ISIN change Aug 2025), traded over the counter
    {"ticker": "LOGC",  "name": "ContextLogic Holdings", "shares": 4,  "bep": 7.50,   "bep_currency": "USD", "status": "🟡 WATCH",    "asset_type": "Stock", "themes": ["Other"]},

    # Funds — Yahoo symbol of a listing in the currency you bought in (ISIN in the comment)
    {"ticker": "EXXT.DE", "name": "iShares Nasdaq-100 UCITS ETF (DE)", "shares": 28, "bep": 148.97, "bep_currency": "EUR", "status": "🟢 HOLD", "asset_type": "ETF", "themes": ["Broad US tech"], "shariah_note": "Conventional index fund — not Shariah-screened. Shariah alternatives: ISUS (iShares MSCI USA Islamic), ISWD (iShares MSCI World Islamic)."},   # DE000A0F5UF5, Xetra
    {"ticker": "PHAU.L",  "name": "WisdomTree Physical Gold ETC",      "shares": 5,  "bep": 479.00, "bep_currency": "USD", "status": "🟢 HOLD", "asset_type": "ETC", "themes": ["Precious metals"], "shariah_note": "Gold ETC — permissible only if it meets AAOIFI Shariah Standard 57 (allocated, physically backed, no interest). Check the issuer's prospectus."},   # JE00B1VS3770, London (USD)
    {"ticker": "PHAG.AS", "name": "WisdomTree Physical Silver ETC",    "shares": 26, "bep": 61.59,  "bep_currency": "EUR", "status": "🟢 HOLD", "asset_type": "ETC", "themes": ["Precious metals"], "shariah_note": "Silver ETC — same AAOIFI SS-57 conditions as gold. Check the issuer's prospectus."},   # JE00B1VS3333, Amsterdam (EUR)
]

# Open orders at your broker. Delete a line when it fills or you cancel it (then update HOLDINGS and CASH_EUR).
# limit and currency as shown in the order; GTC = good till cancelled. Checked every run on the Sell review tab.
OPEN_ORDERS = [
    {"ticker": "TSM",  "side": "Sell", "qty": 10, "limit": 490.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "CRWD", "side": "Sell", "qty": 8,  "limit": 245.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "AVGO", "side": "Sell", "qty": 4,  "limit": 350.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "CRDO", "side": "Sell", "qty": 6,  "limit": 210.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "NVDA", "side": "Sell", "qty": 10, "limit": 240.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "MSFT", "side": "Sell", "qty": 6,  "limit": 560.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "AMZN", "side": "Sell", "qty": 10, "limit": 280.00,  "currency": "USD", "validity": "GTC", "placed": "2026-10-18"},
    {"ticker": "ASML", "side": "Sell", "qty": 1,  "limit": 1720.00, "currency": "EUR", "validity": "GTC", "placed": "2026-10-19"},
    {"ticker": "TEM",  "side": "Sell", "qty": 10, "limit": 69.00,   "currency": "EUR", "validity": "GTC", "placed": "2026-10-19"},
    {"ticker": "SAP",  "side": "Sell", "qty": 10, "limit": 240.40,  "currency": "EUR", "validity": "GTC", "placed": "2026-10-19"},
]

# Cash you hold at each broker, in EUR (update when it changes). Used by the Cash plan tab:
# the reserve it recommends counts this cash first, before any sale proceeds.
CASH_EUR = {"DEGIRO": 3118.49, "Revolut": 0.0}   # DEGIRO: account statement, 19 Oct 2026 16:32

# Money you will need from the portfolio within 12 months (tuition, a car, ...). Always kept as cash.
# Your emergency fund should sit outside the portfolio and is not counted here.
PLANNED_WITHDRAWALS_EUR = 0.0
