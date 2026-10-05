"""
Login for remote access.

The dashboard holds your portfolio, so once it is reachable from other devices
every page, the JSON API and the Refresh button sit behind a password.

  DASHBOARD_PASSWORD_HASH  scrypt hash of your password (set by scripts/setup_remote.sh;
                           the password itself is never stored)
  DASHBOARD_SECRET_KEY     signs the login cookie (random, created by the same script)
  DASHBOARD_REQUIRE_LOGIN  "1" to require login (default when a password hash is set)
  DASHBOARD_PUBLIC_HOST    your Tailscale address, e.g. mac.tail1234.ts.net (accepted as same-origin)

Wrong passwords: after MAX_FAILURES from one address within WINDOW seconds that
address is locked out for LOCKOUT seconds, and after GLOBAL_MAX failures from
everyone in an hour all logins pause for LOCKOUT — this slows down guessing from
many addresses too. A successful login lasts SESSION_DAYS on that device.
"""
import os
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse

from flask import abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

MAX_FAILURES = 5
WINDOW = 15 * 60
LOCKOUT = 15 * 60
GLOBAL_MAX = 30
SESSION_DAYS = 30
OPEN_ENDPOINTS = {"login", "static", "health"}


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


class Limiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.failures = {}       # address -> [timestamps]
        self.all_failures = []
        self.locked_until = {}   # address -> time; "*" = everyone
        self.lock = threading.Lock()

    def locked(self, addr: str) -> float:
        """Seconds left on a lockout for this address (0 = not locked)."""
        now = self.clock()
        with self.lock:
            return max(0.0, self.locked_until.get(addr, 0) - now, self.locked_until.get("*", 0) - now)

    def fail(self, addr: str):
        now = self.clock()
        with self.lock:
            hits = [t for t in self.failures.get(addr, []) if now - t < WINDOW] + [now]
            self.failures[addr] = hits
            self.all_failures = [t for t in self.all_failures if now - t < 3600] + [now]
            if len(hits) >= MAX_FAILURES:
                self.locked_until[addr] = now + LOCKOUT
                self.failures[addr] = []
            if len(self.all_failures) >= GLOBAL_MAX:
                self.locked_until["*"] = now + LOCKOUT
                self.all_failures = []

    def succeed(self, addr: str):
        with self.lock:
            self.failures.pop(addr, None)


def allowed_hosts() -> set:
    """This request's host plus the public address(es) the setup script saved (your Tailscale name)."""
    extra = {h.strip().lower() for h in os.environ.get("DASHBOARD_PUBLIC_HOST", "").split(",") if h.strip()}
    return {request.host.lower()} | extra


def same_origin() -> bool:
    """Block cross-site form posts: another website must not be able to act as you."""
    source = request.headers.get("Origin") or request.headers.get("Referer")
    return bool(source) and urlparse(source).netloc.lower() in allowed_hosts()


def install(app, password_hash: str = None, secret_key: str = None, require_login: bool = None,
            https: bool = None, clock=time.monotonic):
    """Add login, logout, the login check and security headers to the Flask app."""
    password_hash = password_hash if password_hash is not None else os.environ.get("DASHBOARD_PASSWORD_HASH", "")
    if require_login is None:
        require_login = os.environ.get("DASHBOARD_REQUIRE_LOGIN", "1" if password_hash else "0") == "1"
    if require_login and not password_hash:
        raise RuntimeError("Login is required but no DASHBOARD_PASSWORD_HASH is set — run bash scripts/setup_remote.sh")
    app.config["REQUIRE_LOGIN"] = require_login
    app.secret_key = secret_key or os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_hex(32)
    https = https if https is not None else os.environ.get("DASHBOARD_HTTPS", "1" if require_login else "0") == "1"
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=https,
                      SESSION_COOKIE_NAME="pd_session", PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS))
    limiter = Limiter(clock)
    app.extensions["login_limiter"] = limiter

    @app.before_request
    def check_login():
        if not app.config["REQUIRE_LOGIN"] or request.endpoint in OPEN_ENDPOINTS:
            return None
        if session.get("auth"):
            return None
        if request.path.startswith(("/api/", "/refresh")):
            abort(401)
        return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
        if app.config["REQUIRE_LOGIN"]:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not app.config["REQUIRE_LOGIN"]:
            return redirect(url_for("overview"))
        addr = request.remote_addr or "?"
        error, wait = "", limiter.locked(addr)
        if request.method == "POST":
            if not same_origin():
                abort(403)
            if wait:
                error = f"Too many attempts. Try again in {int(wait // 60) + 1} minutes."
            elif check_password_hash(password_hash, request.form.get("password", "")):
                limiter.succeed(addr)
                session.clear()
                session["auth"] = True
                session.permanent = bool(request.form.get("remember"))
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("overview"))
            else:
                limiter.fail(addr)
                wait = limiter.locked(addr)
                error = f"Too many attempts. Try again in {int(wait // 60) + 1} minutes." if wait else "Wrong password."
        elif wait:
            error = f"Too many attempts. Try again in {int(wait // 60) + 1} minutes."
        return render_template("login.html", error=error), (429 if wait else 200)

    @app.route("/logout", methods=["POST"])
    def logout():
        if not same_origin():
            abort(403)
        session.clear()
        return redirect(url_for("login"))

    return app
