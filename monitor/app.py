"""The dashboard's pages and JSON API: / and /map, /graph, /messages,
/dashboard, /api/nodes, /api/links, /api/messages and
/api/recent/<node_id>/<field>.

A query that fails answers 503 with the reason; it never answers an empty list,
which the map would show as "no nodes yet".
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from gateway.deployment import Deployment, DeploymentError, Node, load
from monitor.param import TOTAL_SAMPLES_48HRS, Config
from monitor.utils import ALL_FIELDS, NODE_ID_RE, DatabaseError, for_browser

__all__ = ["create_app", "current_deployment", "deployment_nodes", "map_urls", "mesh_summary"]

MAPS = Path(__file__).resolve().parent / "static" / "maps"


def map_urls(maps: Path = MAPS) -> dict[str, str]:
    """The map's data, each URL carrying its file's hash from maps/SHA256SUMS.

    The browser reads the basemap in byte ranges and may keep ranges of an older
    archive under the same address: mixed with a new one they draw an empty
    island until a reload. A new archive gets a new address instead.
    """
    try:
        sums = {name: digest for digest, name in
                (line.split(maxsplit=1) for line in (maps / "SHA256SUMS").read_text().splitlines())}
    except FileNotFoundError:
        sums = {}
    return {key: f"/static/maps/{name}" + (f"?v={sums[name][:12]}" if name in sums else "")
            for key, name in (("basemap", "basemap.pmtiles"), ("relief", "relief.geojson"))}


def current_deployment(deployment: str | None, log=print) -> Deployment | None:
    """The configured deployment, read on every request, so an edited file
    shows up without a restart. None when there is none; an invalid file is
    logged loudly, and the pages fall back to what the nodes report."""
    if not deployment:
        return None
    try:
        return load(deployment)
    except DeploymentError as exc:
        log(f"[CFG] ERROR: {exc}\n[CFG] The map shows reported GPS only until it is fixed")
        return None


def deployment_nodes(deployment: str | None, log=print) -> list[Node]:
    """The deployment's nodes, for their surveyed and planned positions."""
    dep = current_deployment(deployment, log)
    return list(dep.nodes) if dep else []


def mesh_summary(dep: Deployment | None) -> dict | None:
    """Which mesh the pages show: its name, description and radio."""
    if dep is None:
        return None
    radio = [dep.region, dep.modem_preset,
             f"slot {dep.channel_num}" if dep.channel_num is not None else None]
    return {"name": dep.name, "description": dep.description,
            "radio": " · ".join(r for r in radio if r)}


def create_app(cfg: Config, db, *, async_mode: str = "eventlet", log=print):
    app = Flask(__name__)
    maps = map_urls()

    @app.context_processor
    def which_mesh():
        return {"mesh": mesh_summary(current_deployment(cfg.deployment, log))}
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
        return render_template("map.html", maps=maps)

    @app.route("/graph")
    def graph_view():
        return render_template("graph.html")

    @app.route("/messages")
    def messages_view():
        node_id = request.args.get("node", "")
        dep = current_deployment(cfg.deployment, log)
        return render_template(
            "messages.html", node_id=node_id if NODE_ID_RE.match(node_id) else "",
            nodes=[{"node_id": n.node_id, "name": n.name} for n in (dep.nodes if dep else ())
                   if n.node_id],
            channels={str(i): name for i, name in (dep.channels.items() if dep else ())})

    @app.route("/dashboard")
    def dashboard():
        node_id = request.args.get("node", "")
        if not NODE_ID_RE.match(node_id):
            return render_template("map.html", maps=maps)
        node = next((n for n in deployment_nodes(cfg.deployment, log) if n.node_id == node_id),
                    None)
        # Charts only for what the node carries: no environment flow, no SHT4X
        # (V3b). A node the file does not describe gets them all.
        return render_template("dashboard.html", node_id=node_id,
                               node_name=node.name if node else None,
                               environment=node is None or "environment" in node.intervals)

    # ── APIs ─────────────────────────────────────────────────────────────────

    @app.route("/api/nodes")
    def api_nodes():
        """Position per node, best first: the surveyed coordinate, else the latest
        the node reported over GPS, else where it is planned to go. `source`
        says which.

        Surveyed positions are preferred because they are measured on site and
        do not drift. They are NOT provisioned onto the radios: the node keeps
        reporting its own fix, and the difference is the GPS error — a result,
        not noise. That is why both numbers are returned instead of blended.
        A planned position is a desk choice, shown only until there is anything
        better; a node not provisioned yet has no node_id.
        """
        reported = {n["node_id"]: n for n in db.get_nodes_position()}
        out = []
        for node in deployment_nodes(cfg.deployment, log):
            gps = reported.pop(node.node_id, None)
            if node.surveyed:
                pos, source = node.surveyed, "surveyed"
            elif gps is not None:
                out.append({**gps, "source": "gps"})
                continue
            elif node.planned:
                pos, source = node.planned, "planned"
            else:
                continue
            entry = {"node_id": node.node_id, "node_label": node.name,
                     "lat": pos.lat, "lon": pos.lon, "source": source}
            if gps is not None:
                entry["gps_lat"], entry["gps_lon"] = gps["lat"], gps["lon"]
            out.append(entry)
        out.extend({**gps, "source": "gps"} for gps in reported.values())
        uptimes = db.get_nodes_uptime()
        for entry in out:
            entry.update(uptimes.get(entry["node_id"], {}))
        return jsonify(out)

    @app.route("/api/links")
    def api_links():
        """What the gateway hears straight from each node, without a hop, over
        the last `hours` (default 24, at most a week): packets heard directly
        with their mean RSSI and SNR, and packets that came through a relay.
        The file's nodes are all listed, heard or not; the gateway is named."""
        hours = max(1, min(request.args.get("hours", 24, type=int), 24 * 7))
        nodes = deployment_nodes(cfg.deployment, log)
        heard = {link["node_id"]: link for link in db.get_links(hours)}
        out = []
        for node in nodes:
            if node.function == "gateway":
                continue
            link = heard.pop(node.node_id, None) or {"node_id": node.node_id, "direct": 0,
                                                     "relayed": 0, "rssi": None, "snr": None}
            out.append({**link, "node_label": node.name, "function": node.function})
        out.extend({**link, "function": None} for link in heard.values())
        gateway = next((n.name for n in nodes if n.function == "gateway"), "Gateway")
        return jsonify({"hours": hours, "gateway": gateway, "links": out})

    @app.route("/api/messages")
    def api_messages():
        """The last messages, newest first, as a browser may see them: a PBX
        frame's phone numbers masked (G12). `node` keeps one node's; `limit`
        defaults to 200, at most 1000."""
        node_id = request.args.get("node") or None
        if node_id is not None and not NODE_ID_RE.match(node_id):
            return jsonify({"error": "invalid node_id"}), 400
        limit = max(1, min(request.args.get("limit", 200, type=int), 1000))
        return jsonify([for_browser(m) for m in db.get_messages(limit, node_id)])

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
