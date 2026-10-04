#!/usr/bin/env bash
# Daily run for cron, e.g.:  0 7 * * 1-5  /path/to/stock-analysis/scripts/run_daily.sh
# Reads API keys from .env in the project root (KEY=value lines, git-ignored).
# Optional: HEALTHCHECK_URL (e.g. a healthchecks.io ping URL) gets /start, success or /fail pings.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
if [ -f .env ]; then set -a; . ./.env; set +a; fi

PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python   # created by scripts/setup.sh

ping() { [ -n "${HEALTHCHECK_URL:-}" ] && curl -fsS -m 10 --retry 3 "${HEALTHCHECK_URL}$1" >/dev/null || true; }

log="logs/run_$(date +%Y-%m-%d).log"
ping /start
"$PY" main.py --require-keys >>"$log" 2>&1
code=$?
case $code in
  0) ping "" ;;                                   # success
  2) echo "DEGRADED run (see report)" >>"$log"; ping /fail ;;
  *) echo "FAILED with exit code $code" >>"$log"; ping /fail
     "$PY" -m src.alerts --notify-failure "$log" "$code" >>"$log" 2>&1 ;;  # email/webhook, if set
esac
exit $code
