"""MQTT publishing: topic names and the broker connection.

Topics are <prefix>/<node_label>/<kind>. The prefix comes from MQTT_TOPIC_PREFIX
in .env and has no default: two deployments under one prefix interleave
silently. Telegraf's subscriptions and the broker ACL must use the same prefix
(G4): the broker accepts a publish nothing consumes, and the data is lost.
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from typing import Any, Mapping

import paho.mqtt.client as mqtt

__all__ = ["ENV_TOPIC_PREFIX", "KINDS", "MQTTConnector", "describe_refusal", "topic_for",
           "topic_prefix_from_env"]

ENV_TOPIC_PREFIX = "MQTT_TOPIC_PREFIX"

# Each kind is a Telegraf input; a kind outside this list reaches no measurement.
KINDS = ("position", "device", "environment", "message", "pdr")

# The prefix is also substituted into Telegraf's config and the broker ACL
# (mqtt/entrypoint.sh checks the same pattern), so it stays plain.
_PREFIX = re.compile(r"[A-Za-z0-9._-]+")

# CONNACK refusals for bad credentials: MQTT 3.1.1 codes 4 and 5, as paho maps them.
_AUTH_REFUSALS = {134, 135}
_AUTH_HINT = (" — mqtt/pwfile and secrets/ must come from the same run of "
              "mqtt/init-credentials.sh (G5, docs/troubleshooting.md)")


def _level(value: Any, what: str) -> str:
    if (not isinstance(value, str) or not value
            or any(c in "/+#\0" or c.isspace() for c in value)):
        raise ValueError(f"{what} {value!r} is not a single MQTT topic level "
                         f"(non-empty; no '/', '+', '#' or whitespace)")
    return value


def _prefix(value: Any, what: str = "topic prefix") -> str:
    if not isinstance(value, str) or not _PREFIX.fullmatch(value):
        raise ValueError(f"{what} {value!r}: use only letters, digits, '.', '_' and '-'")
    return value


def topic_for(prefix: str, node_label: str, kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown topic kind {kind!r}: Telegraf consumes only {KINDS}")
    return f"{_prefix(prefix)}/{_level(node_label, 'node label')}/{kind}"


def topic_prefix_from_env(environ: Mapping[str, str] = os.environ) -> str:
    """The deployment's topic prefix. Never defaulted, never trimmed."""
    if not environ.get(ENV_TOPIC_PREFIX):
        raise ValueError(f"{ENV_TOPIC_PREFIX} is not set (.env). There is no default: "
                         f"two deployments under one prefix interleave silently")
    return _prefix(environ[ENV_TOPIC_PREFIX], ENV_TOPIC_PREFIX)


def describe_refusal(rc) -> str:
    return f"{rc}{_AUTH_HINT if getattr(rc, 'value', rc) in _AUTH_REFUSALS else ''}"


class MQTTConnector:
    """Publish-only MQTT client; paho reconnects on its own.

    QoS 1: while the broker is unreachable paho keeps messages in memory and
    sends them on reconnection, so a disconnect is not a loss. `queued` and
    `dropped` count, per topic, what did not go out at once and what never will.
    """

    def __init__(self, broker_address: str, topic_prefix: str, port: int = 1883,
                 client_id: str = "", username: str = "", password: str = ""):
        self.broker_address = broker_address
        self.port = port
        self.topic_prefix = _prefix(topic_prefix)
        self.queued: Counter = Counter()
        self.dropped: Counter = Counter()
        self._refused = None
        self._connected_event = threading.Event()

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
        if username:
            self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(min_delay=5, max_delay=60)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            self._refused = None
            self._connected_event.set()
            print("[MQTT] Connected to broker!")
        else:
            self._refused = rc
            print(f"[MQTT] Connection refused: {describe_refusal(rc)}")

    def on_disconnect(self, client, userdata, flags, rc, properties):
        self._connected_event.clear()
        if rc != 0:
            print(f"[MQTT] Disconnected unexpectedly ({rc}); reconnecting...")

    def connect(self):
        self.client.connect(self.broker_address, self.port, keepalive=60)
        self.client.loop_start()

    def wait_until_connected(self, timeout: float = 10.0):
        if not self._connected_event.wait(timeout):
            why = f": {describe_refusal(self._refused)}" if self._refused is not None else ""
            raise RuntimeError(f"[MQTT] Could not connect to broker at "
                               f"{self.broker_address}:{self.port} within {timeout}s{why}")

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Disconnected from broker.")

    def publish(self, topic: str, message: str):
        rc = self.client.publish(topic, message, qos=1).rc
        if rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[MQTT] → {topic}: {message}")
        elif rc == mqtt.MQTT_ERR_NO_CONN:
            self.queued[topic] += 1
            print(f"[MQTT] Broker unreachable; queued until reconnection: {topic}")
        else:
            self.dropped[topic] += 1
            print(f"[MQTT] ERROR: dropped {topic}: {mqtt.error_string(rc)}")

    def publish_payload(self, node_label: str, kind: str, payload: Mapping[str, Any]):
        # allow_nan=False: NaN is not JSON, and Telegraf would discard the whole line.
        self.publish(topic_for(self.topic_prefix, node_label, kind),
                     json.dumps(payload, allow_nan=False))
