"""
Every run's output is also saved to logs/run_YYYY-MM-DD_HHMMSS.log (the newest
30 are kept), so errors can be read after the terminal is closed. Cron runs
already redirect their output (scripts/run_daily.sh), so only interactive runs
are copied here.
"""
import sys
import os
import glob
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
KEEP = 30
_open = {}


class _Tee:
    def __init__(self, stream, f):
        self.stream, self.f = stream, f

    def write(self, data):
        self.stream.write(data)
        try:
            self.f.write(data)
        except ValueError:   # file closed at shutdown
            pass
        return len(data)

    def flush(self):
        self.stream.flush()
        try:
            self.f.flush()
        except ValueError:
            pass

    def isatty(self):
        return self.stream.isatty()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start(log_dir: str = None, force: bool = False):
    """Copy stdout and stderr to a new log file. Returns its path, or None when not interactive."""
    if not (force or sys.stdout.isatty()):
        return None
    log_dir = log_dir or _LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"run_{datetime.now():%Y-%m-%d_%H%M%S}.log")
    f = open(path, "w", encoding="utf-8", buffering=1)
    _open["file"], _open["streams"] = f, (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = _Tee(sys.stdout, f), _Tee(sys.stderr, f)
    for old in sorted(glob.glob(os.path.join(log_dir, "run_????-??-??_??????.log")))[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def stop():
    """Restore the original streams and close the log file."""
    if "file" in _open:
        sys.stdout, sys.stderr = _open.pop("streams")
        _open.pop("file").close()
