"""Settings from the environment; what could point at the wrong place is required."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from gateway.config import ConfigError, from_env
from gateway.deployment import load
from gateway import startup

ROOT = Path(__file__).resolve().parents[1]
TEST_MESH = ROOT / "tests" / "fixtures" / "deployments" / "test-mesh.yaml"
REQUIRED = {"MESH_DEPLOYMENT": "test-mesh", "MQTT_TOPIC_PREFIX": "testbed",
            "GATEWAY_SERIAL_PORT": "/dev/ttyACM0"}


class TestFromEnv(unittest.TestCase):
    def test_defaults(self):
        cfg = from_env(REQUIRED)
        self.assertEqual((cfg.broker_address, cfg.broker_port), ("localhost", 1883))
        self.assertEqual(cfg.client_id, "testbed-gateway")
        self.assertEqual(dict(cfg.pdr_window_sec),
                         {"device": 3600, "environment": 3600, "position": 3600})
        self.assertEqual(cfg.sweep_interval_sec, 30)
        self.assertEqual((cfg.username, cfg.password), ("", ""))

    def test_each_required_setting_fails_loudly(self):
        for name in REQUIRED:
            with self.subTest(missing=name):
                env = {k: v for k, v in REQUIRED.items() if k != name}
                with self.assertRaisesRegex(ConfigError, name):
                    from_env(env)

    def test_pdr_window_globally_and_per_flow(self):
        cfg = from_env({**REQUIRED, "PDR_WINDOW_SEC": "7200",
                        "PDR_WINDOW_SEC_POSITION": "21600"})
        self.assertEqual(dict(cfg.pdr_window_sec),
                         {"device": 7200, "environment": 7200, "position": 21600})

    def test_bad_numbers_fail_loudly(self):
        for name, value in (("PDR_WINDOW_SEC", "0"), ("PDR_SWEEP_INTERVAL_SEC", "-30"),
                            ("PDR_WINDOW_SEC_DEVICE", "1h"), ("BROKER_PORT", "mqtt")):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ConfigError, name):
                    from_env({**REQUIRED, name: value})

    def test_the_role_specific_credentials_win(self):
        """secrets/gateway.env defines the per-role names; the generic ones are a fallback."""
        cfg = from_env({**REQUIRED, "MQTT_USERNAME_GATEWAY": "gateway", "MQTT_USERNAME": "x",
                        "MQTT_PASSWORD_GATEWAY": "s3cret"})
        self.assertEqual((cfg.username, cfg.password), ("gateway", "s3cret"))


class TestStartupWarnings(unittest.TestCase):
    def setUp(self):
        self.dep = load(str(TEST_MESH))
        self.cfg = from_env(REQUIRED)

    def test_a_correct_setup_is_quiet(self):
        self.assertEqual(startup.warnings(self.dep, self.cfg, "!aabbccdd", "CLIENT_MUTE"), [])

    def test_radio_not_in_the_deployment(self):
        [w] = startup.warnings(self.dep, self.cfg, "!deadbeef", "CLIENT_MUTE")
        self.assertIn("not in test-mesh.yaml", w)

    def test_radio_declared_as_something_else(self):
        [w] = startup.warnings(self.dep, self.cfg, "!0b64122b", "CLIENT_MUTE")
        self.assertIn("'node', not 'gateway'", w)

    def test_a_radio_that_relays_contaminates_the_measurement(self):
        [w] = startup.warnings(self.dep, self.cfg, "!aabbccdd", "CLIENT")
        self.assertIn("G6", w)

    def test_sweep_slower_than_the_shortest_cadence(self):
        cfg = from_env({**REQUIRED, "PDR_SWEEP_INTERVAL_SEC": "120"})
        [w] = startup.warnings(self.dep, cfg, "!aabbccdd", "CLIENT_MUTE")
        self.assertIn("shortest cadence (120 s)", w)


class TestMainFailsLoudly(unittest.TestCase):
    def test_without_configuration_it_exits_non_zero_and_says_why(self):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
        run = subprocess.run([sys.executable, str(ROOT / "main.py")], env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("MQTT_TOPIC_PREFIX", run.stderr)

    def test_an_unknown_deployment_exits_non_zero(self):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               **REQUIRED, "MESH_DEPLOYMENT": "nope"}
        run = subprocess.run([sys.executable, str(ROOT / "main.py")], env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("no such deployment file", run.stderr)


if __name__ == "__main__":
    unittest.main()
