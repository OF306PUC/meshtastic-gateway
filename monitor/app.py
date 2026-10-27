"""The dashboard's pages and JSON API: / and /map, /dashboard, /api/nodes and
/api/recent/<node_id>/<field>.

A query that fails answers 503 with the reason; it never answers an empty list,
which the map would show as "no nodes yet".
"""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from gateway.deployment import DeploymentError, Surveyed, load
from monitor.param import TOTAL_SAMPLES_48HRS, Config
from monitor.utils import ALL_FIELDS, NODE_ID_RE, DatabaseError

__all__ = ["create_app", "surveyed_positions"]


def surveyed_positions(deployment: str | None, log=print) -> list[tuple[str, str, Surveyed]]:
    """(node_id, published name, position) for each node surveyed on site.

    Read on every request, so an edited deployment file shows up without a
    restart. No deployment configured means GPS only; an invalid file is logged
    loudly, and the map falls back to GPS until it is fixed.
    """
    if not deployment:
        return []
    try:
        dep = load(deployment)
    except DeploymentError as exc:
        log(f"[CFG] ERROR: {exc}\n[CFG] The map shows reported GPS only until it is fixed")
        return []
    return [(n.node_id, n.name, n.surveyed) for n in dep.nodes if n.node_id and n.surveyed]


def create_app(cfg: Config, db, *, async_mode: str = "eventlet", log=print):
    app = Flask(__name__)
    socketio = SocketIO(app, cors_allowed_origins=cfg.allowed_origins,
                        async_mode=async_mode, logger=True, engineio_logger=True)

    @app.errorhandler(DatabaseError)
    def database_error(exc):
        log(f"[DB] ERROR: {exc}")
        return jsonify({"error": str(exc)}), 503

    # ── Pages ────────────────────────────────────────────────────────────────

    @app.route("/")
    @app.route("/map")
    def map_view():
        return render_template("map.html")

    @app.route("/dashboard")
    def dashboard():
        node_id = request.args.get("node", "")
        if not NODE_ID_RE.match(node_id):
            return render_template("map.html")
        return render_template("dashboard.html", node_id=node_id)

    # ── APIs ─────────────────────────────────────────────────────────────────

    @app.route("/api/nodes")
    def api_nodes():
        """Position per node: the surveyed coordinate when there is one, else the
        latest the node reported over GPS. `source` says which.

        Surveyed positions are preferred because they are measured on site and
        do not drift. They are NOT provisioned onto the radios: the node keeps
        reporting its own fix, and the difference is the GPS error — a result,
        not noise. That is why both numbers are returned instead of blended.
        """
        reported = {n["node_id"]: n for n in db.get_nodes_position()}
        out = []
        for node_id, name, pos in surveyed_positions(cfg.deployment, log):
            entry = {"node_id": node_id, "node_label": name,
                     "lat": pos.lat, "lon": pos.lon, "source": "surveyed"}
            gps = reported.pop(node_id, None)
            if gps is not None:
                entry["gps_lat"], entry["gps_lon"] = gps["lat"], gps["lon"]
            out.append(entry)
        out.extend({**gps, "source": "gps"} for gps in reported.values())
        return jsonify(out)

    @app.route("/api/recent/<node_id>/<field>")
    def api_recent(node_id, field):
        """The last `limit` points of one field on one node."""
        if not NODE_ID_RE.match(node_id):
            return jsonify({"error": "invalid node_id"}), 400
        if field not in ALL_FIELDS:
            return jsonify({"error": "unknown field"}), 400
        limit = max(1, min(request.args.get("limit", default=TOTAL_SAMPLES_48HRS, type=int), 5000))
        return jsonify(db.get_recent(node_id, field, limit=limit))

    # ── Socket.IO ────────────────────────────────────────────────────────────

    @socketio.on("connect")
    def on_connect():
        log("[WS] client connected")

    @socketio.on("disconnect")
    def on_disconnect():
        log("[WS] client disconnected")

    return app, socketio
