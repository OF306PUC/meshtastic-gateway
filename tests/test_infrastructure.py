"""The configuration files that must agree with each other and with the code.

Each mismatch here is silent in operation: a topic Telegraf does not subscribe
to is accepted by the broker and lost (G4); an account without an ACL rule
connects and can do nothing; a missing variable starts a stack without data.
"""
import re
import tomllib
import unittest
from pathlib import Path

import yaml

from gateway.publish import KINDS

ROOT = Path(__file__).resolve().parents[1]
TELEGRAF = tomllib.loads((ROOT / "telegraf" / "etc" / "telegraf.conf").read_text())
ACL = (ROOT / "mqtt" / "aclfile.template").read_text()
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yaml").read_text())
PREFIX_VAR = "${MQTT_TOPIC_PREFIX}"

# docs/design.md §2.5
MEASUREMENT = {"position": "telemetry", "device": "telemetry", "environment": "telemetry",
               "message": "message", "pdr": "pdr"}
TAGS = {
    "telemetry": ["node_id", "node_label"],
    "message": ["node_id", "node_label", "portnum", "channel", "origin", "src_id", "dst_id"],
    "pdr": ["node_label", "flow", "source"],
}


class TestTelegrafMatchesThePublisher(unittest.TestCase):
    def setUp(self):
        self.inputs = TELEGRAF["inputs"]["mqtt_consumer"]

    def test_every_kind_is_consumed_exactly_once_into_its_measurement(self):
        consumed = {}
        for inp in self.inputs:
            for topic in inp["topics"]:
                consumed.setdefault(topic, []).append(inp["name_override"])
        self.assertEqual(consumed, {f"{PREFIX_VAR}/+/{k}": [MEASUREMENT[k]] for k in KINDS})

    def test_tags_per_measurement(self):
        self.assertEqual({i["name_override"]: i["tag_keys"] for i in self.inputs}, TAGS)

    def test_the_message_text_is_kept(self):
        """The json parser drops a string field it is not told about, silently."""
        [inp] = [i for i in self.inputs if i["name_override"] == "message"]
        self.assertEqual(inp["json_string_fields"], ["text", "content_hex"])

    def test_received_at_is_the_time_key_everywhere(self):
        for inp in self.inputs:
            self.assertEqual((inp["data_format"], inp["json_time_key"], inp["json_time_format"]),
                             ("json", "received_at", "unix"), inp["name_override"])


class TestBrokerAccounts(unittest.TestCase):
    def test_accounts_and_acl_users_match(self):
        """An account with no ACL rule connects and can do nothing."""
        script = (ROOT / "mqtt" / "init-credentials.sh").read_text()
        accounts = re.search(r"^ACCOUNTS=\(([^)]*)\)", script, re.M).group(1).split()
        self.assertEqual(sorted(re.findall(r"^user (\S+)", ACL, re.M)), sorted(accounts))

    def test_acl_rules(self):
        rules, user = {}, None
        for line in ACL.splitlines():
            if line.startswith("user "):
                user = line.split()[1]
            elif line.startswith("topic "):
                rules.setdefault(user, []).append(line[len("topic "):])
        self.assertEqual(rules, {
            "gateway": ["write {prefix}/#"],
            "telegraf": ["read {prefix}/#"],
            # Telemetry and messages; the dashboard masks phone numbers (G12).
            "monitor": ["read {prefix}/+/position", "read {prefix}/+/device",
                        "read {prefix}/+/environment", "read {prefix}/+/message"],
        })


def _written_secrets() -> dict[str, set[str]]:
    """{service: keys} for each secrets/<service>.env that init-credentials.sh writes."""
    script = (ROOT / "mqtt" / "init-credentials.sh").read_text()
    files = re.findall(r'cat > "\$STAGE/secrets/(\w+)\.env" <<EOF\n(.*?)\nEOF', script, re.S)
    return {name: set(re.findall(r"(?m)^([A-Z_]+)=", body)) for name, body in files}


