"""
Technical-debt backlog built from run logs.

Each run's warnings and errors (from src/runlog.py) are grouped into issues:
tickers and numbers are masked, so "✗ FAB.AD no price" and "✗ EAND.AD no
price" become one issue, "✗ <ticker> no price", listing both tickers. The
backlog remembers when each issue was first and last seen and in how many
runs; an issue not seen in RESOLVE_AFTER runs in a row is marked resolved.

  data/tech_debt.json   the backlog itself (machine state, git-ignored)
  TECH_DEBT.md          readable backlog, rewritten after every run — commit it
                        when you want to share or track it

Import old logs:  python3 -m src.tech_debt --scan logs/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob
import hashlib
import json
import re
from datetime import datetime

import config
from src.output_gate import find_violations

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(_ROOT, "data", "tech_debt.json")
MD_PATH = os.path.join(_ROOT, "TECH_DEBT.md")
RESOLVE_AFTER = 5      # runs in a row without the issue before it counts as resolved
MAX_RUNS = 100
MAX_TICKERS = 25

_SYMBOL = re.compile(r"\b[A-Z0-9][A-Z0-9&-]{0,11}\.[A-Z]{1,3}\b")
_NUMBER = re.compile(r"(?<![A-Za-z<])[-+]?\d[\d,]*(\.\d+)?%?")
_URL = re.compile(r"https?://\S+")
_SECRET = re.compile(r"(api[_-]?key|token|apikey|password)=\S+", re.I)
_DOLLAR = re.compile(r"\$[A-Z][A-Z0-9.\-]{0,11}\b")
_QUOTED = re.compile(r"'([^']{1,120})'|\"([^\"]{1,120})\"")
# Long library error texts collapse to their cause
_NOISE = [(re.compile(r"HTTPSConnectionPool\(.*|Max retries exceeded.*", re.S), "connection error"),
          (re.compile(r"Failed to perform, curl:.*", re.S), "connection error (curl)"),
          (re.compile(r"\burl: \S+"), ""),
          (re.compile(r"\[[^\]]{20,}\]?"), "[list]")]

# Root-cause categories, first match wins: (name, pattern, suggested fix)
CATEGORIES = [
    ("Network / source down", re.compile(r"Connection|Proxy|curl|[Tt]imed? ?out|Max retries|Tunnel|unreachable|\b5\d\d\b|429|rate.?limit", re.I),
     "Usually temporary. If it repeats for days, the source changed its API or blocks you — check the URL and add a fallback."),
    ("Missing setup", re.compile(r"API keys|SEC contact|SEC_USER_AGENT|_KEY|not installed|ModuleNotFoundError|requirements|claude.*not", re.I),
     "Run bash scripts/setup.sh, or install what the message names."),
    ("Symbol / listing", re.compile(r"symbol|delisted|Quote not found|no Yahoo quote|wrong listing|no price", re.I),
     "Fix the ticker in config.py (or portfolio_data.py); remove it if the company is no longer listed."),
    ("Email / alerts", re.compile(r"SMTP|email|webhook", re.I),
     "Re-run bash scripts/setup_schedule.sh and check the app password or webhook URL."),
    ("Data quality", re.compile(r"Data-quality|data check|Degraded|stale|usable|mismatch|NO FX", re.I),
     "Follows from the issues above — fix those first; then check thresholds in config.py."),
    ("Code bug", re.compile(r"Traceback|Error\b|Exception|exit code", re.I),
     "Open the log, find the traceback, and fix the code (add a test that reproduces it)."),
]


def categorize(text: str) -> tuple[str, str]:
    for name, pat, fix in CATEGORIES:
        if pat.search(text):
            return name, fix
    return "Other", "Read the example line and the log around it."


def normalize(text: str, tickers=()) -> tuple[str, list]:
    """Return (grouping key, affected tickers) for one issue line."""
    text = _SECRET.sub(r"\1=<hidden>", text)
    found = []

    def sym(m):
        found.append(m.group(0))
        return "<ticker>"

    out = text.splitlines()[0] if text else ""
    for pat, repl in _NOISE:
        out = pat.sub(repl, out)
    out = _URL.sub("<url>", out)
    def dollar(m):
        found.append(m.group(0)[1:])
        return "<ticker>"

    out = _DOLLAR.sub(dollar, out)
    out = _SYMBOL.sub(sym, out)
    known = {t for t in set(tickers) | set(config.BENCHMARKS) if t and "." not in t}
    def quoted(m):
        inner = m.group(1) or m.group(2)
        if inner in known or _SYMBOL.fullmatch(inner):
            found.append(inner)
            return "<ticker>"
        return "'…'"
    out = _QUOTED.sub(quoted, out)
    if known:
        out = re.sub(r"\b(" + "|".join(sorted(map(re.escape, known), key=len, reverse=True)) + r")\b", sym, out)
    out = _NUMBER.sub("N", out)
    out = re.sub(r"\s+", " ", out).strip(" -—:·")
    return out[:220], found


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"runs": [], "issues": {}}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def update(found: list, tickers=(), path: str = None, md_path: str = None, log_file: str = None,
           run_at: str = None) -> dict:
    """Merge one run's issues into the backlog and rewrite TECH_DEBT.md. Returns counts for the summary line."""
    path, md_path = path or JSON_PATH, md_path or MD_PATH
    data = _load(path)
    run_at = run_at or datetime.now().isoformat(timespec="seconds")
    data["runs"] = (data.get("runs", []) + [run_at])[-MAX_RUNS:]
    run_no = data.get("run_count", 0) + 1
    data["run_count"] = run_no
    issues = data.setdefault("issues", {})

    seen_now, new = set(), 0
    for item in found:
        key_text, affected = normalize(item["text"], tickers)
        if not key_text or find_violations(item["text"]):
            continue
        key = hashlib.sha1(f"{item['level']}|{key_text}".encode()).hexdigest()[:12]
        it = issues.get(key)
        if it is None:
            new += 1
            cat, fix = categorize(item["text"])
            it = issues[key] = {"level": item["level"], "title": key_text, "category": cat, "fix": fix, "example": _SECRET.sub(r"\1=<hidden>", item["text"])[:300],
                                "source": item.get("source", ""), "first_seen": run_at, "runs": 0,
                                "occurrences": 0, "tickers": [], "status": "open"}
        if key not in seen_now:
            it["runs"] += 1
        seen_now.add(key)
        it["occurrences"] += 1
        it["last_seen"], it["last_run_no"] = run_at, run_no
        if it["status"] == "resolved":
            it["status"], it["reopened"] = "open", run_at
        it["tickers"] = sorted(set(it["tickers"]) | set(affected))[:MAX_TICKERS]
        if log_file:
            it["log"] = os.path.relpath(log_file, _ROOT) if os.path.isabs(log_file) else log_file

    resolved = 0
    for it in issues.values():
        if it["status"] == "open" and run_no - it.get("last_run_no", run_no) >= RESOLVE_AFTER:
            it["status"], it["resolved_at"] = "resolved", run_at
            resolved += 1
    _save(path, data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(data))
    this = [issues[k] for k in seen_now]
    return {"errors": sum(i["level"] == "ERROR" for i in this), "warnings": sum(i["level"] == "WARNING" for i in this),
            "open": sum(i["status"] == "open" for i in issues.values()), "new": new, "resolved": resolved}


