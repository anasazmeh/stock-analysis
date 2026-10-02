"""
Final avoid-list check: no AVOID_LIST ticker or company name may appear in any
output (report, alerts, Claude text). Offending lines are removed and the run is
marked as failed in Data Health so the leak is visible and can be fixed.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

import config


def _patterns() -> list:
    pats = [re.compile(rf"(?<![A-Za-z0-9.]){re.escape(t)}(?![A-Za-z0-9])") for t in config.AVOID_LIST]
    pats += [re.compile(re.escape(name), re.IGNORECASE) for name in config.AVOID_NAMES.values()]
    return pats


def find_violations(text: str) -> list[str]:
    pats = _patterns()
    return [line for line in text.splitlines() if any(p.search(line) for p in pats)]


def scrub(text: str) -> tuple[str, int]:
    """Remove lines mentioning avoided names. Returns (clean text, lines removed)."""
    pats = _patterns()
    kept, removed = [], 0
    for line in text.splitlines():
        if any(p.search(line) for p in pats):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed
