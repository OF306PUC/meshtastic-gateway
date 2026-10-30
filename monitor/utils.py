"""InfluxDB queries and the live MQTT feed behind the dashboard."""
from __future__ import annotations

import json
import re
import threading

import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient

from gateway.publish import describe_refusal

NODE_ID_RE = re.compile(r"^![0-9a-f]{8}$")

# Fields stored in the telemetry measurement
POSITION_FIELDS    = ["latitude", "longitude", "altitude"]
ENVIRONMENT_FIELDS = ["temperature", "humidity"]
DEVICE_FIELDS      = ["battery_level", "voltage", "channel_util", "air_util_tx", "uptime_seconds"]
RX_METRICS_FIELDS  = ["rssi", "snr", "hop"]
ALL_FIELDS         = POSITION_FIELDS + ENVIRONMENT_FIELDS + DEVICE_FIELDS + RX_METRICS_FIELDS


MESSAGE_MEASUREMENT = "message"


class DatabaseError(RuntimeError):
    """A query that could not run. The API answers 503, never an empty 200."""


def mask_phone(number: str | None) -> str | None:
    """+56 •••••6789: who is talking, without the whole number (G12)."""
    if not number:
        return number
    return f"+56 {'•' * max(len(number) - 4, 0)}{number[-4:]}"


def for_browser(message: dict) -> dict:
    """A message as a browser may see it: a PBX frame's phone numbers masked.
    Node ids, the src_id / dst_id of an app's message, are not personal."""
    if message.get("origin") != "pbx":
        return dict(message)
    return {**message, "src_id": mask_phone(message.get("src_id")),
            "dst_id": mask_phone(message.get("dst_id"))}


class InfluxDBConnector:
    def __init__(self, host, port, username, password, database, measurement="telemetry"):
        self.measurement = measurement
        self.database = database
        # The client only builds HTTP requests: nothing connects here. The
        # monorepo dropped the client when its first check failed (InfluxDB
        # still starting), and every later query returned [] for good.
        self.client = InfluxDBClient(host=host, port=port, username=username,
                                     password=password, database=database)

    def check(self) -> str | None:
        """None when the database exists, otherwise why it is not usable."""
        try:
            names = [d["name"] for d in self.client.get_list_database()]
        except Exception as exc:
            return f"InfluxDB unreachable: {exc}"
        return None if self.database in names else (
            f"database {self.database!r} not found (available: {names})")

    def _points(self, q) -> list[dict]:
        try:
            return list(self.client.query(q).get_points())
        except Exception as exc:
            raise DatabaseError(f"InfluxDB query failed: {exc}") from exc

    def _grouped(self, q) -> list[tuple[dict, dict]]:
        """(tags, row) for each series of a GROUP BY query that returns one row."""
        try:
            series = self.client.query(q).raw.get("series", [])
        except Exception as exc:
            raise DatabaseError(f"InfluxDB query failed: {exc}") from exc
        return [(s.get("tags", {}), dict(zip(s["columns"], s["values"][0])))
                for s in series if s.get("values")]

    def get_nodes_position(self) -> list[dict]:
        q = (f'SELECT LAST("latitude") AS lat, LAST("longitude") AS lon '
             f'FROM "{self.measurement}" GROUP BY "node_id","node_label"')
        return [{"node_id": tags.get("node_id"), "node_label": tags.get("node_label"),
                 "lat": row["lat"], "lon": row["lon"]}
                for tags, row in self._grouped(q)
                if row.get("lat") is not None and row.get("lon") is not None]

    def get_nodes_uptime(self) -> dict[str, dict]:
        """{node_id: {uptime_s, uptime_at}}: the last uptime each node reported, and when."""
        q = (f'SELECT LAST("uptime_seconds") AS uptime FROM "{self.measurement}" '
             f'GROUP BY "node_id"')
        return {tags["node_id"]: {"uptime_s": row["uptime"], "uptime_at": row["time"]}
                for tags, row in self._grouped(q)
                if tags.get("node_id") and row.get("uptime") is not None}

    def get_links(self, hours: int) -> list[dict]:
        """Per node, what the gateway heard over the last `hours`: packets straight
        from it (hop 0), with their mean RSSI and SNR, and packets a relay passed on."""
        since = f'time > now() - {int(hours)}h'
        links = {}
        for tags, row in self._grouped(
                f'SELECT COUNT("hop") AS direct, MEAN("rssi") AS rssi, MEAN("snr") AS snr '
                f'FROM "{self.measurement}" WHERE "hop" = 0 AND {since} '
                f'GROUP BY "node_id","node_label"'):
            links[tags["node_id"]] = {"node_id": tags["node_id"], "node_label": tags.get("node_label"),
                                      "direct": row["direct"], "relayed": 0,
                                      "rssi": row["rssi"], "snr": row["snr"]}
        for tags, row in self._grouped(
                f'SELECT COUNT("hop") AS relayed FROM "{self.measurement}" '
                f'WHERE "hop" > 0 AND {since} GROUP BY "node_id","node_label"'):
            links.setdefault(tags["node_id"], {"node_id": tags["node_id"],
                                               "node_label": tags.get("node_label"), "direct": 0,
                                               "rssi": None, "snr": None})["relayed"] = row["relayed"]
        return list(links.values())

    def get_messages(self, limit: int, node_id: str | None = None) -> list[dict]:
        """The last `limit` messages, newest first, every field and tag. With
        `node_id`, the node's own: heard from it, or addressed to it. Phone
        numbers are whole: mask them (for_browser) before they leave for a browser."""
        if node_id is not None and not NODE_ID_RE.match(node_id):
            raise ValueError(f"refusing to query node_id={node_id!r}")
        where = (f' WHERE ("node_id"=\'{node_id}\' OR "dst_id"=\'{node_id}\')'
                 if node_id else "")
        q = (f'SELECT * FROM "{MESSAGE_MEASUREMENT}"{where} '
             f'ORDER BY time DESC LIMIT {min(int(limit), 5000)}')
        return self._points(q)

    def get_recent(self, node_id: str, field: str, limit: int) -> list[dict]:
        """The last `limit` points of one field on one node, oldest first."""
        if not NODE_ID_RE.match(node_id) or field not in ALL_FIELDS:
            raise ValueError(f"refusing to query node_id={node_id!r} field={field!r}")
        q = (f'SELECT "{field}" FROM "{self.measurement}" '
             f'WHERE "node_id"=\'{node_id}\' '
             f'ORDER BY time DESC LIMIT {min(int(limit), 5000)}')
        return list(reversed(self._points(q)))

    def close(self):
        self.client.close()


