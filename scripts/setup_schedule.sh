#!/usr/bin/env bash
# Sets up email alerts and the daily scheduled run (cron). Safe to re-run.
#   bash scripts/setup_schedule.sh            # interactive
#   bash scripts/setup_schedule.sh --remove   # remove the cron job
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
MARK="# stock-analysis-daily"

remove_cron() { local tab; tab="$( (crontab -l 2>/dev/null || true) | { grep -vF "$MARK" || true; } )"; printf "%s\n" "$tab" | sed "/^$/d" | crontab -; }

if [[ "${1:-}" == "--remove" ]]; then
  remove_cron
  echo "Removed the daily job. Email settings in .env were left as they are."
  exit 0
fi

touch .env
chmod 600 .env
set_key() {  # set_key NAME VALUE — replaces or appends a line in .env
  local name="$1" value="${2//\"/}"
  grep -v "^${name}=" .env > .env.tmp || true
  mv .env.tmp .env
  echo "${name}=\"${value}\"" >> .env
  chmod 600 .env
}
current() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true; }

echo "== 1/3 Email alerts"
echo "Alerts are emailed after a run that finds signals, when a run is degraded, and when a run fails."
if [[ -n "$(current ALERT_EMAIL_TO)" ]]; then
  echo "Already set: alerts go to $(current ALERT_EMAIL_TO)."
  read -r -p "Change them? [y/N] " change
else
  change=y
fi
if [[ "$change" == [yY]* ]]; then
  read -r -p "Send alerts to (your email): " to
  read -r -p "Send from (a Gmail address; Enter = same as above): " from
  from="${from:-$to}"
  host="smtp.gmail.com"; port="587"
  if [[ "$from" != *@gmail.com && "$from" != *@googlemail.com ]]; then
    read -r -p "SMTP server for $from (e.g. smtp.office365.com): " host
    read -r -p "SMTP port [587]: " port
    port="${port:-587}"
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then echo "Not a port number: $port"; exit 1; fi
    echo "Use the password (or app password) for $from."
  else
    echo "Gmail needs an app password, not your normal password:"
    echo "  1. Turn on 2-Step Verification: https://myaccount.google.com/signinoptions/two-step-verification"
    echo "  2. Create an app password:      https://myaccount.google.com/apppasswords"
    echo "  Paste the 16-character code below (spaces are fine)."
  fi
  read -r -s -p "Password (hidden): " pw; echo
  pw="${pw// /}"
  set_key ALERT_EMAIL_TO "$to"
  set_key ALERT_EMAIL_FROM "$from"
  set_key ALERT_SMTP_HOST "$host"
  set_key ALERT_SMTP_PORT "$port"
  set_key ALERT_SMTP_PASSWORD "$pw"
fi

if [[ -n "$(current ALERT_EMAIL_TO)" ]]; then
  echo "Sending a test email…"
  if python3 -m src.alerts --test; then
    echo "Check your inbox (and spam folder)."
  else
    echo "The test failed. Re-run this script and check the address and app password."
    read -r -p "Continue with the schedule anyway? [y/N] " cont
    [[ "$cont" == [yY]* ]] || exit 1
  fi
fi

echo
echo "== 2/3 Schedule"
read -r -p "Run time on weekdays, 24h HH:MM [07:00]: " t
t="${t:-07:00}"
if ! [[ "$t" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then echo "Not a valid time: $t"; exit 1; fi
hh=$((10#${BASH_REMATCH[1]})); mm=$((10#${BASH_REMATCH[2]}))

# cron starts with a minimal PATH, so pass the one where python3 and claude are found now.
for tool in python3 claude; do
  command -v "$tool" >/dev/null 2>&1 || echo "Note: '$tool' is not on your PATH; the scheduled run won't find it either."
done
cron_path="${PATH//%/\\%}"; cron_root="${ROOT//%/\\%}"   # % means newline in crontab
line="$mm $hh * * 1-5 PATH=\"$cron_path\" \"$cron_root/scripts/run_daily.sh\" $MARK"
chmod +x scripts/run_daily.sh
remove_cron
( (crontab -l 2>/dev/null || true); echo "$line" ) | crontab -
printf "Installed: weekdays at %02d:%02d (your computer's local time).\n" "$hh" "$mm"

echo
echo "== 3/3 Optional: get told if a run never starts"
if [[ -z "$(current HEALTHCHECK_URL)" ]]; then
  echo "A free https://healthchecks.io check emails you when the job is missed (computer off, cron broken)."
  read -r -p "Paste its ping URL (Enter to skip): " hc
  [[ -n "$hc" ]] && set_key HEALTHCHECK_URL "$hc"
else
  echo "HEALTHCHECK_URL already set."
fi

echo
echo "Done."
echo "  crontab -l                          # see the job"
echo "  scripts/run_daily.sh                # run it now, the same way cron will"
echo "  logs/run_YYYY-MM-DD.log             # each run's log"
echo "  bash scripts/setup_schedule.sh --remove   # stop the daily run"
if [[ "$(uname)" == "Darwin" ]]; then
  echo "macOS: cron skips runs while the Mac sleeps. If macOS asks, allow 'cron' in"
  echo "System Settings → Privacy & Security → Full Disk Access when the project is in Documents/Desktop."
fi
