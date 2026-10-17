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


# ── Input clean-up: news headlines and Claude's prose name avoided companies all the
# time ("…AI peers such as <avoided>…"). Remove those mentions where they enter, so
# the final gate above only fires on a real pipeline leak.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _clean_text(text: str, pats) -> tuple[str, int]:
    if not any(p.search(text) for p in pats):
        return text, 0
    kept = [s for s in _SENTENCE.split(text) if not any(p.search(s) for p in pats)]
    return " ".join(kept), 1


def _clean(value, pats):
    """Return (cleaned value, mentions removed). Lists drop whole items (a news article, a theme)."""
    import json
    if isinstance(value, str):
        return _clean_text(value, pats)
    if isinstance(value, list):
        out, n = [], 0
        for item in value:
            if isinstance(item, (str, dict)):
                blob = item if isinstance(item, str) else json.dumps(item, default=str)
                if any(p.search(blob) for p in pats):
                    n += 1
                    continue
                out.append(item)
            else:
                item, k = _clean(item, pats)
                out.append(item)
                n += k
        return out, n
    if hasattr(value, "__dataclass_fields__"):
        n = 0
        for name in value.__dataclass_fields__:
            cleaned, k = _clean(getattr(value, name), pats)
            if k:
                setattr(value, name, cleaned)
                n += k
        return value, n
    return value, 0


_OPP_TEXT_FIELDS = ("news", "thesis_notes", "filings", "analysis", "risk", "next_event")


def scrub_inputs(opportunities: list, macro=None) -> int:
    """Remove avoided-company mentions from news, filings, theses, Claude text and macro context, in place."""
    pats = _patterns()
    removed = 0
    for o in opportunities:
        for name in _OPP_TEXT_FIELDS:
            value = getattr(o, name, None)
            if value:
                cleaned, n = _clean(value, pats)
                if n:
                    setattr(o, name, cleaned)
                    removed += n
    if macro is not None:
        removed += _clean(macro, pats)[1]
    if removed:
        print(f"  [avoid-list] {removed} news item(s)/sentence(s) naming avoid-list companies left out")
    return removed