class MQTTConnector:
    """Subscribes to the live feed and forwards every message to the browsers."""

    def __init__(self, broker_address, port=1883, client_id="", username="", password=""):
        self.broker_address = broker_address
        self.port = port
        self.client_id = client_id
        self.socketio = None
        self._subscriptions = []   # re-subscribed on every reconnect

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            print(f"[MQTT] connected to {self.broker_address}:{self.port}")
            for topic in self._subscriptions:
                client.subscribe(topic)
                print(f"[MQTT] (re)subscribed → {topic}")
        else:
            print(f"[MQTT] connection refused: {describe_refusal(rc)} — retrying in 5 s")
            threading.Timer(5, self.connect).start()

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT] disconnected rc={rc} — paho will auto-reconnect")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"[MQTT] bad JSON on {msg.topic}: {e}")
            return

        parts = msg.topic.split("/")
        kind = parts[-1] if len(parts) >= 3 else "unknown"
        if kind == "message":
            payload = for_browser(payload)
        payload["_topic"] = msg.topic
        payload["_type"] = kind

        print(f"[MQTT] {msg.topic} | "
              f"node={payload.get('node_id')} "
              f"type={payload['_type']} "
              f"device_ts={payload.get('device_ts')} "
              f"received_at={payload.get('received_at')}")

        if self.socketio:
            self.socketio.emit("mqtt_message", payload)
        else:
            print("[MQTT] WARNING: socketio not attached, message not forwarded to browser")

    def connect(self):
        try:
            print(f"[MQTT] connecting to {self.broker_address}:{self.port} "
                  f"client_id={self.client_id}")
            self.client.connect(self.broker_address, self.port, keepalive=60)
        except Exception as e:
            print(f"[MQTT] connect failed: {e} — retrying in 5 s")
            threading.Timer(5, self.connect).start()

    def subscribe(self, topic):
        self._subscriptions.append(topic)
        self.client.subscribe(topic)
        print(f"[MQTT] subscribed → {topic}")

    def loop(self):
        self.client.loop_start()
        print("[MQTT] network loop started")

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] disconnected")
