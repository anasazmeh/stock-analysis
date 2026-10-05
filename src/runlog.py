"""
Run logging and issue capture.

start()  copies everything the run prints to logs/run_YYYY-MM-DD_HHMMSS.log
         (terminal runs only — cron already redirects its output; newest 30
         kept) and routes library warnings (yfinance, pandas, Python warnings)
         into that file instead of the screen. In every run it also collects
         the lines that look like warnings or errors.
finish() hands those, plus any Data Health source that wasn't ok, to
         src/tech_debt.py, which keeps the technical-debt backlog in
         TECH_DEBT.md up to date.
"""
import sys
import os
import glob
import logging
import re
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_ROOT, "logs")
KEEP = 30
_state = {}

_ERROR = re.compile(r"Traceback|^\s*\w+(Error|Exception)\b|\bError\b|\berror\b|\bfailed\b|FAILED|✗|❌|HTTP Error \d+")
_WARN = re.compile(r"[Ww]arning|⚠|\bskipped\b|no price|[Mm]ismatch|not found|unavailable|DEGRADED|"
                   r"rate.?limit|\b429\b|timed? ?out|[Dd]eprecat|no Yahoo quote")
_IGNORE = re.compile(r"Stage \d|^\s*Traceback \(most recent call last\)|^\s+File \"|^\s{4,}\S|\b0 failed\b|"
                     r"Avoid-list gate removed 0|No alerts triggered")


def classify(line: str):
    """Return "ERROR", "WARNING" or None for one printed line."""
    if not line.strip() or _IGNORE.search(line):
        return None
    if _ERROR.search(line):
        return "ERROR"
    if _WARN.search(line):
        return "WARNING"
    return None


class _Collector:
    def __init__(self):
        self.issues = []          # [{"level", "text", "source"}]
        self._partial = ""

    def feed(self, data: str):
        self._partial += data
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            level = classify(line)
            if level:
                self.issues.append({"level": level, "text": line.strip(), "source": "output"})

    def add(self, level: str, text: str, source: str):
        self.issues.append({"level": level, "text": text.strip(), "source": source})


class _Tee:
    def __init__(self, stream, f, collector):
        self.stream, self.f, self.collector = stream, f, collector

    def write(self, data):
        self.stream.write(data)
        if self.f is not None:
            try:
                self.f.write(data)
            except ValueError:   # file closed at shutdown
                pass
        self.collector.feed(data)
        return len(data)

    def flush(self):
        self.stream.flush()
        if self.f is not None:
            try:
                self.f.flush()
            except ValueError:
                pass

    def isatty(self):
        return self.stream.isatty()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _LibraryHandler(logging.Handler):
    """Library warnings go to the log file and the issue list, not the screen."""

    def __init__(self, f, collector):
        super().__init__(logging.WARNING)
        self.f, self.collector = f, collector

    def emit(self, record):
        try:
            msg = f"{record.levelname} [{record.name}] {record.getMessage()}"
        except Exception:
            return
        if self.f is not None:
            try:
                self.f.write(msg + "\n")
            except ValueError:
                pass
        self.collector.add("ERROR" if record.levelno >= logging.ERROR else "WARNING", msg, f"library:{record.name}")


def start(log_dir: str = None, force: bool = False):
    """Begin capturing. Returns the log file path, or None when output is already redirected (cron)."""
    stop()
    collector = _Collector()
    f, path = None, None
    if force or sys.stdout.isatty():
        log_dir = log_dir or _LOG_DIR
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"run_{datetime.now():%Y-%m-%d_%H%M%S}.log")
        f = open(path, "w", encoding="utf-8", buffering=1)
        for old in sorted(glob.glob(os.path.join(log_dir, "run_????-??-??_??????.log")))[:-KEEP]:
            try:
                os.remove(old)
            except OSError:
                pass
    handler = _LibraryHandler(f if f is not None else sys.stderr, collector)
    root = logging.getLogger()
    root.addHandler(handler)
    logging.getLogger("yfinance").setLevel(logging.WARNING)   # its 404s go to the file, not the screen
    logging.captureWarnings(True)
    _state.update(file=f, path=path, collector=collector, handler=handler, streams=(sys.stdout, sys.stderr))
    sys.stdout, sys.stderr = _Tee(sys.stdout, f, collector), _Tee(sys.stderr, f, collector)
    return path


def add_tickers(tickers):
    """Tickers seen this run, so log lines about them group into one backlog item."""
    _state.setdefault("tickers", set()).update(tickers)


def issues() -> list:
    return list(_state["collector"].issues) if "collector" in _state else []


def finish(health=None, tickers=(), exit_code: int = 0, backlog_path: str = None, md_path: str = None):
    """Record this run's issues in the technical-debt backlog and print a one-line summary."""
    found = issues()
    if exit_code not in (0, 2):
        found.append({"level": "ERROR", "text": f"Run ended with exit code {exit_code}", "source": "exit code"})
    if health is not None:
        for name, (status, detail) in health.sources.items():
            if status in ("failed", "partial"):
                found.append({"level": "ERROR" if status == "failed" else "WARNING",
                              "text": f"Data Health: {name} {status} — {detail}", "source": "data health"})
        for reason in health.degraded_reasons:
            found.append({"level": "WARNING", "text": f"Degraded run: {reason}", "source": "data health"})
    try:
        from src import tech_debt
        summary = tech_debt.update(found, tickers=set(tickers) | _state.get("tickers", set()), path=backlog_path, md_path=md_path,
                                   log_file=_state.get("path"))
        print(f"🧰 Issues this run: {summary['errors']} error(s), {summary['warnings']} warning(s) · "
              f"{summary['open']} open in TECH_DEBT.md ({summary['new']} new, {summary['resolved']} resolved)")
    except Exception as e:   # the backlog must never break a run
        print(f"  [tech debt] backlog not updated: {type(e).__name__}: {e}")
    return found


def stop():
    """Restore the original streams and close the log file."""
    if "streams" in _state:
        sys.stdout, sys.stderr = _state["streams"]
        logging.getLogger().removeHandler(_state["handler"])
        logging.captureWarnings(False)
        if _state.get("file") is not None:
            _state["file"].close()
        _state.clear()
