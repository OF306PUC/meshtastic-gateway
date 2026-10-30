"""The dashboard: its settings, its API, and how it fails.

Run: .venv/bin/python -m unittest discover -s tests -t .
"""
import contextlib
import hashlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from gateway.config import ConfigError
from monitor.app import create_app, map_urls
from monitor.param import from_env
from monitor.utils import DatabaseError, InfluxDBConnector, MQTTConnector

TEST_MESH = str(Path(__file__).resolve().parent / "fixtures" / "deployments" / "test-mesh.yaml")
ENV = {"MQTT_TOPIC_PREFIX": "testbed", "INFLUXDB_DB": "telemetry_db", "MESH_DEPLOYMENT": TEST_MESH}
N1, P1 = "!0b64122b", "!11223344"


class _DB:
    def __init__(self, positions=(), recent=(), fail=False, uptimes=None, links=()):
        self.positions, self.recent, self.fail, self.calls = list(positions), list(recent), fail, []
        self.uptimes, self.links = dict(uptimes or {}), [dict(link) for link in links]

    def _maybe_fail(self):
        if self.fail:
            raise DatabaseError("InfluxDB query failed: connection refused")

    def get_nodes_position(self):
        self._maybe_fail()
        return [dict(p) for p in self.positions]

    def get_recent(self, node_id, field, limit):
        self.calls.append((node_id, field, limit))
        self._maybe_fail()
        return self.recent

    def get_nodes_uptime(self):
        self._maybe_fail()
        return dict(self.uptimes)

    def get_links(self, hours):
        self.calls.append(("links", hours))
        self._maybe_fail()
        return [dict(link) for link in self.links]


class MonitorCase(unittest.TestCase):
    def client(self, db, **env):
        self.logs = []
        app, _ = create_app(from_env({**ENV, **env}), db, async_mode="threading",
                            log=self.logs.append)
        return app.test_client()


class TestParam(unittest.TestCase):
    def test_the_live_feed_and_client_follow_the_prefix(self):
        cfg = from_env(ENV)
        self.assertEqual(cfg.subscribe_topics, ["testbed/+/position", "testbed/+/device",
                                                "testbed/+/environment"])
        self.assertEqual(cfg.client_id, "testbed-monitor")

    def test_the_database_is_the_one_telegraf_writes_to(self):
        self.assertEqual(from_env(ENV).db_name, "telemetry_db")

    def test_prefix_and_database_are_required(self):
        for name in ("MQTT_TOPIC_PREFIX", "INFLUXDB_DB"):
            with self.subTest(missing=name):
                with self.assertRaisesRegex(ConfigError, name):
                    from_env({k: v for k, v in ENV.items() if k != name})

    def test_allowed_origins(self):
        self.assertIsNone(from_env(ENV).allowed_origins, "same origin, through the proxy")
        cfg = from_env({**ENV, "MONITOR_ALLOWED_ORIGINS": "http://a:5000, http://b:5000"})
        self.assertEqual(cfg.allowed_origins, ["http://a:5000", "http://b:5000"])