class TestCredentialsPerService(unittest.TestCase):
    """Each container gets only its own credentials (G9), and every credential a
    service reads is in its file: a missing one fails without saying why."""

    SECRETS = _written_secrets()

    def test_each_file_holds_exactly_its_services_credentials(self):
        self.assertEqual(self.SECRETS, {
            "influxdb": {"INFLUXDB_ADMIN_USER", "INFLUXDB_ADMIN_PASSWORD", "INFLUXDB_WRITE_USER",
                         "INFLUXDB_WRITE_USER_PASSWORD", "INFLUXDB_READ_USER",
                         "INFLUXDB_READ_USER_PASSWORD"},
            "telegraf": {"MQTT_USERNAME_TELEGRAF", "MQTT_PASSWORD_TELEGRAF", "INFLUXDB_WRITE_USER",
                         "INFLUXDB_WRITE_USER_PASSWORD"},
            "gateway": {"MQTT_USERNAME_GATEWAY", "MQTT_PASSWORD_GATEWAY"},
            "web": {"MQTT_USERNAME_MONITOR", "MQTT_PASSWORD_MONITOR", "INFLUXDB_READ_USER",
                    "INFLUXDB_READ_USER_PASSWORD"},
            "proxy": {"DASHBOARD_USER", "DASHBOARD_PASSWORD_HASH"},
        })

    def test_each_service_reads_its_own_file_and_no_other(self):
        env_files = {name: s.get("env_file") for name, s in COMPOSE["services"].items()}
        self.assertEqual(env_files, {
            "mosquitto": None, "influxdb": "secrets/influxdb.env",
            "telegraf": "secrets/telegraf.env", "gateway-receiver": "secrets/gateway.env",
            "web": "secrets/web.env", "proxy": "secrets/proxy.env"})

    def test_only_influxdb_knows_the_admin_password(self):
        holders = [n for n, keys in self.SECRETS.items() if "INFLUXDB_ADMIN_PASSWORD" in keys]
        self.assertEqual(holders, ["influxdb"])

    def _provided(self, service, file):
        env = COMPOSE["services"][service].get("environment", [])
        return self.SECRETS[file] | {e.split("=", 1)[0] for e in env}

    def test_telegraf_and_caddy_find_every_variable_they_use(self):
        telegraf = set(re.findall(r"\$\{(\w+)\}", (ROOT / "telegraf" / "etc" / "telegraf.conf").read_text()))
        self.assertLessEqual(telegraf, self._provided("telegraf", "telegraf"))
        caddy = set(re.findall(r"\{\$(\w+)\}", (ROOT / "proxy" / "Caddyfile").read_text()))
        self.assertLessEqual(caddy, self._provided("proxy", "proxy"))

    def test_the_receiver_and_the_dashboard_find_their_credentials(self):
        for path, service, file in (("gateway/config.py", "gateway-receiver", "gateway"),
                                    ("monitor/param.py", "web", "web")):
            used = set(re.findall(r'environ\.get\("((?:MQTT|INFLUXDB)_\w*(?:USER|PASSWORD)\w*)"',
                                  (ROOT / path).read_text()))
            used -= {"MQTT_USERNAME", "MQTT_PASSWORD"}          # the outside-compose fallback
            self.assertTrue(used, path)
            self.assertLessEqual(used, self._provided(service, file), path)


