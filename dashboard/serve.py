"""
Serve the dashboard for your phone and other devices (see scripts/setup_remote.sh).

    .venv/bin/python -m dashboard.serve

Runs the dashboard on 127.0.0.1:DASHBOARD_PORT with waitress, a production web
server. Tailscale ("tailscale serve" for your devices only, or "tailscale funnel"
for a public link) forwards https traffic to it, so the dashboard itself is never
bound to your network. Refuses to start without a password.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402  (loads .env)


def build_app():
    from werkzeug.middleware.proxy_fix import ProxyFix
    from dashboard.app import create_app
    if not os.environ.get("DASHBOARD_PASSWORD_HASH"):
        sys.exit("No dashboard password set. Run: bash scripts/setup_remote.sh")
    app = create_app(auth_options={"require_login": True})
    # Only the local Tailscale proxy can connect (we bind to 127.0.0.1), so trust one hop of its headers:
    # the real client address for the login lockout, and the public host name for the same-origin checks.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app


def main():
    from waitress import serve
    port = int(os.environ.get("DASHBOARD_PORT", "8050"))
    print(f"Dashboard (login required) on http://127.0.0.1:{port} — reach it through your Tailscale https address")
    # Keep the proxy's X-Forwarded-* headers for ProxyFix (waitress drops them by default).
    serve(build_app(), host="127.0.0.1", port=port, threads=6, ident="", clear_untrusted_proxy_headers=False)


if __name__ == "__main__":
    main()