class TestApiNodes(MonitorCase):
    GPS = [{"node_id": N1, "node_label": "node-1", "lat": -27.2, "lon": -109.4},
           {"node_id": P1, "node_label": "P1", "lat": -27.3, "lon": -109.5}]

    def test_surveyed_preferred_and_gps_kept_beside_it(self):
        nodes = {n["node_id"]: n for n in self.client(_DB(self.GPS)).get("/api/nodes").json}
        self.assertEqual(nodes[N1], {"node_id": N1, "node_label": "node-1", "lat": -27.1127,
                                     "lon": -109.3497, "source": "surveyed",
                                     "gps_lat": -27.2, "gps_lon": -109.4})
        self.assertEqual(nodes[P1]["source"], "gps", "no survey yet, and GPS beats planned")

    def test_each_node_carries_its_last_uptime_and_when(self):
        db = _DB(self.GPS, uptimes={N1: {"uptime_s": 18703, "uptime_at": "2026-10-28T17:25:54Z"}})
        nodes = {n["node_id"]: n for n in self.client(db).get("/api/nodes").json}
        self.assertEqual((nodes[N1]["uptime_s"], nodes[N1]["uptime_at"]),
                         (18703, "2026-10-28T17:25:54Z"))
        self.assertNotIn("uptime_s", nodes[P1], "none reported")

    def test_a_planned_site_only_when_there_is_nothing_better(self):
        nodes = {n["node_label"]: n for n in self.client(_DB()).get("/api/nodes").json}
        self.assertEqual(nodes["R1"], {"node_id": None, "node_label": "R1", "lat": -27.25,
                                       "lon": -109.25, "source": "planned"})
        self.assertEqual(nodes["P1"]["source"], "planned", "no GPS reported yet")
        self.assertEqual(nodes["node-1"]["source"], "surveyed")
        self.assertNotIn("GW", nodes, "no position of any kind")

    def test_without_a_deployment_the_map_is_gps_only(self):
        nodes = self.client(_DB(self.GPS), MESH_DEPLOYMENT="").get("/api/nodes").json
        self.assertEqual({n["source"] for n in nodes}, {"gps"})

    def test_an_invalid_deployment_is_logged_and_the_map_falls_back_to_gps(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "broken.yaml"
            bad.write_text("meta: {deployment: broken}\nnodes: []\n")
            nodes = self.client(_DB(self.GPS), MESH_DEPLOYMENT=str(bad)).get("/api/nodes").json
        self.assertEqual({n["source"] for n in nodes}, {"gps"})
        self.assertTrue(any("ERROR" in line and "broken.yaml" in line for line in self.logs))

    def test_a_database_failure_is_a_503_not_an_empty_map(self):
        r = self.client(_DB(fail=True)).get("/api/nodes")
        self.assertEqual(r.status_code, 503)
        self.assertIn("connection refused", r.json["error"])
        self.assertTrue(any("[DB] ERROR" in line for line in self.logs))


class TestApiRecent(MonitorCase):
    def test_input_is_validated_before_any_query(self):
        db = _DB()
        client = self.client(db)
        self.assertEqual(client.get("/api/recent/node-1/voltage").status_code, 400)
        self.assertEqual(client.get(f"/api/recent/{N1}/password").status_code, 400)
        self.assertEqual(db.calls, [])

    def test_limit_defaults_and_is_clamped(self):
        db = _DB(recent=[{"time": "t", "voltage": 3.9}])
        client = self.client(db)
        self.assertEqual(client.get(f"/api/recent/{N1}/voltage").json, db.recent)
        client.get(f"/api/recent/{N1}/voltage?limit=999999")
        client.get(f"/api/recent/{N1}/voltage?limit=0")
        self.assertEqual([c[2] for c in db.calls], [576, 5000, 1])

    def test_a_database_failure_is_a_503(self):
        r = self.client(_DB(fail=True)).get(f"/api/recent/{N1}/voltage")
        self.assertEqual(r.status_code, 503)


class TestApiLinks(MonitorCase):
    HEARD = [{"node_id": N1, "node_label": "node-1", "direct": 40, "relayed": 2,
              "rssi": -97.5, "snr": 4.25},
             {"node_id": P1, "node_label": "P1", "direct": 0, "relayed": 7,
              "rssi": None, "snr": None},
             {"node_id": "!deadbeef", "node_label": "stray", "direct": 3, "relayed": 0,
              "rssi": -120.0, "snr": -12.0}]

    def test_every_node_of_the_file_and_every_node_heard(self):
        body = self.client(_DB(links=self.HEARD)).get("/api/links").json
        self.assertEqual(body["gateway"], "GW")
        self.assertEqual(body["hours"], 24)
        links = {link["node_label"]: link for link in body["links"]}
        self.assertEqual(set(links), {"node-1", "P1", "R1", "stray"}, "the gateway is the centre")
        self.assertEqual((links["node-1"]["direct"], links["node-1"]["snr"]), (40, 4.25))
        self.assertEqual((links["P1"]["direct"], links["P1"]["relayed"]), (0, 7))
        self.assertEqual(links["R1"], {"node_id": None, "node_label": "R1", "function": "receiver",
                                       "direct": 0, "relayed": 0, "rssi": None, "snr": None})
        self.assertIsNone(links["stray"]["function"], "heard, but not in the file")

    def test_the_window_is_clamped(self):
        db = _DB()
        client = self.client(db)
        for asked in ("0", "6", "100000"):
            client.get(f"/api/links?hours={asked}")
        self.assertEqual([c[1] for c in db.calls], [1, 6, 168])

    def test_a_database_failure_is_a_503(self):
        self.assertEqual(self.client(_DB(fail=True)).get("/api/links").status_code, 503)


class TestPages(MonitorCase):
    def test_pages(self):
        client = self.client(_DB())
        for path in ("/", "/map", "/dashboard?node=not-an-id"):
            with self.subTest(path=path):
                r = client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIn(b'id="map"', r.data)
        r = client.get(f"/dashboard?node={N1}")
        self.assertIn(N1.encode(), r.data)
        self.assertIn(b'id="dash-error"', r.data)
        self.assertIn(b'id="graph"', client.get("/graph").data)

    def test_the_client_logo_is_on_the_charts_and_served_here(self):
        client = self.client(_DB())
        logo = re.search(r'<img class="client-logo" src="([^"]+)"',
                         client.get(f"/dashboard?node={N1}").data.decode()).group(1)
        self.assertEqual(logo, "/static/assets/sasipa-logo.png")
        r = client.get(logo)
        self.assertEqual((r.status_code, r.mimetype), (200, "image/png"))
        r.close()

    def test_climate_charts_only_for_a_node_with_the_sensor(self):
        client = self.client(_DB())
        for node_id, expected in ((N1, b"true"), (P1, b"false"), ("!0000beef", b"true")):
            with self.subTest(node_id=node_id):
                page = client.get(f"/dashboard?node={node_id}").data
                self.assertIn(b"const HAS_ENVIRONMENT = " + expected, page)

    def test_the_brand(self):
        page = self.client(_DB()).get("/map").data
        self.assertIn(b"<title>LoRa Mesh</title>", page)
        self.assertNotIn(b"Testbed", page)

    def test_every_page_names_its_mesh(self):
        client = self.client(_DB())
        for path in ("/map", "/graph", f"/dashboard?node={N1}"):
            with self.subTest(path=path):
                self.assertIn(b'<span class="mesh-chip" title="gateway tests">test-mesh</span>',
                              client.get(path).data)
        graph = client.get("/graph").data.decode()
        self.assertIn("Meshtastic mesh <span>test-mesh</span>", graph)
        self.assertIn("gateway tests · ANZ · MEDIUM_FAST · slot 45", graph)

    def test_without_a_deployment_the_graph_says_so(self):
        client = self.client(_DB(), MESH_DEPLOYMENT="")
        self.assertNotIn(b"mesh-chip", client.get("/map").data)
        self.assertIn(b"No deployment configured", client.get("/graph").data)


class TestOfflineAssets(MonitorCase):
    """The dashboard must work in the field, without internet, map included."""

    STATIC = Path(__file__).resolve().parents[1] / "monitor" / "static"
    VENDOR = STATIC / "vendor"

    def test_pages_load_no_script_or_style_from_the_internet(self):
        client = self.client(_DB())
        for page in ("/map", "/graph", f"/dashboard?node={N1}"):
            refs = re.findall(r'<(?:script|link)[^>]+(?:src|href)="([^"]+)"',
                              client.get(page).data.decode())
            self.assertTrue(refs, page)
            for ref in refs:
                self.assertTrue(ref.startswith("/static/"), f"{page}: {ref}")
                r = client.get(ref)
                self.assertEqual(r.status_code, 200, ref)
                r.close()

    def test_the_map_reads_its_data_from_this_server(self):
        client = self.client(_DB())
        page = client.get("/map").data.decode()
        refs = re.findall(r'(?:url:|fetch\()\s*"([^"]+)"', page)
        sums = dict(reversed(line.split(maxsplit=1)) for line in
                    (self.STATIC / "maps" / "SHA256SUMS").read_text().splitlines())
        for name in ("basemap.pmtiles", "relief.geojson"):
            # A new archive is a new address: the browser never mixes byte
            # ranges of an older basemap with this one.
            self.assertIn(f"/static/maps/{name}?v={sums[name][:12]}", refs)
        for ref in refs:
            self.assertTrue(ref.startswith("/"), ref)
            r = client.get(ref)
            self.assertEqual(r.status_code, 200, ref)
            r.close()

    def test_without_hashes_the_map_data_has_plain_addresses(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(map_urls(Path(d)), {"basemap": "/static/maps/basemap.pmtiles",
                                                 "relief": "/static/maps/relief.geojson"})

    def test_map_data_is_served_in_ranges(self):
        # The basemap is one file the browser reads piece by piece (HTTP Range).
        r = self.client(_DB()).get("/static/maps/relief.geojson",
                                   headers={"Range": "bytes=0-99"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(len(r.data), 100)
        r.close()

    def test_vendored_and_map_files_match_their_recorded_hashes(self):
        for directory, at_least in ((self.VENDOR, 10), (self.STATIC / "maps", 2)):
            lines = (directory / "SHA256SUMS").read_text().splitlines()
            self.assertGreaterEqual(len(lines), at_least, directory)
            for line in lines:
                digest, name = line.split(maxsplit=1)
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                                 digest, name)


class TestInfluxDBConnector(unittest.TestCase):
    """The real connector against a closed port: loud, never an empty result."""

    def setUp(self):
        self.db = InfluxDBConnector("127.0.0.1", 9, "", "", "telemetry_db")

    def test_check_reports_why(self):
        self.assertIn("unreachable", self.db.check())

    def test_queries_raise_instead_of_returning_nothing(self):
        with self.assertRaises(DatabaseError):
            self.db.get_nodes_position()
        with self.assertRaises(DatabaseError):
            self.db.get_recent(N1, "voltage", limit=10)
        with self.assertRaises(DatabaseError):
            self.db.get_nodes_uptime()
        with self.assertRaises(DatabaseError):
            self.db.get_links(24)


class TestLiveFeed(unittest.TestCase):
    def test_refused_credentials_name_the_usual_cause(self):
        conn = MQTTConnector("localhost", client_id="t")
        out = io.StringIO()
        with mock.patch("monitor.utils.threading.Timer"), contextlib.redirect_stdout(out):
            conn._on_connect(None, None, None, ReasonCode(PacketTypes.CONNACK, identifier=135), None)
        self.assertIn("same run of mqtt/init-credentials.sh", out.getvalue())


if __name__ == "__main__":
    unittest.main()
