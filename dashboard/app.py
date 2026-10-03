"""
Local web dashboard for the stock-analysis pipeline.

    python3 dashboard/app.py          → http://127.0.0.1:5000

Reads reports/latest.json (written by every `python3 main.py` run) and the run
history in runs/. "Refresh data" starts a pipeline run in the background.
Binds to 127.0.0.1 only: it is a personal tool, not meant to be exposed.
"""
import glob
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, render_template, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEVEL_ORDER = ["DANGER", "BUY", "DIP", "WARN", "INFO"]


def create_app(report_dir: str = None, runs_dir: str = None, run_cmd: list = None) -> Flask:
    import config
    app = Flask(__name__)
    app.config["REPORT_DIR"] = report_dir or config.REPORT_DIR
    app.config["RUNS_DIR"] = runs_dir or os.path.join(ROOT, "runs")
    app.config["RUN_CMD"] = run_cmd or [sys.executable, os.path.join(ROOT, "main.py")]
    run_state = {"running": False, "started": None, "finished": None, "exit_code": None}
    lock = threading.Lock()

    def load_latest():
        path = os.path.join(app.config["REPORT_DIR"], "latest.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def load_history():
        rows = []
        for path in sorted(glob.glob(os.path.join(app.config["RUNS_DIR"], "*.json"))):
            try:
                with open(path) as f:
                    snap = json.load(f)
            except (OSError, ValueError):
                continue
            rows.append({"run_at": snap.get("run_at", ""), "value": snap.get("portfolio_value_eur"),
                         "benchmark": snap.get("benchmark_close"), "degraded": snap.get("degraded", False),
                         "top10": snap.get("top10", [])})
        return rows

    @app.context_processor
    def inject_common():
        data = load_latest()
        alerts = (data or {}).get("alerts", [])
        return {
            "nav_alert_count": sum(1 for a in alerts if a["level"] in ("DANGER", "BUY")),
            "run_at": (data or {}).get("run_at", ""),
            "degraded": (data or {}).get("degraded", False),
            "degraded_reasons": (data or {}).get("degraded_reasons", []),
        }

    @app.template_filter("eur")
    def eur(v, signed=False):
        if v is None:
            return "–"
        s = f"€{abs(v):,.0f}"
        return (("+" if v >= 0 else "−") + s) if signed else s

    @app.template_filter("pct")
    def pct(v, signed=True, digits=1):
        if v is None:
            return "–"
        return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"

    @app.template_filter("num")
    def num(v, digits=2):
        if v is None or v == "":
            return "–"
        try:
            return f"{float(v):,.{digits}f}"
        except (TypeError, ValueError):
            return str(v)

    @app.template_filter("ratio")
    def ratio(v):
        return "–" if v is None else f"{v * 100:.1f}%"

    @app.template_filter("when")
    def when(iso):
        try:
            return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            return iso or "–"

    def empty():
        return render_template("empty.html"), 200

    @app.route("/")
    def overview():
        data = load_latest()
        if not data:
            return empty()
        alerts = sorted(data["alerts"], key=lambda a: LEVEL_ORDER.index(a["level"]) if a["level"] in LEVEL_ORDER else 9)
        holdings = [o for o in data["opportunities"] if o.get("portfolio")]
        top10 = sorted([o for o in data["opportunities"] if o.get("top10")], key=lambda o: -o["rank_score"])
        return render_template("overview.html", d=data, alerts=alerts, holdings=holdings, top10=top10)

    @app.route("/portfolio")
    def portfolio():
        data = load_latest()
        if not data:
            return empty()
        holdings = sorted([o for o in data["opportunities"] if o.get("portfolio")],
                          key=lambda o: -((o["portfolio"] or {}).get("value_eur") or 0))
        chart = {
            "pl": [{"t": o["ticker"], "v": o["portfolio"].get("pl_pct")} for o in holdings
                   if o["portfolio"].get("pl_pct") is not None],
            "themes": data["portfolio"].get("themes") or {},
            "currencies": data["portfolio"].get("currencies") or {},
        }
        return render_template("portfolio.html", d=data, holdings=holdings, chart=chart)

    @app.route("/opportunities")
    def opportunities():
        data = load_latest()
        if not data:
            return empty()
        rows = sorted(data["opportunities"], key=lambda o: -(o.get("rank_score") or 0))
        regions = {}
        for o in rows:
            r = regions.setdefault(o.get("region") or "Other", {"n": 0, "ups": [], "risks": [], "yes": 0, "top": None})
            r["n"] += 1
            if o.get("adj_upside") is not None:
                r["ups"].append(o["adj_upside"])
            if (o.get("risk") or {}).get("composite_score") is not None:
                r["risks"].append(o["risk"]["composite_score"])
            if (o.get("shariah") or {}).get("compliant") == "Yes":
                r["yes"] += 1
            if o.get("data_ok") and (r["top"] is None or o["rank_score"] > r["top"]["rank_score"]):
                r["top"] = o
        heat = [{"region": k, "n": v["n"], "yes": v["yes"],
                 "avg_up": sum(v["ups"]) / len(v["ups"]) if v["ups"] else None,
                 "avg_risk": sum(v["risks"]) / len(v["risks"]) if v["risks"] else None,
                 "top": v["top"]["ticker"] if v["top"] else None} for k, v in sorted(regions.items())]
        return render_template("opportunities.html", d=data, rows=rows, heat=heat,
                               regions=sorted(regions), shariah_values=["Yes", "Review", "Unknown", "No"])

    @app.route("/stock/<ticker>")
    def stock(ticker):
        data = load_latest()
        if not data:
            return empty()
        o = next((x for x in data["opportunities"] if x["ticker"] == ticker), None)
        if o is None:
            abort(404)
        alerts = [a for a in data["alerts"] if a["ticker"] == ticker]
        return render_template("stock.html", d=data, o=o, alerts=alerts)

    @app.route("/history")
    def history():
        return render_template("history.html", runs=load_history(), d=load_latest() or {})

    @app.route("/api/latest")
    def api_latest():
        data = load_latest()
        return (jsonify(data), 200) if data else (jsonify({"error": "no run yet"}), 404)

    def same_origin() -> bool:
        """Block cross-site POSTs: a web page you visit must not be able to start runs."""
        source = request.headers.get("Origin") or request.headers.get("Referer")
        return bool(source) and urlparse(source).netloc == request.host

    def run_pipeline():
        log_dir = os.path.join(ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "dashboard_run.log"), "w") as log:
            code = subprocess.call(app.config["RUN_CMD"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        with lock:
            run_state.update(running=False, finished=datetime.now().isoformat(timespec="seconds"), exit_code=code)

    @app.route("/refresh", methods=["POST"])
    def refresh():
        if not same_origin():
            abort(403)
        with lock:
            if run_state["running"]:
                return jsonify(run_state), 409
            run_state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                             finished=None, exit_code=None)
        threading.Thread(target=run_pipeline, daemon=True).start()
        return jsonify(run_state), 202

    @app.route("/refresh/status")
    def refresh_status():
        with lock:
            return jsonify(run_state)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "5000"))
    print(f"Dashboard: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    create_app().run(host="127.0.0.1", port=port, debug=False)