class TestHardening(unittest.TestCase):
    """Step 8 (security review, 2026-10-27). Each of these was open before it."""

    def test_every_service_has_bounded_logs(self):
        """The receiver logs real people's message text."""
        for name, service in COMPOSE["services"].items():
            options = service.get("logging", {}).get("options", {})
            self.assertTrue(options.get("max-size") and options.get("max-file"), name)

    def test_the_broker_is_reachable_from_the_host_only(self):
        self.assertEqual(COMPOSE["services"]["mosquitto"]["ports"], ["127.0.0.1:1883:1883"])
        conf = (ROOT / "mqtt" / "mosquitto.conf").read_text()
        self.assertEqual(re.findall(r"^listener .*", conf, re.M), ["listener 1883"])
        self.assertRegex(conf, r"(?m)^allow_anonymous false$")

    def test_only_the_proxy_is_reachable_from_the_network(self):
        """Option B (user, 2026-10-27): one door with a login; the rest host-only."""
        for name, service in COMPOSE["services"].items():
            for port in service.get("ports", []):
                if name == "proxy":
                    self.assertEqual(port, "${DASHBOARD_PORT:-80}:80")
                else:
                    self.assertTrue(port.startswith("127.0.0.1:"), f"{name}: {port}")

    def test_the_proxy_asks_for_a_login_before_the_dashboard(self):
        caddyfile = (ROOT / "proxy" / "Caddyfile").read_text()
        self.assertRegex(caddyfile, r"basic_auth \{\s*\{\$DASHBOARD_USER\} \{\$DASHBOARD_PASSWORD_HASH\}\s*\}")
        self.assertIn("reverse_proxy web:5000", caddyfile)
        self.assertRegex(caddyfile, r"(?m)^\s*admin off$")

    def test_the_dashboard_hash_is_always_single_quoted(self):
        """Unquoted, compose expands the $ in a bcrypt hash and every login fails
        (seen 2026-10-27: only a warning on the console)."""
        script = (ROOT / "mqtt" / "init-credentials.sh").read_text()
        self.assertIn("DASHBOARD_PASSWORD_HASH='$DASHBOARD_HASH'", script)

    def test_the_script_hashes_with_the_proxys_caddy(self):
        script = (ROOT / "mqtt" / "init-credentials.sh").read_text()
        image = re.search(r'^CADDY_IMAGE="([^"]+)"', script, re.M).group(1)
        self.assertEqual(image, COMPOSE["services"]["proxy"]["image"])

    def test_influxdb_requires_authentication(self):
        self.assertIn("INFLUXDB_HTTP_AUTH_ENABLED=true",
                      COMPOSE["services"]["influxdb"]["environment"])

    def test_telegraf_writes_with_the_write_only_account(self):
        [out] = TELEGRAF["outputs"]["influxdb"]
        self.assertEqual((out["username"], out["password"], out["skip_database_creation"]),
                         ("${INFLUXDB_WRITE_USER}", "${INFLUXDB_WRITE_USER_PASSWORD}", True))

    def test_the_dashboard_reads_with_the_read_only_account(self):
        from monitor.param import from_env
        cfg = from_env({"MQTT_TOPIC_PREFIX": "t", "INFLUXDB_DB": "db",
                        "INFLUXDB_READ_USER": "monitor", "INFLUXDB_READ_USER_PASSWORD": "pw",
                        "INFLUXDB_ADMIN_USER": "admin", "INFLUXDB_ADMIN_PASSWORD": "root"})
        self.assertEqual((cfg.db_username, cfg.db_password), ("monitor", "pw"))

    def test_the_dashboard_does_not_run_as_root(self):
        dockerfile = (ROOT / "monitor" / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"(?m)^USER (?!root)\S+")

    def test_the_receiver_does_not_run_as_root_but_can_open_the_serial_port(self):
        """It parses packets from anyone in radio range. Verified 2026-10-27: the
        user opens a host root:dialout device; one outside dialout cannot."""
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"(?m)^RUN useradd .*--groups dialout gateway$")
        self.assertRegex(dockerfile, r"(?m)^USER gateway$")


class TestOnePrefixEverywhere(unittest.TestCase):
    def test_no_literal_prefix_survives(self):
        for path in ("telegraf/etc/telegraf.conf", "mqtt/aclfile.template",
                     "docker-compose.yaml", "gateway/publish.py", "monitor/param.py",
                     "monitor/templates/map.html", "monitor/templates/dashboard.html"):
            self.assertNotIn("meshtastic-testbed", (ROOT / path).read_text(), path)

    def test_every_service_that_uses_topics_gets_the_prefix_or_refuses_to_start(self):
        for name in ("mosquitto", "telegraf", "gateway-receiver", "web"):
            env = COMPOSE["services"][name]["environment"]
            self.assertIn("MQTT_TOPIC_PREFIX=${MQTT_TOPIC_PREFIX:?set MQTT_TOPIC_PREFIX in .env}",
                          env, name)

    def test_the_receivers_required_settings_refuse_to_default(self):
        env = COMPOSE["services"]["gateway-receiver"]["environment"]
        for var in ("MESH_DEPLOYMENT", "GATEWAY_SERIAL_PORT"):
            self.assertTrue(any(e.startswith(f"{var}=${{{var}:?") for e in env), var)


class TestMounts(unittest.TestCase):
    def test_read_only_where_a_container_must_not_write(self):
        services = COMPOSE["services"]
        for name in ("gateway-receiver", "web"):
            self.assertIn("./deployments:/app/deployments:ro", services[name]["volumes"], name)
        self.assertIn("./mqtt:/mosquitto/config:ro", services["mosquitto"]["volumes"])
        self.assertIn("./telegraf/etc/telegraf.conf:/etc/telegraf/telegraf.conf:ro",
                      services["telegraf"]["volumes"])


if __name__ == "__main__":
    unittest.main()
