"""The dashboard's settings, from the environment (.env and secrets/web.env).

The live feed and the database are the ones the gateway and Telegraf use: the
topics come from MQTT_TOPIC_PREFIX and the database from INFLUXDB_DB, never from
literals of their own (G4).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from gateway.config import ConfigError
from gateway.publish import topic_prefix_from_env

__all__ = ["Config", "ENV_OUT_OF_SERVICE", "ENV_POPUP_AT", "TOTAL_SAMPLES_48HRS", "from_env"]

TOTAL_SAMPLES_48HRS = 576
LIVE_KINDS = ("position", "device", "environment", "message")
ENV_OUT_OF_SERVICE = "MONITOR_ENVIRONMENT_OUT_OF_SERVICE"
ENV_MESSAGE_POPUP = "MONITOR_MESSAGE_POPUP_SEC"
ENV_POPUP_AT = "MONITOR_MESSAGE_POPUP_AT"
DEFAULT_MESSAGE_POPUP_SEC = 30


@dataclass(frozen=True)
class Config:
    db_host: str
    db_port: int
    db_username: str
    db_password: str
    db_name: str
    broker_address: str
    broker_port: int
    client_id: str
    username: str
    password: str
    subscribe_topics: list[str]        # what the pages draw: telemetry and messages
    deployment: str | None             # for surveyed positions; unset = GPS only
    allowed_origins: list[str] | None  # None: same origin only (the proxy's own address)
    # Refs of the nodes whose environment sensor is out of service in the field:
    # their dashboard hides the temperature and humidity charts. A setting of the
    # dashboard, not of the mesh: the deployment file is the platform's (G10).
    environment_out_of_service: tuple[str, ...] = ()
    # How long the map holds the popup of a new message over its node.
    message_popup_sec: int = DEFAULT_MESSAGE_POPUP_SEC
    # Sender ref -> the ref whose marker shows its messages: an access node with
    # no position, shown at a node that has one.
    message_popup_at: Mapping[str, str] = field(default_factory=dict)


def _port(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(env.get(name) or default)
    except ValueError:
        raise ConfigError(f"{name}: expected a port number, got {env[name]!r}") from None


def _seconds(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ConfigError(f"{name}: expected a positive number of seconds, got {raw!r}")
    return value


def _popup_at(env: Mapping[str, str], name: str) -> dict[str, str]:
    """D1:N1,D2:N2 -> {"D1": "N1", "D2": "N2"}."""
    out = {}
    for entry in filter(None, (e.strip() for e in env.get(name, "").split(","))):
        sender, sep, anchor = (p.strip() for p in entry.partition(":"))
        if not (sep and sender and anchor):
            raise ConfigError(f"{name}: expected <sender ref>:<node ref> pairs separated by ',', "
                              f"got {entry!r}")
        out[sender] = anchor
    return out



def from_env(environ: Mapping[str, str] = os.environ) -> Config:
    try:
        prefix = topic_prefix_from_env(environ)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    if not environ.get("INFLUXDB_DB"):
        raise ConfigError("INFLUXDB_DB is not set: the database Telegraf writes to "
                          "(.env)")
    return Config(
        db_host=environ.get("DB_HOST") or "localhost",
        db_port=_port(environ, "DB_PORT", 8086),
        # The read-only account (secrets/web.env).
        db_username=environ.get("INFLUXDB_READ_USER", ""),
        db_password=environ.get("INFLUXDB_READ_USER_PASSWORD", ""),
        db_name=environ["INFLUXDB_DB"],
        broker_address=environ.get("BROKER_ADDRESS") or "localhost",
        broker_port=_port(environ, "BROKER_PORT", 1883),
        client_id=environ.get("CLIENT_ID_MONITOR") or f"{prefix}-monitor",
        # This account is read-only (mqtt/aclfile.template).
        username=environ.get("MQTT_USERNAME_MONITOR") or environ.get("MQTT_USERNAME", ""),
        password=environ.get("MQTT_PASSWORD_MONITOR") or environ.get("MQTT_PASSWORD", ""),
        # Messages too: their phone numbers are masked before a browser gets them.
        subscribe_topics=[f"{prefix}/+/{kind}" for kind in LIVE_KINDS],
        deployment=environ.get("MESH_DEPLOYMENT") or None,
        # Same origin works through the proxy whatever name the browser typed
        # (gateway.local, an IP); a list is only needed for another site.
        allowed_origins=[o.strip() for o in environ["MONITOR_ALLOWED_ORIGINS"].split(",")
                         if o.strip()] if environ.get("MONITOR_ALLOWED_ORIGINS") else None,
        environment_out_of_service=tuple(ref.strip() for ref in
                                         environ.get(ENV_OUT_OF_SERVICE, "").split(",")
                                         if ref.strip()),
        message_popup_sec=_seconds(environ, ENV_MESSAGE_POPUP, DEFAULT_MESSAGE_POPUP_SEC),
        message_popup_at=_popup_at(environ, ENV_POPUP_AT),
    )
