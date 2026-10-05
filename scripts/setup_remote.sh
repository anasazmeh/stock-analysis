#!/usr/bin/env bash
# Reach the dashboard from your phone and other devices, at home or outside.
#   bash scripts/setup_remote.sh            # set up (safe to re-run)
#   bash scripts/setup_remote.sh --public   # also make a public https link (Tailscale Funnel)
#   bash scripts/setup_remote.sh --private  # remove the public link again
#   bash scripts/setup_remote.sh --stop     # stop serving remotely
#
# How it works: the dashboard keeps running on this Mac (where Claude Code is logged in) behind a
# password. Tailscale gives your devices an encrypted https address for it — "serve" for your own
# devices only (they need the free Tailscale app), "funnel" for a public link any browser can open.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.stockanalysis.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="$(grep -E '^DASHBOARD_PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"'" || true)"
PORT="${PORT:-8050}"
MODE="${1:-}"

ts() {  # Tailscale CLI: Homebrew/standalone, or inside the Mac App Store app
  if command -v tailscale >/dev/null 2>&1; then tailscale "$@"
  elif [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then /Applications/Tailscale.app/Contents/MacOS/Tailscale "$@"
  else return 127; fi
}

if [[ "$MODE" == "--stop" ]]; then
  ts serve reset 2>/dev/null || true
  ts funnel reset 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Stopped. The dashboard is no longer reachable from other devices (python3 dashboard/app.py still works locally)."
  exit 0
fi
if [[ "$MODE" == "--private" ]]; then
  ts funnel reset 2>/dev/null || true
  ts serve --bg "$PORT" >/dev/null
  echo "Public link removed. Your own devices (with Tailscale) still reach the dashboard."
  exit 0
fi

[[ "$(uname)" == "Darwin" ]] || echo "Note: written for macOS (launchd). On Linux, run '.venv/bin/python -m dashboard.serve' with systemd instead."
[[ -x .venv/bin/python ]] || { echo "Run bash scripts/setup.sh first (it creates .venv)."; exit 1; }
PY="$ROOT/.venv/bin/python"
"$PY" -m pip install -q -r requirements.txt

touch .env && chmod 600 .env
set_key() {  # set_key NAME VALUE — single-quoted, so $ in the password hash survives shell sourcing
  local name="$1" value="${2//\'/}"
  grep -v "^${name}=" .env > .env.tmp || true
  mv .env.tmp .env
  echo "${name}='${value}'" >> .env
  chmod 600 .env
}
current() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" || true; }

echo "== 1/3 Dashboard password"
if [[ -n "$(current DASHBOARD_PASSWORD_HASH)" ]]; then
  read -r -p "A password is already set. Change it? [y/N] " ch
else
  ch=y
fi
if [[ "$ch" == [yY]* ]]; then
  while true; do
    read -r -s -p "New password (at least 12 characters; a phrase of 4+ words works well): " p1; echo
    read -r -s -p "Same password again: " p2; echo
    if [[ "$p1" != "$p2" ]]; then echo "They don't match — try again."; continue; fi
    if (( ${#p1} < 12 )); then echo "Too short — use at least 12 characters."; continue; fi
    break
  done
  HASH="$(printf '%s' "$p1" | "$PY" -c 'import sys; sys.path.insert(0, "."); from dashboard.auth import hash_password; print(hash_password(sys.stdin.read()))')"
  unset p1 p2
  set_key DASHBOARD_PASSWORD_HASH "$HASH"
  # New secret = everyone is logged out after a password change
  set_key DASHBOARD_SECRET_KEY "$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
fi
set_key DASHBOARD_REQUIRE_LOGIN "1"
set_key DASHBOARD_HTTPS "1"

echo
echo "== 2/3 Start the dashboard automatically (and keep the Mac awake while it runs)"
mkdir -p "$HOME/Library/LaunchAgents" logs
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>$(xml "$PY")</string><string>-m</string><string>dashboard.serve</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$ROOT")</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(xml "$PATH")</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml "$ROOT")/logs/dashboard_server.log</string>
  <key>StandardErrorPath</key><string>$(xml "$ROOT")/logs/dashboard_server.log</string>
</dict></plist>
PLISTEOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 2
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "Running on this Mac (logs/dashboard_server.log). It starts again after a restart."
else
  echo "The dashboard didn't answer yet — check logs/dashboard_server.log."
fi
echo "caffeinate keeps the Mac from sleeping while plugged in; closing the lid of a laptop still sleeps it."

echo
echo "== 3/3 Tailscale (encrypted access from your phone, at home or outside)"
if ! ts version >/dev/null 2>&1; then
  echo "Tailscale is not installed. Install it (free), log in, then re-run this script:"
  echo "  Mac:    https://tailscale.com/download/mac   (or: brew install --cask tailscale)"
  echo "  Phone:  'Tailscale' in the App Store / Google Play — log in with the same account"
  exit 0
fi
if ! ts status >/dev/null 2>&1; then
  echo "Tailscale is installed but not logged in. Open it, log in, then re-run this script."
  exit 0
fi
if [[ "$MODE" == "--public" ]]; then
  echo "Making a public https link (anyone with it sees the login page; the password protects the rest)..."
  if ! ts funnel --bg "$PORT"; then
    echo "Funnel isn't enabled for your account yet: follow the link Tailscale printed above, then re-run with --public."
    exit 1
  fi
else
  ts serve --bg "$PORT"
fi
URL="$(ts status --json 2>/dev/null | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("https://" + d["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
if [[ -n "$URL" ]]; then
  set_key DASHBOARD_PUBLIC_HOST "${URL#https://}"
  launchctl unload "$PLIST" 2>/dev/null || true; launchctl load "$PLIST"   # pick up the address
fi
echo
echo "Done. Open this on your phone${MODE:+ (public link)}:"
echo "  ${URL:-https://<this-mac>.<your-tailnet>.ts.net  (see: tailscale status)}"
if [[ "$MODE" != "--public" ]]; then
  echo "Your phone needs the Tailscale app switched on. For a link that opens anywhere without the app:"
  echo "  bash scripts/setup_remote.sh --public"
fi
echo "Tip: on the phone, use Share → 'Add to Home Screen' to open it like an app."
