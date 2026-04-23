# 📊 Global Stock Analysis — Refreshable Project

## Quick Start

```bash
cd ~/stock-analysis
python3 analyze.py
```

This pulls **live data from Yahoo Finance**, ranks all stocks by analyst upside,
flags Shariah-compliant picks, and saves a `report.md`.

---

## Customising the Watchlist

Open `analyze.py` and edit the `WATCHLIST` dictionary at the top:

```python
WATCHLIST = {
    "NVDA": ("🇺🇸 US", "⚠️ Partial", "AI infrastructure king"),
    # Add any ticker Yahoo Finance supports:
    "2082.SR": ("🌍 Saudi Arabia", "✅ Yes", "ACWA Power — Vision 2030"),
    "9988.HK": ("🇨🇳 China",       "❌ No",  "Alibaba HK listing"),
}
```

Supported formats:
- **US stocks**: `AAPL`, `NVDA`, `TSLA`
- **Saudi (Tadawul)**: `2082.SR`, `1120.SR`
- **Hong Kong**: `9988.HK`, `1810.HK`
- **German (XETRA)**: `SIE.DE`, `BMW.DE`
- **Crypto**: `BTC-USD`, `ETH-USD`

---

## Options in `analyze.py`

| Variable | Default | Description |
|----------|---------|-------------|
| `SHARIAH_COMPLIANT_ONLY` | `False` | Set `True` to filter table to Shariah stocks only |
| `OUTPUT_FILE` | `"report.md"` | Filename to save report, or `None` to print only |
| `BASELINE` | Mar 18 prices | Reference prices for % change column — update after each session |

---

## Updating the Baseline

After a refresh session, copy the current prices into `BASELINE` in `analyze.py`
so the "Vs Baseline" column tracks movement from your chosen reference date.

---

## Requirements

```bash
python3 -m pip install yfinance --break-system-packages
```

Already installed if you ran the initial setup.

---

## Output Files

| File | Description |
|------|-------------|
| `analyze.py` | Main script — edit watchlist and options here |
| `report.md` | Auto-generated on each run — overwritten each time |
| `README.md` | This file |