def _row(it):
    return _row_full(it)


def _row_full(it):
    tick = ", ".join(it["tickers"][:8]) + (f" +{len(it['tickers']) - 8}" if len(it["tickers"]) > 8 else "")
    return (f"| {'🔴' if it['level'] == 'ERROR' else '🟡'} {it['level'].title()} | {it['title'].replace('|', '/')} | "
            f"{tick or '–'} | {it['runs']} | {it['first_seen'][:10]} | {it['last_seen'][:10]} | "
            f"`{it['example'][:120].replace('|', '/').replace('`', '')}` |")


def render_md(data: dict) -> str:
    issues = list(data.get("issues", {}).values())
    open_ = sorted([i for i in issues if i["status"] == "open"],
                   key=lambda i: (i["level"] != "ERROR", -i["runs"], i["title"]))
    done = sorted([i for i in issues if i["status"] == "resolved"], key=lambda i: i.get("resolved_at", ""), reverse=True)
    runs = data.get("runs", [])
    lines = ["# Technical Debt — from run logs", "",
             "> Rewritten automatically after every run by `src/tech_debt.py` from the warnings and errors in the logs.",
             "> Fix an item, then it moves to *Resolved* after "
             f"{RESOLVE_AFTER} runs without it. Known design debt is listed in TODO.md.", "",
             f"Runs tracked: {data.get('run_count', 0)}" + (f" · last run {runs[-1][:16].replace('T', ' ')}" if runs else "")
             + f" · open: {sum(i['level'] == 'ERROR' for i in open_)} errors, "
             f"{sum(i['level'] == 'WARNING' for i in open_)} warnings", "",
             "## Open", ""]
    head = ["| Level | Issue | Tickers | Runs seen | First seen | Last seen | Example |", "|---|---|---|---:|---|---|---|"]
    if not open_:
        lines.append("Nothing open. 🎉")
    order = [c[0] for c in CATEGORIES] + ["Other"]
    for cat in sorted({i.get("category", "Other") for i in open_}, key=order.index):
        group = [i for i in open_ if i.get("category", "Other") == cat]
        fix = group[0].get("fix") or categorize(group[0]["example"])[1]
        lines += [f"### {cat} ({len(group)})", "", f"**Suggested fix:** {fix}", ""] + head + [_row(i) for i in group] + [""]
    lines += ["", "## Resolved (not seen recently)", ""]
    lines += (head + [_row(i) for i in done[:30]]) if done else ["None yet."]
    lines += ["", "*Tickers and numbers are masked so the same problem on different stocks is one item. "
              "Logs are in `logs/`.*", ""]
    return "\n".join(lines)


def scan_logs(paths: list, path: str = None, md_path: str = None) -> int:
    """Import old log files, oldest first, one run per file."""
    from src.runlog import classify
    files = sorted(set(paths), key=os.path.getmtime)
    for p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            found = [{"level": lvl, "text": line.strip(), "source": "output"}
                     for line in f if (lvl := classify(line))]
        stamp = re.search(r"(\d{4}-\d{2}-\d{2})(?:_(\d{2})(\d{2})(\d{2}))?", os.path.basename(p))
        run_at = (f"{stamp.group(1)}T{stamp.group(2)}:{stamp.group(3)}:{stamp.group(4)}" if stamp and stamp.group(2)
                  else f"{stamp.group(1)}T00:00:00" if stamp else datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds"))
        update(found, tickers=config.CURATED_WATCHLIST, path=path, md_path=md_path, log_file=p, run_at=run_at)
    return len(files)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Technical-debt backlog from run logs")
    ap.add_argument("--scan", nargs="+", metavar="PATH", help="log files or folders to import")
    ap.add_argument("--show", action="store_true", help="print TECH_DEBT.md")
    a = ap.parse_args()
    if a.scan:
        files = []
        for p in a.scan:
            files += glob.glob(os.path.join(p, "*.log")) if os.path.isdir(p) else [p]
        print(f"Imported {scan_logs(files)} log file(s) → {MD_PATH}")
    if a.show or not a.scan:
        print(render_md(_load(JSON_PATH)))
