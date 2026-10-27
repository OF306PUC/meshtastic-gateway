"""Topics and publishing. The topic format is half of the published contract
(G4): Telegraf subscribes to these exact strings.

Run: .venv/bin/python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import unittest

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from gateway.publish import (ENV_TOPIC_PREFIX, KINDS, MQTTConnector, topic_for,
                             topic_prefix_from_env)

PREFIX = "meshtastic-testbed"


class TestTopics(unittest.TestCase):
    def test_topic_format_per_kind(self):
        """docs/design.md §2.4, with the monorepo's prefix."""
        self.assertEqual({k: topic_for(PREFIX, "node-1", k) for k in KINDS}, {
            "position": "meshtastic-testbed/node-1/position",
            "device": "meshtastic-testbed/node-1/device",
            "environment": "meshtastic-testbed/node-1/environment",
            "message": "meshtastic-testbed/node-1/message",
            "pdr": "meshtastic-testbed/node-1/pdr",
        })

    def test_a_deployment_publishes_under_its_own_prefix(self):
        self.assertEqual(topic_for("rapa-nui", "n1", "device"), "rapa-nui/n1/device")

    def test_unknown_kind_fails_loudly(self):
        """`env` was the monorepo's method name; the topic is `environment`."""
        with self.assertRaises(ValueError):
            topic_for(PREFIX, "node-1", "env")

    def test_a_level_that_would_reshape_the_topic_is_rejected(self):
        for bad in ("a/b", "+", "#", "", " node-1", "node 1", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    topic_for(PREFIX, bad, "device")
                with self.assertRaises(ValueError):
                    topic_for(bad, "node-1", "device")


class TestPrefixFromEnv(unittest.TestCase):
    def test_read_from_the_environment(self):
        self.assertEqual(topic_prefix_from_env({ENV_TOPIC_PREFIX: "rapa-nui"}), "rapa-nui")

    def test_there_is_no_default(self):
        for env in ({}, {ENV_TOPIC_PREFIX: ""}):
            with self.subTest(env=env):
                with self.assertRaisesRegex(ValueError, ENV_TOPIC_PREFIX):
                    topic_prefix_from_env(env)

    def test_whitespace_is_rejected_not_trimmed(self):
        """Trimmed here but not in Telegraf, the two prefixes would differ silently."""
        with self.assertRaises(ValueError):
            topic_prefix_from_env({ENV_TOPIC_PREFIX: "rapa-nui "})

    def test_characters_that_break_substitution_are_rejected(self):
        """The prefix is substituted into telegraf.conf and the ACL with sed."""
        for bad in ("a&b", "a|b", "a$b", "a\\b", "ñandú"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    topic_prefix_from_env({ENV_TOPIC_PREFIX: bad})


class _FakeClient:
    def __init__(self, rc=mqtt.MQTT_ERR_SUCCESS):
        self.rc, self.calls = rc, []

    def publish(self, topic, message, qos):
        self.calls.append((topic, message, qos))
        return _Info(self.rc)


class _Info:
    def __init__(self, rc):
        self.rc = rc


def _connector(rc=mqtt.MQTT_ERR_SUCCESS):
    conn = MQTTConnector("localhost", PREFIX)
    conn.client = _FakeClient(rc)
    return conn


def _quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


class TestPublish(unittest.TestCase):
    def test_payload_goes_to_its_topic_as_json_with_qos_1(self):
        conn = _connector()
        payload = {"node_id": "!0b64122b", "dst_id": None, "malformed": 0}
        _quiet(conn.publish_payload, "node-1", "message", payload)
        topic, message, qos = conn.client.calls[0]
        self.assertEqual(topic, "meshtastic-testbed/node-1/message")
        self.assertEqual(json.loads(message), payload)
        self.assertIn('"dst_id": null', message)        # G3b survives serialisation
        self.assertEqual(qos, 1)

    def test_a_disconnect_queues_it_does_not_drop(self):
        conn = _connector(mqtt.MQTT_ERR_NO_CONN)
        _quiet(conn.publish_payload, "node-1", "device", {"voltage": 3.9})
        self.assertEqual(conn.queued["meshtastic-testbed/node-1/device"], 1)
        self.assertFalse(conn.dropped)

    def test_a_refused_publish_is_counted_as_dropped(self):
        conn = _connector(mqtt.MQTT_ERR_QUEUE_SIZE)
        _quiet(conn.publish_payload, "node-1", "device", {"voltage": 3.9})
        self.assertEqual(conn.dropped["meshtastic-testbed/node-1/device"], 1)
        self.assertFalse(conn.queued)

    def test_nan_fails_loudly_instead_of_publishing_invalid_json(self):
        conn = _connector()
        with self.assertRaises(ValueError):
            conn.publish_payload("node-1", "environment", {"temperature": float("nan")})
        self.assertEqual(conn.client.calls, [])

    def test_the_connector_rejects_a_bad_prefix(self):
        with self.assertRaises(ValueError):
            MQTTConnector("localhost", "")


class TestConnect(unittest.TestCase):
    def test_bad_credentials_name_the_usual_cause(self):
        """rc=5 / not authorised: pwfile and the service credentials disagree (G5)."""
        conn = MQTTConnector("localhost", PREFIX)
        _quiet(conn.on_connect, None, None, None, ReasonCode(PacketTypes.CONNACK, identifier=135), None)
        with self.assertRaisesRegex(RuntimeError, "same run of mqtt/init-credentials.sh"):
            conn.wait_until_connected(timeout=0.01)

    def test_a_successful_connack_unblocks(self):
        conn = MQTTConnector("localhost", PREFIX)
        _quiet(conn.on_connect, None, None, None, ReasonCode(PacketTypes.CONNACK, identifier=0), None)
        conn.wait_until_connected(timeout=0.01)


if __name__ == "__main__":
    unittest.main()
