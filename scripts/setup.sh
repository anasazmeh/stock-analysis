#!/usr/bin/env bash
# One-time setup: installs dependencies, checks Claude Code, and writes your keys to .env.
# Run from anywhere:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4 Python packages (into .venv, a private environment in this folder)"
# Homebrew and recent Linux Pythons refuse system-wide pip installs (PEP 668), so use a venv.
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
PY=.venv/bin/python
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r requirements.txt
read -r -p "Install FinBERT sentiment too? (~1-2 GB download) [y/N] " fb
if [[ "$fb" == [yY]* ]]; then "$PY" -m pip install -q -r requirements-ml.txt; fi

echo
echo "== 2/4 Claude Code (used for the AI analysis — no API key, uses your Claude plan)"
if command -v claude >/dev/null 2>&1; then
  echo "Found: $(claude --version 2>/dev/null | head -1)"
  echo "If you have never logged in, run 'claude' once in another terminal and complete the login."
else
  echo "Claude Code not found. Install it (https://code.claude.com/docs), run 'claude' once to log in,"
  echo "then re-run this script. The pipeline still runs without it, just without AI analysis."
fi

touch .env
chmod 600 .env
set_key() {  # set_key NAME VALUE  — replaces or appends a line in .env
  local name="$1" value="$2"
  grep -v "^${name}=" .env > .env.tmp || true
  mv .env.tmp .env
  value="${value//\"/}"            # keep it shell-safe for scripts/run_daily.sh
  echo "${name}=\"${value}\"" >> .env
  chmod 600 .env
}
current() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true; }

echo
echo "== 3/4 SEC contact (the SEC requires a name and email on automated requests)"
if [[ -z "$(current SEC_USER_AGENT)" ]]; then
  read -r -p "Your name: " name
  read -r -p "Your email: " email
  set_key SEC_USER_AGENT "${name} ${email}"
else
  echo "Already set: $(current SEC_USER_AGENT)"
fi

echo
echo "== 4/4 Free API keys (press Enter to skip any)"
ask_key() {  # ask_key NAME URL WHAT
  local name="$1" url="$2" what="$3"
  if [[ -n "$(current "$name")" ]]; then echo "$name already set"; return; fi
  echo "$what"
  echo "  Sign up (free): $url"
  read -r -p "  Paste $name: " value
  if [[ -n "$value" ]]; then set_key "$name" "$value"; fi
}
ask_key FINNHUB_API_KEY "https://finnhub.io/register" "Finnhub — second price source, earnings calendar, company news."
ask_key FRED_API_KEY "https://fredaccount.stlouisfed.org/apikeys" "FRED — Fed rate, inflation, yield curve, VIX."
ask_key ALPHA_VANTAGE_API_KEY "https://www.alphavantage.co/support/#api-key" "Alpha Vantage (optional) — EPS surprises, missing analyst targets."

echo
echo "Done. Keys are in .env (private, not committed)."
echo "In each new terminal, first run:   source .venv/bin/activate"
echo "Then:"
echo "  python3 main.py"
echo "  python3 dashboard/app.py"
echo "  bash scripts/setup_schedule.sh"
